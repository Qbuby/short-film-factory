"""HyperFrames 渲染路线(HTML/CSS + GSAP → MP4)。

与 mg harness 的区别:
  - mg harness:页面自己 `window.renderAt(t)` 画每一帧,纯函数,确定性最强;
  - HyperFrames:用 GSAP 时间轴 + CSS 布局,由它接管逐帧 seek 与编码,
    在"排版叙事 / 大字号 / 图文混排"这类片子上更省事。

用法:
    python tools/motion_design/render_hyperframes.py --project projects/code-first/<slug> \
        --out out/video.mp4 --fps 30 [--audio out/audio.wav] [--check]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path, timeout: int = 1800) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, shell=(os.name == "nt"))
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="HyperFrames 渲染")
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--audio", default="", help="音轨 wav/mp3;HyperFrames 自己不出声,渲染完再 mux 进去")
    ap.add_argument("--fps", type=int, default=0)
    ap.add_argument("--quality", default="looks")
    ap.add_argument("--workers", default="")
    ap.add_argument("--check", action="store_true", help="只跑 hyperframes check(lint+validate)")
    args = ap.parse_args(argv)

    project = Path(args.project).resolve()
    if not (project / "index.html").exists():
        print(json.dumps({"ok": False, "error": "项目里没有 index.html", "project": str(project)}, ensure_ascii=False))
        return 2
    if not shutil.which("npx"):
        print(json.dumps({"ok": False, "error": "找不到 npx"}, ensure_ascii=False))
        return 3

    npx = shutil.which("npx") or "npx"

    if args.check:
        code, out = run([npx, "--yes", "hyperframes", "check"], project, 900)
        print(json.dumps({"ok": code == 0, "log_tail": out[-1500:]}, ensure_ascii=False))
        return 0 if code == 0 else 1

    # 相对路径按项目目录解析,避免把产物写到仓库根下
    if args.out:
        out_path = str((project / args.out).resolve()) if not Path(args.out).is_absolute() else args.out
    else:
        out_path = str(project / "renders" / "video.mp4")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [npx, "--yes", "hyperframes", "render", ".", "--output", out_path, "--quality", args.quality]
    if args.fps:
        cmd += ["--fps", str(args.fps)]
    if args.workers:
        cmd += ["--workers", str(args.workers)]

    code, log = run(cmd, project, 2400)
    ok = code == 0 and Path(out_path).exists()
    audio_muxed = False
    if ok and args.audio:
        # HyperFrames 渲染出的 MP4 没有声音(它的 hasAudio 永远是 false,
        # 除非合成里自己放了 <audio>/<video>) —— 所以音轨在这里补进去。
        apath = Path(args.audio)
        if not apath.is_absolute():
            apath = (project / args.audio).resolve()
        if apath.exists() and shutil.which("ffmpeg"):
            tmp = Path(out_path).with_name(Path(out_path).stem + ".mux.mp4")
            mux = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", out_path, "-i", str(apath),
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", "-movflags", "+faststart", str(tmp),
            ]
            mcode, mlog = run(mux, project, 600)
            if mcode == 0 and tmp.exists():
                tmp.replace(out_path)
                audio_muxed = True
                log += "\n[mux] " + str(apath)
            else:
                log += "\n[mux failed] " + mlog[-500:]

    print(json.dumps({"ok": ok, "out": out_path, "bytes": Path(out_path).stat().st_size if Path(out_path).exists() else 0,
                      "audio_muxed": audio_muxed, "log_tail": log[-1200:]}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())