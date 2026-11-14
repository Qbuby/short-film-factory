"""按需拉取 mg-styles-15 的 CC0 采样库(约 58MB),不进 git 仓库。

为什么按需:103 个 FLAC 共 58MB,直接 vendor 会让仓库变成"库比代码大";而采样是可重建的。
本脚本从上游 GitHub 拉 `lib/audio/samples/**` 到 `<mgaudio>/samples/`(或 `MGAUDIO_SAMPLES` 指定的目录),
逐文件校验字节数,并写 `MANIFEST.json` 记录来源 commit、路径、大小、SHA-256。

用法:
    python tools/motion_design/fetch_samples.py                 # 拉到默认位置
    python tools/motion_design/fetch_samples.py --dest D:/cache/mg-samples
    python tools/motion_design/fetch_samples.py --check         # 只校验,不下载

许可:上游采样为 CC0(VCSL 子集),来源说明见 lib/motion_design/NOTICE.md。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

REPO_SLUG = "Vincentwei1021/mg-styles-15"
BRANCH = "main"
API_TREE = f"https://api.github.com/repos/{REPO_SLUG}/git/trees/{BRANCH}?recursive=1"
RAW = f"https://raw.githubusercontent.com/{REPO_SLUG}/{BRANCH}/"
PREFIX = "lib/audio/samples/"
DEFAULT_DEST = Path(__file__).resolve().parents[2] / "lib" / "motion_design" / "mgstyles" / "audio" / "samples"


def opener():
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener()


def list_remote(op) -> list[dict]:
    req = urllib.request.Request(API_TREE, headers={"User-Agent": "openmontage-agent"})
    with op.open(req, timeout=120) as r:
        tree = json.loads(r.read().decode("utf-8"))
    files = [t for t in tree.get("tree", []) if t.get("type") == "blob" and t["path"].startswith(PREFIX)]
    return files


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="拉取 mg-styles-15 CC0 采样库")
    ap.add_argument("--dest", default=str(DEFAULT_DEST))
    ap.add_argument("--check", action="store_true", help="只校验现有文件,不下载")
    ap.add_argument("--limit", type=int, default=0, help="只拉前 N 个(调试用)")
    args = ap.parse_args(argv)

    dest = Path(args.dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    op = opener()
    files = list_remote(op)
    if args.limit:
        files = files[: args.limit]
    total = sum(f.get("size", 0) for f in files)
    print(f"[samples] 远端 {len(files)} 个文件,共 {total / 1e6:.1f} MB → {dest}")

    manifest_path = dest / "MANIFEST.json"
    manifest = {"source": f"github.com/{REPO_SLUG}", "path_prefix": PREFIX, "branch": BRANCH, "license": "CC0 (VCSL subset, see NOTICE.md)", "files": []}
    ok = skipped = failed = 0
    for f in files:
        rel = f["path"][len(PREFIX):]
        out = dest / rel
        size = int(f.get("size", 0))
        if out.exists() and out.stat().st_size == size:
            skipped += 1
        elif args.check:
            print(f"MISSING {rel} (期望 {size} B)")
            failed += 1
            continue
        elif True:
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                # 文件名里有 #(如 G#2),必须按 path segment 编码,否则 URL 会把它当成 fragment
                url = RAW + urllib.parse.quote(f["path"], safe="/")
                req = urllib.request.Request(url, headers={"User-Agent": "openmontage-agent"})
                with op.open(req, timeout=180) as r:
                    data = r.read()
                if len(data) != size:
                    raise IOError(f"字节数不符 {len(data)} != {size}")
                out.write_bytes(data)
                ok += 1
            except Exception as exc:
                print(f"FAIL {rel}: {str(exc)[:100]}")
                failed += 1
                continue
        manifest["files"].append({"path": rel, "size": size, "sha256": sha256(out.read_bytes())})
        if (ok + skipped) % 20 == 0:
            print(f"  ... {ok + skipped}/{len(files)}")

    if not args.check:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"dest": str(dest), "downloaded": ok, "already_ok": skipped, "failed": failed, "manifest": str(manifest_path)}, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())