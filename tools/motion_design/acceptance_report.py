"""汇总 code-first 验收片的客观评审证据。

每个项目一个目录,里面有 storyboard.json / out/video.mp4 / out/review/review-evidence.json。
本脚本只读已存在的证据,不重新渲染、不重新打分 —— 报告里的每个数字
都来自 review.py 真实跑出来的结果,没有的字段写 null(不猜、不补)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROJECTS = REPO / "projects" / "code-first"

ORDER = [
    ("message-journey", "一条消息的旅程", "mg-flat-vector"),
    ("battery-age", "电池为什么两年就不耐用", "mg-hud"),
    ("pixel-save", "为什么像素游戏的存档机制让人上瘾", "mg-pixel"),
    ("zen-koan", "本来无一物", "mg-line-art"),
    ("ai-weekly", "本周 AI 三件事", "mg-synthwave"),
    ("oil-crisis", "1973 石油禁运与滞胀", "mg-collage"),
    ("hf-proof", "另一种渲染路线(HyperFrames)", "mg-bauhaus"),
    ("openchatcut", "OpenChatCut 讲解(带口播)", "mg-paperclip"),
    ("anxiety-formula", "焦虑的公式(带口播)", "mg-line-art"),
    ("intel-crash", "英特尔崩盘(带口播·封面)", "mg-hud"),
]


def load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def collect(slug: str):
    proj = PROJECTS / slug
    board = load(proj / "storyboard.json") or {}
    ev = (load(proj / "out" / "final-review" / "review-evidence.json")
          or load(proj / "out" / "review" / "review-evidence.json") or {})
    audio = load(proj / "out" / "audio.qc.json") or {}
    video = proj / "out" / "video.mp4"
    if not video.exists():
        cands = sorted((proj / "out").glob("*.mp4"), key=lambda q: q.stat().st_size, reverse=True)
        video = cands[0] if cands else video
    # 渲染路线:HyperFrames 用的是 GSAP 时间轴,不是 renderAt(t)
    route = "hyperframes" if (proj / "hyperframes.json").exists() else "mg-harness"
    return {
        "slug": slug,
        "route": route,
        "style": board.get("style"),
        "duration": board.get("duration"),
        "size": [board.get("width"), board.get("height")],
        "fps": board.get("fps"),
        "motion_blur": (board.get("render") or {}).get("motion_blur"),
        "beats": len(board.get("beats") or []),
        "recipe": (board.get("audio") or {}).get("recipe"),
        "video_exists": video.exists(),
        "video_bytes": video.stat().st_size if video.exists() else 0,
        "lufs": audio.get("lufs_integrated"),
        "true_peak": audio.get("true_peak_db"),
        "dead_spans": ev.get("dead_spans"),
        "black_frames": ev.get("black_frames"),
        "silence": ev.get("silence"),
        "motion_per_second": ev.get("motion_per_second"),
        "hit_alignment": ev.get("hit_alignment"),
        "objective_issues": ev.get("objective_issues"),
        "vision_status": (ev.get("vision") or {}).get("status"),
        "vision_scores": (ev.get("vision") or {}).get("scores"),
        "vision_average": ev.get("vision_score_average"),
    }


def main() -> int:
    rows = []
    for slug, title, style in ORDER:
        r = collect(slug)
        r["title"] = title
        r["expected_style"] = style
        rows.append(r)

    lines = []
    lines.append("# Code-First Motion Design 验收报告")
    lines.append("")
    lines.append("六条片子,六种风格,全部由代码绘制 + 程序化音频合成,没有一张图片素材。")
    lines.append("第 7 条是 HyperFrames 渲染路线的验证片,用来证明这条路线也能出真片。")
    lines.append("下面每个数字都来自 `tools/motion_design/review.py` 真实产出的 `review-evidence.json`,")
    lines.append("以及 `audio.py` 产出的 `audio.qc.json`;缺的项目写 null,不猜。")
    lines.append("")

    lines.append("| # | 片子 | 风格 | 渲染路线 | 节拍 | 运动模糊 | 时长/分辨率/帧率 | 音乐 | 响度 | 真峰值 | 死场 | 黑帧 | 命中点 | 客观问题 | 评委均分 |")
    lines.append("|---|------|------|----------|------|----------|------------------|------|------|--------|------|------|--------|----------|---------|")
    for i, r in enumerate(rows, 1):
        hits = r.get("hit_alignment")
        if isinstance(hits, list) and hits:
            ok = sum(1 for h in hits if h.get("ok"))
            hit_s = f"{ok}/{len(hits)}"
        else:
            hit_s = "null"
        dead = r.get("dead_spans")
        if isinstance(dead, list):
            dead_s = "无" if not dead else ", ".join(f"{d['start']}-{d['end']}s" for d in dead)
        else:
            dead_s = "null"
        black = r.get("black_frames")
        black_s = ("无" if isinstance(black, list) and not black else str(black)) if black is not None else "null"
        issues = r.get("objective_issues")
        issue_s = ("无" if isinstance(issues, list) and not issues else "; ".join(map(str, issues or []))) if issues is not None else "null"
        dur = r.get("duration")
        size = r.get("size") or [None, None]
        spec = f"{dur or '?'}s / {size[0]}×{size[1]} / {r.get('fps') or '?'}fps"
        avg = r.get("vision_average")
        vis_s = f"{avg}" if avg is not None else ("未评" if r.get("vision_status") == "not_configured" else "null")
        lines.append(
            f"| {i} | {r['title']} | `{r.get('style') or 'null'}` | {r.get('route') or 'null'} | {r.get('beats')} | "
            f"{r.get('motion_blur')} | {spec} | {r.get('recipe') or 'null'} | "
            f"{r.get('lufs') if r.get('lufs') is not None else 'null'} | "
            f"{r.get('true_peak') if r.get('true_peak') is not None else 'null'} | "
            f"{dead_s} | {black_s} | {hit_s} | {issue_s} | {vis_s} |"
        )
    lines.append("")
    lines.append("「评委均分」是 magpie 路由组(`group/never-stuck`)按 7 维 rubric 给的主观分,")
    lines.append("每片抽 6 帧送评。分数低是事实:这批片子的验收标准是**方法跑通**,不是成品水准。")
    lines.append("")

    lines.append("## 逐片说明")
    lines.append("")
    for i, r in enumerate(rows, 1):
        lines.append(f"### {i}. {r['title']}(`{r.get('style') or 'null'}` / {r.get('route') or 'null'})")
        lines.append("")
        lines.append(f"- 项目目录:`projects/code-first/{r['slug']}/`")
        lines.append(f"- 成片:`out/video.mp4`({r['video_bytes']} 字节,{'已生成' if r['video_exists'] else '缺失'})")
        mps = r.get("motion_per_second")
        if isinstance(mps, list):
            lines.append(f"- 逐秒运动能量(变化像素占比 %):{mps}")
        hits = r.get("hit_alignment")
        if isinstance(hits, list):
            detail = "; ".join(
                f"{h.get('hit')}s→峰值 {h.get('peak')}s(偏移 {h.get('offset')}s){'✓' if h.get('ok') else '✗'}"
                for h in hits
            )
            lines.append(f"- 命中点对齐:{detail}")
        lines.append("")

    out = PROJECTS / "ACCEPTANCE.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"ok": True, "out": str(out), "rows": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
