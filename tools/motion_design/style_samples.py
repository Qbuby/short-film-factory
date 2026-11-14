"""Render the library's authored five-second style demonstrations.

Uses its own Remotion entry point; never rewrites the user film registry.
Render into a NEW output directory, review it, then explicitly publish approved
files to public/styles. Silent H.264 clips are decoded lazily by the desktop UI.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor

REPO = Path(__file__).resolve().parents[2]
COMPOSER = REPO / "remotion-composer"
ENTRY = "src/style-showcase/index.tsx"
IDS = tuple(row["id"] for row in json.loads(
    (Path(__file__).parent / "film_styles.json").read_text(encoding="utf-8"))["styles"])


def cli() -> list[str]:
    bundled = REPO / "dist" / "短片工厂-1.3.0" / "runtime" / "node" / "node.exe"
    node = os.environ.get("OE_NODE_DIR")
    node = str(Path(node) / "node.exe") if node else shutil.which("node")
    node = node or str(bundled)
    return [node, str(COMPOSER / "node_modules" / "@remotion" / "cli" / "remotion-cli.js")]


def render(sid: str, out: Path, stills: bool, concurrency: int) -> dict:
    log = out / f"{sid}.log"
    # The design canvas is 1080x1920, output is a crisp720x1280. Do not override FPS.
    if stills:
        dest = out / f"{sid}.png"
        command = [*cli(), "still", ENTRY, f"showcase-{sid}", str(dest),
                   "--frame", "60", "--scale", str(2 / 3), "--log=error"]
    else:
        dest = out / f"{sid}.mp4"
        command = [*cli(), "render", ENTRY, f"showcase-{sid}", str(dest),
                   "--scale", str(2 / 3), "--codec", "h264", "--crf", "19",
                   "--pixel-format", "yuv420p", "--muted", "--concurrency", str(concurrency), "--log=error"]
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(command, cwd=COMPOSER, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"{sid} render failed (exit {result.returncode}); see {log}")
    if not stills:
        # Poster comes from the encoded sample, not a separate unverified still.
        ffmpeg = shutil.which("ffmpeg") or str(REPO / "dist/短片工厂-1.3.0/runtime/bin/ffmpeg.exe")
        subprocess.run([ffmpeg, "-v", "error", "-y", "-ss", "2", "-i", str(dest),
                        "-frames:v", "1", "-update", "1", str(out / f"{sid}.png")], check=True)
    row = {"id": sid, "file": dest.name, "bytes": dest.stat().st_size,
           "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()}
    print(json.dumps(row, ensure_ascii=False), flush=True)
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default="")
    parser.add_argument("--out", required=True, help="NEW output directory, never user projects")
    parser.add_argument("--stills", action="store_true")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    ids = [s.strip() for s in args.only.split(",") if s.strip()] or list(IDS)
    if len(set(ids)) != len(ids) or any(s not in IDS for s in ids):
        parser.error("unknown or duplicate style identifier")
    if not 1 <= args.jobs <= 3 or not 1 <= args.concurrency <= 8:
        parser.error("jobs must be1..3, concurrency1..8")
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        rows = list(pool.map(lambda sid: render(sid, out, args.stills, args.concurrency), ids))
    (out / "manifest.json").write_text(json.dumps({"kind": "authored-style-demonstrations",
        "seconds": 5, "fps": 30, "width": 720, "height": 1280, "samples": rows},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
