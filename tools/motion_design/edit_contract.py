"""剪辑模式的决策契约 v2 —— 与生成类视频的 edit_decisions 完全隔离。

背景:仓库里 schemas/artifacts/edit_decisions.schema.json 的 `in_seconds`
在三个消费方有三种含义(源内偏移 / 时间轴位置 / 源内偏移+累加),
且 additionalProperties:false 让文字卡、字幕卡无合法表达。
直接复用会让「校验通过但三个后端各剪各的」。

这里另起 edit_decisions_v2,把语义一次钉死:

  source_in / source_out   源文件内的秒(必填,不含变速)
  timeline_start           时间轴起点,由 compute_timeline 算出并写回
  timeline_duration        = (source_out - source_in) / speed - 转场重叠
  speed                    0.25–4.0
  layer                    0 = 主轨;>0 = 画中画层,不参与主线时间累计
  transition_in/out        命中的转场库配方名,duration 秒
  transform                scale / position / crop
  source                   null 时是组件镜头(文字卡/纯色卡),overlay 必填

旧 schema 与三个消费方保持原样,生成类链路零改动。
"""
from __future__ import annotations

import math
from pathlib import Path

VERSION = "edit_decisions_v2"
SCHEMA_STAGE = "edit"
RENDER_RUNTIME = "ffmpeg:editmode"

# 实测过的 xfade 配方(ffmpeg xfade transition 索引),不让用户填表达式。
# 键是 UI 里显示的名字,值是可直接拼进 filter_complex 的 transition 名。
TRANSITIONS: dict[str, str] = {
    "硬切": "",
    "淡入淡出": "fade",
    "黑场过渡": "fadeblack",
    "白场过渡": "fadewhite",
    "左擦除": "wipeleft",
    "右擦除": "wiperight",
    "上擦除": "wipeup",
    "下擦除": "wipedown",
    "左推入": "slideleft",
    "右推入": "slideright",
    "上推入": "slideup",
    "下推入": "slidedown",
    "圆形展开": "circleopen",
    "圆形收拢": "circleclose",
    "径向": "radial",
    "溶解": "dissolve",
    "像素化": "pixelize",
}

SPEED_MIN, SPEED_MAX = 0.25, 4.0
MAX_DURATION = 120.0
TOLERANCE = 0.08  # 与 review.py 的时长容差一致


def _num(v, name: str, *, low: float | None = None, high: float | None = None) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        raise ValueError(f"{name} 必须是数字")
    x = float(v)
    if low is not None and x < low:
        raise ValueError(f"{name} 不能小于 {low}")
    if high is not None and x > high:
        raise ValueError(f"{name} 不能大于 {high}")
    return x


def _transition(row: dict, key: str) -> dict:
    raw = row.get(key) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{key} 必须是对象")
    name = raw.get("type") or "硬切"
    if name not in TRANSITIONS:
        raise ValueError(f"{key} 未知转场「{name}」,可用:{', '.join(TRANSITIONS)}")
    duration = _num(raw.get("duration", 0.4), f"{key}.duration", low=0.0, high=2.0)
    if name == "硬切":
        duration = 0.0
    elif duration <= 0:
        raise ValueError(f"{key} 非硬切必须有正的 duration")
    return {"type": name, "duration": duration}


def _transform(row: dict) -> dict:
    raw = row.get("transform") or {}
    if not isinstance(raw, dict):
        raise ValueError("transform 必须是对象")
    out = {
        "scale": _num(raw.get("scale", 1.0), "transform.scale", low=0.1, high=8.0),
        "position": [0.5, 0.5],
        "crop": None,
    }
    pos = raw.get("position")
    if pos is not None:
        if not isinstance(pos, (list, tuple)) or len(pos) != 2:
            raise ValueError("transform.position 必须是 [x, y]")
        out["position"] = [_num(pos[0], "position.x", low=0.0, high=1.0),
                           _num(pos[1], "position.y", low=0.0, high=1.0)]
    crop = raw.get("crop")
    if crop is not None:
        if not isinstance(crop, dict):
            raise ValueError("transform.crop 必须是对象")
        out["crop"] = {k: _num(crop.get(k, d), f"crop.{k}", low=0.0, high=1.0)
                       for k, d in (("x", 0.0), ("y", 0.0), ("width", 1.0), ("height", 1.0))}
        if out["crop"]["width"] <= 0 or out["crop"]["height"] <= 0:
            raise ValueError("crop 的宽高必须大于 0")
    return out


def normalize_cut(row: dict, index: int) -> dict:
    """把一条 cut 校验成唯一语义的规范形式(不查磁盘,纯结构)。"""
    if not isinstance(row, dict):
        raise ValueError(f"cuts[{index}] 必须是对象")
    src = row.get("source")
    speed = _num(row.get("speed", 1.0), f"cuts[{index}].speed", low=SPEED_MIN, high=SPEED_MAX)
    layer = row.get("layer", 0)
    if isinstance(layer, bool) or not isinstance(layer, int) or layer < 0 or layer > 8:
        raise ValueError(f"cuts[{index}].layer 必须是 0–8 的整数")
    tin = _transition(row, "transition_in")
    tout = _transition(row, "transition_out")
    pip_start = _num(row.get("pip_start", 0.0), f"cuts[{index}].pip_start", low=0.0, high=MAX_DURATION)
    out = {
        "id": str(row.get("id") or f"cut{index + 1}"),
        "source": str(src) if src else None,
        "speed": speed,
        "layer": layer,
        "transform": _transform(row),
        "transition_in": tin,
        "transition_out": tout,
        "reason": str(row.get("reason") or "")[:300],
        "overlay": None,
        "source_in": 0.0,
        "source_out": 0.0,
        "timeline_start": 0.0,
        "timeline_duration": 0.0,
        "pip_start": pip_start,
    }
    if src:
        # 先拦旧字段,否则 _num(None) 会报「必须是数字」,把真正的语义问题盖住。
        if row.get("in_seconds") is not None and row.get("source_in") is None:
            raise ValueError(f"cuts[{index}] 用了旧字段 in_seconds;v2 必须写 source_in/source_out")
        out["source_in"] = _num(row.get("source_in"), f"cuts[{index}].source_in", low=0.0)
        out["source_out"] = _num(row.get("source_out"), f"cuts[{index}].source_out", low=0.0)
        if out["source_out"] <= out["source_in"]:
            raise ValueError(f"cuts[{index}].source_out 必须大于 source_in")
        if out["source_out"] - out["source_in"] > MAX_DURATION * SPEED_MAX:
            raise ValueError(f"cuts[{index}] 单段过长")
    else:
        ov = row.get("overlay")
        if not isinstance(ov, dict) or not str(ov.get("text") or "").strip():
            raise ValueError(f"cuts[{index}] 组件镜头必须有 overlay.text")
        out["overlay"] = {
            "type": str(ov.get("type") or "text"),
            "text": str(ov["text"])[:500],
            "backgroundColor": str(ov.get("backgroundColor") or "#101E33"),
            "color": str(ov.get("color") or "#F1EAD2"),
        }
        out["duration"] = _num(row.get("duration", 2.0), f"cuts[{index}].duration", low=0.2, high=MAX_DURATION)
    return out


def compute_timeline(cuts: list[dict]) -> tuple[list[dict], float]:
    """算出每条主轨 cut 的 timeline_start / timeline_duration 与总时长。

    转场重叠:非硬切的 transition_in.duration 会从本段与前段的合计里扣掉,
    因为 xfade 是两段叠化而不是顺序相加。画中画层(layer>0)不占主线时间。
    """
    main = [c for c in cuts if c["layer"] == 0]
    t = 0.0
    prev_dur = 0.0
    for i, c in enumerate(main):
        overlap = c["transition_in"]["duration"] if i > 0 else 0.0
        if overlap > prev_dur - TOLERANCE and i > 0:
            raise ValueError(f"cuts[{i}] 转场时长 {overlap}s 超过前一段可用长度 {prev_dur:.2f}s")
        # 变速只作用于源素材;组件镜头(文字卡)的 duration 就是时间轴时长。
        dur = (c["source_out"] - c["source_in"]) / c["speed"] if c["source"] else c["duration"]
        start = round(max(0.0, t - overlap), 6)
        c["timeline_start"] = start
        c["timeline_duration"] = round(dur, 6)
        t = start + dur
        prev_dur = dur
    total = round(t, 6)
    if total > MAX_DURATION + TOLERANCE:
        raise ValueError(f"成片 {total:.2f}s 超过 {MAX_DURATION:.0f}s 上限")
    # 画中画层不占主线时间,但 overlay 的 enable 需要自己的时间窗。
    # 用户给了 timeline_start 就用,没给就默认从 0 起覆盖自己的时长。
    for c in cuts:
        if c["layer"] == 0:
            continue
        raw = (c["source_out"] - c["source_in"]) / c["speed"] if c["source"] else c["duration"]
        c["timeline_duration"] = round(raw, 6)
        c["timeline_start"] = round(
            max(0.0, min(float(c.get("pip_start") or 0.0), max(0.0, total - raw))), 6)
    return cuts, total


def validate(doc: dict, *, asset_paths: dict[str, dict] | None = None) -> tuple[dict, float]:
    """校验并返回 (规范文档, 总时长)。

    asset_paths: {source字符串: {"duration": 秒, "status": "ready"|...}}
    给了就顺带校验越界与素材缺失 —— 缺素材直接 FAIL,不静默跳过。
    """
    if not isinstance(doc, dict):
        raise ValueError("edit_decisions 必须是对象")
    if doc.get("version") not in (None, VERSION):
        raise ValueError(f"version 必须是 {VERSION}")
    if doc.get("render_runtime") not in (None, RENDER_RUNTIME):
        raise ValueError(f"render_runtime 必须是 {RENDER_RUNTIME}")
    raw_cuts = doc.get("cuts")
    if not isinstance(raw_cuts, list) or not raw_cuts:
        raise ValueError("cuts 必须是非空数组")
    cuts = [normalize_cut(r, i) for i, r in enumerate(raw_cuts)]
    if not any(c["layer"] == 0 for c in cuts):
        raise ValueError("至少要有一条主轨(layer=0)镜头")
    for i, c in enumerate(cuts):
        if c["layer"] > 0 and c["transition_in"]["duration"] > 0:
            raise ValueError(f"cuts[{i}] 画中画层不支持转场")
    for c in cuts:
        if not c["source"] or not asset_paths:
            continue
        info = asset_paths.get(c["source"])
        if not info:
            raise ValueError(f"素材未登记:{c['source']}")
        if info.get("status") != "ready":
            raise ValueError(f"素材不可用(缺失或已变更):{c['source']}")
        if c["source_out"] > float(info.get("duration") or 0) + TOLERANCE:
            raise ValueError(f"{c['source']} 的 source_out {c['source_out']}s 超过素材时长 {info['duration']:.2f}s")
    cuts, total = compute_timeline(cuts)
    out = {
        "version": VERSION,
        "stage": SCHEMA_STAGE,
        "render_runtime": RENDER_RUNTIME,
        "title": str(doc.get("title") or "剪辑短片")[:160],
        "requirement": str(doc.get("requirement") or "")[:2000],
        "output": {
            "width": int(doc.get("output", {}).get("width") or 1080),
            "height": int(doc.get("output", {}).get("height") or 1920),
            "fps": int(doc.get("output", {}).get("fps") or 30),
        },
        "audio": {
            "mode": str(doc.get("audio", {}).get("mode") or "source"),
            "music": doc.get("audio", {}).get("music"),
        },
        "cuts": cuts,
        "total": total,
        "transitions": list(TRANSITIONS),
    }
    return out, total


def blank_doc(title: str = "剪辑短片", requirement: str = "") -> dict:
    """给 UI 一个可编辑的起点。"""
    return {
        "version": VERSION, "stage": SCHEMA_STAGE, "render_runtime": RENDER_RUNTIME,
        "title": title, "requirement": requirement,
        "output": {"width": 1080, "height": 1920, "fps": 30},
        "audio": {"mode": "source", "music": None},
        "cuts": [], "total": 0.0, "transitions": list(TRANSITIONS),
    }


def doc_path(project: Path) -> Path:
    return project / "edit_decisions.json"
