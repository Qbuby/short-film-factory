"""短片工厂 —— 把 code-first 短视频管线收成一条命令。

普通人视角只有三步:
    film new   ->  建项目(选风格,填稿子或让模型起草)
    film make  ->  口播→字幕→配乐→渲染→评审→归档,一条龙
    film styles->  看 15 个风格都能做什么

设计原则:
  - 每一步都可以单独重跑;缓存按内容寻址,改了稿子不会复用旧音频;
  - 事实只来自用户给的来源,模型起草也不许编数;
  - 评审不过就如实报 FAIL,不用「看起来还行」糊弄。

用法:
    python tools/motion_design/film.py styles
    python tools/motion_design/film.py new  --name my-film --style mg-paperclip
    python tools/motion_design/film.py draft --project my-film --source article.txt
    python tools/motion_design/film.py voice --project my-film            # TTS
    python tools/motion_design/film.py voice --project my-film --audio 我.wav  # 真人录音
    python tools/motion_design/film.py build --project my-film
    python tools/motion_design/film.py render --project my-film [--stills 1.5,8]
    python tools/motion_design/film.py check  --project my-film
    python tools/motion_design/film.py ship  --project my-film
    python tools/motion_design/film.py make  --name my-film --style mg-paperclip --source article.txt
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools" / "motion_design"
PY = REPO / ".venv" / "Scripts" / "python.exe"
if not PY.exists():
    PY = Path(sys.executable)
# 静态工具/素材仍来自 REPO; app_paths 负责准备工作区内的 composer。
WORKSPACE = Path(os.environ["OE_WORKSPACE"]).expanduser().resolve() if os.environ.get("OE_WORKSPACE") else REPO
PROJECTS = WORKSPACE / "projects" / "code-first"
RROOT = WORKSPACE / "remotion-composer"
PUBLIC = RROOT / "public"
SRC = RROOT / "src"
CATALOG = json.loads((TOOLS / "film_styles.json").read_text(encoding="utf-8"))
VOICES = json.loads((TOOLS / "voices.json").read_text(encoding="utf-8"))
TYPES = json.loads((TOOLS / "video_types.json").read_text(encoding="utf-8"))
RATIOS = json.loads((TOOLS / "ratios.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(TOOLS))
import quality as qcfg  # noqa: E402
import scene_contract as sc  # noqa: E402
STYLES = {s["id"]: s for s in CATALOG["styles"]}
FAST_BACKEND = "remotion:StickerFilm"
STYLE_BACKEND = "remotion:StyleFilm"
# Playwright 逐帧渲染后端（mg-wallstreet）。它不是 Remotion 组合：
# 自己起本机浏览器按 window.ready/window.seek(t) 逐帧截图、ffmpeg 编码并合成音频。
# 同样要跑 build 拿 props/audio，所以列进 FAST_BACKENDS 放行闸门；
# 但 _write_registry 要把它排除，别给它注册一个不会被用到的 Remotion 组合。
PLAYWRIGHT_BACKEND = "playwright:wallstreet"
FAST_BACKENDS = (FAST_BACKEND, STYLE_BACKEND, PLAYWRIGHT_BACKEND)


def is_playwright(meta: dict) -> bool:
    """这一条片是否走 Playwright 逐帧渲染后端。"""
    return (STYLES.get(meta.get("style")) or {}).get("backend") == PLAYWRIGHT_BACKEND

def _coerce_steps(x) -> list[dict]:
    out = []
    for s in (x or [])[:3]:
        if isinstance(s, str):
            out.append({"label": s})
        elif isinstance(s, dict):
            out.append({"label": str(s.get("label") or s.get("text") or s.get("title") or ""),
                        "icon": s.get("icon")})
    return out


def normalize_film(film: dict) -> dict:
    """把模型/人手写的简写统一成模板吃的形状。普通人不该关心字段细节。"""
    for b in film.get("beats", []):
        k = b.get("kind")
        t = b.get("title")
        if isinstance(t, str) and "\n" in t:
            b["title"] = t.split("\n")
        if k == "flow":
            b["steps"] = _coerce_steps(b.get("steps"))
        if k in ("compare", "verdict"):
            for side in ("left", "right"):
                v = b.get(side)
                if isinstance(v, str):
                    b[side] = {"label": v}
        if k == "checklist":
            items = []
            for it in (b.get("items") or [])[:3]:
                if isinstance(it, str):
                    items.append({"title": it})
                elif isinstance(it, dict):
                    items.append({"n": it.get("n"),
                                  "title": str(it.get("title") or it.get("text") or it.get("label") or ""),
                                  "sub": it.get("sub"), "icon": it.get("icon"), "tone": it.get("tone")})
            b["items"] = items
        if k == "hook":
            if b.get("phone") not in (None, "lock"):
                b["phone"] = "shop"
            v = str(b.get("visual") or "").strip().lower()
            if v in ("robot", "机器人", "机械"):
                b["visual"] = "robot"
            elif v in ("none", "无", "纯文字"):
                b["visual"] = "none"
            else:
                b["visual"] = "face"
            sp = b.get("spec")
            rows: list = []
            if isinstance(sp, dict):
                rows = [[str(kk), str(vv)] for kk, vv in list(sp.items())[:4]]
            elif isinstance(sp, list):
                for item in sp[:4]:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        rows.append([str(item[0]), str(item[1])])
                    elif isinstance(item, str):
                        a, _, bb = item.replace("：", ":").partition(":")
                        if bb.strip():
                            rows.append([a.strip(), bb.strip()])
            elif isinstance(sp, str):
                for bit in re.split(r"[,，;；]", sp):
                    a, _, bb = bit.replace("：", ":").partition(":")
                    if bb.strip():
                        rows.append([a.strip(), bb.strip()])
            if rows:
                b["spec"] = rows
        # note 是给观众看的一行短说明,不是给画师看的制作指令。
        # 模型经常写成"机器人剖面标出芯片、摄像头…"这种:既是废话,
        # 又会在成片上变成一行压住字幕的说明句。超长或像制作指令的一律丢掉。
        note = str(b.get("note") or "").strip()
        # 20 字:模板那条 note 贴纸一行放得下(940px 宽、36px 字号),
        # 再长就要折两行以上、顶到字幕条上。宁可少说一句,也不要压字幕。
        if note and (len(note) > 20 or _NOTE_IS_DIRECTION(note)):
            b["note"] = ""
    return film


# 这些词一出现,就说明模型在写"画面该怎么画",而不是"给观众的一句话"
_DIRECTION_WORDS = ("画面出现", "画面里", "画一个", "画出", "标出", "展示", "呈现",
                    "镜头", "构图", "特写", "渲染", "贴纸")


def _NOTE_IS_DIRECTION(note: str) -> bool:
    return any(word in note for word in _DIRECTION_WORDS)


BEAT_KINDS = ("hook", "flow", "compare", "verdict", "checklist", "cta")


def sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("  $", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], **kw)


def npx(action: str, *args: str, cwd: Path, check: bool = False) -> subprocess.CompletedProcess:
    """调用 Remotion(action = "render" / "still")。

    便携包里用「自带 node + CLI 入口脚本」的绝对路径,不走 PATH ——
    Node 的 OpenSSL DLL 会污染 Python 子进程的 TLS 握手。
    仓库环境下回落到 npx。
    """
    node_dir = os.environ.get("OE_NODE_DIR", "")
    cli = cwd / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
    node_exe = Path(node_dir) / "node.exe" if node_dir else None
    if node_exe and node_exe.exists() and cli.exists():
        return sh([str(node_exe), str(cli), action, *args], cwd=cwd, check=check)
    base = ["cmd", "/c", "npx"] if os.name == "nt" else ["npx"]
    return sh([*base, "remotion", action, *args], cwd=cwd, check=check)


def die(msg: str, code: int = 2):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    raise SystemExit(code)


# 阶段标记:让界面能显示**真实**的进度,而不是一个不知道在干什么的转圈。
# 格式是一行 JSON,只多一个键;日志正文仍然是给人读的中文。
# 界面从任务日志里提取这些行,所以每一个阶段都必须对应一次真实发生的工作。
# 走 stderr 而不是 stdout:命令行下 stdout 只留结果 JSON,不会被标记行弄坏
# (界面那边 stderr 与 stdout 是同一个管道,照样收得到)。
def stage(name: str, note: str = "") -> None:
    print(json.dumps({"stage": name, "note": note}, ensure_ascii=False), file=sys.stderr, flush=True)


def checked_duration(value, label: str = "实际时长") -> float:
    try:
        return qcfg.validate_duration(value, label)
    except ValueError as exc:
        die(str(exc))


def validate_timing(tm: dict) -> float:
    total = checked_duration(tm.get("total"))
    # 不能只信 total:旧文件可能把总长写小,分段/结束时间却已超过上限。
    try:
        gap = float(tm.get("gap", 0))
        elapsed = 0.0
        if not math.isfinite(gap) or gap < 0:
            raise ValueError
        for segment in tm.get("segments", []):
            duration = float(segment["dur"])
            start = float(segment.get("start", elapsed))
            end = float(segment.get("end", start + duration + gap))
            if not all(math.isfinite(v) and v >= 0 for v in (duration, start, end)) or end < start:
                raise ValueError
            elapsed = end
            if max(start + duration, end) > qcfg.MAX_DURATION:
                checked_duration(max(start + duration, end), "分段时间轴")
    except (TypeError, ValueError, KeyError, OverflowError):
        die("时间轴无效。请调整脚本/口播稿或音频后重新运行 voice。")
    return total


def media_duration(path: Path, segment: bool = False) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True)
    raw = result.stdout.strip()
    # 单句可以不足一秒,整片仍必须至少一秒;任何单句也不能超过上限。
    if segment:
        try:
            value = float(raw)
            if math.isfinite(value) and 0 < value < qcfg.MIN_DURATION:
                return value
        except (ValueError, OverflowError):
            pass
    return checked_duration(raw, "音视频实际时长")


def is_silent(meta: dict) -> bool:
    return meta["narration"] == "silent" if meta.get("narration") else meta.get("voice_mode") == "silent"


def archive_title(title: str) -> str:
    """Windows 文件名安全;不修改项目中原本的中文标题。"""
    return re.sub(r'[<>:"/\\\\|?*\x00-\x1f]', "-", title).strip(" .") or "未命名"


def proj_dir(name: str) -> Path:
    p = PROJECTS / name
    if not p.exists():
        die(f"项目不存在: {p}")
    return p


def resolve_ratio(key: str) -> tuple[int, int, str]:
    """比例 key → (宽, 高, 中文名)。

    自定义宽高需为 64..4000 的有限正数,长宽比最多 4:1。
    统一为短边 1080 的偶数画布,长边最多 4320;分辨率只做输出缩放。
    """
    key = (key or "9:16").strip()
    if key.startswith("custom:"):
        raw = key.split(":", 1)[1].lower().replace("×", "x").replace("*", "x")
        try:
            cw, ch = raw.split("x", 1)
            w, h = float(cw), float(ch)
            if not all(math.isfinite(v) and 64 <= v <= 4000 for v in (w, h)):
                raise ValueError
            if max(w, h) / min(w, h) > 4:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            die("自定义画幅无效:宽高必须是 64–4000 的有限正数,长宽比不能超过 4:1。请调整画幅。")
        cw = int(round(1080 * w / min(w, h) / 2) * 2)
        ch = int(round(1080 * h / min(w, h) / 2) * 2)
        return cw, ch, f"自定义 {w:g}×{h:g}"
    if key not in RATIOS:
        die(f"未知画幅: {key}。请选择预设比例或 custom:1080x1920。")
    r = RATIOS[key]
    return int(r["w"]), int(r["h"]), r.get("zh", key)


def slugify(name: str) -> str:
    s = re.sub(r"[^0-9A-Za-z_-]+", "-", name).strip("-").lower()
    if not s:
        die(f"--name 需要至少一个字母/数字(用于 Remotion 组合名): {name!r}")
    return s


def read_text_source(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in (".html", ".htm"):
        raw = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
        raw = re.sub(r"(?s)<[^>]+>", " ", raw)
        raw = re.sub(r"&[a-z]+;", " ", raw)
    return re.sub(r"[ \t\r\f\v]+", " ", raw)


# ────────────────────────────── styles ──────────────────────────────
def cmd_styles(args):
    fast = [s for s in CATALOG["styles"] if s["backend"] in FAST_BACKENDS]
    print(f"15 个风格,{len(fast)} 个已接上「一条命令直渲」的快车道,其余走逐帧代码管线(进阶):\n")
    for s in CATALOG["styles"]:
        tag = "★可出片" if s["backend"] in FAST_BACKENDS else "  未接入  "
        line = f'{tag}  {s["id"]:16s} {s["zh"]}    {s["feel"]}'
        print(line)
        if s.get("best_for"):
            print(f'{" ":22s}适合:{s["best_for"]}')
        if s.get("example"):
            print(f'{" ":22s}成片例:{s["example"]}')
    print("\n选风格:new/make 时 --style <id>;不确定就先用 mg-paperclip。")


# ────────────────────────────── new ──────────────────────────────
def default_theme(style_id: str) -> dict:
    if style_id == "mg-paperclip":
        return {
            "canvas": "#E8EDF0", "paper": "#FAF4E8", "white": "#FFFFFF",
            "ink": "#172838", "slate": "#3C5264", "muted": "#AFC0CB",
            "red": "#F04438", "green": "#14866D", "yellow": "#F6C453",
            "skin": "#FFD2AE", "skinShade": "#E8A77D",
        }
    return {}


SCRIPT_SKELETON_NOTE = (
    "text=字幕上显示的字;say 只在 TTS 合成时用(如「三个点四六」防止读成「三点四十六」)。"
    "事实只写来源里有的;来源里没有的,宁可删掉也不要编。"
)


def skeleton_film(name: str, style_id: str) -> dict:
    return {
        "note": "画面脚本:不改 TSX 也能出片。kind 可选 hook/flow/compare/verdict/checklist/cta,字段见 docs/短片工厂-使用指南.md。",
        "theme": default_theme(style_id),
        "header": "AI 时代 · 短片工厂",
        "footer": {"label": datetime.now().strftime("%Y.%m") + " · 短片工厂"},
        "beats": [
            {"id": "hook", "kind": "hook", "title": ["在这里放最狠的一句话", "第二行用红色强调"],
             "stamp": "可你根本不在场", "note": "开场 3 秒必须有会动的东西,别放静态封面。",
             "face": True, "phone": "shop"},
            {"id": "point1", "kind": "flow", "title": "把第一件事讲成三步",
             "steps": [{"label": "第一步", "icon": "照"}, {"label": "第二步", "icon": "▶"}, {"label": "第三步", "icon": "换"}],
             "big": "一个关键数字", "bigSub": "数字下面这行小字解释它", "stamp": "不是段子", "note": "数据必须来自来源。"},
            {"id": "point2", "kind": "compare", "title": "制造一次反转", "left": {"label": "LIVE"}, "right": {"label": "PLAYBACK"},
             "stamp": "反转图章", "lines": ["上一句铺垫", "下一句推翻它"], "note": "观众记住的就是这一下。"},
            {"id": "point3", "kind": "checklist", "title": "给观众能做的事", "note": "动作要具体到能立刻做。",
             "items": [
                 {"n": "01", "title": "第一件事", "sub": "具体怎么做,一句话", "icon": "锁", "tone": "green"},
                 {"n": "02", "title": "第二件事", "sub": "具体怎么做,一句话", "icon": "拒", "tone": "slate"},
                 {"n": "03", "title": "第三件事", "sub": "具体怎么做,一句话", "icon": "警", "tone": "red"},
             ]},
            {"id": "end", "kind": "cta", "title": ["收尾金句第一行", "第二行用红色"], "stamp": "转给谁,写清楚",
             "note": "转发理由越具体,越容易被转发。", "phone": "lock"},
        ],
    }


def cmd_new(args):
    style = STYLES.get(args.style)
    if not style:
        die(f"没有这个风格: {args.style} (用 film styles 查看)")
    duration = checked_duration(getattr(args, "duration", 35), "目标时长")
    rw, rh, _rzh = resolve_ratio(getattr(args, "ratio", "9:16"))
    d = PROJECTS / args.name
    if d.exists() and not args.force:
        die(f"目录已存在: {d} (加 --force 覆盖骨架)")
    (d / "out").mkdir(parents=True, exist_ok=True)
    slug = slugify(args.name)
    fb = skeleton_film(args.name, args.style)["beats"]
    meta = {"name": args.name, "slug": slug, "style": args.style,
            "title": args.title or args.name, "created": datetime.now().isoformat(timespec="seconds"),
            "ratio": getattr(args, "ratio", "9:16"),
            "voice": getattr(args, "voice", "zh-CN-YunjianNeural"),
            "video_type": getattr(args, "type", "explain"),
            "narration": getattr(args, "narration", "") or "voice",
            "resolution": getattr(args, "resolution", "") or qcfg.DEFAULT_RESOLUTION,
            "fps": int(getattr(args, "fps", 0) or qcfg.DEFAULT_FPS),
            "tier": getattr(args, "tier", "") or qcfg.DEFAULT_TIER,
            "duration": duration}
    (d / "project.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    segs = [{"id": b["id"], "role": "HOOK" if i == 0 else ("END" if i == len(fb) - 1 else "BUILD"),
             "title": b.get("title") if isinstance(b.get("title"), str) else (b.get("title") or [""])[0],
             "text": "", "rate": "+0%", "pitch": "+0Hz"}
            for i, b in enumerate(fb)]
    script = {"note": SCRIPT_SKELETON_NOTE, "source": "", "segments": segs}
    (d / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "film.json").write_text(json.dumps(skeleton_film(args.name, args.style), ensure_ascii=False, indent=2), encoding="utf-8")
    sb = {"brief": args.title or args.name, "style": args.style, "style_name": style["zh"],
          "duration": 0, "width": rw, "height": rh, "fps": int(qcfg.fps_of(meta)),
          "palette": {"primary": ["#172838", "#F04438"], "accent": [], "background": "#E8EDF0",
                      "text": "#172838", "muted": "#AFC0CB"},
          "techniques": ["粗描边贴纸", "slam 砸落", "crash-zoom 转场"], "render": {"codec": "h264", "scale": 1.0},
          "audio": {"recipe": style["music"]["recipe"], "sfx": []}}
    (d / "storyboard.json").write_text(json.dumps(sb, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "project": str(d), "next": [
        f'python tools/motion_design/film.py draft --project {args.name} --source 你的素材.txt',
        f'python tools/motion_design/film.py make --project {args.name}',
    ]}, ensure_ascii=False, indent=1))


# ────────────────────────────── draft ──────────────────────────────
DRAFT_SYSTEM = """你是短视频口播编剧。输出严格的 JSON(不要 markdown 代码块):
{"segments":[{"id":"hook","role":"HOOK","title":"...","text":"...","rate":"-4%","pitch":"-2Hz"}],
 "film":{"header":"...","footer":{"label":"..."},"beats":[ ... 与输入 beats 同数量、同 id、同 kind ... ]}}

硬规则:
0) 按「video_type」和「duration_seconds」写;char_budget 是硬约束,别超。
1) text 全角标点;百分号写成半角的 % (如 "100%"),不要写成 "100＝"。
2) 事实只准来自「来源」;来源没有的数字、日期、机构一律不写。不许编。
3) 不用「打X折」「X成」这类含糊量词;用绝对数或原文口径。
4) 每一拍都必须能被这一拍的画面画出来:数字、对比、步骤都要具体。
   若来源里有具体对象(人造太阳、血小板、脑电、飞行器等),把「画面该出现什么」
   写进 art 字段(这是给画师的画面要求,不会出现在成片上);
   note 字段是给观众看的一行短说明(≤20 字),不要写"画面出现…"这类制作指令。
   不要写「人物」「手机」「支付」这类与内容无关的元素。
5) beats 与 segments 一一对应:id 相同、顺序相同。
6) beats 字段只准用这些 kind:hook/flow/compare/verdict/checklist/cta。
   flow 用 steps(3项)+big+bigSub+stamp;compare 用 left/right+stamp+lines;
   verdict 用 statement+big+stamp;checklist 用 items(3项);cta 用 title(2行)+stamp;
   hook 用 title(2行)+stamp,可给 big/bigSub/spec(最多 4 行,值必须来自来源)。
   每一拍都可写 art(画面要求)和 note(≤20 字的观众向短句),都可省略。
7) 不要输出 visual/phone/face 字段:那是旧模板的固定构图,会让每个题材都长成
   「一张脸 + 一部手机」。画面归画面管线,你只负责把内容说具体。

8)【注意力法则】观众不是来听你讲道理的,是来看热闹的。这条比什么都重要。
   a) 前 3 秒的钩子必须具体到能想象出画面:一个"不该出现在这里"的小东西
      (趴在财报上的小黄鸭、给芯片浇水的小机器人、蹲在机柜上的猫)。
      它要**弱相关**于主题(别放完全无关的宠物),并且能被一句话转述。
      把它写进 hook 那一拍的 art 字段,并写明它会怎么动。
   b) 全片不许出现"所以/因此/总之/这就/首先我们来看"这种教科书连接词。
      换成短句、转折、问句、感叹。
   c) 每一拍都要有一处意外或冲突:反常识的数字、被误解的身份、让人想反驳的判断。
      宁可写"这事儿听着像笑话,但它是真的",也不要平铺直叙。
   d) 素材里最反常、最具体、最像人的那一个细节**必须出现在稿子里**(通常放 hook)。
      荒唐的对话、尴尬的误会、一个具体的场景 —— 这种才有人愿意转述。
      不要只挑"概念"和"结论"当内容。
   e) 用大白话。"后训练"说成"教机器人干活","算力"说成"芯片的力气";
      专业名词第一次出现时用一句话解释,之后可以放心用。
   f) 结尾给一个具体、能转述的动作(去看某个东西、去查某个数字、去问谁),
      不要"关注我了解更多"。
9) 事实仍然只来自素材(第 2 条)。钩子物是画面上的"意外",不是事实主张 ——
   它不许带数字、不许下结论、不许编造出处。
"""


# 模型偶尔把百分号写成全角等号("成功率逼近100＝"),配音会读成"一百等于",
# 画面上也是一串乱码。数字后面跟着全角等号,只可能是百分号。
_PCT_FIX = re.compile(r"(?<=[0-9])＝")
_PUNCT_FIX = str.maketrans({",": "，", ";": "；", ":": "：", "!": "！", "?": "？",
                            "％": "%", "（": "(", "）": ")"})


def fix_cn_text(text: str) -> str:
    """把模型写的中文文本收拾干净:全角标点、百分号误写。"""
    if not text:
        return text
    out = _PCT_FIX.sub("%", text)
    return out.translate(_PUNCT_FIX)


def _llm_configured() -> bool:
    try:
        if str(TOOLS) not in sys.path:
            sys.path.insert(0, str(TOOLS))
        import llm  # noqa: WPS433
        return bool(llm.available())
    except Exception:
        return False


def cmd_draft(args):
    d = proj_dir(args.project)
    src = Path(args.source)
    if not src.exists():
        die(f"来源文件不存在: {src}")
    text = read_text_source(src)[: args.max_chars]
    script = json.loads((d / "script.json").read_text(encoding="utf-8"))
    film = json.loads((d / "film.json").read_text(encoding="utf-8"))
    sys.path.insert(0, str(TOOLS))
    import llm as mllm

    if not mllm.available():
        die("没有配置 MOTION_LLM_*,draft 不可用。手填 script.json 后直接跑 make;"
            "或用 film make 也会跳过起草、按骨架渲一版占位片。")
    meta = json.loads((d / "project.json").read_text(encoding="utf-8"))
    vtype = TYPES.get(meta.get("video_type", "explain"), TYPES["explain"])
    dur = int(meta.get("duration", 35) or 35)
    # 中文口播约每秒 4.6 字,反推这个时长该写多少字,写多了模型会超
    chars = max(40, int(dur * 4.6))
    user = {
        "style": STYLES.get(meta.get("style", ""), {}).get("zh", ""),
        "video_type": vtype["zh"],
        "type_desc": vtype["desc"],
        "pace": vtype["pace"],
        "duration_seconds": dur,
        "char_budget": f"全文约 {chars} 字(±15%),不要超",
        "beats_schema": [{"id": b["id"], "kind": b["kind"]} for b in film["beats"]],
        "source": text,
    }
    # 华尔街逐帧后端的画面参数由这里带出:巨数、柱子形态、眉题都在逐帧舞台上画。
    # 数字照样只准来自来源(第 2 条);bars 是同一坐标系里的相对高度(0~1)。
    if is_playwright(meta):
        user["wallstreet_beats"] = (
            "每一拍额外写这四个画面字段:big=这一镜的巨数(美元数字写全,如 \"$80,000,000,000\","
            "只准用来源里的数字;没有数字就留空字符串);"
            "bars=[4 个 0~1 的相对高度,同一坐标系里这组柱子的形态,没有可比数字就留空];"
            "stamp=眉题短标签(如 MARKET NOTE / FOLLOW THE MONEY);en=眉题后的英文小字。"
            "hook 那拍的 art 字段继续写钩子物(舞台上会画一只小黄鸭)。")
    # 模型偶发返回坏 JSON(少一个逗号、字符串里带未转义引号),或者段落 id 对不上。
    # 这不该让整条任务失败:带确切错误重试一次,成功率远高于直接放弃。
    ids = [b["id"] for b in film["beats"]]
    data = None
    last_error = ""
    for attempt in (1, 2):
        out = mllm.complete(DRAFT_SYSTEM, json.dumps(user, ensure_ascii=False),
                            max_tokens=12000, temperature=0.5 if attempt == 1 else 0.2,
                            timeout=600)
        try:
            candidate = mllm.extract_json(out)
        except (ValueError, json.JSONDecodeError) as e:
            last_error = f"返回的不是合法 JSON:{str(e)[:120]}"
            continue
        segs = candidate.get("segments") or []
        beats = (candidate.get("film") or {}).get("beats") or []
        if [s.get("id") for s in segs] != ids or [b.get("id") for b in beats] != ids:
            last_error = f"段落/节拍 id 必须依次是 {', '.join(ids)}"
            continue
        bad_kind = next((b.get("kind") for b in beats if b.get("kind") not in BEAT_KINDS), None)
        if bad_kind:
            die(f"非法 kind: {bad_kind}")
        data = candidate
        break
    if data is None:
        die(f"模型起草失败({last_error})。请重试,或手填 script.json。")
    segs = data.get("segments") or []
    beats = (data.get("film") or {}).get("beats") or []
    for s in segs:
        # 半角标点统一成全角,字幕排版才不会出现窄逗号
        s["text"] = fix_cn_text(str(s.get("text", "")))
    script["segments"] = segs
    script["source"] = str(src)
    script["note"] = SCRIPT_SKELETON_NOTE
    film = normalize_film(film)
    film["beats"] = beats
    if data.get("film", {}).get("header"):
        film["header"] = data["film"]["header"]
    if data.get("film", {}).get("footer", {}).get("label"):
        film["footer"]["label"] = data["film"]["footer"]["label"]
    (d / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "film.json").write_text(json.dumps(film, ensure_ascii=False, indent=2), encoding="utf-8")
    total_chars = sum(len(s["text"]) for s in segs)
    est = round(total_chars / 4.6, 1)
    want = int(meta.get("duration", 35) or 35)
    warn = ""
    if est > want * 1.25 or est < want * 0.6:
        warn = f"字数与目标时长({want}s)不匹配,实测约 {est}s"
    print(json.dumps({"ok": True, "segments": len(segs), "chars": total_chars,
                      "est_seconds": est, "target_seconds": want, "warning": warn},
                     ensure_ascii=False))


# ────────────────────────────── voice ──────────────────────────────
REFINE_SYSTEM = """你是严格的短视频编辑复审,不是再写一遍。输入是一份已经成稿的口播脚本和画面节拍。
按七条审:
1. 前 3 秒钩子必须具体、可感知,不能是"今天我们来聊聊"这类套话。
   观众不是来听道理的,是来看热闹的:钩子得是"不该出现在这里"的一个小东西,
   弱相关于主题,并且能被一句话转述。它写在 hook 那一拍的 art 里。
2. 每个事实必须来自素材原文;素材里没有的数字、时间、结论一律不许出现,宁可不写。
3. 口播字数贴合目标时长(中文约每秒 4.6 字,允许 ±15%)。
4. 画面节拍的 title 一眼能读完(≤14 字),note/stamp 要具体,不写空话。
5. 不许有"所以/因此/总之/这就/首先我们来看"这种教科书连接词;
   每一拍都要有一处意外、冲突或让人想反驳的判断。
6. 素材里最反常、最像人的那个细节必须在稿子里;只讲概念和结论的稿子要重写。
7. note 是给观众看的一行短说明(≤20 字),不是制作指令 ——
   写"机器人剖面标出芯片…"这种就当没写。
只输出严格 JSON(不要 markdown):
{"segments":[{"id":"...","text":"...","rate":"+0%","pitch":"+0Hz"}],
 "film":{"beats":[{"id":"...","kind":"...","title":["第一行","第二行"],"note":"...","stamp":"...",
                   "big":"...","bigSub":"...","left":{"label":"..."},"right":{"label":"..."},
                   "items":[{"title":"...","sub":"..."}]}]},
 "changes":["一句一条改动理由"]}
id 与 kind 必须与输入同序、同名,不增不减。"""

NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _numerals(text: str) -> set[str]:
    return set(NUM_RE.findall(text or ""))


def cmd_refine(args):
    """档位要求的复审改稿:模型改稿 → 结构/事实/字数三重校验,不过就整轮丢弃。"""
    d = proj_dir(args.project)
    meta = json.loads((d / "project.json").read_text(encoding="utf-8"))
    script = json.loads((d / "script.json").read_text(encoding="utf-8"))
    film = json.loads((d / "film.json").read_text(encoding="utf-8"))
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    import llm as mllm

    if not mllm.available():
        die("没有配置模型,复审改稿不可用")
    src = script.get("source") or ""
    source_text = read_text_source(Path(src)) if src and Path(src).exists() else ""
    dur = int(meta.get("duration", 35) or 35)
    budget = max(40, int(dur * 4.6))
    old_ids = [s.get("id") for s in script.get("segments", [])]
    old_kinds = [b.get("kind") for b in film.get("beats", [])]
    user = {
        "duration_seconds": dur,
        "char_budget": f"全文约 {budget} 字(±15%)",
        "source": source_text[:12000],
        "segments": [{"id": s.get("id"), "text": s.get("text", "")} for s in script.get("segments", [])],
        "beats": film.get("beats", []),
        "round": getattr(args, "round", 1),
    }
    user_text = json.dumps(user, ensure_ascii=False)
    # 模型偶发返回坏 JSON(少逗号、多写一句解释)。一次重试比整轮作废划算:
    # 复审是按轮次计价的,格式错误不是内容问题。
    data = None
    last_err = ""
    for attempt in (1, 2):
        out = mllm.complete(REFINE_SYSTEM, user_text, max_tokens=12000,
                            temperature=0.4 if attempt == 1 else 0.1, timeout=600)
        try:
            data = mllm.extract_json(out)
            break
        except (ValueError, json.JSONDecodeError) as e:
            last_err = str(e)[:200]
            if attempt == 2:
                die(f"复审改稿返回的不是合法 JSON({last_err}),整轮丢弃")
    segs = data.get("segments") or []
    beats = (data.get("film") or {}).get("beats") or []
    if [s.get("id") for s in segs] != old_ids:
        die("复审改稿的段落 id 与原文不一致,整轮丢弃")
    if [b.get("id") for b in beats] != [b.get("id") for b in film.get("beats", [])]:
        die("复审改稿的节拍 id 与原文不一致,整轮丢弃")
    if [b.get("kind") for b in beats] != old_kinds:
        die("复审改稿改了镜头类型,整轮丢弃")
    texts = [str(s.get("text") or "").strip() for s in segs]
    if any(not t for t in texts):
        die("复审改稿出现空句,整轮丢弃")
    total = sum(len(t) for t in texts)
    if not (budget * 0.6 <= total <= budget * 1.3):
        die(f"复审改稿字数 {total} 不在目标 {budget} 的 ±15% 附近,整轮丢弃")
    # 事实闸门:不允许出现素材和原稿里都没有的数字
    allowed = _numerals(source_text) | _numerals("".join(s.get("text") or "" for s in script.get("segments", [])))
    invented = sorted(_numerals("".join(texts)) - allowed)
    if invented:
        die("复审改稿写出了素材里没有的数字(" + ", ".join(invented) + "),整轮丢弃")
    for s, t in zip(segs, texts):
        s["text"] = fix_cn_text(t)
        s.setdefault("rate", "+0%")
        s.setdefault("pitch", "+0Hz")
    # 合并,不是替换:模型只被要求改 text,但常顺手删掉 role/title/rate,
    # 替换掉会让配音丢角色、字幕丢小标题,还会把音频缓存签名打乱。
    old_by_id = {s.get("id"): s for s in script.get("segments", [])}
    merged = []
    for s in segs:
        base = dict(old_by_id.get(s.get("id")) or {})
        base.update({k: v for k, v in s.items() if v not in (None, "")})
        merged.append(base)
    script["segments"] = merged
    script["note"] = f"{script.get('note','')} · 复审 {getattr(args,'round',1)} 轮"
    # 节拍同理:模型只该改文案,不该把 spec/steps/items/left/right 整块抹掉。
    # 画面靠这些字段画,丢了就是空框。
    old_beats = {b.get("id"): b for b in film.get("beats", [])}
    kept = []
    for b in beats:
        base = dict(old_beats.get(b.get("id")) or {})
        base.update({k: v for k, v in b.items() if v not in (None, "", [], {})})
        kept.append(base)
    film["beats"] = kept
    # 合并之后再规范化,否则 spec/steps 这些简写不会被转成模板要的形状。
    film = normalize_film(film)
    (d / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "film.json").write_text(json.dumps(film, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "round": getattr(args, "round", 1), "chars": total,
                      "changes": data.get("changes") or []}, ensure_ascii=False))


def cmd_voice(args):
    d = proj_dir(args.project)
    out = d / "out"
    meta = json.loads((d / "project.json").read_text(encoding="utf-8"))
    if not args.audio:
        stage("配音", "合成中文口播")
    if meta.get("duration") is not None:
        checked_duration(meta["duration"], "目标时长")
    if is_silent(meta) and args.audio:
        die("当前为无口播模式,不能同时使用 --audio 真人录音。请移除录音参数;如需口播,先切换为有口播并重新运行 voice。")
    if args.audio:
        meta["voice_mode"] = "human"
        json.dump(meta, (d / "project.json").open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
        src = Path(args.audio)
        if not src.exists():
            die(f"录音不存在: {src}")
        stage("配音", "对齐真人录音")
        raw = out / "narr_raw.wav"
        sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
            "-af", "highpass=f=80,silenceremove=start_periods=1:start_threshold=-50dB,"
                   "areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse",
            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", raw], check=True)
        media_duration(raw)
        r = sh([PY, TOOLS / "align_narration.py", "--project", d, "--audio", raw,
                "--max-len", "16", "--tail", "0.8"])
        if r.returncode:
            die("align_narration 失败,看上面输出")
        validate_timing(json.loads((d / "timing.json").read_text(encoding="utf-8")))
        narr = out / "narr_raw.wav"
        I, TP = _loudness(narr)
        g = -16.0 - I
        sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", narr, "-af",
            f"volume={g:.2f}dB,alimiter=limit=0.87:attack=5:release=60:level=false",
            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", out / "narration_human.wav"], check=True)
        print(json.dumps({"ok": True, "mode": "human", "loudnorm": _loudness(out / "narration_human.wav")}, ensure_ascii=False))
        return
    if is_silent(meta):
        # 无口播:不合成人声。
        # 没有真实音频就没有实测时间轴,只能按字数估算,再对齐到用户要的时长。
        meta["voice_mode"] = "silent"
        json.dump(meta, (d / "project.json").open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
        script = json.loads((d / "script.json").read_text(encoding="utf-8"))
        gap = 0.22
        rows = []
        for i, sg in enumerate(script.get("segments", [])):
            text = (sg.get("text") or sg.get("say") or "").strip()
            if not text:
                continue
            rows.append({"id": sg.get("id") or f"s{i+1}", "text": text,
                         "dur": round(len(text) / 4.6, 3)})   # 中文口播约 4.6 字/秒
        if not rows:
            die("没有可排的内容(稿子还是空的)")
        gaps = gap * max(0, len(rows) - 1)
        raw = sum(r["dur"] for r in rows)
        target = float(meta.get("duration") or 0)
        k = 1.0
        if target > 0 and raw > 0:
            k = max(0.6, min(2.0, (target - gaps) / raw))
        for r in rows:
            r["dur"] = round(r["dur"] * k, 3)
        total = checked_duration(sum(r["dur"] for r in rows) + gaps)
        total = round(total, 3)
        t = 0.0
        for r in rows:
            r["start"] = round(t, 3)
            t += r["dur"] + gap
            r["end"] = round(t - gap, 3)
        (d / "timing.json").write_text(json.dumps(
            {"gap": gap, "total": total, "segments": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        # 静音轨:保证成片有正常的音轨(配乐 + 静音人声),响度才拉得住
        sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
            "-i", "anullsrc=r=48000:cl=stereo", "-t", str(total),
            "-c:a", "pcm_s16le", out / "silence.wav"], check=True)
        r = sh([PY, TOOLS / "make_subs.py", "--project", d, "--max-len", "16"])
        if r.returncode:
            die("make_subs 失败")
        print(json.dumps({"ok": True, "mode": "silent", "total": total,
                          "target": target or None, "note": "无口播:时间轴按字数估算"},
                         ensure_ascii=False))
        return
    meta["voice_mode"] = "tts"
    json.dump(meta, (d / "project.json").open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
    voice = meta.get("voice") or "zh-CN-YunjianNeural"
    r = sh([PY, TOOLS / "voiceover.py", "--project", d, "--provider", args.provider,
            "--voice", voice, "--gap", "0.22"])
    if r.returncode:
        die("voiceover 失败")
    validate_timing(json.loads((d / "timing.json").read_text(encoding="utf-8")))
    r = sh([PY, TOOLS / "make_subs.py", "--project", d, "--max-len", "16"])
    if r.returncode:
        die("make_subs 失败")
    print(json.dumps({"ok": True, "mode": "tts"}, ensure_ascii=False))


def _loudness(f: Path) -> tuple[float, float]:
    s = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(f), "-af", "ebur128=peak=true",
                        "-f", "null", "-"], capture_output=True, text=True).stderr
    tail = s[s.rfind("Summary:"):]
    I = float(re.search(r"I:\s+(-?\d+\.\d+) LUFS", tail).group(1))
    TP = float(re.search(r"Peak:\s+(-?\d+\.\d+) dBFS", tail).group(1))
    return I, TP


# ────────────────────────────── scene(模型写画面) ──────────────────────────────
def scene_slug(meta: dict) -> str:
    return sc.scene_filename(str(meta.get("slug") or meta.get("name") or ""))


def scene_path(meta: dict) -> Path:
    return sc.generated_dir(RROOT) / f"{scene_slug(meta)}.tsx"


def has_scene(meta: dict) -> bool:
    """有专属画面文件,并且已经被注册进 registry。"""
    p = scene_path(meta)
    reg = sc.generated_dir(RROOT) / sc.REGISTRY_NAME
    try:
        body = reg.read_text(encoding="utf-8")
    except OSError:
        return False
    # 精确匹配键,别让 "sun" 命中 "sunrise"
    return p.is_file() and f'"{scene_slug(meta)}":' in body


def scene_motion_gaps(meta: dict) -> list[str]:
    """已有专属画面里「没有画面」或「整段不动」的 beat id。

    现在的布局是"每拍一个文件 + 一个聚合文件"。聚合文件只做分发(它自己对
    motion 一无所知),所以必须查**单拍文件**,不能查聚合文件 —— 否则好好的
    画面会被判成静止,重建时白跑一次模型。
    """
    try:
        film = json.loads((PROJECTS / meta["name"] / "film.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return []
    beat_ids = [str(b.get("id")) for b in film.get("beats") or [] if b.get("id")]
    if not beat_ids:
        return []
    slug = str(meta.get("slug") or meta.get("name") or "")
    per_beat = {p.stem: p for p in sc.beat_paths(RROOT, slug)}
    if per_beat:
        gaps: list[str] = []
        for bid in beat_ids:
            path = per_beat.get(sc.beat_stem(slug, bid))
            if path is None:
                gaps.append(bid)
                continue
            try:
                code = sc.strip_comments(path.read_text(encoding="utf-8"))
            except OSError:
                gaps.append(bid)
                continue
            if not any(h in code for h in sc._MOTION_HINTS):  # noqa: SLF001
                gaps.append(bid)
        return gaps

    # 老的整份文件布局:沿用原来的分支分析
    p = scene_path(meta)
    try:
        src = p.read_text(encoding="utf-8")
    except OSError:
        return []
    code = sc.strip_comments(src)  # noqa: SLF001
    drawn = set(sc._BRANCH_RE.findall(code)) | sc.beat_mentions(code, beat_ids)  # noqa: SLF001
    kinds = {str(b.get("id")): str(b.get("kind") or "") for b in film.get("beats") or [] if b.get("id")}
    kinds_drawn = set(sc._KIND_BRANCH_RE.findall(code))  # noqa: SLF001
    missing = [b for b in beat_ids if b not in drawn and kinds.get(b) not in kinds_drawn]
    if missing:
        return missing
    if not any(h in code for h in sc._MOTION_HINTS):  # noqa: SLF001
        return beat_ids
    return []


def sync_scene_registry(live_slugs: set[str] | None = None) -> dict:
    """重建 src/generated/registry.ts;给了 live_slugs 就顺手删掉死项目的产物。"""
    return sc.sync_scene_registry(RROOT, live_slugs)


def _live_slugs() -> set[str]:
    slugs: set[str] = set()
    if not PROJECTS.exists():
        return slugs
    for p in PROJECTS.iterdir():
        pj = p / "project.json"
        if not pj.is_file():
            continue
        try:
            m = json.loads(pj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        slugs.add(sc.scene_filename(str(m.get("slug") or m.get("name") or p.name)))
    return slugs


def _record_scene(d: Path, meta: dict, status: str, reason: str = "") -> None:
    """把专属画面的结果写进 project.json。

    以前失败只打一行日志就退回模板,用户在作品详情里看不出这条片子
    是"模型画的专属画面"还是"通用 PPT 模板"—— 两者观感差得很远。
    这里把状态和原因记下来,界面直接显示。
    """
    meta["scene"] = {"status": status, "reason": reason[:200]}
    try:
        (d / "project.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _scene_discard(why: str) -> None:
    print(f"      ! 专属画面未采用:{why};继续用模板渲染。", flush=True)


def _draw_one_beat(mllm, gen: Path, film: dict, meta: dict, beat: dict, *,
                   slug: str, index: int, total: int, width: int, height: int) -> tuple[str, str, str]:
    """画一拍。返回 (beat_id, 组件名或空串, 失败原因)。

    单拍失败只影响这一拍:其它拍照画,聚合文件里这一拍落到内置兜底。
    每拍最多试 3 次,每次把确切错误回给模型。
    """
    bid = str(beat.get("id"))
    name = sc.beat_stem(slug, bid)
    system, user = sc.build_beat_prompt(film, meta, beat, width=width, height=height,
                                        index=index, total=total)
    user = user + chr(10) + chr(10) + sc.OUTPUT_REMINDER
    why = "没有调用模型"
    for attempt in range(1, 4):
        try:
            raw = mllm.complete(system, user, max_tokens=12000,
                                temperature=0.35 if attempt == 1 else 0.2, timeout=600)
        except Exception as e:  # noqa: BLE001 - 单拍失败不该打断整条
            why = type(e).__name__ + ": " + str(e)[:160]
            continue
        candidate = sc.extract_tsx(raw)
        ok, why = sc.validate_beat_source(candidate, beat)
        if ok:
            probe = gen / (name + ".probe.tsx")
            try:
                probe.write_text(candidate.rstrip() + chr(10), encoding="utf-8", newline=chr(10))
                ok, why = sc.check_scene_syntax(probe, composer=RROOT)
            finally:
                probe.unlink(missing_ok=True)
        if ok:
            target = gen / (name + ".tsx")
            target.write_text(candidate.rstrip() + chr(10), encoding="utf-8", newline=chr(10))
            return bid, name, ""
        # 把确切错误回给模型;它自己写的错自己最容易改对
        user = (user + chr(10) + chr(10) + "上一版不能直接用:" + why[:300]
                + chr(10) + "上一版开头:" + chr(10) + candidate[:900]
                + chr(10) + chr(10) + sc.OUTPUT_REMINDER)
    return bid, "", why


def cmd_scene(args):
    """让模型为这条片子写专属画面 —— **一拍一个组件**,并发画完再拼起来。

    以前是一次让模型写完 5 拍的整份 TSX(约 22KB)。实测它会稳定地只写到
    第 4 拍就停(语法还是好的),校验按"缺拍"拒掉,整片退回通用模板 ——
    用户看到的就是 PPT。拆成一拍一件小事之后每件只有 3~5KB,写完立刻校验,
    坏一拍不影响别的拍。

    每拍之间互相独立,所以并发画(默认 3 路):串行是 5×4 分钟,并发后是
    两轮左右。并发数可用 MOTION_SCENE_JOBS 调。
    """
    import concurrent.futures as futures

    d = proj_dir(args.project)
    meta = json.loads((d / "project.json").read_text(encoding="utf-8"))
    film = normalize_film(json.loads((d / "film.json").read_text(encoding="utf-8")))
    beats = [b for b in film.get("beats") or [] if b.get("id")]
    if not beats:
        die("film.json 里没有节拍,先 draft 或手写看板")
    sys.path.insert(0, str(TOOLS))
    import llm as mllm

    if not mllm.available():
        _record_scene(d, meta, "failed", "未配置模型,没有生成专属画面")
        if getattr(args, "quiet", False):
            return
        die("没有配置 MOTION_LLM_*,scene 不可用。画面会继续用通用模板渲染。")

    rw, rh, _ = resolve_ratio(meta.get("ratio", "9:16"))
    gen = sc.generated_dir(RROOT)
    gen.mkdir(parents=True, exist_ok=True)
    slug = str(meta.get("slug") or meta.get("name") or "")
    total = len(beats)
    try:
        jobs = max(1, min(4, int(os.environ.get("MOTION_SCENE_JOBS", "3"))))
    except ValueError:
        jobs = 3

    stage("画面", "模型正在为 " + str(total) + " 拍各画一张专属画面")
    print("      · 并发 " + str(jobs) + " 路,每拍最多试 3 次", flush=True)
    results: dict[str, tuple[str, str]] = {}
    done = 0
    with futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        pending = {
            pool.submit(_draw_one_beat, mllm, gen, film, meta, beat, slug=slug,
                        index=i, total=total, width=rw, height=rh): str(beat.get("id"))
            for i, beat in enumerate(beats)
        }
        for fut in futures.as_completed(pending):
            bid, comp, why = fut.result()
            done += 1
            results[bid] = (comp, why)
            if comp:
                stage("画面", "已完成 " + str(done) + "/" + str(total) + " · " + bid)
                print("      · 画面 " + str(done) + "/" + str(total) + " " + bid + " 完成", flush=True)
            else:
                stage("画面", "已完成 " + str(done) + "/" + str(total) + " · " + bid + "(兜底)")
                print("      ! 画面 " + str(done) + "/" + str(total) + " " + bid
                      + " 没画出来:" + why[:90], flush=True)

    components = [c for c, _ in results.values() if c]
    failed = [b for b, (c, _) in results.items() if not c]
    notes = [b + ": " + results[b][1][:80] for b in failed]
    if not components:
        _scene_discard("每一拍都没生成成功:" + (notes[0] if notes else "未知原因"))
        _record_scene(d, meta, "failed", "所有拍都没画出来;" + "; ".join(notes)[:160])
        return

    # 聚合:按 beat.id 分发到各拍组件;没画出来的拍落到内置兜底。
    drawn = [b for b in beats if results.get(str(b.get("id")), ("",))[0]]
    comps = [results[str(b.get("id"))][0] for b in drawn]
    agg = sc.write_scene_aggregator(RROOT, slug, drawn, comps, width=rw, height=rh)
    ok, why = sc.check_scene_syntax(agg, composer=RROOT)
    if not ok:
        agg.unlink(missing_ok=True)
        _scene_discard("聚合文件语法校验失败:" + why[:160])
        _record_scene(d, meta, "failed", "聚合失败:" + why[:160])
        return
    reg = sync_scene_registry(_live_slugs())
    if failed:
        _record_scene(d, meta, "partial",
                      "这些拍用兜底画面:" + ", ".join(failed) + ";" + "; ".join(notes)[:120])
    else:
        _record_scene(d, meta, "ok", "")
    print(json.dumps({"ok": True, "scene": str(agg), "beats_drawn": len(components),
                      "beats_failed": failed, "registered": reg.get("modules", []),
                      "note": "专属画面已生成:render 会优先用 scene-<slug>"},
                     ensure_ascii=False))


# ────────────────────────────── build ──────────────────────────────
SFX_BY_KIND = {
    "hook": [("impact", 0.5, -3.0)],
    "flow": [("impact", 0.0, -3.0), ("boom", 2.0, -2.0)],
    "compare": [("impact", 2.233, -2.0)],
    "verdict": [("impact", 1.333, -2.0)],
    "checklist": [("pop", 0.833, -4.0), ("pop", 2.233, -4.0), ("pop", 3.633, -4.0)],
    "cta": [("impact", 2.5, -3.0)],
}


def refresh_storyboard(d: Path, style: dict):
    tm = json.loads((d / "timing.json").read_text(encoding="utf-8"))
    film = json.loads((d / "film.json").read_text(encoding="utf-8"))
    sb = json.loads((d / "storyboard.json").read_text(encoding="utf-8"))
    # TTS 路只有 dur/gap;真人路有绝对 start/end。统一成绝对时间。
    gap = float(tm.get("gap", 0))
    t = 0.0
    for s in tm["segments"]:
        s.setdefault("start", round(t, 3))
        s.setdefault("end", round(t + float(s["dur"]) + gap, 3))
        t = float(s["end"])
    (d / "timing.json").write_text(json.dumps(tm, ensure_ascii=False, indent=2), encoding="utf-8")
    starts = {s["id"]: float(s["start"]) for s in tm["segments"]}
    ends = {s["id"]: float(s["end"]) for s in tm["segments"]}
    kinds = {b["id"]: b.get("kind", "quote") for b in film["beats"]}
    sfx: list[dict] = []
    order = [b["id"] for b in film["beats"]]
    for i, bid in enumerate(order):
        t0 = starts[bid]
        if i > 0:
            sfx.append({"name": "whoosh", "t": round(t0 - 0.25, 3), "gain": -5.0})
        for name, off, gain in SFX_BY_KIND.get(kinds[bid], []):
            t = t0 + off
            if name == "impact" and off == 0.5 and bid == order[0]:
                t = 0.5
            # 一拍可能比固定偏移还短(短片的收尾拍常常只有 1.x 秒)。
            # 落在拍外的音效根本不会响,却会让审片判「音效未落在期望点」——
            # 直接丢掉,而不是硬塞一个够不到的时间。
            if t > ends[bid] - 0.05:
                continue
            sfx.append({"name": name, "t": round(t, 3), "gain": gain})
        if kinds[bid] == "hook" and film.get("split"):
            split = float(film["split"])
            if split < ends[bid] - 0.05:
                sfx.append({"name": "impact", "t": round(split, 3), "gain": -2.0})
        if kinds[bid] == "cta" and bid == order[-1]:
            t = max(t0 + 0.05, ends[bid] - 0.6)
            sfx.append({"name": "reverse_cymbal", "t": round(t, 3), "gain": -4.0})
    sb["duration"] = round(float(tm["total"]), 3)
    sb["audio"]["sfx"] = sorted(sfx, key=lambda x: x["t"])
    (d / "storyboard.json").write_text(json.dumps(sb, ensure_ascii=False, indent=2), encoding="utf-8")
    return sb, tm


def recipe_exists(recipe: str) -> tuple[bool, str]:
    """校验配乐配方是否真的存在。

    风格表里的 recipe 是我手写的,曾经写过不存在的名字(世界族没有 folk、
    retro 族没有 vinyl),结果用户点生成才在配乐那一步炸掉。
    这里提前检查,并给出一条能直接照抄的修正建议。
    """
    fam, _, form = (recipe or "").partition(":")
    try:
        sys.path.insert(0, str(REPO / "lib" / "motion_design" / "mgstyles" / "audio"))
        import inspect

        from mgaudio import recipes as R  # noqa: WPS433
        mod = getattr(R, fam, None)
        if mod is None:
            return False, f"没有 {fam} 族,可选:chill/club/fun/retro/world"
        fns = {n for n, _ in inspect.getmembers(mod, inspect.isfunction) if not n.startswith("_")}
        # 把工具函数排掉,只留曲式
        util = {"bass_events", "chord_tone_melody", "comp_events", "fade", "layer",
                "new_mix", "ns", "pc", "place_notes", "place_segments", "midi"}
        forms = sorted(fns - util)
        if form not in forms:
            return False, f"{fam} 族没有 {form};可用: {', '.join(forms)}"
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, f"无法校验(音频库加载失败):{type(e).__name__}: {e}"


def _sync_templates() -> None:
    """把安装目录里的渲染模板同步进工作区。

    工作区是第一次启动时种下的,应用升级之后它不会自己更新 —— 于是用户
    一直在用旧模板渲染(字幕压字、文字溢出都是旧模板的问题)。
    src/generated/ 里模型写的专属画面不动。
    """
    if WORKSPACE == REPO:
        return
    try:
        if str(TOOLS) not in sys.path:
            sys.path.insert(0, str(TOOLS))
        from app_paths import get_paths, sync_composer_templates
        updated = sync_composer_templates(get_paths(REPO, os.environ, validate=False))
        if updated:
            print(f"      · 已把 {len(updated)} 个渲染模板更新到工作区", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"      ! 模板同步跳过({type(e).__name__})", flush=True)


def cmd_build(args):
    d = proj_dir(args.project)
    meta = json.loads((d / "project.json").read_text(encoding="utf-8"))
    if meta.get("duration") is not None:
        checked_duration(meta["duration"], "目标时长")
    resolve_ratio(meta.get("ratio", "9:16"))
    if not (d / "timing.json").exists():
        die("先跑 voice(或 make)")
    stage("装配", "字幕、配乐与混音")
    validate_timing(json.loads((d / "timing.json").read_text(encoding="utf-8")))
    silent = is_silent(meta)
    human = not silent and meta.get("voice_mode") == "human" and (d / "out" / "narration_human.wav").exists()
    if human:
        media_duration(d / "out" / "narration_human.wav")
    elif not silent:
        timing = json.loads((d / "timing.json").read_text(encoding="utf-8"))
        measured = sum(media_duration(Path(s["wav"]), segment=True) for s in timing["segments"])
        checked_duration(measured + float(timing.get("gap", 0)) * len(timing["segments"]))
    style = STYLES.get(meta["style"]) or {}
    # 16 种风格都有一键出片的通用模板(贴纸走 StickerFilm,其余走 StyleFilm)。
    # 只有既不在表里、又不是这两种后端的风格才需要拦下 —— 否则会被静默渲成贴纸,
    # 交付一条「风格不符」的片子。
    if (style.get("backend") or "") not in FAST_BACKENDS:
        die(f"风格 {meta['style']} 没有可用的渲染后端({style.get('backend') or '空'})。")
    recipe = (style.get("music") or {}).get("recipe", "fun:explainer")
    ok, why = recipe_exists(recipe)
    if not ok:
        die(f"配乐配方 {recipe} 不可用:{why}")
    # 分句(仅 TTS 路需要;human 路已由 align 生成)
    if not human and not (d / "subtitles.json").exists():
        r = sh([PY, TOOLS / "make_subs.py", "--project", d, "--max-len", "16"])
        if r.returncode:
            die("make_subs 失败")
    sb, tm = refresh_storyboard(d, style)
    # 音乐
    sh([PY, TOOLS / "audio.py", "--storyboard", d / "storyboard.json",
        "--out", d / "out" / "music.wav", "--recipe", style.get("music", {}).get("recipe", "fun:explainer"),
        "--report", d / "out" / "music.qc.json"], check=True)
    # 人声轨
    pub = PUBLIC / meta["slug"]
    pub.mkdir(parents=True, exist_ok=True)
    if human:
        sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", d / "out" / "narration_human.wav",
            "-af", f"apad=whole_dur={tm['total']}", "-c:a", "pcm_s16le", d / "out" / "voice_pad.wav"], check=True)
        voice = d / "out" / "voice_pad.wav"
    elif silent:
        # 无口播:人声轨是等长静音,配乐照走,响度照常归一
        voice = d / "out" / "silence.wav"
        sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
            "-i", "anullsrc=r=48000:cl=stereo", "-t", str(tm["total"]),
            "-c:a", "pcm_s16le", voice], check=True)
    else:
        segs = tm["segments"]
        gap = float(tm.get("gap", 0))
        sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-t", str(gap), "-c:a", "pcm_s16le", d / "out" / "gap.wav"], check=True)
        lines = []
        for s in segs:
            lines += [f"file '{Path(s['wav']).resolve().as_posix()}'",
                      f"file '{(d / 'out' / 'gap.wav').resolve().as_posix()}'"]
        (d / "out" / "voice_list.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
            "-i", d / "out" / "voice_list.txt", "-c:a", "pcm_s16le", d / "out" / "voice_full.wav"], check=True)
        voice = d / "out" / "voice_full.wav"
    mv = style.get("music", {}).get("volume", 0.30)
    if silent:
        fc = (f"[0:a]volume={mv}[m];[1:a]volume=0[mute];"
              f"[m][mute]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
    else:
        fc = (f"[0:a]volume={mv}[m];[1:a]asplit=2[v1][v2];"
              f"[m][v2]sidechaincompress=threshold=0.035:ratio=12:attack=5:release=280[duck];"
              f"[v1][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
    sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", d / "out" / "music.wav", "-i", voice,
        "-filter_complex", fc, "-map", "[a]", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
        d / "out" / "mix_raw.wav"], check=True)
    I, TP = _loudness(d / "out" / "mix_raw.wav")
    g = -14.0 - I
    sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", d / "out" / "mix_raw.wav", "-af",
        f"volume={g:.2f}dB,alimiter=limit=0.87:attack=5:release=60:level=false",
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", d / "out" / "audio.wav"], check=True)
    shutil.copyfile(d / "out" / "audio.wav", pub / "audio.wav")
    # props:字幕 + 音频 + 画面脚本(带实测节拍)
    subs = json.loads((d / "subtitles.json").read_text(encoding="utf-8"))
    film = normalize_film(json.loads((d / "film.json").read_text(encoding="utf-8")))
    (d / "film.json").write_text(json.dumps(film, ensure_ascii=False, indent=2), encoding="utf-8")
    film["total"] = round(float(tm["total"]), 3)
    # 分辨率仅控制输出像素;各档保留同一套完整内容与转场。
    film["quality"] = qcfg.output_spec(meta)
    film["timing"] = {s["id"]: [round(float(s["start"]), 3), round(float(s["end"]), 3)] for s in tm["segments"]}
    cue1 = next((c["start"] for c in subs if 0 < c["start"] < film["timing"][film["beats"][0]["id"]][1]), None)
    film["split"] = round(float(cue1), 3) if cue1 else round(film["timing"][film["beats"][0]["id"]][1] * 0.4, 3)
    props = {"subs": [[c["start"], c["end"], c["text"]] for c in subs],
             "audioSrc": f"{meta['slug']}/audio.wav", "film": film}
    (pub / "props.json").write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
    _write_registry()
    print(json.dumps({"ok": True, "duration": film["total"], "loudnorm": [I, TP],
                      "human": human, "props": str(pub / "props.json")}, ensure_ascii=False))


def _write_registry():
    reg = {}
    for p in sorted(PROJECTS.iterdir()):
        tf, pj = p / "timing.json", p / "project.json"
        if not (tf.exists() and pj.exists()):
            continue
        m = json.loads(pj.read_text(encoding="utf-8"))
        style = m.get("style") or "mg-paperclip"
        backend = (STYLES.get(style) or {}).get("backend")
        if backend not in FAST_BACKENDS:
            continue
        # Playwright 逐帧后端不注册 Remotion 组合：它没有 sf-/scene- 组合，
        # 注册了只会多一条永远不会被渲染、却会让 --check 误判的组合。
        if backend == PLAYWRIGHT_BACKEND:
            continue
        rw, rh, _ = resolve_ratio(m.get("ratio", "9:16"))
        # 帧率进注册表:低帧率必须用「更少的帧」而不是「同帧数慢放」,
        # 否则片子会被拉长 30/24 倍,尾巴多出一段静音。
        fps = int(qcfg.fps_of(m))
        reg[m.get("slug", slugify(p.name))] = {
            "total": round(float(json.loads(tf.read_text(encoding="utf-8"))["total"]), 3),
            "w": rw, "h": rh,
            "style": style, "fps": fps,
        }
    body = ["// AUTO-GENERATED by tools/motion_design/film.py build — don't edit.",
            "export const STICKER_FILMS: Record<string, { total: number; w: number; h: number; style: string; fps: number }> = " +
            json.dumps(reg, ensure_ascii=False, indent=1) + ";", ""]
    (SRC / "stickerFilmRegistry.ts").write_text("\n".join(body), encoding="utf-8", newline="\n")
    # 项目可能被删了:顺带把没有对应项目的专属画面一起清掉,
    # 否则 Root 会把一个不存在的 slug 注册进组合,渲染时才炸。
    try:
        sync_scene_registry(set(reg))
    except Exception as e:  # noqa: BLE001
        print(f"  ! 专属画面注册表重建失败(不影响模板渲染): {type(e).__name__}: {e}", flush=True)


# ────────────────────────────── check / render / ship ──────────────────────────────
def cmd_registry(args):
    """重建 Remotion 组合注册表。

    注册表决定「哪些项目能被渲染成组合」。项目是在包里现建的,
    如果注册表是打包时从仓库抄来的,新项目就没有对应组合,渲染会报
    「Composition not found」。所以打包后、以及每次 build,都要重建一次。
    """
    _write_registry()
    print(json.dumps({"ok": True, "registry": str(SRC / "stickerFilmRegistry.ts")}, ensure_ascii=False))


def _filtered_issues(e: dict) -> list:
    """评审问题清单里,容器/音频时长天然差的几十毫秒(AAC 编码延迟)不算问题。

    cmd_check 与 cmd_make 必须共用这一份过滤,否则一个打印 PASS、另一个判 FAIL。
    """
    issues = list(e.get("objective_issues") or [])
    try:
        actual = checked_duration(e.get("spec", {}).get("duration"), "成片实际时长")
        target = float(e["target"]["duration"])
    except (KeyError, TypeError, ValueError):
        return issues
    return [i for i in issues if not (
        isinstance(i, str) and i.startswith("时长偏差") and abs(actual - target) <= 0.15
    )]


def review_verdict(path: Path) -> str:
    """从评审证据得出最终结论;证据缺失/损坏一律 FAIL(不能当成通过)。"""
    try:
        e = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "FAIL"
    dead = e.get("dead_spans") or []
    black = e.get("black_frames") or []
    silent = e.get("silence") or []
    issues = _filtered_issues(e)
    return "PASS" if not (dead or black or silent or issues) else "FAIL"


def cmd_check(args):
    d = proj_dir(args.project)
    meta = json.loads((d / "project.json").read_text(encoding="utf-8"))
    stage("评审", "客观检查死场、黑帧、静音与音效落点")
    silent = is_silent(meta)
    human = not silent and meta.get("voice_mode") == "human"
    if not human and not silent:
        r = sh([PY, TOOLS / "verify_voice.py", "--project", d])
        if r.returncode:
            die("口播与稿子不一致(verify_voice FAIL)")
    rw, rh, _ = resolve_ratio(meta.get("ratio", "9:16"))
    spec = qcfg.output_spec(meta)
    q = spec
    # 缩放档渲染出来的像素与画布不同,评审要拿真实像素去比,否则会误报「宽度不符」
    exp_w, exp_h = qcfg.output_dimensions(rw, rh, spec)
    video = SRC.parent / "out" / f"{meta['slug']}.mp4"
    if not video.exists():
        die(f"先渲染: {video}")
    media_duration(video)
    # 先量成片真实尺寸/帧率:与档位期望一致就按真实值评(评审里不会再误报),
    # 不一致就按期望值评(让评审把问题指出来)
    out_w, out_h, out_fps = exp_w, exp_h, int(spec["fps"])
    try:
        pr = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate", "-of", "csv=p=0", str(video)],
            capture_output=True, text=True, check=True).stdout.strip()
        pw, ph, pfr = (pr.split(",") + ["", "", ""])[:3]
        num, _, den = pfr.partition("/")
        pf = float(num) / float(den or 1)
        if abs(int(pw) - exp_w) <= 3 and abs(int(ph) - exp_h) <= 3 and abs(pf - float(spec["fps"])) <= 0.5:
            out_w, out_h, out_fps = int(pw), int(ph), round(pf, 3)
    except Exception:  # noqa: BLE001
        pass
    ev = d / "out" / "review"
    r = sh([PY, TOOLS / "review.py", "--video", video, "--audio", d / "out" / "audio.wav",
            "--out", ev, "--storyboard", d / "storyboard.json",
            "--duration", json.loads((d / "timing.json").read_text(encoding="utf-8"))["total"],
            "--width", str(out_w), "--height", str(out_h), "--fps", str(out_fps),
            *qcfg.review_args(meta)])
    if r.returncode:
        die("review 失败")
    e = json.loads((ev / "review-evidence.json").read_text(encoding="utf-8"))
    dead, black = e.get("dead_spans", []), len(e.get("black_frames", []))
    silent = e.get("silence", [])
    hits = e.get("hit_alignment", [])
    ok_hits = sum(1 for h in hits if h.get("ok"))
    issues = _filtered_issues(e)
    verdict = "PASS" if not (dead or black or silent or issues) else "FAIL"
    print(json.dumps({"verdict": verdict, "dead_spans": dead, "black_frames": black,
                      "silence": silent, "sfx_hits": f"{ok_hits}/{len(hits)}",
                      "lufs": e.get("audio_qc", {}).get("lufs"), "issues": issues}, ensure_ascii=False, indent=1))
    # FAIL 是**评审结论**,不是命令执行失败。默认(命令行/一键出片)保留非零退出码,
    # 让自动化能凭退出码判断;界面上的「重新评审」传 --report-only,任务显示为
    # 「已完成 + FAIL」,而不是一个看不出原因的「退出码 1」。
    if verdict == "FAIL" and not getattr(args, "report_only", False):
        raise SystemExit(1)


def scene_compositions(meta: dict) -> list[str]:
    """渲染候选:有专属画面就 scene-<slug> 优先,失败才退回 sf-<slug>。"""
    slug = meta["slug"]
    comps: list[str] = []
    if has_scene(meta):
        gaps = scene_motion_gaps(meta)
        if gaps:
            # 拿一张定格图交片比诚实退回模板更糟:直接说明,用模板。
            print(f"      ! 专属画面在 {'、'.join(gaps)} 拍完全没有运动(会形成死场),"
                  f"已改用通用模板 sf-{slug}", flush=True)
        else:
            comps.append(f"scene-{slug}")
    return comps + [f"sf-{slug}"]


def render_selected(meta: dict, action: str, dest: Path, props: Path, extra, *,
                    log: str = "info", check: bool = True):
    """按候选顺序渲一次,失败只回退一次。返回 (实际用的组合, 进程结果)。

    场景失败**不是致命错误**:记一条中文原因,换模板把片子渲出来。
    模板也失败才 die —— 绝不能因为画面代码有问题就丢掉整条视频。

    Playwright 后端不走 Remotion 组合:正片/预览/关键帧/封面四个调用点
    在这里一次分流,cmd_render / cmd_ship / cmd_check / UI 都不用改。
    """
    if is_playwright(meta):
        import wallstreet_backend
        # 后端需要知道项目目录(找 evidence/ 与 out/playwright/)，补一个只在这里用的键。
        pm = dict(meta)
        pm["_project_dir"] = str(proj_dir(meta["name"]))
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        return wallstreet_backend.render(pm, dest, action=action, props=props,
                                         extra=extra, log=log, check=check)
    slug = meta["slug"]
    comps = scene_compositions(meta)
    last = None
    why = ""
    for comp in comps:
        # 上一次失败可能留下半个文件;不先删掉,后面 check 会把残缺片当成品。
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        last = npx(action, "src/index.tsx", comp, dest, "--props", props, *extra,
                   f"--log={log}", cwd=SRC.parent, check=False)
        if last.returncode == 0:
            if why:
                print(f"      ! 已改用通用模板 {comp} 完成渲染", flush=True)
            return comp, last
        if comp.startswith("scene-"):
            why = (f"专属画面组合 {comp} 渲染失败(退出码 {last.returncode};"
                   f"通常是组合未注册或 TSX 打包报错),退回通用模板 sf-{slug}")
            print(f"      ! {why}", flush=True)
            continue
        break
    if check:
        die(f"渲染失败({comps[-1]}),退出码 {getattr(last, 'returncode', '?')}")
    return comps[-1], last


def cmd_render(args):
    _sync_templates()
    d = proj_dir(args.project)
    meta = json.loads((d / "project.json").read_text(encoding="utf-8"))
    pub = PUBLIC / meta["slug"]
    props = pub / "props.json"
    if not props.exists():
        die("先跑 build")
    stage("渲染", "Playwright 逐帧渲染 + 证据轨" if is_playwright(meta) else "Remotion 逐帧渲染")
    if meta.get("duration") is not None:
        checked_duration(meta["duration"], "目标时长")
    validate_timing(json.loads((d / "timing.json").read_text(encoding="utf-8")))
    payload = json.loads(props.read_text(encoding="utf-8"))
    checked_duration(payload.get("film", {}).get("total"), "装配实际时长")
    # 检查已装配的音频,即使时间轴/props 手动改短,也不允许渲染时悄悄截断。
    media_duration(pub / "audio.wav")
    out = SRC.parent / "out" / f"{meta['slug']}.mp4"
    q = qcfg.output_spec(meta)
    rw, rh, _ = resolve_ratio(meta.get("ratio", "9:16"))
    if args.stills:
        for t in [x for x in args.stills.split(",") if x.strip()]:
            fr = int(round(float(t) * q["fps"]))
            dest = SRC.parent / "out" / "stills" / f"{meta['slug']}-{t}.png"
            dest.parent.mkdir(parents=True, exist_ok=True)
            render_selected(meta, "still", dest, props, ("--frame", str(fr)), log="error")
        return
    # 预览模式:先用低分辨率低帧率出一版,确认内容/节奏对了再出正片。
    # 用户要的是「先看个大概」,不是等 20 分钟才知道讲的是什么。
    if getattr(args, "preview", False):
        prev = SRC.parent / "out" / f"{meta['slug']}-预览.mp4"
        # 预览只降分辨率与码率,不动帧率 —— 帧率是合成里定好的,
        # 命令行再改会把片长拉长(等于慢放),预览就失真了。
        render_selected(meta, "render", prev, props,
                        ("--scale", str(qcfg.output_spec({"resolution": "480p"})["scale"]),
                         "--crf", "30", "--concurrency", "6"))
        print(json.dumps({"ok": True, "preview": str(prev), "quality": q["zh"]}, ensure_ascii=False))
        return
    comp, _r = render_selected(meta, "render", out, props, tuple(qcfg.render_args(q)))
    print(json.dumps({"ok": True, "video": str(out), "composition": comp,
                      "scene": comp.startswith("scene-"),
                      "resolution": q["resolution"], "fps": q["fps"],
                      "tier": q["tier"], "crf": q["crf"], "concurrency": q["concurrency"],
                      "size": list(qcfg.output_dimensions(rw, rh, q))},
                     ensure_ascii=False))


def cmd_ship(args):
    d = proj_dir(args.project)
    meta = json.loads((d / "project.json").read_text(encoding="utf-8"))
    video = SRC.parent / "out" / f"{meta['slug']}.mp4"
    if not video.exists():
        die("先 render")
    final = PROJECTS / "final"
    final.mkdir(parents=True, exist_ok=True)
    nums = [int(m.group(1)) for f in final.glob("*.mp4") if (m := re.match(r"(\d+)-", f.name))]
    nn = max(nums, default=0) + 1
    zh = meta.get("title") or meta["name"]
    style_id = meta.get("style") or "mg-paperclip"
    style_zh = (STYLES.get(style_id) or {}).get("zh") or style_id
    safe_title = archive_title(zh)
    dst = final / f"{nn:02d}-{safe_title}-{style_id}.mp4"
    shutil.copyfile(video, dst)
    cover = final / f"{nn:02d}-{safe_title}-{archive_title(style_zh)}-封面.png"
    cover.parent.mkdir(parents=True, exist_ok=True)
    fps = qcfg.fps_of(meta)
    total = validate_timing(json.loads((d / "timing.json").read_text(encoding="utf-8")))
    cover_frame = min(round(1.5 * fps), math.ceil(total * fps) - 1)
    engine = ("Playwright 逐帧渲染(window.ready/window.seek)+ 实拍/新闻证据轨"
              if is_playwright(meta) else "Remotion 4.0")
    # 封面必须和正片同一个画面语言:有专属画面就用 scene-<slug>,失败才退回模板。
    render_selected(meta, "still", cover, PUBLIC / meta["slug"] / "props.json",
                    ("--frame", str(cover_frame)), log="error")
    ev = d / "out" / "review" / "review-evidence.json"
    metrics = json.loads(ev.read_text(encoding="utf-8")) if ev.exists() else {}
    rw, rh, _ = resolve_ratio(meta.get("ratio", "9:16"))
    width, height = qcfg.output_dimensions(rw, rh, qcfg.output_spec(meta))
    report = f"""# {zh} · {style_id}

**成片**:`{dst.as_posix()}`
**封面**:`{cover.as_posix()}`

{metrics.get('spec', {}).get('duration', total):.2f}s / {width}×{height} / {fps}fps / H.264 + AAC
风格:{style_id}({style_zh})· 渲染:{engine} · 工具:短片工厂 film.py

## 验收(来自 review.py,非自评)

- 死场:{metrics.get('dead_spans') or '无'} / 黑帧:{len(metrics.get('black_frames', []))} / 静音:{metrics.get('silence') or '无'}
- 客观问题:{metrics.get('objective_issues') or '无'}
- 音效落点:{sum(1 for h in metrics.get('hit_alignment', []) if h.get('ok'))}/{len(metrics.get('hit_alignment', []))}
- 响度/真峰值:{metrics.get('audio_qc', {}).get('lufs')} LUFS / {metrics.get('audio_qc', {}).get('true_peak')} dBTP

## 复现

```bash
python tools/motion_design/film.py make --project {meta['name']}
```
"""
    (d / "REPORT.md").write_text(report, encoding="utf-8", newline="\n")
    print(json.dumps({"ok": True, "video": str(dst), "cover": str(cover)}, ensure_ascii=False))


# ────────────────────────────── make ──────────────────────────────
def wrap_cjk(text: str, per_line: int = 13) -> list[str]:
    """按标点断行,不在词中间硬切。

    先按逗号/分号切,短语再按长度合并到 per_line 附近;
    单个短语过长时,只在标点处再切,找不到标点才硬切。
    """
    text = re.sub(r"[。！？!?]+$", "", text.strip())
    phrases = [p for p in re.split(r"(?<=[，、；：,;:])", text) if p.strip()]
    if not phrases:
        return [text]
    lines, cur = [], ""
    for p in phrases:
        if len(cur) + len(p) <= per_line + 2:
            cur += p
        else:
            if cur:
                lines.append(cur)
            while len(p) > per_line + 4:
                lines.append(p[:per_line])
                p = p[per_line:]
            cur = p
    if cur:
        lines.append(cur)
    return lines or [text]


def cmd_script(args):
    """没有模型时的**纯文字排版**模式。

    说清楚它做什么、不做什么:
      做  按你的原文分句、断行、排成一屏一屏;
      不做 不推断画面、不编造配图、不把长句切成半截词。

    它产出的是一条「能听得懂、看得清」的排版片,而不是内容动画。
    想要画面贴合内容,必须配置模型让它读素材。
    """
    d = proj_dir(args.project)
    src = Path(args.source)
    if not src.exists():
        die(f"来源文件不存在: {src}")
    text = read_text_source(src)
    raw = [s.strip() for s in re.split(r"(?<=[。！？!?])|\n+", text) if s.strip()]
    sents = [s for s in raw if len(s) >= 4]
    if not sents:
        die("素材里没有可用的完整句子(至少 4 个字)")

    # 一句一屏 —— 一句话跨两屏会读断。只有超长句(>60 字)才拆屏,
    # 且只在标点处拆,不按字数硬切。
    screens: list[str] = []
    for s in sents:
        if len(s) <= 60:
            screens.append(s)
        else:
            screens.extend(wrap_cjk(s, 26))
    screens = screens[:12] or sents

    segs, beats = [], []
    n = len(screens)
    for i, txt in enumerate(screens):
        bid = f"b{i + 1}"
        role = "HOOK" if i == 0 else ("END" if i == n - 1 else "BUILD")
        rate, pitch = ("-4%", "-2Hz") if i == 0 else (("-8%", "-3Hz") if i == n - 1 else ("+0%", "+0Hz"))
        segs.append({"id": bid, "role": role, "title": txt[:16],
                     "text": txt, "rate": rate, "pitch": pitch})
        beats.append({
            "id": bid, "kind": "quote",
            "n": f"{i + 1:02d}",
            "title": wrap_cjk(txt, 13 if len(txt) < 30 else 15),
            "lines": wrap_cjk(txt, 13 if len(txt) < 30 else 15),
            "stamp": "原文 · 未改写" if i == 0 or i == n - 1 else "",
        })

    film = json.loads((d / "film.json").read_text(encoding="utf-8"))
    film["beats"] = beats
    film["layout"] = "text-only"
    script = {"note": "纯文字排版模式:只分句断行,不改写、不配内容图。要内容动画请配置模型。",
              "source": str(src), "mode": "text-only", "segments": segs}
    (d / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "film.json").write_text(json.dumps(normalize_film(film), ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(s["text"]) for s in segs)
    print(json.dumps({"ok": True, "mode": "text-only", "screens": n, "chars": total,
                      "est_seconds": round(total / 4.6, 1),
                      "note": "纯排版:画面只有文字,不做内容配图"}, ensure_ascii=False))


def cmd_make(args):
    if not args.project:
        die("make 需要 --project(先用 film new 建项目,或加 --name --style 新建)")
    d = PROJECTS / args.project
    if not d.exists():
        if not (args.name and args.style):
            die(f"项目不存在: {d}。用 film new --name ... --style ... 先建,或给 make 加 --name/--style")
        cmd_new(argparse.Namespace(name=args.name, style=args.style, title=args.title, force=True,
                                   duration=args.duration, ratio=args.ratio, voice=args.voice,
                                   type=args.type, narration=getattr(args, "narration", ""),
                                   resolution=getattr(args, "resolution", ""),
                                   fps=getattr(args, "fps", 0),
                                   tier=getattr(args, "tier", "")))
    meta = json.loads((d / "project.json").read_text(encoding="utf-8"))
    # 面板参数以命令行为准(用户可能中途改设置)
    for k, key in (("duration", "duration"), ("ratio", "ratio"), ("voice", "voice"),
                   ("type", "video_type"), ("narration", "narration"),
                   ("resolution", "resolution"), ("fps", "fps"), ("tier", "tier")):
        val = getattr(args, k, None)
        if val not in (None, ""):
            meta[key] = val
    meta["tier"] = (meta.get("tier") or qcfg.DEFAULT_TIER)
    if meta["tier"] not in qcfg.TIERS:
        die(f"未知制作档位: {meta['tier']}")
    # 华尔街风格走原版 kit 镜头表,是 16:9 横版设计;竖版裁切会毁掉构图,直接强制。
    if is_playwright(meta) and meta.get("ratio") != "16:9":
        print("      ! 华尔街风格为 16:9 横版(原技能的设计画幅),已把比例改为 16:9", flush=True)
        meta["ratio"] = "16:9"
    checked_duration(meta.get("duration"), "目标时长")
    resolve_ratio(meta.get("ratio", "9:16"))
    if is_silent(meta) and args.audio:
        die("当前为无口播模式,请移除 --audio 真人录音参数,或切换为有口播后重试。")
    (d / "project.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    script = json.loads((d / "script.json").read_text(encoding="utf-8"))
    empty = any(not s.get("text") for s in script["segments"])
    if args.source and empty:
        use_llm = not getattr(args, "offline", False) and _llm_configured()
        if use_llm:
            stage("写稿", "模型正在把素材整理成口播稿")
            print("[1/5] 用模型起草口播…", flush=True)
            print("      (带思考的模型写稿通常要 30–90 秒,界面右上角有计时)", flush=True)
            drafted = True
            try:
                cmd_draft(argparse.Namespace(project=args.project, source=args.source, max_chars=args.max_chars))
            except SystemExit as e:
                if e.code:
                    drafted = False
                    print("  ! 模型起草失败,改走原文直出", flush=True)
                    cmd_script(argparse.Namespace(project=args.project, source=args.source))
            if drafted:
                # Playwright 后端不用模型写的 TSX 专属画面(那套是 Remotion 组合),
                # 让模型去写只会白花一次调用,还会在 project.json 记一个用不上的状态。
                if is_playwright(meta):
                    print("[1/5] 逐帧后端不使用 TSX 专属画面,跳过这一步。", flush=True)
                    # v2:让模型按原 skill 的 kit 场景手册写镜头表(同题对比实测,
                    # 固定舞台的差距是架构性的)。失败如实说明,退回 v1 固定舞台。
                    try:
                        import wallstreet_kit
                        stage("镜头表", "华尔街风格:按 kit 场景选型")
                        ok, info = wallstreet_kit.plan_shots(d, meta)
                        if ok:
                            print(f"      镜头表已生成:{info}", flush=True)
                        else:
                            print(f"      ! 镜头表未采用({info});退回固定竖版舞台。", flush=True)
                    except Exception as e:  # noqa: BLE001
                        print(f"      ! 镜头表生成失败({type(e).__name__}: {str(e)[:120]});"
                              "退回固定竖版舞台。", flush=True)
                else:
                    # 画面也交给模型:一次便宜的调用,失败就静默退回模板。
                    stage("画面", "模型为这条片子写专属画面代码")
                    print("[1/5] 让模型为这条片子写专属画面…", flush=True)
                    try:
                        cmd_scene(argparse.Namespace(project=args.project, quiet=True))
                    except SystemExit:
                        print("      ! 专属画面未采用;继续用模板渲染。", flush=True)
                        _record_scene(d, meta, "failed", "专属画面生成中断")
                    except Exception as e:  # noqa: BLE001
                        print(f"      ! 专属画面未采用({type(e).__name__}: {str(e)[:120]});继续用模板渲染。", flush=True)
                        _record_scene(d, meta, "failed", f"{type(e).__name__}: {str(e)[:160]}")
        else:
            print("[1/5] 未配置模型 → 只能做纯文字排版(不配内容画面)。"
                  "想让它读懂素材、配对应画面,请到「设置」里配置模型。", flush=True)
            cmd_script(argparse.Namespace(project=args.project, source=args.source))
    elif empty:
        print("[1/5] script.json 里还有空句子;先手填,或加 --source 自动成稿。先继续渲占位片。", flush=True)
    else:
        print("[1/5] 已有稿子,跳过起草", flush=True)
        # 华尔街风格:稿子改过或还没有镜头表时,(重)让模型写一张 kit 镜头表。
        if is_playwright(meta) and not getattr(args, "offline", False) and _llm_configured():
            _shots = d / "wallstreet_shots.json"
            stale = (not _shots.exists()
                     or _shots.stat().st_mtime < (d / "script.json").stat().st_mtime)
            if stale:
                try:
                    import wallstreet_kit
                    stage("镜头表", "华尔街风格:按 kit 场景选型")
                    ok, info = wallstreet_kit.plan_shots(d, meta)
                    if ok:
                        print(f"      镜头表已生成:{info}", flush=True)
                    else:
                        print(f"      ! 镜头表未采用({info});退回固定竖版舞台。", flush=True)
                except Exception as e:  # noqa: BLE001
                    print(f"      ! 镜头表生成失败({type(e).__name__}: {str(e)[:120]});"
                          "退回固定竖版舞台。", flush=True)
        # 老项目的专属画面可能有问题(比如某一拍整段静止,或根本没生成过)。
        if (not is_playwright(meta) and not getattr(args, "offline", False)
                and _llm_configured() and args.source
                and (not has_scene(meta) or scene_motion_gaps(meta))):
            why = "还没有专属画面" if not has_scene(meta) else "已有专属画面里存在静止拍"
            print(f"[1/5] {why},让模型重画一版…", flush=True)
            try:
                cmd_scene(argparse.Namespace(project=args.project, quiet=True))
            except SystemExit:
                print("      ! 专属画面未采用;继续用模板渲染。", flush=True)
                _record_scene(d, meta, "failed", "专属画面生成中断")
            except Exception as e:  # noqa: BLE001
                print(f"      ! 专属画面未采用({type(e).__name__}: {str(e)[:120]});继续用模板渲染。", flush=True)
                _record_scene(d, meta, "failed", f"{type(e).__name__}: {str(e)[:160]}")
    print("[1/5] 口播稿…", flush=True)
    rounds = int(qcfg.tier_of(meta)["script_rounds"])
    # 这里的 script 必须是**起草之后**的稿子。之前读的是起草前的快照
    # (空 text),导致档位要求的复审永远被「脚本还没写出来」挡掉,0/3 轮。
    script = json.loads((d / "script.json").read_text(encoding="utf-8"))
    done = 0
    reason = ""
    if rounds:
        if getattr(args, "offline", False):
            reason = "纯文字排版模式不调用模型,复审改稿跳过"
        elif not _llm_configured():
            reason = "未配置模型,复审改稿跳过(档位要求的轮次未执行)"
        elif not (script.get("segments") and all(s.get("text") for s in script["segments"])):
            reason = "脚本还没写出来,复审改稿跳过"
        else:
            stage("复审", f"模型复审改稿 {rounds} 轮")
            for i in range(rounds):
                print(f"[1/5] 复审改稿 第 {i + 1}/{rounds} 轮…", flush=True)
                try:
                    cmd_refine(argparse.Namespace(project=args.project, round=i + 1))
                    done += 1
                except SystemExit as e:
                    if e.code:
                        reason = f"第 {i + 1} 轮被拒(改动未通过校验),停止复审"
                        break
                except Exception as e:  # noqa: BLE001
                    reason = f"第 {i + 1} 轮失败:{type(e).__name__}"
                    break
    if rounds and done == 0 and reason:
        print(f"      ! {reason}", flush=True)
    # 重新读一遍再写:专属画面那一步已经往 project.json 里写过 scene 状态,
    # 用 cmd_make 开头那份旧 meta 覆盖会把「通用模板渲染」的记录抹掉。
    meta = json.loads((d / "project.json").read_text(encoding="utf-8"))
    meta["tier_review"] = {"tier": meta["tier"], "rounds_planned": rounds,
                           "rounds_done": done, "note": reason if done < rounds else ""}
    (d / "project.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[2/5] 口播…", flush=True)
    cmd_voice(argparse.Namespace(project=args.project, audio=(args.audio or None), provider=args.provider))
    print("[3/5] 装配(字幕/配乐/混音)…", flush=True)
    cmd_build(argparse.Namespace(project=args.project))
    print("[4/5] 渲染…", flush=True)
    cmd_render(argparse.Namespace(project=args.project, stills=None))
    print("[5/5] 评审…", flush=True)
    # 一键出片时评审 FAIL 也要把片子交出来(已有成片、已有证据),否则用户
    # 只会看到一个「退出码 1」,连问题清单都看不到。结论用 PASS/FAIL 报;
    # 真正的渲染/装配错误仍然会异常退出。
    cmd_check(argparse.Namespace(project=args.project, report_only=True))
    # 结论必须和 cmd_check 用**同一套过滤规则**。之前这里直接读原始
    # objective_issues,把容器时长与音频时长天然差的几十毫秒(AAC 编码延迟)
    # 当成 FAIL,于是终端打印 PASS、一键出片却报 FAIL,片子还不归档。
    # 把这段规则抽成函数,两边共用一个真相。
    verdict = review_verdict(d / "out" / "review" / "review-evidence.json")
    if verdict == "PASS":
        if not args.no_ship:
            cmd_ship(argparse.Namespace(project=args.project))
    else:
        # 不归档:final/ 是「可交付」的地方,评审没过就别往里放,但成片与
        # 问题清单都留在项目里,用户改完再「重新评审」或重渲。
        print("      ! 评审未通过:成片保留在 out/ 未归档。看完问题清单后再改稿或重渲。",
              flush=True)
    print(json.dumps({"ok": True, "done": True, "verdict": verdict}, ensure_ascii=False))


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog="film", description="短片工厂:一条命令出一条 30–50 秒竖屏短片")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("styles", help="看 15 个风格").set_defaults(fn=cmd_styles)
    sub.add_parser("registry", help="重建 Remotion 组合注册表").set_defaults(fn=cmd_registry)

    p = sub.add_parser("new", help="新建项目骨架")
    p.add_argument("--name", required=True, help="项目目录名(建议英文/数字)")
    p.add_argument("--style", default="mg-paperclip", help="风格 id,见 film styles")
    p.add_argument("--title", default="", help="中文片名(用于归档命名)")
    p.add_argument("--duration", type=int, default=35, help="目标时长(秒)")
    p.add_argument("--ratio", default="9:16", help="画面比例:9:16/16:9/1:1/4:5/3:4/2:3/21:9 或 custom:1080x1920")
    p.add_argument("--voice", default="zh-CN-YunjianNeural", help="TTS 音色 id")
    p.add_argument("--type", default="explain", choices=list(TYPES), help="视频类型")
    p.add_argument("--narration", default="", choices=["", "voice", "silent"], help="有口播 / 无口播")
    p.add_argument("--resolution", default="", choices=["", *qcfg.RESOLUTIONS], help="画质(分辨率)")
    p.add_argument("--fps", type=int, default=0, choices=[0, 24, 30, 60], help="刷新率")
    p.add_argument("--tier", default="", choices=["", *qcfg.TIERS], help="制作档位:快速/标准/精品")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("script", help="不依赖模型:把原文逐句直出成口播")
    p.add_argument("--project", required=True)
    p.add_argument("--source", required=True)
    p.set_defaults(fn=cmd_script)

    p = sub.add_parser("draft", help="让模型按来源起草口播+画面脚本")
    p.add_argument("--project", required=True)
    p.add_argument("--source", required=True, help="txt/md/html 来源文件")
    p.add_argument("--max-chars", type=int, default=12000)
    p.set_defaults(fn=cmd_draft)

    p = sub.add_parser("scene", help="让模型为这条片子写专属 TSX 画面(失败退回模板)")
    p.add_argument("--project", required=True)
    p.set_defaults(fn=cmd_scene)

    p = sub.add_parser("refine", help="复审改稿一轮(档位要求,需配置模型)")
    p.add_argument("--project", required=True)
    p.add_argument("--round", type=int, default=1)
    p.set_defaults(fn=cmd_refine)

    p = sub.add_parser("voice", help="合成口播或采用真人录音")
    p.add_argument("--project", required=True)
    p.add_argument("--audio", default="", help="真人录音 wav/mp3;给了就走对齐管线")
    p.add_argument("--provider", default="edge", choices=["edge", "minimax", "piper"])
    p.set_defaults(fn=cmd_voice)

    p = sub.add_parser("build", help="字幕+配乐+混音+props")
    p.add_argument("--project", required=True)
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("render", help="渲染成片或静帧")
    p.add_argument("--project", required=True)
    p.add_argument("--stills", default="", help="逗号分隔的秒数,只出关键帧")
    p.add_argument("--preview", action="store_true", help="先出低清预览(确认内容用)")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("check", help="客观评审:死场/黑帧/静音/音效对齐")
    p.add_argument("--project", required=True)
    p.add_argument("--report-only", action="store_true",
                   help="只出结论,FAIL 也退出 0(给界面「重新评审」用;命令行走严格模式)")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("ship", help="归档到 final/ 并生成封面+报告")
    p.add_argument("--project", required=True)
    p.set_defaults(fn=cmd_ship)

    p = sub.add_parser("make", help="一条龙:new→draft→voice→build→render→check→ship")
    p.add_argument("--project", default="")
    p.add_argument("--name", default="")
    p.add_argument("--style", default="")
    p.add_argument("--title", default="")
    p.add_argument("--duration", type=int, default=35, help="目标时长(秒)")
    p.add_argument("--ratio", default="9:16", help="画面比例,支持 custom:1080x1920")
    p.add_argument("--voice", default="zh-CN-YunjianNeural", help="TTS 音色 id")
    p.add_argument("--type", default="explain", choices=list(TYPES), help="视频类型")
    p.add_argument("--narration", default="", choices=["", "voice", "silent"], help="有口播 / 无口播")
    p.add_argument("--resolution", default="", choices=["", *qcfg.RESOLUTIONS], help="画质(分辨率)")
    p.add_argument("--fps", type=int, default=0, choices=[0, 24, 30, 60], help="刷新率")
    p.add_argument("--tier", default="", choices=["", *qcfg.TIERS], help="制作档位:快速/标准/精品")
    p.add_argument("--source", default="")
    p.add_argument("--audio", default="")
    p.add_argument("--provider", default="edge", choices=["edge", "minimax", "piper"])
    p.add_argument("--max-chars", type=int, default=12000)
    p.add_argument("--no-ship", action="store_true")
    p.add_argument("--offline", action="store_true", help="不用模型,按原文逐句直出")
    p.set_defaults(fn=cmd_make)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()