"""剪辑模式的 CLI 入口 —— 让 film_ui 的 run_task 能像生成类一样追踪阶段。

    python edit_mode.py render --project <slug> [--preview]
    python edit_mode.py plan   --project <slug> --requirement "..." [--duration 15]
    python edit_mode.py status

不改 film.py 的任何命令:生成类链路与剪辑模式完全隔离,避免回归。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# 用 -I 直接跑本文件时,脚本目录不在 sys.path 上;同目录的模块必须显式可达。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app_paths import get_paths
from edit_contract import validate, blank_doc, doc_path
import edit_render
import edit_planner
import material_library as lib

PROJECTS = get_paths().projects


def stage(name: str, note: str = "") -> None:
    """结构化阶段标记,film_ui._stage_marker 只认这个形状。"""
    print(json.dumps({"stage": name, "note": note}, ensure_ascii=False), flush=True)


def _project(name: str, *, create: bool = False) -> Path:
    import re
    safe = re.sub(r"[^\w.\-]+", "_", name or "")[:80]
    p = PROJECTS / safe
    if not p.exists():
        if not create:
            raise RuntimeError(f"项目不存在: {safe}")
        p.mkdir(parents=True, exist_ok=True)
        (p / "project.json").write_text(json.dumps({
            "name": safe, "slug": safe, "title": "剪辑短片",
            "style": "edit-mode", "mode": "edit", "duration": 15,
            "ratio": "9:16", "resolution": "1080p", "fps": 30,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def cmd_plan(args) -> dict:
    p = _project(args.project, create=True)
    stage("理解需求", "拆成镜头并检索素材")
    doc = edit_planner.build(
        args.requirement, target_duration=float(args.duration),
        output={"width": int(args.width), "height": int(args.height), "fps": int(args.fps)},
        model=None if args.model == "auto" else args.model == "on",
        allow_web=not args.no_web,
    )
    if doc.get("contract_error"):
        raise RuntimeError("时间轴校验失败: " + doc["contract_error"])
    if not doc.get("cuts"):
        raise RuntimeError("没有找到符合需求的素材:" + str(doc.get("missing_reason") or "")[:300])
    doc_path(p).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    if doc.get("web_used"):
        import web_sources  # noqa: WPS433
        (p / "CREDITS.md").write_text(web_sources.credits(doc["web_used"]), encoding="utf-8")
    stage("锁定素材", (f"{len(doc['cuts'])} 个镜头 / {doc['total']:.2f}s"
                       + (f" / 联网 {len(doc['web_used'])} 段" if doc.get("web_used") else "")))
    return {"ok": True, "project": p.name, "mode": doc["mode"],
            "total": doc["total"], "cuts": len(doc["cuts"]),
            "web_used": len(doc.get("web_used") or []),
            "candidates": len(doc.get("candidates", []))}


def cmd_render(args) -> dict:
    p = _project(args.project)
    f = doc_path(p)
    if not f.is_file():
        raise RuntimeError("先做需求规划(edit_decisions.json 不存在)")
    doc = json.loads(f.read_text(encoding="utf-8"))
    status = lib.check_status()
    if status["missing"] or status["changed"]:
        names = ", ".join(x["name"] for x in (status["missing"] + status["changed"])[:5])
        raise RuntimeError(f"素材库有缺失或已变更文件,请先重新定位或移除:{names}")
    amap = lib.asset_map()
    norm, total = validate(doc, asset_paths=amap)
    stage("渲染剪辑", f"{len(norm['cuts'])} 段 / {total:.2f}s / {'预览' if args.preview else '成片'}")
    out = p / "out"
    out.mkdir(parents=True, exist_ok=True)
    dest = out / (f"{p.name}-剪辑预览.mp4" if args.preview else f"{p.name}.mp4")
    r = edit_render.render(norm, dest, preview=args.preview)
    # 成片同时拷到 remotion-composer/out/<slug>.mp4,作品库的 find_video 才找得到。
    if not args.preview:
        rout = get_paths().composer / "out"
        rout.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copyfile(dest, rout / f"{p.name}.mp4")
    stage("音画合成", "H.264 + AAC")
    return r


def cmd_status(_args) -> dict:
    return lib.check_status()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="短片工厂 · 剪辑模式")
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("plan")
    q.add_argument("--project", required=True)
    q.add_argument("--requirement", default="")
    q.add_argument("--duration", type=float, default=15)
    q.add_argument("--width", type=int, default=1080)
    q.add_argument("--height", type=int, default=1920)
    q.add_argument("--fps", type=int, default=30)
    q.add_argument("--model", choices=("auto", "on", "off"), default="auto")
    q.add_argument("--no-web", action="store_true", help="本地未命中时也不联网找素材")
    r = sub.add_parser("render")
    r.add_argument("--project", required=True)
    r.add_argument("--preview", action="store_true")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    try:
        out = {"plan": cmd_plan, "render": cmd_render, "status": cmd_status}[a.cmd](a)
        print(json.dumps(out, ensure_ascii=False), flush=True)
        return 0
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
