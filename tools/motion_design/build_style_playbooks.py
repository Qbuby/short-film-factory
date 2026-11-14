"""把 mg-styles 风格提示词转成 OpenMontage playbook(styles/mg-*.yaml)。

复用而不是重写:提示词原文仍是风格定义的权威来源,这里只做结构化抽取,
把「视觉特征 / 关键技法 / 配色 / 节奏」映射到 playbook schema 的字段。
"""
import io
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # 仓库根
MGS = REPO / "lib" / "motion_design" / "mgstyles"
PROMPTS = MGS / "prompts"
OUT = REPO / "styles"

HEX = re.compile(r"#[0-9A-Fa-f]{6}")

# 提示词里常常只有"洋红/青/新闻纸"这类文字描述,抽不出十六进制色值,
# 于是全部落到同一份兜底色板,各种风格看起来像同一种。这里按风格的
# 视觉特征补一份明确的色板,只覆盖那些原文没给出 hex 的风格。
STYLE_PALETTES = {
    "mg-synthwave": ["#FF2E97", "#00E5FF", "#FF9E2C", "#7B2FF7", "#12021F"],
    "mg-collage": ["#E8E4D9", "#1A1A1A", "#B03A2E", "#C9A227", "#3F4E5E"],
    "mg-liquid": ["#5B8CFF", "#38E1B0", "#FF6EC7", "#1A1B3A", "#F2F5FF"],
    "mg-morph": ["#FF7A45", "#7A5CFF", "#00C2A8", "#10121F", "#F5F0FF"],
    "mg-isometric": ["#3D7BEA", "#F2994A", "#6FCF97", "#1D2340", "#F0F4FF"],
    "mg-3d-render": ["#F5C518", "#F27A45", "#5BC0EB", "#1F2430", "#FFF6E9"],
    "mg-cel-boil": ["#FF4E50", "#FFB03A", "#3FC1C9", "#2B213A", "#FFF4E6"],
    "mg-hanazi": ["#C8553D", "#E8A33D", "#2E6E5B", "#4A3728", "#F5EFE3"],
    "mg-aurora-glass": ["#5EEAD4", "#A78BFA", "#F472B6", "#0B1026", "#E2E8F0"],
    "mg-paperclip": ["#E9EEF2", "#FF5A36", "#2F6BFF", "#F4C430", "#5A6472"],
    "mg-wallstreet": ["#101C2E", "#0B1422", "#F1EAD2", "#EFDC7A", "#FFD84A", "#F4F1EA"],
}


def section(text: str, name: str) -> str:
    """取 '# name' 到下一个 '# ' 之间的内容。"""
    # 标题带括号注释(如 "# Signature features and key techniques (the result is judged against these)")
    # 所以按标题前缀匹配,别要求整行相等。
    m = re.search(rf"^#\s+{re.escape(name)}.*$", text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"^#\s+", rest, re.M)
    return (rest[: nxt.start()] if nxt else rest).strip()


def prompt_block(md: str) -> str:
    """取文件里第一段 ```text 代码块。"""
    m = re.search(r"```text\s*(.*?)```", md, re.S)
    return m.group(1) if m else md


def yaml_quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def yaml_block(lines) -> str:
    return "\n".join("  " + l for l in lines)


def build_playbook(md: str, style_name: str = "") -> dict:
    p = prompt_block(md)
    style = section(p, "Style")
    route = section(p, "Suggested technical route")
    seed = section(p, "Creative seed")
    sig = section(p, "Signature features and key techniques")

    # 视觉特征 / 关键技法 两行
    vis = ""
    tech = ""
    for line in sig.splitlines():
        if line.startswith("视觉特征"):
            vis = line.split("视觉特征", 1)[1].strip()
        if line.startswith("关键技法"):
            tech = line.split("关键技法", 1)[1].strip()

    colors = HEX.findall(seed)
    colors += HEX.findall(vis)
    seen = []
    for c in colors:
        if c.upper() not in [x.upper() for x in seen]:
            seen.append(c)
    palette = seen or STYLE_PALETTES.get(style_name, []) or ["#2B2BFF", "#FF5A4E", "#FFC62B", "#2EE6A8", "#151433"]

    # 关键技法拆成一条条(可检验的技巧清单)
    techniques = []
    for chunk in re.split(r"[;；]", tech):
        chunk = chunk.strip(" 。,，;；")
        if len(chunk) > 6:
            techniques.append(chunk)
    if not techniques:
        techniques = [vis or "元素弹性入退场", "错峰入场 2~4 帧", "同一时刻只让一个主体动"]

    beats = []
    for line in seed.splitlines():
        line = line.strip()
        m = re.match(r"^-\s*([0-9.]+)–([0-9.]+)s\s*([^:：]*)[:：]\s*(.*)$", line)
        if m:
            beats.append({"start": float(m.group(1)), "end": float(m.group(2)), "title": m.group(3).strip(), "note": m.group(4).strip()})
    hook = next((b for b in beats if "HOOK" in b["title"].upper()), beats[0] if beats else None)

    name_zh = style.split("\n")[0].strip()
    name_en = style.split("\n")[1].strip() if "\n" in style else name_zh

    return {
        "identity": {
            "name": name_en,
            "category": "motion-graphics",
            "mood": ", ".join(re.findall(r"[A-Za-z一-鿿-]{3,}", vis)[:3]) or "expressive",
            "pace": "fast",
            "best_for": "Code-first 动效短片;可与其他风格混合或作为新风格的起点",
        },
        "visual_language": {
            "color_palette": {
                "primary": palette[:2] or ["#2B2BFF"],
                "accent": palette[2:5] or palette[:2] or ["#FF5A4E"],
                # 深色舞台风格(华尔街)的提示词里纸张白也在色板里,
                # 按"最后一个色值"取背景会拿到白纸卡而不是舞台底。
                # 其余风格维持原来的规则,不改已有 playbook。
                "background": (palette[0] if style_name == "mg-wallstreet"
                               else palette[-1] if len(palette) > 5 else "#0F172A"),
                "text": "#F8FAFC",
                "muted": "#94A3B8",
            },
            "composition": vis or "画面由代码绘制的图形构成,主体明确,留白干净",
            "texture": "; ".join(techniques[:2]),
        },
        "typography": {
            "headings": {"font": "Inter", "weight": 800, "tracking": "-0.02em"},
            "body": {"font": "Inter", "weight": 400, "line_height": 1.5},
            "code": {"font": "Fira Code", "weight": 400},
            "stat_card": {"font": "Inter", "weight": 800, "size_multiplier": 4.0},
            "scale_system": "perfect_fourth",
            "weight_matrix": {"title": 800, "heading": 700, "body": 400, "caption": 300},
        },
        "motion": {
            "transitions": ["shape-wipe", "element-fly", "cut"],
            "animation_style": "; ".join(techniques[:3]),
            "pacing_rules": {
                "min_scene_hold_seconds": 1.0,
                "max_scene_hold_seconds": 4.0,
                "text_card_hold_seconds": 2.0,
                "stat_card_hold_seconds": 1.6,
                "transition_duration_seconds": 0.3,
            },
            "entrance": techniques[0] if techniques else "弹性入场",
            "exit": "弹性收束",
        },
        "audio": {
            "voice_style": "简洁口语,每个短句一次落点",
            "music_mood": (re.search(r"Sound:\s*(.+)", seed).group(1).strip() if re.search(r"Sound:\s*(.+)", seed) else "程序化生成的节奏音乐"),
            "music_volume": 0.14,
            "sfx_style": "入场/转场/高潮各一个程序化音效,与画面对齐",
            "ducking_threshold_db": -4,
        },
        "asset_generation": {
            "image_prompt_prefix": f"{name_en}, code-first motion design, ",
            "image_negative_prompt": "照片素材,模板感,默认字体",
            "diagram_style": "由代码绘制的图形,品牌色一致",
            "consistency_anchors": [vis or "签名视觉特征"] + techniques[:3],
        },
        "quality_rules": [
            "画面主体必须由代码绘制(禁止用静态图片 + 缩放转场凑数)",
            "前 0.5 秒必须出现一个在动的元素",
            "每个关键技法必须能在成片里被指出时间码",
            "字幕/标题在竖屏安全区内,字号 ≥ 44px",
            "音频与画面命中点对齐(误差 ≤ 1 帧)",
            "总时长精确等于设定值,无黑帧",
        ],
        "chart_palette": palette[:6],
        "color_rules": {"harmony_type": "triadic", "contrast_validation": True, "colorblind_safe": True},
        "taste_profile": {
            "design_read": vis or name_zh,
            "visual_variance": 7,
            "motion_intensity": 8,
            "information_density": 6,
            "palette_discipline": "固定使用本风格色板:" + ", ".join(palette[:5]),
            "layout_variation": "版式随节拍变化,每镜只让一个主体动",
            "reference_strategy": "以 " + route[:120] + " 为技术路线",
            "anti_patterns": ["静态图片加缩放转场", "同屏多个主体同时运动", "文字被裁切"],
            "quality_gates": techniques[:4],
        },
    }


def to_yaml(d: dict, indent: int = 0) -> str:
    pad = "  " * indent
    lines = []
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f"{pad}{k}:")
            lines.append(to_yaml(v, indent + 1))
        elif isinstance(v, list):
            if v and isinstance(v[0], dict):
                lines.append(f"{pad}{k}:")
                for item in v:
                    first = True
                    for kk, vv in item.items():
                        prefix = f"{pad}  - " if first else f"{pad}    "
                        if isinstance(vv, dict):
                            lines.append(f"{prefix}{kk}:")
                            lines.append(to_yaml(vv, indent + 3))
                        else:
                            lines.append(f"{prefix}{kk}: {yaml_quote(str(vv))}")
                        first = False
            else:
                lines.append(f"{pad}{k}:")
                for item in v:
                    if isinstance(item, str) and ("," in item or ":" in item or "#" in item or item.strip() != item):
                        lines.append(f"{pad}  - {yaml_quote(item)}")
                    else:
                        lines.append(f"{pad}  - {item}")
        else:
            if isinstance(v, bool):
                lines.append(f"{pad}{k}: {'true' if v else 'false'}")
            elif isinstance(v, (int, float)):
                lines.append(f"{pad}{k}: {v}")
            else:
                lines.append(f"{pad}{k}: {yaml_quote(str(v))}")
    return "\n".join(lines)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    made = []
    for md in sorted(PROMPTS.glob("*.md")):
        slug = "mg-" + re.sub(r"^\d+-", "", md.stem)
        pb = build_playbook(io.open(md, encoding="utf-8").read(), slug)
        path = OUT / f"{slug}.yaml"
        header = (
            f"# 由风格提示词机器转换而来 —— {md.name}\n"
            f"# 风格原文:lib/motion_design/mgstyles/prompts/{md.name}\n"
            f"# 转换脚本:tools/motion_design/build_style_playbooks.py\n"
        )
        path.write_text(header + to_yaml(pb) + "\n", encoding="utf-8", newline="\n")
        made.append(path.name)
    print(json.dumps({"playbooks": made}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
