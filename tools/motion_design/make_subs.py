"""把口播稿按标点切成字幕,对齐到 timing.json 的实测时间窗。

字幕不是"把整段话丢上去":一段 7 秒的口播有 30 多个字,一屏放不下也读不完。
按标点切成小句,每句时长按字数比例分配 —— 这是最朴素也最接近人工打轴的做法。

两个历史缺陷(都在这一个文件里收口):

1. 按**字符**硬切。`piece[:max_len]` 会把 "EAST" 切成 "EAS"+"T",把 "1亿℃"
   切成 "1亿"+"℃"。字幕断得难看还是其次 —— TTS 念的是同一份文本,
   于是 "EAST人造太阳" 被念成 "E-A-S / T人造太阳",整句就听不懂了。
   现在先分词元(拉丁词、数字+单位、日期各自是不可分割的原子),再按词元换行,
   任何词元都不会被切开;TTS 通道走同样的分词,不会再出现"念到一半换行"。

2. 数字和单位直接丢给 TTS。"1亿℃" / "4.21克" / "2030年" 各家的读法不一致,
   有的念"一亿摄氏度",有的念"一 亿 ℃"。这里给出**确定性的朗读形**:
   字幕保留原写法(1亿℃),TTS 通道换成"一亿摄氏度"。规则只覆盖白名单单位,
   转换不出来就原样保留 —— 宁可不念,不许猜。

对外契约(CLI 参数、输出文件、JSON 键)保持不变;新增的只有
`spoken_units()` / `speak()` 这两个函数,给 voiceover.py 共用。
"""
from __future__ import annotations

import argparse
import io
import json
import re
from pathlib import Path

# 断句符一律用码位写死。之前这里两个字面量逗号看着像全角、实际都是 U+002C,
# 中文逗号从来没生效 —— 长句只能被 max_len 硬切,切在「只拿到」中间。
SOFT = "\uFF0C\u3001\uFF1B\uFF1A"          # ，、；：
STOP = "\u3002\uFF01\uFF1F\u2026"          # 。！？…
# 半角标点同样按断句符处理:英文标点的稿子也走同一套切分,行为才一致。
_SOFT_ASCII = ",;:"
_STOP_ASCII = ".!?"
SOFT_ALL = SOFT + _SOFT_ASCII
STOP_ALL = STOP + _STOP_ASCII

# 朗读规则改动时 +1:voiceover 把它折进音频文件名,旧缓存自动失效。
# v2:修掉「一半」「一辆」被从词中间切开插逗号,以及朗读形不幂等。
SPEECH_RULES_VERSION = 2

# 口播单元的上限(汉字/字符数)。超过 ~28 字一口气念不完,听感就糊了。
SPOKEN_MAX = 28

# ── 词元 ──────────────────────────────────────────────────────────────
# 字幕绝不能从中间切开的三种东西:
#   拉丁词    EAST / CoulombFly / Max
#   数字+单位 1亿℃ / 1066秒 / 4.21克 / 500人
#   日期      2030年 / 10月31日
# 顺序有讲究:先认日期,再认"数字+单位",最后才是裸数字和拉丁词。
# 拉丁词排在裸数字后面,所以 "GPT4" 会被整体当成拉丁词,数字不会被单独拎出来。
_UNIT_WORDS = (
    "摄氏度", "小时", "分钟", "毫秒", "微秒", "公里", "千米", "公斤",
    "平方米", "美元", "赫兹", "瓦", "伏", "秒", "克", "人", "年", "月",
    "日", "天", "岁", "次", "倍", "元", "米", "度", "吨", "升",
)
_UNIT_ALT = "|".join(sorted(_UNIT_WORDS, key=len, reverse=True))
_SCALE = "亿万千百"

# 括号整段当一个词元:括号里的补充说明不该被切成两行,也不该在行间拆开。
# `cn_*` 两条认的是**已经转成中文**的读法 —— speakable() 之后要再断一次句,
# 那时「一亿摄氏度」/「二零三零年」都已经没有数字了。必须在这里当成原子,
# 否则会从「一亿摄氏」「度」之间切开,TTS 听起来就像换了半句话。
_ATOM_RE = re.compile(
    r"""
      (?P<bracket>（[^（）]*）|\([^()]*\)|【[^【】]*】|\[[^\[\]]*\]|｛[^｛｝]*｝|\{[^{}]*\})
    | (?P<date>\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}月\d{1,2}日|\d{4}年)
    | (?P<measure>\d+(?:\.\d+)?[""" + _SCALE + r"""]?(?:℃|°C|""" + _UNIT_ALT + r"""))
    | (?P<cn_date>[零一二三四五六七八九]{4}年[零一二三四五六七八九十]{1,3}月[零一二三四五六七八九十]{1,3}日
                  |[零一二三四五六七八九十]{1,3}月[零一二三四五六七八九十]{1,3}日
                  |[零一二三四五六七八九]{4}年)
    # 已转成中文的数字读法:四点二一 / 零点五六八克 / 一千零六十六。必须整体当一个词元,
    # 否则第二遍断句会从「四点」「二一克」或「一千零六十」「六」之间切开,幂等就破了。
    | (?P<cn_decimal>[零一二三四五六七八九]+点[零一二三四五六七八九]+
                     (?:""" + _UNIT_ALT + r""")?)
    | (?P<cn_measure>[零一二三四五六七八九十百千万亿]+(?:""" + _UNIT_ALT + r"""))
    # 中文数字串(可带量级),没有单位的也要整体:三亿 / 五百万 / 一千零六十六。
    | (?P<cn_scaled>[零一二三四五六七八九十百千万亿]{2,})
    # 裸数字带量级也算一个整体:3亿 / 500万。不然 3 和 亿 会被拆开,念成"三 亿"。
    | (?P<number>\d+(?:\.\d+)?[""" + _SCALE + r"""]?)
    | (?P<latin>[A-Za-z][A-Za-z0-9]*(?:[._+\-/'][A-Za-z0-9]+)*)
    | (?P<other>[\s\S])
    """,
    re.X,
)

# 量级(亿/万/千/百)的读法:只念"三亿"里的"亿",数字部分照常转。
_SCALE_SPOKEN = {"亿": "亿", "万": "万", "千": "千", "百": "百"}

# 单位 → 朗读形。只有这张白名单里的单位会被改写,其它一律原样保留。
_UNIT_SPOKEN = {
    "℃": "摄氏度",
    "°C": "摄氏度",
    "摄氏度": "摄氏度",
    "小时": "小时",
    "分钟": "分钟",
    "毫秒": "毫秒",
    "微秒": "微秒",
    "公里": "公里",
    "千米": "千米",
    "公斤": "公斤",
    "秒": "秒", "克": "克", "人": "人", "年": "年", "月": "月", "日": "日",
    "天": "天", "岁": "岁", "次": "次", "倍": "倍", "元": "元", "米": "米",
    "度": "度", "吨": "吨", "升": "升",
}

_DIGITS_CN = "零一二三四五六七八九"
_SECTION_UNITS = ("", "十", "百", "千")

# 括号内通常是注释/补充说明,念出来是噪音;字幕里保留,朗读时丢掉。
_BRACKETS = {"（": "）", "(": ")", "【": "】", "［": "］", "[": "]", "｛": "｝", "{": "}"}
# 引号只去符号、留内容 —— 引号里往往就是真正要说的话。
_QUOTES = "「」『』“”‘’"


def _atoms(text: str) -> list[tuple[str, str]]:
    """切成不可再分的词元。返回 (kind, token),kind ∈ bracket/date/measure/number/latin/soft/stop/space/other。"""
    out: list[tuple[str, str]] = []
    for m in _ATOM_RE.finditer(text):
        kind = m.lastgroup or "other"
        tok = m.group(0)
        if kind == "other":
            if tok in SOFT_ALL:
                kind = "soft"
            elif tok in STOP_ALL:
                kind = "stop"
            elif tok.isspace():
                kind = "space"
        out.append((kind, tok))
    return out


# 数字类词元:用于"这句话里塞了几组数据"的密度判断。
_NUM_KINDS = ("measure", "cn_measure", "cn_date", "number", "date")


def _clauses(atoms: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """把词元按标点聚成"小句"(clause):每个小句以自己的标点收尾。

    小句是断行的最小单位 —— **能装下的小句绝不切开**。
    之前是按词元自由断,于是「暴雨点云少一大半,」(11 字,明明装得下)
    被从"一大"后面劈开,读出来成了"少一大,半"。
    """
    out: list[list[tuple[str, str]]] = []
    cur: list[tuple[str, str]] = []
    for atom in atoms:
        cur.append(atom)
        if atom[0] in ("soft", "stop"):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _clause_len(clause: list[tuple[str, str]]) -> int:
    return sum(len(tok) for _, tok in clause)


def _clause_body_len(clause: list[tuple[str, str]]) -> int:
    """小句的"正文字数",不算末尾标点。

    speak() 会给整段补一个句号。如果句号也算进长度预算,一段刚好 max_len 的
    文本第二遍就变成 max_len+1,于是又被切开 —— 幂等永远不成立。
    标点是停顿符,不是要念的字,不该挤占字数。
    """
    n = len(clause)
    while n > 0 and clause[n - 1][0] in ("soft", "stop", "space"):
        n -= 1
    return sum(len(tok) for _, tok in clause[:n])


def _clause_text(clause: list[tuple[str, str]]) -> str:
    return "".join(tok for _, tok in clause)


def _count_atoms(clause: list[tuple[str, str]], kinds: tuple[str, ...]) -> int:
    return sum(1 for k, _ in clause if k in kinds)


def _split_by_numbers(clause: list[tuple[str, str]], num_cap: int) -> list[list[tuple[str, str]]]:
    """把塞了太多数字的小句按**数字边界**分成几块。

    数字+单位本身是原子的,所以这个切法不会切开任何一个词。
    注意:这里只是把文本分成几块,**不插任何标点** —— 原文没有的停顿不能凭空造。
    """
    if num_cap <= 0 or _count_atoms(clause, _NUM_KINDS) <= num_cap:
        return [clause]
    blocks: list[list[tuple[str, str]]] = []
    cur: list[tuple[str, str]] = []
    seen = 0
    for atom in clause:
        cur.append(atom)
        if atom[0] in _NUM_KINDS:
            seen += 1
            if seen % num_cap == 0:
                blocks.append(cur)
                cur = []
    if cur:
        blocks.append(cur)
    return blocks


def _split_by_length(clause: list[tuple[str, str]], budget: int) -> list[list[tuple[str, str]]]:
    """按词元边界把内容切成若干块,每块 <= budget(词元太长时例外)。

    budget 留给后面补进来的标点,保证切出来的块加上标点仍然放得下 ——
    这正是 speak() 能收敛(幂等)的关键。
    """
    if not clause:
        return []
    total = _clause_len(clause)
    if total <= budget:
        return [clause]
    k = max(1, -(-total // budget))
    target = -(-total // k)
    blocks: list[list[tuple[str, str]]] = []
    cur: list[tuple[str, str]] = []
    cur_len = 0
    for atom in clause:
        alen = len(atom[1])
        if cur and (cur_len + alen > budget
                    or (cur_len >= target and len(blocks) < k - 1)):
            blocks.append(cur)
            cur, cur_len = [], 0
        cur.append(atom)
        cur_len += alen
    if cur:
        blocks.append(cur)
    return blocks


def _blocks(text: str, max_len: int, add_comma: bool,
            num_cap: int) -> list[tuple[str, int, int]]:
    """把文本切成"块":(文本, 逗号数, 数字数)。

    - 装得下的小句原样保留(绝不切开);
    - 装不下的小句才在词元边界切开,口播通道在切缝补一个逗号当换气,
      字幕通道一个字都不加(字幕必须和原文逐字相同);
    - 塞了太多数字的小句按数字边界分块,给口播单元用(同样不插标点)。
    """
    out: list[tuple[str, int, int]] = []
    prefix = ""      # 稿子以标点开头时,先存着,贴到第一个有内容的块上
    for clause in _clauses(_atoms(text)):
        trailing = ""
        content = clause
        if clause and clause[-1][0] in ("soft", "stop"):
            trailing = clause[-1][1]
            content = clause[:-1]
        if not content:
            # 只有标点的小句(如「,」「。」连写):标点必须贴到相邻内容上,
            # 否则会切出一行以「,」开头的字幕,或者让标点独占一行。
            if out:
                prev_txt, prev_commas, prev_nums = out[-1]
                out[-1] = (prev_txt + trailing, prev_commas + (1 if trailing in SOFT_ALL else 0), prev_nums)
            elif prefix:
                prefix += trailing
            else:
                prefix = trailing
            continue
        if _clause_len(clause) <= max_len:
            pieces = [(c, False) for c in _split_by_numbers(content, num_cap)]
        else:
            # 切缝要放逗号/末尾标点 → 内容每块最多 max_len-1。
            raw = _split_by_length(content, max(1, max_len - 1))
            pieces = [(c, i < len(raw) - 1) for i, c in enumerate(raw)]
        for i, (piece, needs_comma) in enumerate(pieces):
            txt = _clause_text(piece)
            commas = _count_atoms(piece, ("soft",))
            nums = _count_atoms(piece, _NUM_KINDS)
            if needs_comma and add_comma:
                txt += "，"
                commas += 1
            elif i == len(pieces) - 1 and trailing:
                txt += trailing
                if trailing in SOFT_ALL:
                    commas += 1
            out.append((txt, commas, nums))
    if prefix:
        if out:
            # 稿子以标点开头:把它并到第一块前面,逐字保留。
            first_txt, first_commas, first_nums = out[0]
            out[0] = (prefix + first_txt, first_commas + (1 if prefix in SOFT_ALL else 0), first_nums)
        else:
            out.append((prefix, 0, 0))
    return out


def _group(blocks: list[tuple[str, int, int]], max_len: int,
           comma_cap: int | None = None, num_cap: int | None = None) -> list[str]:
    """把块装成若干"行"/"单元"。

    装行只按宽度和逗号/数字密度来断,断点落在块边界上,
    所以永远不会在句子中间凭空插标点。句号是硬边界:跨过去会一屏塞两个句子。
    """
    lines: list[str] = []
    cur: list[str] = []
    cur_len = 0
    cur_commas = 0
    cur_nums = 0

    def flush() -> None:
        nonlocal cur, cur_len, cur_commas, cur_nums
        if cur:
            lines.append("".join(cur))
        cur, cur_len, cur_commas, cur_nums = [], 0, 0, 0

    for txt, commas, nums in blocks:
        if cur:
            too_long = cur_len + len(txt) > max_len
            too_comma = bool(comma_cap) and cur_commas + commas > comma_cap
            too_num = bool(num_cap) and cur_nums + nums > num_cap
            hard = cur[-1].endswith(tuple(STOP_ALL))
            if too_long or too_comma or too_num or hard:
                flush()
        cur.append(txt)
        cur_len += len(txt)
        cur_commas += commas
        cur_nums += nums
    flush()
    return [x for x in lines if x.strip()]


def chunk(text: str, max_len: int = 18) -> list[str]:
    """把一段口播稿切成字幕行。每行 <= max_len 个字,拉丁词/数字单位绝不切断。

    字幕是**原文**:切行只换位置,不加分隔符,所以拼回去必须逐字等于原文。
    唯一的例外:单个词元本身比 max_len 还长(例如一个长英文名),
    那它自己占一行 —— 切开它只会让 TTS 念成一串字母。
    """
    text = (text or "").strip()
    if not text:
        return []
    try:
        max_len = int(max_len)
    except (TypeError, ValueError):
        max_len = 18
    if max_len <= 0:
        max_len = 18
    return _group(_blocks(text, max_len, add_comma=False, num_cap=0), max_len)


# ── 朗读形 ────────────────────────────────────────────────────────────
def _section_cn(n: int) -> str:
    """0..9999 的读法(不含零的省略规则,由 _int_to_cn 统一处理)。"""
    s = ""
    digits = str(n)
    zero = False
    for pos, ch in enumerate(digits):
        d = int(ch)
        place = len(digits) - pos - 1
        if d == 0:
            zero = True
            continue
        if zero and s:
            s += "零"
        zero = False
        s += _DIGITS_CN[d] + _SECTION_UNITS[place]
    return s


def _int_to_cn(n: int) -> str:
    """整数读法。超出 1e12 抛 ValueError —— 宁可原样保留,不猜。

    分组处理(亿/万/个),组与组之间补"零":10001 → 一万零一,100000001 → 一亿零一。
    """
    if n < 0:
        raise ValueError("negative")
    if n == 0:
        return "零"
    if n >= 10 ** 12:
        raise ValueError("too large")
    out = ""
    rest = n
    for base, name in ((10 ** 8, "亿"), (10 ** 4, "万"), (1, "")):
        q, rest = divmod(rest, base)
        if not q:
            continue
        # 低一组不足四位时中间要补零(一万零一),否则读起来会连成一个数。
        if out and q < 1000:
            out += "零"
        out += _section_cn(q) + name
    if out.startswith("一十"):
        out = out[1:]
    return out


def _num_to_cn(tok: str) -> str | None:
    """数字串 → 中文读法。4.21 → 四点二一;1066 → 一千零六十六。"""
    try:
        if "." in tok:
            ip, _, fp = tok.partition(".")
            if not ip.isdigit() or not fp.isdigit():
                return None
            return _int_to_cn(int(ip)) + "点" + "".join(_DIGITS_CN[int(c)] for c in fp)
        if not tok.isdigit():
            return None
        return _int_to_cn(int(tok))
    except (ValueError, IndexError):
        return None


def _year_to_cn(y: str) -> str:
    """年份按位念:2030 → 二零三零。"""
    return "".join(_DIGITS_CN[int(c)] for c in y)


def _number_to_cn(tok: str) -> str:
    """裸数字 → 读法。只处理**带白名单单位**的写法(3亿 / 500万),其余原样保留。

    这是契约的一部分:数字后面没有可念的单位时,别猜该怎么念。
    「98.6%」转成「九十八点六%」、「123个」转成「一百二十三个」都更糟 ——
    百分号/「个」不在白名单里,原样交给 TTS 反而念得对。
    带单位的完整写法由 _measure_to_cn 负责(1亿℃ / 1066秒 / 4.21克)。
    """
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([" + _SCALE + r"])", tok)
    if not m:
        return tok
    num, scale = m.group(1), m.group(2)
    spoken = _num_to_cn(num)
    if spoken is None:
        return tok
    return spoken + _SCALE_SPOKEN.get(scale, scale)


def _date_to_cn(tok: str) -> str:
    m = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", tok)
    if m:
        mo, day = _num_to_cn(m.group(2)), _num_to_cn(m.group(3))
        if mo and day:
            return _year_to_cn(m.group(1)) + "年" + mo + "月" + day + "日"
        return tok
    m = re.fullmatch(r"(\d{1,2})月(\d{1,2})日", tok)
    if m:
        mo, day = _num_to_cn(m.group(1)), _num_to_cn(m.group(2))
        if mo and day:
            return mo + "月" + day + "日"
        return tok
    m = re.fullmatch(r"(\d{4})年", tok)
    if m:
        return _year_to_cn(m.group(1)) + "年"
    return tok


def _measure_to_cn(tok: str) -> str:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([" + _SCALE + r"]?)(.+)", tok)
    if not m:
        return tok
    num, scale, unit = m.group(1), m.group(2), m.group(3)
    spoken = _num_to_cn(num)
    if spoken is None:
        return tok
    return spoken + scale + _UNIT_SPOKEN.get(unit, unit)


def _drop_bracketed(text: str) -> str:
    """删掉成对的括号内容(含括号)。落单的括号原样保留。"""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        close = _BRACKETS.get(ch)
        if close:
            depth = 0
            j = i
            while j < n:
                if text[j] == ch:
                    depth += 1
                elif text[j] == close:
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if j < n:
                i = j + 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def speakable(text: str) -> str:
    """把字幕文本整理成"可以直接念"的文本(还没做断句)。

    - 括号内的补充说明丢掉(字幕仍然保留);
    - 引号只去符号,内容保留;
    - 全角数字转半角,数字+命中白名单单位转中文读法。
    """
    if not text:
        return ""
    s = str(text)
    s = s.translate({0xFF10 + i: 0x30 + i for i in range(10)})  # ０-９ → 0-9
    s = _drop_bracketed(s)
    s = s.translate({ord(c): None for c in _QUOTES})
    s = re.sub(r"[ \t\u3000]+", " ", s).strip()

    out: list[str] = []
    for kind, tok in _atoms(s):
        if kind == "date":
            out.append(_date_to_cn(tok))
        elif kind == "measure":
            out.append(_measure_to_cn(tok))
        elif kind == "number":
            out.append(_number_to_cn(tok))
        else:
            out.append(tok)
    return "".join(out).strip()


def spoken_units(text: str, max_len: int = SPOKEN_MAX) -> list[str]:
    """切成"一口气念得完"的口播单元,每段 <= max_len 个字。

    三条规则:
      1. 装得下的小句绝不切开(「少一大半」不会被劈成「少一大」+「半」);
      2. 装不下的小句才在词元边界切开,切缝里补一个逗号当换气;
      3. 一段里塞了超过 2 个数字时,按**数字边界**再分几块 ——
         数据一多,一口气念不完。但数字+单位是原子的,这个切法不伤词。

    幂等:speak(speak(x)) == speak(x)。所以这里补出来的逗号必须让下一轮
    看到的每个小句都"装得下" —— 补一个逗号就要留出一个字的位置。
    """
    text = (text or "").strip()
    if not text:
        return []
    try:
        max_len = int(max_len)
    except (TypeError, ValueError):
        max_len = SPOKEN_MAX
    if max_len <= 0:
        max_len = SPOKEN_MAX
    blocks = _blocks(text, max_len, add_comma=True, num_cap=2)
    return _group(blocks, max_len, comma_cap=2, num_cap=2)


def speak(text: str) -> str:
    """TTS 通道的最终文本:先整理成朗读形,再按口播单元断句。

    已有标点原样保留(全角标点不会被改掉);只有在**真的切开了小句**的地方
    才补一个逗号当换气 —— 那是"换气",不是"句子结束",所以不用句号。
    补句号会让 TTS 在「EAST人」这种词中间做出完整句尾降调,听起来像话说了一半断了。

    这个函数是**幂等**的:speak(speak(x)) == speak(x)。否则 voiceover 与
    verify_voice 各调一次会得到两份不同的音频,互相关校验直接失败。
    """
    units = spoken_units(speakable(text))
    if not units:
        return ""
    parts: list[str] = []
    last = len(units) - 1
    for i, u in enumerate(units):
        u = u.strip()
        if not u:
            continue
        if u[-1] in STOP_ALL:
            parts.append(u)
        elif u[-1] in SOFT_ALL:
            # 单元已在标点处结束;最后一句给个句号收尾。
            parts.append(u if i < last else u[:-1] + "。")
        elif i < last:
            parts.append(u + "，")
        else:
            parts.append(u + "。")
    return "".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--max-len", type=int, default=18)
    args = ap.parse_args()

    proj = Path(args.project).resolve()
    timing = json.loads((proj / "timing.json").read_text(encoding="utf-8"))
    gap = float(timing.get("gap", 0.0))

    subs = []
    t0 = 0.0
    for seg in timing["segments"]:
        pieces = chunk(seg["text"], args.max_len)
        total_chars = sum(len(x) for x in pieces) or 1
        cur = t0
        for i, piece in enumerate(pieces):
            share = len(piece) / total_chars
            dur = seg["dur"] * share
            start = cur
            end = cur + dur
            # 最后一句稍微留一点余量,避免字幕提早消失
            if i == len(pieces) - 1:
                end = t0 + seg["dur"]
            subs.append({
                "text": piece,
                "start": round(start, 3),
                "end": round(end, 3),
                "w": min(960, max(300, len(piece) * 46 + 60)),
            })
            cur = end
        t0 += seg["dur"] + gap

    if not subs:
        # 空稿:写空数组而不是崩掉。film.py 只在有内容时才读它。
        subs = []

    (proj / "subtitles.json").write_text(
        json.dumps(subs, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    js = "window.__SUBS__ = " + json.dumps(subs, ensure_ascii=False) + ";\n"
    with io.open(proj / "subs.js", "w", encoding="utf-8", newline="\n") as fp:
        fp.write(js)
    last_end = subs[-1]["end"] if subs else 0.0
    print(json.dumps({"ok": True, "cues": len(subs), "last_end": last_end}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
