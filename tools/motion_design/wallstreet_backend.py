"""Playwright 逐帧渲染后端 + 实拍/新闻证据轨（短片工厂 · mg-wallstreet）。

这是 HeyChengC/wallstreet-explainer 真正被接进来的生产链，不是一层风格皮肤：

  * 逐帧渲染器 —— 移植它的 `window.ready` / `window.seek(t)` 确定性协议、
    JPEG 流喂 ffmpeg、多 worker 分段编码、空画面自检（render_playwright.mjs）。
    原仓库缺最后一环音画合成，这里补上，直接出带 AAC 的成片。
  * 实拍与新闻能力 —— 复用 vendor 里的 snap_news.mjs（新闻原文截图）、
    footage.py（实拍抽帧）、matte*.py（逐帧抠像）、host_timeline.py（口播对齐）；
    它们的产物挂进 `<project>/evidence/`，由舞台按 (t-t0)*fps 取帧显示。
  * 没有证据时画面明确写「未附实拍 / 新闻证据」，绝不伪造新闻截图或真人。

外部依赖边界（写清楚，绝不静默伪装）：
  * Chromium / Chrome / Edge：本机有 Chrome/Edge 就能离线跑；也可带 Playwright 自带 chromium。
  * 新闻截图 snap_news.mjs、实拍下载 footage.py get：需要联网 + Playwright。
  * 逐帧抠像 matte.py：需要 ~/.rembg 的 ONNX 模型 + onnxruntime；没有就只走实拍/新闻。
  * 字体：不随包分发（原 skill 明确要求用户自备），缺字体退系统字体，不影响出片。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
WS = TOOLS / "wallstreet"
sys.path.insert(0, str(TOOLS))

import quality as qcfg  # noqa: E402

RENDER_MJS = WS / "render_playwright.mjs"
STAGE = WS / "stage"
VENDOR = WS / "vendor"
NODE = os.environ.get("OE_NODE") or ""
RATIOS = json.loads((TOOLS / "ratios.json").read_text(encoding="utf-8"))


def _resolve_ratio(key: str) -> tuple[int, int]:
    """和 film.py resolve_ratio 同规则的独立实现（避免从 film.py 反向 import）。"""
    key = (key or "9:16").strip()
    if key.startswith("custom:"):
        raw = key.split(":", 1)[1].lower().replace("×", "x").replace("*", "x")
        cw, ch = raw.split("x", 1)
        w, h = float(cw), float(ch)
        return (int(round(1080 * w / min(w, h) / 2) * 2),
                int(round(1080 * h / min(w, h) / 2) * 2))
    row = RATIOS.get(key) or RATIOS.get("9:16")
    if isinstance(row, dict):
        return int(row.get("w") or 1080), int(row.get("h") or 1920)
    if isinstance(row, (list, tuple)) and len(row) >= 2:
        return int(row[0]), int(row[1])
    return 1080, 1920


def _node() -> str:
    if NODE and Path(NODE).is_file():
        return NODE
    nd = os.environ.get("OE_NODE_DIR")
    if nd:
        exe = Path(nd) / "node.exe"
        if exe.is_file():
            return str(exe)
    return shutil.which("node") or "node"


def _evidence_dir(project: Path) -> Path:
    return project / "evidence"


def _probe_evidence(project: Path) -> dict:
    """把 <project>/evidence/ 里真实存在的素材登记成证据轨。

    目录约定（全部可选，缺哪条就明说，不编造）：
      news/<id>.png          —— snap_news.mjs 截出的新闻/报告原文
      news/<id>.json         —— 同名的 news.json 条目，含 hits[].rects 高亮坐标
      clips/<名>/0001.jpg…   —— footage.py extract 出的实拍逐帧
      cut/<名>/0001.png…     —— matte.py 抠出的 RGBA 人像 + box.json
      host/0001.jpg…         —— 真人口播逐帧
      evidence.json          —— 人工/模型写的挂载表：哪一段用哪条证据、出处怎么写
    """
    root = _evidence_dir(project)
    out: dict = {"news": [], "clips": [], "cuts": [], "host": None, "mount": {}}
    if not root.is_dir():
        return out
    for png in sorted((root / "news").glob("*.png")):
        meta = png.with_suffix(".json")
        item = {"src": png.as_posix(), "id": png.stem}
        if meta.is_file():
            try:
                j = json.loads(meta.read_text(encoding="utf-8"))
                hits = j.get("hits") or []
                if hits and hits[0].get("rects"):
                    r = hits[0]["rects"][0]
                    # snap_news.mjs 的坐标是 1600 宽网页 CSS 像素，换算成 0~1 比例。
                    item["hl"] = [round(v / 1600, 4) for v in r[:4]]
                item["credit"] = j.get("title") or png.stem
            except (OSError, ValueError):
                pass
        out["news"].append(item)
    for kind, key, ext in (("clips", "clips", "jpg"), ("cut", "cuts", "png"), ("host", "host", "jpg")):
        base = root / kind
        if not base.is_dir():
            continue
        if kind == "host":
            frames = sorted(base.glob(f"*.{ext}"))
            if frames:
                out["host"] = {"dir": base.as_posix(), "count": len(frames), "ext": ext}
            continue
        for sub in sorted(p for p in base.iterdir() if p.is_dir()):
            frames = sorted(sub.glob(f"*.{ext}"))
            if not frames:
                continue
            item = {"dir": sub.as_posix(), "count": len(frames), "ext": ext, "name": sub.name}
            box = sub / "box.json"
            if box.is_file():
                try:
                    j = json.loads(box.read_text(encoding="utf-8"))
                    item["cx"] = j.get("cx") or []
                    item["scale"] = j.get("scale")
                except (OSError, ValueError):
                    pass
            out[key].append(item)
    mf = root / "evidence.json"
    if mf.is_file():
        try:
            out["mount"] = json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return out


def _mount_for(beat_id: str, ev: dict) -> dict | None:
    """按 evidence.json 的挂载表把证据分配到某一拍；没表就按出现顺序轮转。"""
    mount = ev.get("mount") or {}
    row = mount.get(beat_id)
    if isinstance(row, dict) and row.get("kind"):
        return row
    # 没有挂载表时，把已有的新闻/实拍按拍序各用一次，保证「证据能力」真的出现在片里。
    return None


def build_film_data(meta: dict, project: Path, pub: Path, width: int, height: int,
                    fps: int, duration: float) -> dict:
    """把短片工厂的 film.json / props.json / subtitles.json 变成逐帧舞台数据。"""
    props = json.loads((pub / "props.json").read_text(encoding="utf-8"))
    film = props.get("film") or {}
    timing = film.get("timing") or {}
    beats = film.get("beats") or []
    subs = props.get("subs") or []
    ev = _probe_evidence(project)

    used_news = used_clip = used_cut = 0
    stage_beats = []
    for b in beats:
        bid = str(b.get("id") or "")
        t0, t1 = timing.get(bid) or [0.0, max(1.0, duration / max(1, len(beats)))]
        row: dict = {
            "id": bid, "t0": round(float(t0), 3), "t1": round(float(t1), 3),
            "title": b.get("title") or [], "stamp": b.get("stamp") or "",
            "en": b.get("en") or "", "note": b.get("note") or "",
            "big": b.get("big") or "", "bars": b.get("bars") or [0.42, 0.66, 0.88, 1.0],
        }
        m = _mount_for(bid, ev)
        if not m:
            # 自动挂载：开头一拍上新闻原文，中间一拍上实拍/抠像，其余保持代码图解。
            if ev["news"] and used_news < len(ev["news"]) and bid == (beats[0].get("id") or ""):
                m = {"kind": "news", "index": 0}
            elif ev["cuts"] and used_cut < len(ev["cuts"]):
                m = {"kind": "cut", "index": used_cut}
            elif ev["clips"] and used_clip < len(ev["clips"]):
                m = {"kind": "footage", "index": used_clip}
        if m:
            k = m.get("kind")
            pool = {"news": ev["news"], "footage": ev["clips"], "cut": ev["cuts"],
                    "host": [ev["host"]] if ev["host"] else []}.get(k) or []
            idx = min(int(m.get("index") or 0), max(0, len(pool) - 1))
            if pool:
                src = dict(pool[idx])
                src["kind"] = k
                src.setdefault("label", src.get("name") or src.get("id") or "")
                if k == "news":
                    src.setdefault("credit", src.get("credit") or "新闻原文 / 来源截图")
                    used_news += 1
                elif k == "cut":
                    used_cut += 1
                elif k == "footage":
                    src.setdefault("credit", src.get("name") or "实拍画面")
                    used_clip += 1
                elif k == "host":
                    src.setdefault("shape", m.get("shape") or "pip")
                row["evidence"] = src
        stage_beats.append(row)

    # 真人口播模式：用户挂了 host 帧时，整片叠加圆窗。
    host = ev["host"]
    if host:
        for row in stage_beats:
            row.setdefault("evidence", {"kind": "host", "shape": "pip", **host})

    # 纹理走 vendor/kit/assets，不联网、不随字体走。
    assets = {}
    for name, fn in (("fabric", "fabric.jpg"), ("grain", "grain.png")):
        f = VENDOR / "kit" / "assets" / fn
        if f.is_file():
            assets[name] = f.as_posix()

    title = meta.get("title") or meta.get("name") or ""
    return {
        "w": width, "h": height, "fps": fps, "duration": round(duration, 3),
        "title": title, "footer": (film.get("footer") or {}).get("label")
                        if isinstance(film.get("footer"), dict) else "",
        "brand": {"color": "#3B7A1C"},
        "assets": assets,
        "fonts": ["700 46px 'Microsoft YaHei'", "800 104px 'Microsoft YaHei'"],
        "hook": {"enabled": True, "name": "小黄鸭"},
        "beats": stage_beats,
        "subs": [[float(c[0]), float(c[1]), str(c[2])] for c in subs],
        "evidence_summary": {
            "news": len(ev["news"]), "clips": len(ev["clips"]), "cuts": len(ev["cuts"]),
            "host": bool(ev["host"]),
        },
    }


def _copy_stage(work: Path, film_data: dict) -> Path:
    """把 stage/ 里的 HTML/JS、vendor 纹理、证据图都放进同一个 http 根目录。

    render.mjs 的服务器根目录 = --dir，页面里 ../ 会 404。所以纹理和证据必须
    复制/链接到 stage 目录内；这里用真实复制（分发包里不能带 junction）。
    """
    stage = work / "stage"
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copy2(STAGE / "index.html", stage / "index.html")
    shutil.copy2(STAGE / "film.js", stage / "film.js")
    (stage / "__DATA__.js").write_text(
        "window.__FILM__ = " + json.dumps(film_data, ensure_ascii=False) + ";",
        encoding="utf-8")
    # index.html 里的占位符换成实际数据文件名
    html = (stage / "index.html").read_text(encoding="utf-8").replace("__DATA__.js", "__DATA__.js")
    (stage / "index.html").write_text(html, encoding="utf-8")

    def rel(src: str, prefix: str) -> str:
        """把一个绝对/相对素材路径复制进 stage，返回页面可用的相对 URL。"""
        p = Path(src)
        if not p.is_absolute():
            p = (work / src).resolve()
        if not p.is_file():
            return ""
        dest_dir = stage / prefix / p.parent.name
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / p.name
        if not dest.exists():
            shutil.copy2(p, dest)
        return (prefix + "/" + p.parent.name + "/" + p.name).replace("\\", "/")

    for key in ("fabric", "grain"):
        if film_data["assets"].get(key):
            film_data["assets"][key] = rel(film_data["assets"][key], "assets")
    for b in film_data["beats"]:
        e = b.get("evidence")
        if not e:
            continue
        if e.get("src"):
            e["src"] = rel(e["src"], "evidence")
        if e.get("dir"):
            d = Path(e["dir"])
            dest = stage / "evidence" / "frames" / d.name
            if not dest.exists() and d.is_dir():
                shutil.copytree(d, dest)
            e["dir"] = ("evidence/frames/" + d.name).replace("\\", "/")
    # 复制后 __DATA__.js 里的路径已变，重写一次
    (stage / "__DATA__.js").write_text(
        "window.__FILM__ = " + json.dumps(film_data, ensure_ascii=False) + ";",
        encoding="utf-8")
    return stage


def render(meta: dict, dest: Path, *, action: str, props: Path, extra,
           log: str = "info", check: bool = True):
    """被 film.py render_selected 调用的入口。返回 (伪 composition 名, CompletedProcess)。

    action == "still" 时 dest 是 PNG，extra 里带 ("--frame", "45")；
    否则 dest 是 MP4，extra 里带 --scale/--crf/--concurrency。
    """
    project = Path(meta["_project_dir"]) if meta.get("_project_dir") else None
    if project is None:
        raise RuntimeError("playwright 后端需要 project 目录")
    pub = props.parent
    q = qcfg.output_spec(meta)

    # ── v2:kit 模板档直通(模型写的镜头表)。v1 固定舞台降级为兜底。──
    if action != "still" and (project / "wallstreet_shots.json").is_file():
        import wallstreet_kit  # noqa: WPS433
        kit_ok, kit_why = wallstreet_kit.available()
        if kit_ok:
            rw, rh = _resolve_ratio("16:9")
            width, height = qcfg.output_dimensions(rw, rh, q)
            info = wallstreet_kit.render_kit(
                meta, project, dest, height=height,
                log=lambda m, _l=log: print(m, flush=True))
            return "pw-wallstreet-kit", subprocess.CompletedProcess(
                ["wallstreet-kit", str(info.get("shots", 0))], 0)
        print(f"[wallstreet] kit 不可用({kit_why});退回 v1 固定竖版舞台", flush=True)

    rw, rh = _resolve_ratio(meta.get("ratio", "9:16"))
    width, height = qcfg.output_dimensions(rw, rh, q)
    fps = int(q["fps"])
    timing_total = float(json.loads(props.read_text(encoding="utf-8"))["film"]["total"])
    duration = timing_total

    work = project / "out" / "playwright"
    work.mkdir(parents=True, exist_ok=True)
    film_data = build_film_data(meta, project, pub, width, height, fps, duration)
    stage = _copy_stage(work, film_data)

    audio = pub / "audio.wav"
    common = ["--dir", str(stage), "--out", str(dest), "--work", str(work / "frames"),
              "--w", str(width), "--h", str(height), "--fps", str(fps),
              "--duration", str(duration), "--audio", str(audio)]
    if action == "still":
        fr = 0
        for i, x in enumerate(extra):
            if x == "--frame" and i + 1 < len(extra):
                fr = int(float(extra[i + 1]))
        # v2:kit 成片已存在时,封面直接从成片抽帧(竖版舞台画的是另一套东西)。
        if (project / "wallstreet_shots.json").is_file():
            import wallstreet_kit  # noqa: WPS433
            vid = pub.parent.parent / "out" / f"{meta.get('slug')}.mp4"
            if vid.is_file() and wallstreet_kit.cover_from(vid, dest, fr, fps):
                return "pw-wallstreet-kit", subprocess.CompletedProcess(["still"], 0)
        argv = [RENDER_MJS.as_posix(), *common, "--mode", "still", "--frame", str(fr)]
    else:
        # output_spec 已把分辨率 crf 与档位 crf_delta 合并过，别再减一次。
        crf = str(int(q["crf"]))
        workers = max(1, min(4, int(q["concurrency"])))
        argv = [RENDER_MJS.as_posix(), *common, "--mode", "video",
                "--crf", crf, "--workers", str(workers)]

    node = _node()
    cmd = [node, *[str(a) for a in argv]]
    env = dict(os.environ)
    env.setdefault("OE_FFMPEG", shutil.which("ffmpeg") or "ffmpeg")
    r = subprocess.run(cmd, cwd=str(stage), env=env,
                       stdout=None if log != "error" else subprocess.DEVNULL)
    result = subprocess.CompletedProcess(cmd, r.returncode)
    if check and r.returncode:
        raise RuntimeError(f"Playwright 逐帧渲染失败(退出码 {r.returncode})")
    return "pw-wallstreet", result
