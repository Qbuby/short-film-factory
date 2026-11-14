"""用多模态 LLM 理解素材 —— 语义分段、标签、时间点都由模型给出。

关键设计(用户定的顺序):**LLM 先整体吃完素材,标签/切片是理解的输出**;
ffmpeg/numpy 只负责抽帧和把模型给的秒数对齐到帧,不做任何语义决策。

为什么必须密集抽帧:企业办公室实拍可能只在一条 10 分钟视频里出现 3 秒。
整片抽 6 帧必然漏掉。这里按 1 帧/秒(上限 60 帧)生成带时间码的接触表,
让模型逐格标注「这一秒看见了什么」,再按内容转折合并成语义段。

复用 vision_score.py 的传输层(OpenAI/Anthropic 双风格、推理模型 thinking 块、
JSON 括号配对解析),不复制代码,零新增依赖。
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
from pathlib import Path

import numpy as np

import vision_score as vs

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
MAX_FRAMES = 60
SAMPLE_FPS = 1.0
CELL = 240
COLS = 6


# ────────────────────────────── 端点 ──────────────────────────────
def endpoint() -> dict:
    """视觉端点优先;没配就复用同一套 LLM 配置(若它支持图片)。

    不重复问用户填第二遍配置 —— 产品不变量:不重复输入已有事实。
    """
    c = vs.config()
    if c["base"] and c["key"] and c["model"]:
        return {**c, "source": "vision"}
    import llm  # noqa: WPS433
    l = llm.config()
    if l["base"] and l["key"] and l["model"]:
        return {"base": l["base"], "key": l["key"], "model": l["model"],
                "api": "openai", "source": "llm"}
    return {"base": "", "key": "", "model": "", "api": "auto", "source": "none"}


def available() -> bool:
    return bool(endpoint()["base"])


# ────────────────────────────── 抽帧 / 接触表 ──────────────────────────────
def extract_contact_sheet(video: Path, start: float, end: float, out: Path,
                          *, cell: int = CELL, cols: int = COLS) -> tuple[Path, list[float]]:
    """把 [start,end) 每秒抽的帧拼成一张带编号和时间码的接触表。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.5, end - start)
    n = max(2, min(MAX_FRAMES, int(math.ceil(duration * SAMPLE_FPS))))
    times = [round(start + i * duration / n, 3) for i in range(n)]
    tmp = out.parent / ("_cells_" + out.stem)
    tmp.mkdir(parents=True, exist_ok=True)
    for f in tmp.glob("*.jpg"):
        f.unlink()
    cells: list[Path] = []
    for i, t in enumerate(times):
        p = tmp / f"c{i:03d}.jpg"
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-ss", f"{t:.3f}",
             "-i", str(video), "-frames:v", "1", "-vf", f"scale={cell}:-2", str(p)],
            capture_output=True, creationflags=NO_WINDOW, timeout=90)
        if r.returncode == 0 and p.exists():
            cells.append(p)
    if not cells:
        raise RuntimeError("抽帧失败,无法生成接触表")
    from PIL import Image, ImageDraw
    ims = [Image.open(p).convert("RGB") for p in cells]
    ch = max(im.height for im in ims)
    rows = math.ceil(len(ims) / cols)
    sheet = Image.new("RGB", (cols * cell, rows * (ch + 18)), (16, 22, 34))
    draw = ImageDraw.Draw(sheet)
    for i, im in enumerate(ims):
        x, y = (i % cols) * cell, (i // cols) * (ch + 18)
        sheet.paste(im, (x, y))
        draw.text((x + 3, y + ch + 2), f"#{i}  {times[i]:.1f}s", fill=(240, 230, 190))
    sheet.save(out, "JPEG", quality=80)
    for p in cells:
        p.unlink(missing_ok=True)
    try:
        tmp.rmdir()
    except OSError:
        pass
    return out, times[:len(ims)]


def _vision_direct(frames: list[Path], system: str, user: str, timeout: int = 300) -> dict:
    """用自己的提示词,复用 vision_score 的传输细节(不复制它的 RUBRIC)。"""
    c = endpoint()
    if not c["base"]:
        raise RuntimeError("未配置视觉或多模态 LLM 端点")
    base, key, model = c["base"], c["key"], c["model"]
    root = base[:-3] if base.endswith("/v1") else base
    api = c.get("api", "auto")

    def openai_call() -> str:
        content: list[dict] = [{"type": "text", "text": user}]
        for p in frames:
            mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
            content.append({"type": "image_url", "image_url": {
                "url": f"data:{mime};base64," + vs._b64(p)}})
        body = {"model": model, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": content}],
            "max_tokens": 4096, "temperature": 0.2}
        payload = vs._post(base + "/chat/completions", body, key, timeout, False)
        return vs._openai_text(payload)

    def anthropic_call() -> str:
        content: list[dict] = [{
            "type": "image", "source": {"type": "base64",
                                         "media_type": "image/jpeg", "data": vs._b64(p)}}
            for p in frames]
        content.append({"type": "text", "text": user})
        body = {"model": model, "max_tokens": 4096, "system": system,
                "messages": [{"role": "user", "content": content}]}
        payload = vs._post(root + "/v1/messages", body, key, timeout, True)
        return vs._anthropic_text(payload)

    order = {"openai": [openai_call], "anthropic": [anthropic_call]}.get(
        api, [anthropic_call, openai_call])
    last: Exception | None = None
    for fn in order:
        try:
            txt = fn()
            if not txt.strip():
                raise RuntimeError("模型返回空内容")
            return vs.extract_json_object(txt)
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"视觉端点调用失败: {last}")


# ────────────────────────────── 提示词 ──────────────────────────────
SYSTEM = """你是一个视频素材库的编目员。用户会给你一张「接触表」:把一个视频按时间顺序
抽出的若干帧拼成网格,每格标了 #编号 和秒数。

你的任务是**先整体看完所有格子**,理解这条视频讲了什么、里面有哪些不同的画面内容,
然后按【内容/主题的变化】把它切成若干语义段落。

铁律:
- 只描述你真正看见的东西。不要推测品牌、公司名、地点,不要编造数字或人物身份。
- 段落边界由内容决定(话题换了、主体换了、场景换了、叙事阶段换了),不是靠像素差。
- 一段视频里只出现几秒的画面(例如 3 秒的办公室实拍)必须单独成段,不能因为短就被合并掉。
- 相邻格子若内容连续(同一个场景/同一个话题),合并进同一段。
- 时间用秒(数字),段落必须首尾相接、覆盖整条视频。
- 输出严格 JSON,不要 markdown、不要解释。"""

USER_TMPL = """文件名:{name}
批次标签:{tags}
接触表共 {n} 格,每格对应的秒数(按顺序):{times}
视频总时长 {duration:.2f} 秒,本次分析区间 {start:.2f}–{end:.2f} 秒。

请为每个「画面内容不同的区间」输出一段,包含:
- title: 8 字以内的中文短标题
- description: 一到两句中文,写清这一段的画面主体、动作、文字(如果有)
- tags: 3–8 个中文标签,用于日后检索(要有具体名词,例如「办公室」「工位」「前台」「会议室」「走廊」「员工」「电脑屏幕」)
- search_terms: 2–5 个中文检索短语,写用户可能怎么找这段
- subjects: 画面里出现的主体(人/物/场景)
- scene: 场景类型(办公室/户外/街景/屏幕录制/图文卡/人物特写/其他)
- usable_as: 适合当什么(开头/论据/过渡/结尾/空镜),数组
- quality: 可用|模糊|过曝|抖动|无内容
- start_seconds / end_seconds: 这一段的起止秒数(数字)

同时给整条视频:
- summary: 一句话中文描述
- global_tags: 5–12 个覆盖整条视频的中文标签
- content_type: 口播|实拍|屏幕录制|图文卡|混合

输出格式:
{{"summary":"…","global_tags":["…"],"content_type":"…",
  "segments":[{{"index":0,"start_seconds":0.0,"end_seconds":8.0,"title":"…","description":"…","tags":["…"],"search_terms":["…"],"subjects":["…"],"scene":"…","usable_as":["…"],"quality":"可用"}}]}}

注意:即使某段只有 2–3 秒,只要画面内容不同就必须单独列出。"""

REFINE_SYSTEM = """你是视频素材检索员。给你一张接触表(每格标了秒数)和一个具体需求,
请只回答:这条视频里**有没有**符合需求的画面?如果有,精确到秒给出起止。

铁律:只依据画面证据,不要猜。找不到就明确说没有,不要用相似场景凑数。
输出严格 JSON:
{{"found": true|false, "reason": "命中/未命中的画面依据(中文,一句话)",
 "clips":[{{"start_seconds":1.0,"end_seconds":4.0,"title":"…","description":"…","tags":["…"],"confidence":0.9}}]}}
clips 最多 3 个,按置信度排序;found=false 时 clips 必须是空数组。"""

REFINE_TMPL = """需求:{query}
文件名:{name}
本次精读区间 {start:.2f}–{end:.2f} 秒,共 {n} 格,时间:{times}

请找出所有符合需求的画面区间。哪怕只有 2–3 秒也要列出来。"""


# ────────────────────────────── 对外主函数 ──────────────────────────────
def understand_video(video: Path, *, work: Path, name: str = "", tags: str = "",
                     duration: float = 0.0, windows: int = 1) -> dict:
    """LLM 整体吃完一条视频 → 摘要/全局标签/语义分段(含精确秒数)。"""
    video = Path(video)
    if not video.is_file():
        raise RuntimeError(f"素材不存在: {video}")
    if duration <= 0:
        duration = _duration(video)
    work.mkdir(parents=True, exist_ok=True)
    nwin = max(1, min(8, int(windows or 1)))
    # 长片自动分窗:每窗不超过 60 秒,保证 1 帧/秒的密度
    nwin = max(nwin, math.ceil(duration / 60.0))
    nwin = min(nwin, 8)
    span = duration / nwin
    all_segs: list[dict] = []
    summary, global_tags, content_type = "", [], ""
    for w in range(nwin):
        a, b = w * span, min(duration, (w + 1) * span)
        if b - a < 0.4:
            continue
        sheet, times = extract_contact_sheet(video, a, b, work / f"sheet{w:02d}.jpg")
        user = USER_TMPL.format(
            name=name or video.name, tags=tags or "无", n=len(times),
            times=", ".join(f"#{i}={t:.1f}s" for i, t in enumerate(times)),
            duration=duration, start=a, end=b)
        t0 = time.time()
        data = _vision_direct([sheet], SYSTEM, user, timeout=300)
        elapsed = round(time.time() - t0, 1)
        if w == 0:
            summary = str(data.get("summary") or "")[:500]
            global_tags = [str(x)[:40] for x in (data.get("global_tags") or [])][:20]
            content_type = str(data.get("content_type") or "")[:20]
        for s in data.get("segments") or []:
            if not isinstance(s, dict):
                continue
            try:
                s0 = max(a, float(s.get("start_seconds", a)))
                s1 = min(b, float(s.get("end_seconds", b)))
            except (TypeError, ValueError):
                continue
            if s1 - s0 < 0.3:
                continue
            s["start_seconds"], s["end_seconds"] = round(s0, 3), round(s1, 3)
            s["window"], s["elapsed"] = w, elapsed
            s["boundary_source"] = "llm"
            all_segs.append(s)
        try:
            sheet.unlink(missing_ok=True)
        except OSError:
            pass
    all_segs.sort(key=lambda s: s["start_seconds"])
    merged: list[dict] = []
    for s in all_segs:
        if merged:
            prev = merged[-1]
            ta, tb = set(prev.get("tags") or []), set(s.get("tags") or [])
            overlap = len(ta & tb) / max(1, len(ta | tb))
            if s["start_seconds"] - prev["end_seconds"] < 0.6 and overlap >= 0.6:
                prev["end_seconds"] = s["end_seconds"]
                prev["tags"] = list(dict.fromkeys([*(prev.get("tags") or []), *(s.get("tags") or [])]))[:12]
                continue
        merged.append(s)
    for i, s in enumerate(merged):
        s["index"] = i
    return {"ok": True, "summary": summary, "global_tags": global_tags,
            "content_type": content_type, "duration": duration,
            "segments": merged, "endpoint": endpoint()["source"],
            "understood_at": time.time()}


def _duration(video: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video)], capture_output=True, text=True,
         creationflags=NO_WINDOW)
    try:
        return float(r.stdout.strip())
    except (TypeError, ValueError):
        raise RuntimeError("无法读取视频时长") from None


# ────────────────────────────── 帧级对齐 ──────────────────────────────
def align_boundaries(video: Path, seconds: list[float], *, window: float = 1.2) -> dict:
    """把 LLM 给的语义边界对齐到最近的真实画面切换点(不改动语义决策)。

    只用 numpy 逐帧差(32×32 RGB),零额外依赖。找不到明显切点就原样返回,
    并标 confidence=none —— 不假装精确。
    """
    out: dict[float, dict] = {}
    for s in sorted(set(round(float(x), 3) for x in seconds)):
        a, b = max(0.0, s - window), s + window
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-v", "error", "-i", str(video),
             "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-an",
             "-vf", "fps=10,scale=32:32", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
            capture_output=True, creationflags=NO_WINDOW, timeout=180)
        px = 32 * 32 * 3
        n = len(r.stdout) // px
        if n < 3:
            out[s] = {"aligned": s, "source": "llm", "confidence": "none"}
            continue
        frames = np.frombuffer(r.stdout[:n * px], dtype=np.uint8).reshape(n, 32, 32, 3).astype(np.int16)
        diffs = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2, 3))
        med, thr = float(np.median(diffs)), 0.0
        thr = max(18.0, med * 3.0)
        best, best_d = -1, 0.0
        for i, d in enumerate(diffs):
            if d > thr and d > best_d:
                best, best_d = i, float(d)
        if best < 0:
            out[s] = {"aligned": s, "source": "llm", "confidence": "none"}
        else:
            out[s] = {"aligned": round(a + (best + 1) / 10.0, 3),
                      "source": "frame_diff", "llm_boundary": s,
                      "confidence": "high" if best_d > thr * 1.5 else "low"}
    return out


# ────────────────────────────── 查询驱动精读 ──────────────────────────────
def refine_for_query(video: Path, query: str, *, work: Path, name: str = "",
                     start: float = 0.0, end: float = 0.0, duration: float = 0.0) -> dict:
    """粗召回后,发更密的帧让 LLM 精确指出「那几秒」在哪。

    这是「长片里藏 3 秒办公室」能被找到的关键:粗索引只挑出候选视频,
    精确时间码由这一步给。
    """
    if not query.strip():
        return {"found": False, "reason": "空需求", "clips": []}
    if duration <= 0:
        duration = _duration(video)
    end = min(end or duration, duration) or duration
    sheet, times = extract_contact_sheet(video, start, end, work / "refine.jpg",
                                         cell=200, cols=6)
    user = REFINE_TMPL.format(query=query, name=name or video.name,
                              start=start, end=end, n=len(times),
                              times=", ".join(f"#{i}={t:.1f}s" for i, t in enumerate(times)))
    data = _vision_direct([sheet], REFINE_SYSTEM, user, timeout=300)
    clips = []
    for c in data.get("clips") or []:
        if not isinstance(c, dict):
            continue
        try:
            s0, s1 = float(c["start_seconds"]), float(c["end_seconds"])
        except (KeyError, TypeError, ValueError):
            continue
        if s1 <= s0 or s0 < start - 0.5 or s1 > end + 1.0:
            continue
        clips.append({**c, "start_seconds": round(s0, 3), "end_seconds": round(s1, 3),
                      "source": "llm_refine"})
    try:
        sheet.unlink(missing_ok=True)
    except OSError:
        pass
    return {"found": bool(data.get("found")) and bool(clips),
            "reason": str(data.get("reason") or "")[:300], "clips": clips[:3]}


def expand_query(query: str) -> list[str]:
    """让文本 LLM 把口语需求扩成检索词(纯文本,不发图)。失败返回原句。"""
    try:
        import llm  # noqa: WPS433
        if not llm.available():
            return [query]
        prompt = ("把下面的视频素材需求扩成 8–14 个中文检索词或短语,覆盖同义说法、"
                  "具体物体、场景、动作。只输出 JSON 数组,不要解释。\n需求:" + query)
        txt = llm.complete("你是素材库检索词扩展器,只输出 JSON 数组。", prompt,
                           max_tokens=400, temperature=0.2)
        m = re.search(r"\[[\s\S]*\]", txt or "")
        arr = json.loads(m.group(0)) if m else []
        return [str(x)[:40] for x in arr if isinstance(x, str)][:14] or [query]
    except Exception:  # noqa: BLE001
        return [query]
