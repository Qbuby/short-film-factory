"""Code-first 评审工具:给「独立评审」提供客观证据。

产出三样东西:
  1. 规格检查:时长 / 分辨率 / fps / 音轨存在与否(ffprobe);
  2. 画面证据:contact sheet(每 0.5s 一帧拼图)+ 指定关键帧;
  3. 音频证据:响度 / 真峰值 / onset 命中(复用 vendored mgaudio 的 qc);
另外自动标出客观问题:黑帧、静音段、削波、字幕/画面过曝之类能自动检出的。

**它不替代评委**:rubric 的 7 个维度打分与修复清单由 agent 依据这些证据来写。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AUDIO_DIR = REPO / "lib" / "motion_design" / "mgstyles" / "audio"
sys.path.insert(0, str(AUDIO_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mgaudio import qc as mg_qc  # noqa: E402


def jsonable(obj):
    """把 numpy 标量/数组转成 JSON 可写的原生类型。"""
    try:
        import numpy as np
    except ImportError:
        return obj
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return (proc.stdout or "") + (proc.stderr or "")


def probe(video: Path) -> dict:
    out = run([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
        "-of", "json", str(video),
    ])
    try:
        data = json.loads(out or "{}")
    except json.JSONDecodeError:
        return {"error": "ffprobe 无法解析"}
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fps = 0.0
    if video_stream and "/" in str(video_stream.get("r_frame_rate", "")):
        num, den = video_stream["r_frame_rate"].split("/")
        fps = float(num) / float(den) if float(den) else 0.0
    return {
        "duration": float(fmt.get("duration", 0) or 0),
        "size_bytes": int(fmt.get("size", 0) or 0),
        "bit_rate": fmt.get("bit_rate"),
        "width": (video_stream or {}).get("width"),
        "height": (video_stream or {}).get("height"),
        "fps": round(fps, 3),
        "video_codec": (video_stream or {}).get("codec_name"),
        "audio_codec": (audio_stream or {}).get("codec_name"),
        "sample_rate": (audio_stream or {}).get("sample_rate"),
        "channels": (audio_stream or {}).get("channels"),
        "has_audio": audio_stream is not None,
    }


def detect_black_frames(video: Path, duration: float) -> list[float]:
    """找出接近全黑的帧(亮度极低)的时间点。"""
    out = run([
        "ffmpeg", "-hide_banner", "-loglevel", "info", "-i", str(video),
        "-vf", "blackdetect=d=0.08:pix_th=0.10", "-an", "-f", "null", "-",
    ])
    return [float(m) for m in re.findall(r"black_start:([0-9.]+)", out)]


def detect_silence(video: Path) -> list[dict]:
    out = run([
        "ffmpeg", "-hide_banner", "-loglevel", "info", "-i", str(video),
        "-af", "silencedetect=n=-45dB:d=0.4", "-vn", "-f", "null", "-",
    ])
    segs = []
    start = None
    for line in out.splitlines():
        m = re.search(r"silence_start: (-?[0-9.]+)", line)
        if m:
            start = float(m.group(1))
        m = re.search(r"silence_end: ([0-9.]+)", line)
        if m and start is not None:
            segs.append({"start": round(start, 3), "end": round(float(m.group(1)), 3)})
            start = None
    return segs


def extract_stills(video: Path, times: list[float], out_dir: Path) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for t in times:
        dst = out_dir / f"t{t:06.3f}.png"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(dst)])
        rows.append({"t": round(t, 3), "path": str(dst), "exists": dst.exists()})
    return rows


def contact_sheet(video: Path, out: Path, duration: float, every: float = 0.5, cols: int = 5) -> dict:
    """每 every 秒抽一帧,拼成一张 contact sheet。"""
    n = max(1, int(duration / every))
    times = [round(i * every, 3) for i in range(n)]
    tmp = out.parent / "_sheet_frames"
    tmp.mkdir(parents=True, exist_ok=True)
    for t in times:
        dst = tmp / f"s{t:06.3f}.png"
        if not dst.exists():
            run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video),
                 "-frames:v", "1", "-vf", "scale=320:-1", str(dst)])
    files = sorted(tmp.glob("s*.png"))
    if not files:
        return {"path": str(out), "frames": 0}
    listfile = tmp / "list.txt"
    listfile.write_text("\n".join(f"file '{f.as_posix()}'" for f in files), encoding="utf-8")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-vf", f"tile={cols}x{max(1, -(-len(files) // cols))}", "-frames:v", "1", str(out)])
    return {"path": str(out), "frames": len(files), "every_seconds": every}



def motion_profile(video: Path, duration: float, fps_sample: float = 10.0, width_px: int = 160,
                   dead_scale: float = 1.0) -> dict:
    """逐秒运动能量(0–255 灰度的平均帧差),用来找"死场"。

    短视频最贵的错误不是不好看,而是有一段时间画面不动 —— 观众就在那里划走了。
    """
    import numpy as np

    tmp = video.parent / "_motion_frames"
    tmp.mkdir(parents=True, exist_ok=True)
    for f in tmp.glob("*.png"):
        f.unlink()
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
        "-vf", f"fps={fps_sample},scale={width_px}:-1", "-pix_fmt", "gray", str(tmp / "f%05d.png"),
    ])
    frames = sorted(tmp.glob("f*.png"))
    if len(frames) < 2:
        return {"per_second": [], "dead_spans": [], "frames_sampled": len(frames)}
    from PIL import Image

    prev = np.asarray(Image.open(frames[0]), dtype=np.float32)
    energies: list[float] = []
    changed: list[float] = []          # 变化像素占比:小物体运动也能捕捉到
    for f in frames[1:]:
        cur = np.asarray(Image.open(f), dtype=np.float32)
        d = np.abs(cur - prev)
        energies.append(float(d.mean()))
        changed.append(float((d > 8).mean()))
        prev = cur
    per_second: list[float] = []
    changed_per_second: list[float] = []
    step = int(round(fps_sample))
    for i in range(0, len(energies), step):
        chunk = energies[i : i + step]
        cchunk = changed[i : i + step]
        per_second.append(round(float(sum(chunk) / max(1, len(chunk))), 2))
        changed_per_second.append(round(float(100 * sum(cchunk) / max(1, len(cchunk))), 3))

    # 死场判定用"变化像素占比"(%),而不是整帧平均差 —— 后者对小的运动物体过于迟钝
    dead: list[dict] = []
    # 允许的静止时长随片长缩放:10s 短片里 1s 不动就该改;
    # 2 分钟的讲解片里,一张卡停 3 秒让人读字是正常节奏,不是缺陷。
    max_hold = max(1.0, min(4.0, duration * 0.03)) * dead_scale
    start = None
    for sec, e in enumerate(changed_per_second):
        if e < 0.5:
            if start is None:
                start = sec
        else:
            if start is not None and sec - start >= max_hold:
                dead.append({"start": start, "end": sec, "seconds": sec - start})
            start = None
    if start is not None and len(changed_per_second) - start >= max_hold:
        dead.append({"start": start, "end": len(changed_per_second), "seconds": len(changed_per_second) - start})
    return {
        "per_second": per_second,
        "changed_per_second": changed_per_second,
        "dead_spans": dead,
        "frames_sampled": len(frames),
    }


def audio_envelope_hits(wav: Path, hits: list[float], tolerance: float = 0.09) -> list[dict]:
    """在期望命中点附近找音频能量峰,给出"是否对齐"的客观判定。

    实现在 hitdetect 里,和 audio.py 共用,免得两处报告口径不一致。
    """
    import hitdetect

    return hitdetect.envelope_hits(wav, hits, tolerance=tolerance)


def run_vision(video: Path, out_dir: Path, context: str, duration: float, frames_n: int = 6) -> dict:
    """把均匀抽出的关键帧交给视觉评委(magpie 路由组)打分。

    抽多帧而不是一帧:评委只看一张图就判断不了"动效工艺",会误判成静态幻灯片。
    """
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import vision_score

    cfg = vision_score.config()
    if not (cfg["base"] and cfg["key"] and cfg["model"]):
        return {"status": "not_configured", "detail": "未配置 MOTION_VISION_BASE/KEY/MODEL,不生成评分"}

    times = [round(duration * (i + 0.5) / frames_n, 3) for i in range(frames_n)]
    rows = extract_stills(video, times, out_dir / "vision-frames")
    paths = [Path(r["path"]) for r in rows if r.get("exists")]
    if not paths:
        return {"status": "no_frames"}
    try:
        result = vision_score.call_vision(
            paths, context, cfg["base"], cfg["key"], cfg["model"], api=cfg["api"],
        )
    except Exception as exc:
        return {"status": "error", "detail": str(exc)[:400]}
    # call_vision 只返回解析出来的 JSON,status/model 要在这里补上,
    # 否则上层会把"跑通了"误判成"没跑"。
    result["status"] = "ok"
    result["model"] = cfg["model"]
    result["api"] = cfg["api"]
    result["frames"] = [str(p) for p in paths]
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Code-first 评审证据生成")
    ap.add_argument("--video", required=True)
    ap.add_argument("--audio", default="")
    ap.add_argument("--out", required=True, help="评审证据目录")
    ap.add_argument("--stills", default="", help="关键帧时间点(逗号分隔)")
    ap.add_argument("--duration", type=float, default=0, help="目标时长(用于规格比对)")
    ap.add_argument("--width", type=int, default=0)
    ap.add_argument("--height", type=int, default=0)
    ap.add_argument("--fps", type=float, default=0)
    ap.add_argument("--storyboard", default="", help="读 audio.sfx 命中点做对齐检查")
    ap.add_argument("--vision", action="store_true", help="附带跑视觉评委(需要 MOTION_VISION_*)")
    ap.add_argument("--vision-context", default="", help="给视觉评委的生产上下文(题材/风格/时长)")
    # 制作档位:同一支片,快速档容忍更多静止/响度偏差,精品档更严。
    # 默认值与历史行为完全一致。
    ap.add_argument("--dead-scale", type=float, default=1.0,
                    help="死场判定阈值的倍数;<1 更严,>1 更宽松")
    ap.add_argument("--lufs-tol", type=float, default=1.0, help="响度允许偏离 −14 LUFS 的幅度")
    ap.add_argument("--sfx-min-ratio", type=float, default=0.0,
                    help="音效命中的最低比例(0 表示不额外要求)")
    ap.add_argument("--black-tolerance", type=int, default=0, help="允许的黑帧段数")
    ap.add_argument("--silence-tolerance", type=int, default=0, help="允许的静音段数")
    args = ap.parse_args(argv)

    video = Path(args.video).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    spec = probe(video)
    duration = args.duration or spec.get("duration", 0)

    stills = [float(x) for x in args.stills.split(",") if x.strip()]
    still_rows = extract_stills(video, stills, out_dir / "stills") if stills else []
    sheet = contact_sheet(video, out_dir / "contact-sheet.png", duration or spec.get("duration", 10))

    issues = []
    if args.duration and abs(spec.get("duration", 0) - args.duration) > 0.08:
        issues.append(f"时长偏差:{spec.get('duration'):.3f}s vs 目标 {args.duration:.3f}s")
    if args.width and spec.get("width") != args.width:
        issues.append(f"宽度不符:{spec.get('width')} vs {args.width}")
    if args.height and spec.get("height") != args.height:
        issues.append(f"高度不符:{spec.get('height')} vs {args.height}")
    if args.fps and abs((spec.get("fps") or 0) - args.fps) > 0.2:
        issues.append(f"帧率不符:{spec.get('fps')} vs {args.fps}")
    if not spec.get("has_audio"):
        issues.append("成片没有音轨")

    motion = motion_profile(video, duration, dead_scale=args.dead_scale)
    blacks = detect_black_frames(video, duration)
    if len(blacks) > args.black_tolerance:
        issues.append(f"检测到黑帧起始:{blacks}")
    silences = detect_silence(video)
    if len(silences) > args.silence_tolerance:
        issues.append(f"检测到静音段:{silences}")

    if motion.get("dead_spans"):
        spans = ", ".join("%d-%ds" % (d["start"], d["end"]) for d in motion["dead_spans"])
        issues.append("死场(≥1s 画面几乎不动):" + spans)

    audio_qc = {}
    hit_rows: list[dict] = []
    if args.audio and Path(args.audio).exists():
        apath = Path(args.audio).resolve()
        res = mg_qc.analyze(str(apath), expected=duration or None)
        audio_qc = {k: v for k, v in res.items() if k != "onsets"}
        lufs = audio_qc.get("lufs_integrated", audio_qc.get("lufs"))
        if isinstance(lufs, (int, float)) and abs(lufs - (-14.0)) > args.lufs_tol:
            issues.append(f"响度偏离 −14 LUFS:{lufs:.1f}(允许 ±{args.lufs_tol:g})")
        tp = audio_qc.get("true_peak_db", audio_qc.get("true_peak"))
        if isinstance(tp, (int, float)) and tp > -1.0:
            issues.append(f"真峰值超 −1 dBTP:{tp:.1f}")
        # 命中点对齐:用包络峰判定,不依赖 librosa
        import json as _json
        sb = args.storyboard or str(Path(args.video).resolve().parents[1] / "storyboard.json")
        if Path(sb).exists():
            try:
                board = _json.loads(Path(sb).read_text(encoding="utf-8"))
                hits = [float(s.get("t", 0)) for s in ((board.get("audio") or {}).get("sfx") or [])]
                if hits:
                    hit_rows = audio_envelope_hits(apath, hits)
                    bad = [r for r in hit_rows if not r.get("ok")]
                    if bad:
                        issues.append("音效未落在期望时间点:" + ", ".join(f"{r['hit']}s→{r['peak']}s" for r in bad))
                    ratio = sum(1 for r in hit_rows if r.get("ok")) / len(hit_rows)
                    if args.sfx_min_ratio > 0 and ratio < args.sfx_min_ratio:
                        issues.append(f"音效命中率 {ratio:.0%} 低于档位要求 {args.sfx_min_ratio:.0%}")
            except Exception:
                hit_rows = []

    report = {
        "video": str(video),
        "spec": spec,
        "target": {"duration": args.duration, "width": args.width, "height": args.height, "fps": args.fps},
        "contact_sheet": sheet,
        "keyframes": still_rows,
        "audio_qc": audio_qc,
        "motion_per_second": motion.get("per_second"),
        "changed_per_second": motion.get("changed_per_second"),
        "dead_spans": motion.get("dead_spans"),
        "hit_alignment": hit_rows,
        "black_frames": blacks,
        "silence": silences,
        "requirements": {"dead_scale": args.dead_scale, "lufs_tol": args.lufs_tol,
                         "sfx_min_ratio": args.sfx_min_ratio,
                         "black_tolerance": args.black_tolerance,
                         "silence_tolerance": args.silence_tolerance},
        "objective_issues": issues,
    }

    # 主观评审:把关键帧交给视觉模型(magpie 路由组)。没配置端点就明确
    # 返回 not_configured,不能拿"客观上没问题"冒充"评委给了 8 分"。
    if args.vision:
        vision = run_vision(video, out_dir, args.vision_context, duration or spec.get("duration", 10))
        report["vision"] = vision
        if vision.get("status") == "ok":
            scores = vision.get("scores") or {}
            try:
                avg = sum(float(v) for v in scores.values()) / max(1, len(scores))
            except (TypeError, ValueError, ZeroDivisionError):
                avg = None
            report["vision_score_average"] = round(avg, 2) if avg is not None else None
        else:
            issues.append("视觉评审未完成:" + str(vision.get("detail") or vision.get("status")))

    report = jsonable(report)
    (out_dir / "review-evidence.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    slim = {k: report[k] for k in ("spec", "objective_issues", "dead_spans", "motion_per_second", "hit_alignment", "vision_score_average") if k in report}
    print(json.dumps(slim, ensure_ascii=False, indent=1)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
