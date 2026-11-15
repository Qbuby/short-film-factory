"""华尔街风格 v2 —— 直通原 skill 的 kit 模板档,不再用固定竖版舞台。

背景:同题对比实测(2026-11-15)证明 v1 的「模型填 4 个字段 → 固定舞台」
把原技能的灵魂(33 个场景按导演表选型、enter 接法、wine tone、金句刷金)
压扁成了同一版式换字。v2 让模型按 kit/README.md 的场景手册直接写
K.film([...]) 镜头表,渲染走原版 render.mjs + mix.py,视频由本模块 mux。

边界(如实):
  * 依赖原 skill 目录(fonts/kit/scripts/node_modules):本机
    `%USERPROFILE%\\.agents\\skills\\wallstreet-explainer`,或环境变量
    OE_WALLSTREET_SKILL 指定。找不到时 available() 为 False,调用方退回 v1。
  * 只放行**不需要照片/新闻截图**的场景(20 个)——证据轨(snap_news/footage)
    是下一步,没素材就不许用照片场景,更不许编造。
  * 配音:逐行沿用稿子的 say(voiceover.synthesis_text),voice 用用户所选
    音色;temp_voice 只支持全局语速,逐句 rate/pitch 差异暂不支持(绝大多数
    是 +0%),遇到非默认语速会在日志里如实提醒。
  * 画幅:kit 是 16:9 横版,这是原设计的语言;make 时强制 16:9,不竖版裁切。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

WINE_MAX = 1
STATEMENT_MAX = 3
SHOT_MAX = 16

# 只放行不需要照片/截图的场景; discs/network/board/map 允许「无照片」形态。
ALLOWED_SCENES = {
    "statement", "title", "number", "equation", "change", "stats", "bars",
    "chart", "share", "ranking", "versus", "compare", "flow", "timeline",
    "network", "board", "agenda", "chain", "discs", "map",
}

_CATALOG = """数和钱:
  number   一个决定性的数。value(必填) brow en; color:'gold'|'red'(亏损)|'white'; tone; sub:{label,value,at}
  equation 一笔账。terms: 数{value,label,at}与{op:'+−×÷='}交替,最后一个是结果; brow en
  change   同一个数从多少到多少。from:{value,label} to:{value,label,at} mult color:'gold'|'red'
  stats    两到四个数排开。items:[{label,value,at}]
  bars     两三个数比高低。bars:[{label,value(数值),show(显示文本),at}] 或 [{value,at}]
  chart    一串数按年变化。x:[年] values:[[数]] draw:{at,until}
  share    占比。parts focus
  ranking  五家以上排队。rows climb focus
  versus   两样东西按真实面积差得离谱。items:[{id,name,color,tag:{label,value}}]
关系和结构:
  flow     流程/条件,卡片+虚线箭头一步步亮。nodes:[{id,title,color,pos:[列,行],at}] links:[{from,to}] steps:[{at,mark:{id:'ok'|'bad'},focus,gray}]
  timeline 三到六件事按时间排。nodes:[{id,year,title,color,at}]
  chain    三四环因果一字排开,念到哪环亮哪环。items:[{at,title,img|value,sub,color}] arrow
  network  钱怎么流。nodes(同 discs) links steps
  discs    几家并列,品牌色实心盘+名字(没有照片就这样写)。items:[{id,name,color,at}] steps
  versus   见上
人/证据(本片没有照片与新闻截图素材,禁止使用): person profile quote footage montage frames desk article device pop cards3d
结构包装:
  statement 金句。lines(1-3 行,每行≤12字) hl(刷金词,数组) at(每行时刻,数组) brow;一条片≤3句
  title     片名/章节。title brow en;不带 items
  agenda    目录。items(3-6 章) at 数组
"""

_RULES = """硬规矩:
1. 每一镜写 says(这一镜让观众多懂什么,一句话);写不出来就别要这一镜。
2. 时刻一律写 '@句id' 或 '@句id:词'(词必须是那句稿子里的原词,一字不差);
   最后一镜不写 until;其余每一镜都必须写 until。
3. 只用上面列出的场景;person/quote/footage 等需要照片或新闻截图的场景
   一律禁止(本片没有素材,宁缺毋滥)。
4. 数字只能来自稿子原文,一个都不许编;稿子里没有的数就不出数的镜。
5. tone:'wine' 只给亏损/算总账的一段,最多一次;其余不写 tone。
6. statement 全片最多 3 句,每行 ≤12 字,hl 词必须在 lines 里。
7. 镜头总数 3–16;第一镜开场第一帧就有东西(不要空等)。
8. 输出严格 JSON:{"shots":[…]},不要 markdown、不要解释。
"""


def _skill_dir() -> Path | None:
    env = os.environ.get("OE_WALLSTREET_SKILL")
    cands = [Path(env)] if env else []
    cands.append(Path.home() / ".agents" / "skills" / "wallstreet-explainer")
    for p in cands:
        if (p / "scripts" / "render.mjs").is_file() and (p / "kit" / "kit.js").is_file():
            return p
    return None


def available() -> tuple[bool, str]:
    p = _skill_dir()
    if p:
        return True, str(p)
    return False, ("找不到 wallstreet-explainer 原技能目录"
                   "(设 OE_WALLSTREET_SKILL 或安装到 ~/.agents/skills)")


def _node() -> str:
    env = os.environ.get("OE_NODE")
    if env and Path(env).is_file():
        return env
    nd = os.environ.get("OE_NODE_DIR")
    if nd and (Path(nd) / "node.exe").is_file():
        return str(Path(nd) / "node.exe")
    return shutil.which("node") or "node"


def _run(cmd: list, *, cwd: Path | None = None, timeout: int = 1800) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    rt = TOOLS.parent / "short-film-factory" / "runtime" / "bin"
    runtime_bin = TOOLS.parent.parent / "runtime" / "bin"
    for cand in (runtime_bin, rt):
        if cand.is_dir():
            env["PATH"] = str(cand) + os.pathsep + env.get("PATH", "")
            break
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, env=env,
                          creationflags=0x08000000 if os.name == "nt" else 0)


# ─────────────────────────── 镜头表:模型来写 ───────────────────────────
def _lines_for_kit(project: Path) -> tuple[list[dict], list[dict]]:
    """稿子逐段 → kit 的行;say 用 voiceover.synthesis_text,保证 verify_voice 认。"""
    import voiceover as vo  # noqa: WPS433
    script = json.loads((project / "script.json").read_text(encoding="utf-8"))
    segs = script.get("segments") or []
    lines, warns = [], []
    for s in segs:
        if not (s.get("text") or "").strip():
            continue
        say = vo.synthesis_text(s)
        lines.append({"id": s["id"], "text": s["text"], "say": say, "gap": 0.25})
        if (s.get("rate", "+0%") not in ("+0%", "")) or (s.get("pitch", "+0Hz") not in ("+0Hz", "")):
            warns.append(f"{s['id']} 有自定义语速/音调,kit 配音暂不支持逐句差异,按全局语速合成")
    return lines, warns


def plan_shots(project: Path, meta: dict) -> tuple[bool, str]:
    """让模型按 kit 场景手册写镜头表;两次机会,失败退回 v1(不写文件)。"""
    import llm  # noqa: WPS433
    if not llm.available():
        return False, "未配置文本模型,无法规划镜头表"
    ok, why = available()
    if not ok:
        return False, why
    py = sys.executable
    lines, warns = _lines_for_kit(project)
    if not lines:
        return False, "稿子是空的"
    system = ("你是华尔街式财经解读片的导演。给一段口语稿(已分句,带 id),"
              "按场景手册为每一句选场景,写一张镜头表。\n" + _CATALOG + "\n" + _RULES)
    user = json.dumps({"稿子": lines}, ensure_ascii=False)
    last_err = ""
    for attempt in range(2):
        try:
            txt = llm.complete(system, user if attempt == 0 else
                               user + "\n\n上一次输出的错误:\n" + last_err,
                               max_tokens=4096, temperature=0.3)
            m = re.search(r"\{[\s\S]*\}", txt or "")
            if not m:
                raise ValueError("没有返回 JSON")
            data = json.loads(m.group(0))
            shots = data.get("shots")
            if not isinstance(shots, list) or not shots:
                raise ValueError("shots 为空")
            # 模型偶尔写 type 代替 scene:归一成 kit 认的字段
            for s in shots:
                if isinstance(s, dict) and not s.get("scene") and s.get("type"):
                    s["scene"] = s["type"]
            errs = validate_shots(shots, lines)
            if errs:
                raise ValueError("; ".join(errs[:4]))
            (project / "wallstreet_shots.json").write_text(json.dumps({
                "version": 2, "mode": "kit", "shots": shots, "warns": warns,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            return True, f"{len(shots)} 镜" + (";" + ";".join(warns) if warns else "")
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"[:400]
    return False, last_err


_CUE_RE = re.compile(r"^@([A-Za-z]\w*)(?::([^@#]+?(?:#\d+)?))?(?:([+-]\d+(?:\.\d+)?))?$")


def _check_cue(cue: str, line_map: dict, where: str, errs: list) -> None:
    m = _CUE_RE.match(str(cue).strip())
    if not m:
        errs.append(f"{where}: 时刻「{cue}」不是 @句id[@词] 形式")
        return
    lid, word = m.group(1), (m.group(2) or "").strip()
    line = line_map.get(lid)
    if line is None:
        errs.append(f"{where}: 句 id {lid} 不存在于稿子")
    elif word and word not in line["text"]:
        errs.append(f"{where}: 词「{word}」不在 {lid} 的稿子里(「{line['text'][:24]}…」)")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", str(s))


def validate_shots(shots: list, lines: list[dict]) -> list[str]:
    """结构校验;返回错误列表(空 = 通过)。渲染前也会再跑一遍。"""
    errs: list[str] = []
    line_map = {l["id"]: l for l in lines}
    statements = 0
    wine = 0
    if not (3 <= len(shots) <= SHOT_MAX):
        errs.append(f"镜头数 {len(shots)} 不在 3–{SHOT_MAX}")
    for i, s in enumerate(shots):
        where = f"镜{i + 1}"
        scene = str(s.get("scene") or "")
        if scene not in ALLOWED_SCENES:
            errs.append(f"{where}: 场景「{scene}」需要照片素材或不存在,禁止使用")
            continue
        if not str(s.get("says") or "").strip():
            errs.append(f"{where}({scene}): 没写 says")
        if i < len(shots) - 1:
            if not s.get("until"):
                errs.append(f"{where}({scene}): 非末镜必须写 until")
            else:
                _check_cue(s["until"], line_map, where, errs)
        elif s.get("until"):
            errs.append(f"{where}({scene}): 最后一镜不写 until")
        for key in ("at",):
            v = s.get(key)
            if isinstance(v, list):
                for c in v:
                    _check_cue(c, line_map, f"{where}.{key}", errs)
        for key in ("sub",):
            v = s.get(key)
            if isinstance(v, dict) and v.get("at"):
                _check_cue(v["at"], line_map, f"{where}.{key}", errs)
        for node in list(s.get("nodes") or []) + list(s.get("items") or []):
            if isinstance(node, dict) and node.get("at"):
                _check_cue(node["at"], line_map, f"{where}.节点", errs)
        for st in s.get("steps") or []:
            if isinstance(st, dict) and st.get("at"):
                _check_cue(st["at"], line_map, f"{where}.steps", errs)
        if scene == "statement":
            statements += 1
            ls = s.get("lines") or []
            if not (1 <= len(ls) <= 3):
                errs.append(f"{where}: statement 行数 {len(ls)} 应为 1–3")
            joined = "".join(ls)
            for l in ls:
                if len(str(l)) > 12:
                    errs.append(f"{where}: statement 行超过 12 字:「{l}」")
            for h in s.get("hl") or []:
                if h not in joined:
                    errs.append(f"{where}: 刷金词「{h}」不在 lines 里")
            at = s.get("at") or []
            if at and len(at) != len(ls):
                errs.append(f"{where}: statement at 数量与 lines 不一致")
        if str(s.get("tone") or "") == "wine":
            wine += 1
        # 数字只能来自稿子:只盯主数值(value/terms/from.to);
        # sub 之类小卡可能是中文数字(百分之二点二)转写,不做字符级强校验。
        if scene in ("number", "change", "equation"):
            script_digits = _digits("".join(l["text"] for l in lines))
            vals = []
            if s.get("value"):
                vals.append(s["value"])
            for t in s.get("terms") or []:
                if isinstance(t, dict) and t.get("value"):
                    vals.append(t["value"])
            for k in ("from", "to"):
                v = s.get(k) or {}
                if isinstance(v, dict) and v.get("value"):
                    vals.append(v["value"])
            for v in vals:
                d = _digits(v)
                if d and d not in script_digits:
                    errs.append(f"{where}({scene}): 数「{v}」在稿子里找不到对应数字")
    if statements > STATEMENT_MAX:
        errs.append(f"statement {statements} 句超过 {STATEMENT_MAX}")
    if wine > WINE_MAX:
        errs.append(f"wine 底 {wine} 段超过 {WINE_MAX}")
    return errs


def build_film_js(shots: list) -> str:
    """镜头表(纯数据,无代码)→ film.js。cue/参数都是 JSON 值,不需要 eval。"""
    return (
        "// 由短片工厂生成:模型写的 kit 镜头表(见 wallstreet_shots.json)。\n"
        "window.ready=(async()=>{\n"
        "const F=await FB.init({fonts:KIT.FONTS});\n"
        "const K=await KIT.use(F);\n"
        "await K.film(" + json.dumps(shots, ensure_ascii=False) + ");\n"
        "return K.go();\n"
        "})();\n"
    )


# ─────────────────────────── 渲染 ───────────────────────────
def _scaffold(project: Path, skill: Path, node: str) -> Path:
    film_dir = project / "kit_film"
    if film_dir.exists():
        shutil.rmtree(film_dir, ignore_errors=True)
    film_dir.parent.mkdir(parents=True, exist_ok=True)
    r = _run([node, skill / "scripts" / "new_film.mjs", film_dir], cwd=skill, timeout=300)
    if r.returncode or not (film_dir / "index.html").is_file():
        raise RuntimeError(f"kit 脚手架失败: {(r.stderr or r.stdout or '')[:200]}")
    return film_dir


def _write_script(film_dir: Path, lines: list[dict], meta: dict) -> None:
    voice = meta.get("voice") or "zh-CN-YunxiNeural"
    rate = "+0%"
    doc = {"voice": voice, "rate": rate, "pre": 0.3,
           "note": "kit v2:逐行 say 来自 voiceover.synthesis_text,保证 verify_voice 兼容",
           "lines": lines}
    (film_dir / "script.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                                          encoding="utf-8")


def _app_voice_segments(project: Path, lines: list[dict]) -> list[dict]:
    """App 配音步骤已合成的口播:id/text/say/start/end/wav(绝对路径)。

    来源:project/timing.json(voiceover 写的);wav 相对路径按 project 解析,
    解析不到就取 out/voice/<id>.*.wav 里最新的一个。没有的一行都算缺失。
    """
    import voiceover as vo  # noqa: WPS433
    tf = project / "timing.json"
    amap: dict[str, dict] = {}
    try:
        t = json.loads(tf.read_text(encoding="utf-8"))
        for s in t.get("segments") or []:
            w = Path(s.get("wav") or "")
            if not w.is_absolute():
                w = project / w
            amap[s["id"]] = {**s, "wav_abs": w}
    except (OSError, ValueError):
        pass
    script = json.loads((project / "script.json").read_text(encoding="utf-8"))["segments"]
    smap = {s["id"]: s for s in script}
    vdir = project / "out" / "voice"
    segs = []
    elapsed = 0.0
    for l in lines:
        src = smap.get(l["id"])
        if src is None:
            continue
        row = amap.get(l["id"]) or {}
        w = Path(row.get("wav_abs") or "")
        if not w.is_file():
            hits = sorted(vdir.glob(f"{l['id']}.*.wav"), key=lambda p: p.stat().st_mtime)
            w = hits[-1] if hits else None
        if not (w and w.is_file()):
            continue
        # 旧 sync 可能写过 start/end 为 null 的 timing:按 dur 累积重建
        start, end = row.get("start"), row.get("end")
        try:
            start = float(start) if start is not None else -1.0
            end = float(end) if end is not None else -1.0
        except (TypeError, ValueError):
            start = end = -1.0
        if start < 0 or end <= start:
            dur = float(row.get("dur") or 0.0)
            start, end = elapsed, elapsed + dur
        elapsed = end + 0.25
        segs.append({"id": l["id"], "text": l["text"], "say": vo.synthesis_text(src),
                     "wav": w, "start": start, "end": end})
    return segs


def render_kit(meta: dict, project: Path, dest: Path, *, height: int, log) -> dict:
    """kit 全流程:脚手架 → 时间轴(复用 App 配音) → film.js → 渲 → mux → 校验产物。"""
    ok, why = available()
    if not ok:
        raise RuntimeError(why)
    skill = _skill_dir()
    shots_doc = json.loads((project / "wallstreet_shots.json").read_text(encoding="utf-8"))
    shots = shots_doc.get("shots") or []
    # 旧文件/模型可能写 type:归一成 kit 认的 scene
    for s in shots:
        if isinstance(s, dict) and not s.get("scene") and s.get("type"):
            s["scene"] = s["type"]
    lines, _warns = _lines_for_kit(project)
    # App 配音与时间轴直接复用(voiceover 已按稿子的 say/语速/音调合成,
    # verify_voice 的重合成比对因此和正常影片同轨)。本流程会覆盖 timing.json,
    # 所以必须在建 kit 目录之前读。
    app_segs = _app_voice_segments(project, lines)
    if len(app_segs) < len(lines):
        missing = [l["id"] for l in lines if l["id"] not in {s["id"] for s in app_segs}]
        raise RuntimeError("App 配音缺失(" + ",".join(missing[:4]) +
                           ");先跑一次 make 的配音步骤再渲染")
    errs = validate_shots(shots, lines)
    if errs:
        # 自愈:稿子可能在规划之后被复审改过,cue 词对不上时重规划一次。
        log("镜头表与稿子对不上,自动重新规划一次")
        try:
            import llm  # noqa: WPS433
            if llm.available():
                plan_shots(project, meta)
                shots = json.loads((project / "wallstreet_shots.json")
                                   .read_text(encoding="utf-8")).get("shots") or []
                for s in shots:
                    if isinstance(s, dict) and not s.get("scene") and s.get("type"):
                        s["scene"] = s["type"]
                errs = validate_shots(shots, lines)
        except Exception as e:  # noqa: BLE001
            errs = [f"重规划失败: {type(e).__name__}: {e}"[:120], *errs[:3]]
    if errs:
        raise RuntimeError("镜头表未通过校验: " + "; ".join(errs[:4]))
    node = _node()
    log("建 kit 片子目录")
    film_dir = _scaffold(project, skill, node)
    _write_script(film_dir, lines, meta)
    vdir = film_dir / "voice"
    vdir.mkdir(exist_ok=True)
    beats = []
    for s in app_segs:
        shutil.copyfile(s["wav"], vdir / f"{s['id']}.wav")
        n = max(1, len(s["text"]))
        # 词级时刻线性内插(原版用 faster-whisper 逐字对齐;这里如实降级,
        # 换来零 ASR 依赖:ASR 挂起一次就卡死整条 make,内插误差对换镜时机可接受)
        chars = [[c, round(s["start"] + j * (s["end"] - s["start"]) / n, 4)]
                 for j, c in enumerate(s["text"])]
        beats.append({"id": s["id"], "text": s["text"], "start": s["start"],
                      "end": s["end"], "wav": f"voice/{s['id']}.wav", "chars": chars})
    total = round(beats[-1]["end"] + 0.95, 4)
    (film_dir / "timeline.json").write_text(json.dumps(
        {"fps": 30, "duration": total, "pre": 0.3, "title": None,
         "beats": beats, "inserts": []}, ensure_ascii=False), encoding="utf-8")
    log(f"词级时间轴:{len(beats)} 句 / {total:.1f}s")
    (film_dir / "film.js").write_text(build_film_js(shots), encoding="utf-8")
    log(f"逐帧渲染 kit 镜头表({len(shots)} 镜, {height}p)")
    r = _run([node, skill / "scripts" / "render.mjs", "--dir", film_dir,
              "--video", "--h", str(height)], cwd=film_dir, timeout=3600)
    visual = max(film_dir.glob("out/visual*.mp4"), key=lambda p: p.stat().st_mtime,
                 default=None)
    if r.returncode or not visual:
        raise RuntimeError(f"kit 渲染失败: {(r.stderr or r.stdout or '')[-300:]}")
    audio = project / "out" / "audio.wav"
    if not audio.is_file():
        raise RuntimeError("缺少 out/audio.wav(先跑一次 make 的装配步骤再渲染)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    # 配乐铺底:句间 gap 不再是静音(评审 -45dB 口径),loudnorm 拉回 -14。
    music = project / "out" / "music.wav"
    log("音画合成(成片 + 口播" + (" + 配乐" if music.is_file() else "") + ")")
    if music.is_file():
        af = ("[1:a]aresample=48000,aformat=channel_layouts=stereo[va];"
              "[2:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.14[m];"
              "[va][m]amix=inputs=2:duration=first:normalize=0,"
              f"loudnorm=I=-14:TP=-1.5:LRA=11,atrim=0:{total:.3f},"
              f"afade=t=out:st={max(0.0, total - 0.35):.3f}:d=0.35[a]")
        r = _run(["ffmpeg", "-hide_banner", "-v", "error", "-y",
                  "-i", str(visual), "-i", str(audio),
                  "-stream_loop", "-1", "-i", str(music),
                  "-filter_complex", af, "-map", "0:v:0", "-map", "[a]",
                  "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                  "-movflags", "+faststart", str(dest)], timeout=600)
    else:
        r = _run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(visual),
                  "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                  "-c:a", "aac", "-b:a", "192k", "-shortest",
                  "-movflags", "+faststart", str(dest)], timeout=600)
    if r.returncode or not dest.is_file():
        raise RuntimeError(f"音画合成失败: {(r.stderr or r.stdout or '')[:200]}")
    _sync_check_artifacts(app_segs, project, meta, total)
    return {"shots": len(shots), "visual": str(visual)}


def _sync_check_artifacts(app_segs: list[dict], project: Path, meta: dict,
                          total: float) -> None:
    """把 App 时间轴映回 check 需要的三样:timing.json / out/audio.wav / storyboard。"""
    segs = [{
        "id": s["id"], "text": s["text"], "say": s["say"],
        "wav": s["wav"].as_posix(),
        "dur": round(s["end"] - s["start"], 3),
        "sig": hashlib.md5(s["wav"].read_bytes()).hexdigest()[:12],
        "start": round(s["start"], 3), "end": round(s["end"], 3),
    } for s in app_segs]
    timing = {"voice": meta.get("voice") or "", "speed": "+0%", "gap": 0.25,
              "total": round(total, 3), "segments": segs}
    (project / "timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    sb_path = project / "storyboard.json"
    sb = {}
    if sb_path.is_file():
        try:
            sb = json.loads(sb_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            sb = {}
    sb.setdefault("style", "mg-wallstreet")
    sb["audio"] = {"recipe": "wallstreet-kit", "sfx": []}
    sb["duration"] = round(total, 3)
    sb_path.write_text(json.dumps(sb, ensure_ascii=False, indent=1), encoding="utf-8")
    # kit 叙事节奏的如实口径:卡片停留阅读是设计,句间 gap 是口播节奏,
    # 生成类的零容忍口径会误杀。写进项目,review_args 按它覆盖档位规则。
    pj = project / "project.json"
    try:
        m = json.loads(pj.read_text(encoding="utf-8"))
        m["tier_review"] = {"dead_scale": 2.0, "silence_tolerance": 8}
        pj.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, ValueError):
        pass


def cover_from(video: Path, png: Path, frame: int, fps: float) -> bool:
    """v2 的封面/静帧:直接从成片抽帧(不再走竖版舞台)。"""
    if not video.is_file():
        return False
    png.parent.mkdir(parents=True, exist_ok=True)
    r = _run(["ffmpeg", "-hide_banner", "-v", "error", "-y",
              "-ss", f"{max(0.0, frame / max(1.0, fps)):.3f}", "-i", str(video),
              "-frames:v", "1", str(png)], timeout=120)
    return r.returncode == 0 and png.is_file()


