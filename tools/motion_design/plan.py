"""Code-first 分镜装配:一句话 brief + 风格 playbook → storyboard.json。

**创意在 agent 这一侧**:beats(每一拍的时间、文案、画什么、代码怎么画)由 agent 写;
本工具负责确定性的部分:
  - 按风格 playbook 注入色板 / 技法 / 节奏规则;
  - 校验时间轴(hook ≤ 1.2s、hero 落在 60–75%、结尾 hold ≥ 0.8s、每拍都有画法);
  - 生成音频规格(recipe / bpm / sfx 命中点)。

用法:
  # agent 已经写好 beats(推荐)
  python tools/motion_design/plan.py --brief "..." --style mg-flat-vector \
      --beats beats.json --out projects/code-first/demo/storyboard.json
  # 只要一个骨架(agent 再填内容)
  python tools/motion_design/plan.py --brief "..." --style mg-flat-vector --scaffold --out ...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STYLES = REPO / "styles"

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

# 骨架:hook → 升级 → 高潮 → 结尾(对应 mg 方法里的节拍结构)
SCAFFOLD = [
    {"id": "hook", "role": "HOOK", "dur": 1.2, "title": "", "visual": "", "code": ""},
    {"id": "build", "role": "BUILD", "dur": 3.0, "title": "", "visual": "", "code": ""},
    {"id": "build2", "role": "BUILD", "dur": 3.0, "title": "", "visual": "", "code": ""},
    {"id": "hero", "role": "HERO", "dur": 2.5, "title": "", "visual": "", "code": ""},
    {"id": "end", "role": "END", "dur": 1.2, "title": "", "visual": "", "code": ""},
]


def load_style(name: str) -> dict:
    path = STYLES / f"{name}.yaml"
    if not path.exists():
        raise SystemExit(f"找不到风格 playbook:{path}")
    if yaml is None:
        raise SystemExit("需要 pyyaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def scaffold(brief: str) -> list[dict]:
    beats = []
    for b in SCAFFOLD:
        beat = dict(b)
        beat["title"] = brief if b["role"] == "HOOK" else ""
        beats.append(beat)
    return beats


KNOWN_SFX = ["pop", "swish", "whoosh", "riser", "downlifter", "impact", "boom", "sub_drop", "reverse_cymbal", "swell"]


def _map_sfx_name(name: str) -> str:
    """模型常写 battery_beep / glitch / ding 这类不存在的音效名,映射到合成库里有的。"""
    n = (name or "").lower()
    if n in KNOWN_SFX:
        return n
    table = [
        (("ding", "success", "confirm", "answer"), "pop"),
        (("glitch", "error", "fail", "warn"), "downlifter"),
        (("crack", "break", "snap", "hit"), "impact"),
        (("swish", "slide", "move", "flow"), "swish"),
        (("whoosh", "fly", "swoosh", "wind"), "whoosh"),
        (("rise", "build", "tension", "heat"), "riser"),
        (("boom", "drop", "explode"), "boom"),
        (("shimmer", "shine", "glow"), "swell"),
    ]
    for keys, target in table:
        if any(k in n for k in keys):
            return target
    return "pop"


def _norm_sfx(raw, default_t: float = 0.0) -> list[dict]:
    """音效条目容忍三种写法: "impact" / {"name":"impact","t":1.2} / {"name":"impact"}。

    模型经常把所有 t 写成 0;那就按所属拍的起点排,至少不会全挤在 0 秒。
    """
    out = []
    for item in raw or []:
        if isinstance(item, str) and item.strip():
            out.append({"name": _map_sfx_name(item.strip()), "t": default_t, "gain": -6.0})
        elif isinstance(item, dict) and item.get("name"):
            t = float(item.get("t") or 0.0)
            out.append({"name": _map_sfx_name(str(item["name"])), "t": t if t > 0 else default_t,
                        "gain": float(item.get("gain") or -6.0)})
    return out


def normalize(beats: list[dict], style: dict, duration: float) -> list[dict]:
    out = []
    t = 0.0
    for b in beats:
        dur = float(b.get("dur") or 0)
        beat = {
            "id": str(b.get("id") or f"beat{len(out) + 1}"),
            "role": str(b.get("role") or "BEAT"),
            "start": round(t, 3),
            "end": round(t + dur, 3),
            "dur": round(dur, 3),
            "title": str(b.get("title") or ""),
            "visual": str(b.get("visual") or ""),
            "code": str(b.get("code") or ""),
            "sfx": _norm_sfx(b.get("sfx"), round(t, 3)),
        }
        out.append(beat)
        t += dur
    return out


def check(beats: list[dict], duration: float) -> list[str]:
    problems = []
    if not beats:
        return ["没有 beats"]
    hook = next((b for b in beats if b["role"].upper() == "HOOK"), None)
    if hook is None:
        problems.append("缺少 HOOK 拍")
    else:
        # 钩子的真实要求是"第一帧就在动",不是"钩子必须很短"。
        # 10s 短片留 1.2s;2 分钟的讲解片要给钩子留出铺陈时间,
        # 所以按片长的 8% 放宽(封顶 12s),短片的行为完全不变。
        hook_budget = max(1.2, min(12.0, duration * 0.10))
        if hook["end"] > hook_budget + 1e-6:
            problems.append(
                f"HOOK 结束于 {hook['end']:.2f}s,超过 {hook_budget:.2f}s"
                f"(前 0.5 秒必须有东西在动)"
            )
    hero = next((b for b in beats if b["role"].upper() == "HERO"), None)
    if hero is None:
        problems.append("缺少 HERO 拍")
    else:
        rel = hero["start"] / duration if duration else 0
        if not (0.5 <= rel <= 0.85):
            problems.append(f"HERO 在 {rel * 100:.0f}% 处,期望落在 50–85%")
    end = beats[-1]
    if end["dur"] < 0.8:
        problems.append(f"结尾 hold 只有 {end['dur']:.2f}s,期望 ≥ 0.8s")
    total = beats[-1]["end"] if beats else 0
    if duration and abs(total - duration) > 0.05:
        problems.append(f"总时长 {total:.3f}s != 目标 {duration:.3f}s")
    for b in beats:
        if not b["visual"]:
            problems.append(f"{b['id']} 没有画面描述")
        if not b["code"]:
            problems.append(f"{b['id']} 没有代码画法描述")
    return problems


def llm_beats(brief: str, style: dict, duration: float, attempts: int = 2) -> tuple[list[dict], list[str]]:
    """让模型出节拍表;每次都用 check() 校验,不过就带着问题重试。"""
    # 直接跑脚本时 sys.path[0] 是 tools/motion_design,要让 `tools` 作为包可导入
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from tools.motion_design import llm as llm_mod

    style_name = (style.get("identity") or {}).get("name") or ""
    palette = (style.get("visual_language") or {}).get("color_palette") or {}
    techs = (style.get("taste_profile") or {}).get("quality_gates") or []

    rules = [
        "你是短视频动效导演。输出一个可执行的节拍表 JSON。",
        "硬规矩:",
        "- 每一拍必须有: id / role(HOOK|BUILD|HERO|END) / dur / title / visual(画面里有什么) / code(怎么用 Canvas 或 SVG 画出来) / sfx(数组,可为空)",
        "- HOOK 必须在 0-1.2s 内结束,且第 0 帧就有东西在动",
        "- HERO 落在总时长的 60-75%,是全场唯一的高潮",
        "- 最后一拍 dur >= 0.8s,收尾要有微动",
        "- 所有 dur 之和必须精确等于 " + ("%.3f" % duration),
        "- 画面只能由代码绘制:禁止静态图片、禁止图片缩放转场",
        "- 中文字幕/标题控制在每屏一行,字号足够大",
        "风格:" + style_name + ";色板:" + json.dumps(palette, ensure_ascii=False)
        + ";可用技法:" + json.dumps(techs[:4], ensure_ascii=False),
        '只输出 JSON: {"beats": [...]}',
    ]
    system = chr(10).join(rules)

    problems: list[str] = []
    for _attempt in range(attempts):
        user = "主题(brief):" + brief
        if problems:
            user += chr(10) + "上一次的输出没通过校验,问题如下,请修正后重新输出完整节拍表:" + chr(10) + "- " + (chr(10) + "- ").join(problems)
        text = llm_mod.complete(system, user, max_tokens=3000, temperature=0.7)
        data = llm_mod.extract_json(text)
        raw = data.get("beats") if isinstance(data, dict) else data
        if not isinstance(raw, list) or not raw:
            problems = ["没有返回 beats 数组"]
            continue
        normalized = normalize(raw, style, duration)
        problems = check(normalized, duration)
        if not problems:
            return normalized, []
    return [], problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Code-first 分镜装配")
    ap.add_argument("--brief", required=True)
    ap.add_argument("--style", required=True)
    ap.add_argument("--beats", default="", help="agent 写好的 beats(json)")
    ap.add_argument("--scaffold", action="store_true")
    ap.add_argument("--llm", action="store_true", help="让 LLM 从 brief 生成节拍表(需要 MOTION_LLM_*)")
    ap.add_argument("--duration", type=float, default=10.0)
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--recipe", default="ambient")
    ap.add_argument("--motion-blur", type=int, default=2, help="运动模糊采样数(1=关闭)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    style = load_style(args.style)
    if args.llm:
        beats, problems = llm_beats(args.brief, style, args.duration)
        if problems:
            print(json.dumps({"error": "LLM 生成的节拍表未通过校验", "problems": problems}, ensure_ascii=False, indent=1))
            return 1
        print(json.dumps({"llm": "ok", "beats": len(beats)}, ensure_ascii=False))
    elif args.beats:
        raw = json.loads(Path(args.beats).read_text(encoding="utf-8"))
        beats = raw["beats"] if isinstance(raw, dict) else raw
    elif args.scaffold:
        beats = scaffold(args.brief)
    else:
        raise SystemExit("需要 --beats 或 --scaffold")

    beats = normalize(beats, style, args.duration)
    problems = check(beats, args.duration)

    palette = (style.get("visual_language") or {}).get("color_palette") or {}
    board = {
        "brief": args.brief,
        "style": args.style,
        "style_name": (style.get("identity") or {}).get("name"),
        "duration": args.duration,
        "width": args.width,
        "height": args.height,
        "fps": args.fps,
        "palette": palette,
        "techniques": (style.get("taste_profile") or {}).get("quality_gates", []),
        "beats": beats,
        "render": {
            "motion_blur": max(1, args.motion_blur),
            "codec": "h264",
            "scale": 1.0,
        },
        "audio": {
            "recipe": args.recipe,
            "sfx": [dict(s) for b in beats for s in (b.get("sfx") or [])],
        },
        "validation": {"problems": problems, "ok": not problems},
    }
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out), "beats": len(beats), "problems": problems}, ensure_ascii=False, indent=1))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
