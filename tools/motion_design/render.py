"""Code-first 渲染器:把「代码画每一帧」的 HTML 页面渲成 MP4 + 关键帧。

复用 mg-styles-15 的 harness/render.mjs(逐帧渲染:MIT,见 lib/motion_design/NOTICE.md),
本文件只做三件事:
  1. 找到本机 Chrome(puppeteer-core 需要可执行文件路径);
  2. 补齐 ffmpeg / Node 依赖的环境;
  3. 把参数翻译成 harness 的命令行。

页面契约(mg harness):
    window.DEMO = { width, height, fps, duration }
    window.renderAt = async (t) => { /* 画第 t 秒这一帧 */ }
    window.__ready = true            // 页面就绪后置位
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "lib" / "motion_design" / "mgstyles" / "harness" / "render.mjs"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]


def find_chrome() -> str | None:
    env = os.environ.get("MG_CHROME")
    if env and Path(env).exists():
        return env
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    found = shutil.which("chrome") or shutil.which("chromium") or shutil.which("google-chrome")
    return found


def check_balance(html: Path) -> list[str]:
    """粗查页面里 ctx.save()/ctx.restore() 是否成对。

    这类不平衡是 code-first 渲染里最难查的 bug:单帧静帧完全正常,
    但逐帧渲染时变换/透明度会一路累积,成片整段崩坏。
    只做整体计数 —— 按函数分开数会被 return 早退的分支误报。
    """
    try:
        src = html.read_text(encoding="utf-8")
    except OSError:
        return []
    # 注释里出现 "ctx.restore()" 会被数进去,先剥掉行注释与块注释
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)//.*$", "", src)
    saves = src.count("ctx.save()")
    restores = src.count("ctx.restore()")
    if saves != restores:
        return [f"ctx.save() {saves} 次 / ctx.restore() {restores} 次 —— 不平衡会逐帧累积画布状态"]
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Code-first 逐帧渲染(HTML → MP4)")
    ap.add_argument("--project", required=True, help="工程目录(里面有 index.html)")
    ap.add_argument("--page", default="index.html")
    ap.add_argument("--out", default="", help="输出 mp4 路径(默认 <project>/out/video.mp4)")
    ap.add_argument("--audio", default="", help="要混入的 wav")
    ap.add_argument("--stills", default="", help="关键帧时间点(逗号分隔),给了就只出静帧不出视频")
    ap.add_argument("--width", type=int, default=0)
    ap.add_argument("--height", type=int, default=0)
    ap.add_argument("--fps", type=int, default=0)
    ap.add_argument("--duration", type=float, default=0)
    ap.add_argument("--scale", type=float, default=1.0, help="预览缩放(布局按 W×H CSS 像素不变)")
    ap.add_argument("--mb", type=int, default=0, help="运动模糊采样数(0=读 storyboard,缺省 1)")
    ap.add_argument("--storyboard", default="", help="从这里读 duration/width/height/fps/motion_blur 默认值")
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args(argv)

    # storyboard 里的 render 设置作为默认值
    board = {}
    sb = args.storyboard or str(Path(args.project) / "storyboard.json")
    if Path(sb).exists():
        try:
            board = json.loads(Path(sb).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            board = {}
    render_cfg = board.get("render") or {}
    if not args.duration and board.get("duration"):
        args.duration = float(board["duration"])
    if not args.width and board.get("width"):
        args.width = int(board["width"])
    if not args.height and board.get("height"):
        args.height = int(board["height"])
    if not args.fps and board.get("fps"):
        args.fps = int(board["fps"])
    if not args.mb:
        args.mb = int(render_cfg.get("motion_blur") or 1)
    if not args.scale or args.scale == 1.0:
        if render_cfg.get("scale"):
            args.scale = float(render_cfg["scale"])

    project = Path(args.project).resolve()
    if not (project / args.page).exists():
        print(f"[render] 页面不存在:{project / args.page}", file=sys.stderr)
        return 2

    # 出片前先查 save/restore 平衡:静帧照样渲染正常,只有逐帧成片会崩
    balance = check_balance(project / args.page)
    for msg in balance:
        print(f"[render] 警告:{msg}", file=sys.stderr)

    chrome = find_chrome()
    if not chrome:
        print("[render] 找不到 Chrome,请设置环境变量 MG_CHROME", file=sys.stderr)
        return 3
    if not shutil.which("ffmpeg"):
        print("[render] 找不到 ffmpeg,请把它放进 PATH", file=sys.stderr)
        return 4

    cmd = ["node", str(HARNESS), str(project), "--page", args.page, "--root", str(project)]
    # 相对路径按 project 解析,避免写到仓库根下
    def _resolve(p: str) -> str:
        return str((project / p).resolve()) if not Path(p).is_absolute() else p
    if args.out:
        cmd += ["--out", _resolve(args.out)]
    if args.audio:
        cmd += ["--audio", _resolve(args.audio)]
    if args.stills:
        cmd += ["--stills", args.stills]
    if args.width:
        cmd += ["--w", str(args.width)]
    if args.height:
        cmd += ["--h", str(args.height)]
    if args.fps:
        cmd += ["--fps", str(args.fps)]
    if args.duration:
        cmd += ["--duration", str(args.duration)]
    if args.scale != 1.0:
        cmd += ["--scale", str(args.scale)]
    if args.mb != 1:
        cmd += ["--mb", str(args.mb)]
    if args.workers != 1:
        cmd += ["--workers", str(args.workers)]

    env = dict(os.environ)
    env["MG_CHROME"] = chrome
    env.setdefault("NODE_OPTIONS", "--max-old-space-size=4096")

    print("[render] " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(HARNESS.parent), env=env)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
