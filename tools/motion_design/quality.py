"""输出规格:分辨率只决定像素/编码,不删减内容或降级风格。

帧率由合成控制;画布短边为 1080,输出按精确短边比例缩放。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

TOOLS = Path(__file__).resolve().parent

SPEC: dict = json.loads((TOOLS / "quality.json").read_text(encoding="utf-8"))
RESOLUTIONS: dict = SPEC["resolutions"]
FPS_CHOICES: dict = SPEC["fps"]
DENSITY_RULES: dict = SPEC["density_rules"]
TIERS: dict = SPEC["tiers"]
MAX_DURATION: int = int(SPEC.get("max_duration", 120))
MIN_DURATION: int = int(SPEC.get("min_duration", 1))

DEFAULT_RESOLUTION = "1080p"
DEFAULT_FPS = "30"
DEFAULT_TIER = "standard"


def tier_of(meta: dict) -> dict:
    """制作档位:品质与速度的取舍,附带复审轮次与评审门槛。"""
    key = (meta or {}).get("tier") or DEFAULT_TIER
    return TIERS.get(key) or TIERS[DEFAULT_TIER]


def review_args(meta: dict) -> list[str]:
    """把档位的评审要求翻译成 review.py 参数。

    项目级覆盖:meta["tier_review"] 里的键优先(华尔街 kit 风格的叙事节奏
    和生成类不同——卡片停留阅读是设计,句间换镜停顿是口播 gap,
    零容忍口径会把它误杀;由 wallstreet_kit 写入)。
    """
    rule = dict(tier_of(meta)["review"])
    rule.update((meta or {}).get("tier_review") or {})
    return ["--dead-scale", str(rule["dead_scale"]),
            "--lufs-tol", str(rule["lufs_tol"]),
            "--sfx-min-ratio", str(rule["sfx_min_ratio"]),
            "--black-tolerance", str(rule["black_tolerance"]),
            "--silence-tolerance", str(rule["silence_tolerance"])]



def resolution_of(meta: dict) -> dict:
    r = (meta or {}).get("resolution") or DEFAULT_RESOLUTION
    return RESOLUTIONS.get(r) or RESOLUTIONS[DEFAULT_RESOLUTION]


def fps_of(meta: dict) -> int:
    try:
        return int((meta or {}).get("fps") or DEFAULT_FPS)
    except (TypeError, ValueError):
        return int(DEFAULT_FPS)


def validate_duration(sec, label: str = "时长") -> float:
    """不截断、不夹取:超限必须由用户调整稿子或音频。"""
    message = (f"{label}必须为 {MIN_DURATION}–{MAX_DURATION} 秒的有限数值(当前 {sec!r})。"
               "请调整脚本/口播稿或音频后重试;不会自动截断。")
    try:
        value = float(sec)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(message) from None
    if isinstance(sec, bool) or not math.isfinite(value) or not MIN_DURATION <= value <= MAX_DURATION:
        raise ValueError(message)
    return value


def clamp_duration(sec) -> float:
    """兼容旧调用名,现在严格校验而非静默截断。"""
    return validate_duration(sec, "目标时长")


def output_spec(meta: dict) -> dict:
    """算出这一条片的完整输出规格,写进 props 交给模板。"""
    res = resolution_of(meta)
    fps = fps_of(meta)
    tier = tier_of(meta)
    # 所有分辨率沿用同一套完整视觉语言,不能因低清输出而隐藏配图。
    rule = DENSITY_RULES[DEFAULT_RESOLUTION]
    # 档位只调压缩率(画质/体积)与并发(速度),不再删减内容。
    crf = max(16, min(32, int(res["crf"] + int(tier["crf_delta"]))))
    return {
        "resolution": res["id"],
        "zh": res["zh"],
        "fps": fps,
        "scale": res["short"] / 1080,
        "crf": crf,
        "concurrency": int(tier["concurrency"]),
        "tier": tier["id"],
        "tier_zh": tier["zh"],
        "script_rounds": int(tier["script_rounds"]),
        "density": int(rule["density"]),
        "transition": rule["transition"],
        "polish": bool(int(rule["density"]) >= 2 and fps >= 30),
    }


def output_dimensions(width: int, height: int, spec: dict) -> tuple[int, int]:
    """匹配 Remotion H.264 的偶数尺寸规则,而非 Python 的银行家舍入。

    Remotion 先递减画布尺寸,直到缩放后 Math.round 的结果为偶数。
    例如 1080×1920 的 480p 输出为 480×852,画布和构图不变。
    """
    scale = spec["scale"]

    def dimension(value: int) -> int:
        while math.floor(value * scale + 0.5) % 2:
            value -= 1
        return math.floor(value * scale + 0.5)

    return dimension(width), dimension(height)


def render_args(spec: dict) -> list[str]:
    """给 Remotion 的渲染参数。

    注意:这里绝不能传 --fps。合成里已经按项目 fps 设好了帧率,
    命令行再传一次等于「同样的帧数按更低的帧率放」,片子会被拉长
    (30fps 的 25.6 秒会变成 32 秒,尾巴多一段静音)。
    """
    return [
        "--scale", str(spec["scale"]),
        "--crf", str(spec["crf"]),
        "--concurrency", str(spec.get("concurrency", 4)),
    ]
