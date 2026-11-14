"""命中点对齐检测(共享)。

上游 mgaudio.qc.hit_alignment 依赖 librosa 的谱通量 onset 检测;本机没装 librosa 时
它会静默返回空列表,报告里就变成"所有命中都失败"——那是"没有检测器",不是"没对齐"。
这里用一个不依赖 librosa 的短时能量包络检测器兜底:
20ms 窗 / 10ms 跳,在命中点 ±tol 内找能量峰,看峰值是否落在容差内。
"""
from __future__ import annotations

from pathlib import Path


def envelope_hits(wav: str | Path, hits: list[float], tolerance: float = 0.09) -> list[dict]:
    """在期望命中点附近找音频能量峰,给出客观的对齐判定。

    返回 [{hit, peak, offset, ok}],peak 为 None 表示该点附近根本没有音频能量。
    """
    import numpy as np
    import soundfile as sf

    data, sr = sf.read(str(wav), always_2d=True)
    mono = data.mean(axis=1)
    win = int(0.02 * sr)
    hop = int(0.01 * sr)
    if len(mono) < win:
        return []
    frames = np.lib.stride_tricks.sliding_window_view(mono, win)[::hop]
    env = np.sqrt((frames ** 2).mean(axis=1))
    times = np.arange(len(env)) * (hop / sr)
    rows = []
    for h in hits:
        lo, hi = h - tolerance, h + tolerance
        idx = np.where((times >= lo) & (times <= hi))[0]
        if len(idx) == 0:
            rows.append({"hit": round(float(h), 3), "peak": None, "offset": None, "ok": False})
            continue
        k = idx[int(np.argmax(env[idx]))]
        peak = float(times[k])
        rows.append({
            "hit": round(float(h), 3),
            "peak": round(peak, 3),
            "offset": round(peak - h, 3),
            "ok": abs(peak - h) <= tolerance,
        })
    return rows
