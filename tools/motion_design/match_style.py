"""风格匹配:一句话 brief → top-N 个 code-first 风格(带理由与可执行要点)。

不需要模型:playbook 里的 `taste_profile.design_read`、`visual_language.composition`、
`motion.animation_style`、`quality_gates` 都是结构化文本,做「提示词特征 + 中文二元组」匹配即可。
输出永远给**候选 + 理由**,不替 agent 拍板。

用法:
    python tools/motion_design/match_style.py --brief "讲一个像素游戏里的老式存档机制"
    python tools/motion_design/match_style.py --brief "..." --top 5 --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STYLES = REPO / "styles"

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

# 题材 → 风格的中文线索(命中的权重高于文本相似度)
HINTS: dict[str, list[str]] = {
    "mg-isometric": ["等距", "等轴", "微缩", "立体城市", "2.5d", "俯视", "沙盘", "建筑"],
    "mg-3d-render": ["写实", "渲染", "材质", "产品", "3d", "光泽", "影棚"],
    "mg-pixel": ["像素", "8bit", "8-bit", "复古游戏", "红白机", "点阵"],
    "mg-synthwave": ["赛博", "霓虹", "合成波", "80年代", "复古未来", "网格", "vhs"],
    "mg-line-art": ["线稿", "线描", "白描", "勾线", "极简线条", "手绘线"],
    "mg-collage": ["拼贴", "剪贴", "杂志", "复古印刷", "达达"],
    "mg-liquid": ["液态", "流体", "粘稠", "融化", "水感", "金属液"],
    "mg-morph": ["变形", "morph", "转换", "演变", "过渡"],
    "mg-bauhaus": ["包豪斯", "构成", "几何", "原色", "海报", "平面设计"],
    "mg-aurora-glass": ["玻璃", "极光", "毛玻璃", "通透", "柔光", "渐变"],
    "mg-hanazi": ["汉字", "字体设计", "排版", "极繁", "字形", "中文字体"],
    "mg-paperclip": ["回形针", "金属", "工业", "机械", "零件"],
    "mg-hud": ["hud", "仪表", "科幻界面", "数据面板", "瞄准", "终端"],
    "mg-cel-boil": ["赛璐璐", "手绘动画", "动画片", "抖动", "逐帧手绘"],
    "mg-flat-vector": ["扁平", "几何", "企业解说", "矢量", "图标", "sass", "科普"],
    "mg-wallstreet": ["华尔街", "财经", "金融", "估值", "融资", "营收", "利润", "成本", "市值",
                      "财报", "账", "烧钱", "市场规模", "投资", "现金流", "小Lin说"],
}

CONTENT_HINTS: dict[str, list[str]] = {
    "mg-flat-vector": ["机制", "原理", "流程", "步骤", "为什么", "如何", "科普", "解释", "数据", "旅程", "过程", "一次"],
    "mg-hud": ["系统", "监控", "指标", "延迟", "协议", "网络", "日志", "终端", "消息", "数据包"],
    "mg-bauhaus": ["概念", "对比", "构成", "观点", "定义"],
    "mg-collage": ["历史", "年代", "档案", "旧闻", "城市记忆"],
    "mg-line-art": ["禅", "诗", "哲", "手记", "素描"],
    "mg-3d-render": ["产品", "发布", "硬件", "材料"],
    "mg-wallstreet": ["钱", "亿", "万亿", "美元", "估值", "营收", "利润", "成本", "市场",
                      "融资", "财报", "涨价", "跌", "涨", "贵", "账", "投资"],
}

STOP = set("的了和与在是把被让给对从到就都也很还可这那你我他它一个为什么怎么如何以及并且或者如果因为所以但是然而并且".split())


def tokens(text: str) -> set[str]:
    """中文按二元组切,英文按词切。"""
    out: set[str] = set()
    for word in re.findall(r"[A-Za-z][A-Za-z0-9\-]+", text.lower()):
        if len(word) > 1:
            out.add(word)
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        for i in range(len(run) - 1):
            bigram = run[i : i + 2]
            if bigram not in STOP:
                out.add(bigram)
    return out


def load_styles() -> dict[str, dict]:
    styles = {}
    for path in sorted(STYLES.glob("mg-*.yaml")):
        if yaml is None:
            raise SystemExit("需要 pyyaml")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        styles[path.stem] = data
    return styles


def style_text(data: dict) -> str:
    tp = data.get("taste_profile") or {}
    vl = data.get("visual_language") or {}
    mo = data.get("motion") or {}
    parts = [
        str(tp.get("design_read") or ""),
        str(vl.get("composition") or ""),
        str(vl.get("texture") or ""),
        str(mo.get("animation_style") or ""),
        " ".join(str(g) for g in (tp.get("quality_gates") or [])),
        " ".join(str(a) for a in (tp.get("anti_patterns") or [])),
        str((data.get("identity") or {}).get("best_for") or ""),
    ]
    return " ".join(parts)


def score_style(brief: str, name: str, data: dict, brief_tokens: set[str]) -> dict:
    text = style_text(data)
    text_tokens = tokens(text)
    overlap = brief_tokens & text_tokens
    overlap_score = len(overlap) * 1.0

    hint_hits = [h for h in HINTS.get(name, []) if h in brief.lower()]
    hint_score = len(hint_hits) * 3.0

    content_hits = [h for h in CONTENT_HINTS.get(name, []) if h in brief.lower()]
    hint_score += len(content_hits) * 1.5

    # 节奏/能量词:brief 说"快/炸/冲击"时偏向 motion_intensity 高的风格
    tp = data.get("taste_profile") or {}
    energy = 0.0
    if re.search(r"快|燃|炸|冲击|强节奏|高潮|爽", brief):
        energy = float(tp.get("motion_intensity") or 0) * 0.15
    if re.search(r"安静|克制|温柔|舒缓|文艺", brief):
        energy = (10 - float(tp.get("motion_intensity") or 5)) * 0.15

    total = overlap_score + hint_score + energy
    return {
        "style": name,
        "score": round(total, 2),
        "hint_hits": hint_hits + content_hits,
        "matched_terms": sorted(overlap)[:12],
        "design_read": str(tp.get("design_read") or "")[:90],
        "palette": (data.get("visual_language") or {}).get("color_palette") or {},
        "techniques": (tp.get("quality_gates") or [])[:4],
    }


def recommend(brief: str, top: int = 3) -> list[dict]:
    styles = load_styles()
    brief_tokens = tokens(brief)
    scored = [score_style(brief, name, data, brief_tokens) for name, data in styles.items()]
    scored.sort(key=lambda r: (-r["score"], r["style"]))
    if scored and scored[0]["score"] <= 0:
        # 没有任何题材线索:明确说明,并把通用解说风格排在第一位做起点
        flat = next((r for r in scored if r["style"] == "mg-flat-vector"), None)
        if flat is not None:
            flat = dict(flat)
            flat["note"] = "brief 没有明显的风格线索,按通用解说风格起步;可再用 --require 指定"
            scored = [flat] + [r for r in scored if r["style"] != "mg-flat-vector"]
    return scored[:top]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="brief → 风格候选")
    ap.add_argument("--brief", required=True)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    picks = recommend(args.brief, args.top)
    if args.json:
        print(json.dumps({"brief": args.brief, "candidates": picks}, ensure_ascii=False, indent=1))
        return 0

    print(f"brief: {args.brief}\n")
    for i, p in enumerate(picks, 1):
        print(f"{i}. {p['style']}  score={p['score']}")
        if p["hint_hits"]:
            print(f"   命中题材词:{'、'.join(p['hint_hits'])}")
        if p["matched_terms"]:
            print(f"   文本重合:{'、'.join(p['matched_terms'][:8])}")
        print(f"   感觉:{p['design_read']}")
        print(f"   技法:{'; '.join(p['techniques'][:3])}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())