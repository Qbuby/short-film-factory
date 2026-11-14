"""Code-first 音频:按分镜的节拍表生成音乐与音效(纯代码合成,不需要任何 API Key)。

复用 mg-styles-15 的 lib/audio/mgaudio(MIT,见 lib/motion_design/NOTICE.md):
  - recipes.chill/club/fun/retro/world → 风格化的音乐 Form
  - sfx.* → 程序化音效(whoosh / riser / impact / downlifter / swell …)
  - master.master / export → −14 LUFS 母带、−1 dBTP 真峰值
  - qc.analyze → 响度/真峰值/onset 命中检查

分镜文件格式(storyboard.json):
{
  "duration": 10.0,
  "audio": {"recipe": "ambient", "bpm": 96, "key": "E", "sfx": [
      {"name": "riser", "t": 0.0, "gain": -6},
      {"name": "impact", "t": 6.4, "gain": -3}
  ]}
}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AUDIO_DIR = REPO / "lib" / "motion_design" / "mgstyles" / "audio"
sys.path.insert(0, str(AUDIO_DIR))

import numpy as np  # noqa: E402

from mgaudio import master as mg_master  # noqa: E402
from mgaudio import qc as mg_qc  # noqa: E402
from mgaudio import sfx as mg_sfx  # noqa: E402
from mgaudio.recipes import chill, club, fun, retro, world  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hitdetect  # noqa: E402

RECIPES = {"chill": chill, "club": club, "fun": fun, "retro": retro, "world": world}


def _recipe_fns(mod) -> list[tuple[str, object]]:
    """模块里所有公开的曲式函数(签名带 duration)。"""
    out = []
    for name in dir(mod):
        if name.startswith("_"):
            continue
        fn = getattr(mod, name)
        if callable(fn) and hasattr(fn, "__code__"):
            params = fn.__code__.co_varnames[: fn.__code__.co_argcount]
            if "duration" in params:
                out.append((name, fn))
    return out


def build_music(recipe: str, duration: float, bpm: float | None, key: str | None):
    """recipe 的写法:

      "ambient"            → 族名,取该族第一个可用曲式
      "chill:lofi"         → 族名 + 具体曲式
      "lofi:boombap"       → 曲式名 + **参数**(boombap 是 lofi 的 flavor,不是曲式)
      "chill:lofi:boombap" → 族 + 曲式 + 参数

    第三段是参数名时,会以 kwargs 传给曲式函数。
    之前 "lofi:boombap" 会被当成"族=lofi、曲式=boombap",两个都不存在,
    于是静默回落到 ambient —— 拼贴风格要的 boom-bap 手感就丢了。
    """
    parts = recipe.split(":")
    # 第一段如果是曲式名(如 lofi),第二段就是它的参数(如 boombap);
    # 如果第一段是族名(如 chill),第二段才是曲式名,第三段是参数。
    _form_names = {n for mod in RECIPES.values() for n, _ in _recipe_fns(mod)}
    if parts[0] in _form_names and len(parts) > 1:
        # "lofi:boombap" → 曲式 lofi + flavor="boombap"
        # 注意别用 `key` 做局部变量名:那会遮蔽形参 key(调性),
        # 把 "flavor" 当成调性传进曲式,报 "bad pitch class 'flavor'"。
        wanted, extra = parts[0], {"flavor": parts[1]}
        family = parts[0]
    else:
        family, wanted = parts[0], (parts[1] if len(parts) > 1 else "")
        extra = {parts[2]: parts[3] if len(parts) > 3 else True} if len(parts) > 2 else {}
    # 某个族可能整体不可用(依赖的采样在上游缺失),按顺序回落到可用的族
    order = [family] + [f for f in ("chill", "club", "fun", "retro", "world") if f != family]
    mod = None
    for fam in order:
        if fam in RECIPES:
            mod = RECIPES[fam]
            family = fam
            break
    mod = mod or chill
    fns = _recipe_fns(mod)
    if not fns:
        raise RuntimeError(f"配方 {recipe} 里没有可用曲式")
    if wanted:
        hit = [(n, f) for n, f in fns if n == wanted]
        if hit:
            fns = hit
        else:
            # wanted 可能本身是曲式名(如 "lofi"),那就跨族找它
            found = None
            for fam2, mod2 in RECIPES.items():
                for n2, f2 in _recipe_fns(mod2):
                    if n2 == wanted:
                        found, mod, family = f2, mod2, fam2
                        break
                if found:
                    break
            if not found:
                raise RuntimeError(f"配方 {recipe}:找不到曲式 {wanted}")
            fns = [(wanted, found)]
    elif recipe in {n for n, _ in fns}:
        fns = [(n, f) for n, f in fns if n == recipe] or fns
    errors = []
    for name, fn in fns:
        kwargs = {"duration": duration}
        if bpm:
            kwargs["bpm"] = bpm
        if key:
            kwargs["key"] = key
        try:
            mix = fn(**kwargs, **extra)
            print(f"[audio] recipe={family} form={name} {extra or ''}", flush=True)
            return mix
        except Exception as exc:      # 某些曲式依赖采样,缺样本时换下一个
            errors.append(f"{name}: {str(exc)[:80]}")
    # 当前族全挂:换下一个族再试
    for fam in order[1:]:
        alt = RECIPES.get(fam)
        if not alt:
            continue
        for name, fn in _recipe_fns(alt):
            try:
                mix = fn(duration=duration, **({"bpm": bpm} if bpm else {}),
                         **({"key": key} if key else {}), **extra)
                print(f"[audio] recipe={fam} form={name} (fallback from {recipe})", flush=True)
                return mix
            except Exception:
                continue
    raise RuntimeError(f"配方 {recipe} 全部曲式失败: " + "; ".join(errors[:3]))


def add_sfx(mix, spec: dict, duration: float) -> list[str]:
    """把分镜里的音效挂到混音上。返回实际加入的音效名。"""
    added = []
    for item in spec.get("sfx", []):
        name = str(item.get("name", "")).strip()
        at = float(item.get("t", 0.0))
        gain = float(item.get("gain", -6.0))
        fn = getattr(mg_sfx, name, None)
        if fn is None or not callable(fn):
            continue
        try:
            sound = fn()
        except TypeError:
            try:
                sound = fn(duration=0.6)
            except Exception:
                continue
        except Exception:
            continue
        if sound is None:
            continue
        try:
            mix.sfx(sound, at, gain=gain)
            added.append(f"{name}@{at:.2f}")
        except Exception:
            continue
    return added


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Code-first 音频合成(分镜 → wav)")
    ap.add_argument("--storyboard", required=True)
    ap.add_argument("--out", required=True, help="输出 wav")
    ap.add_argument("--recipe", default="")
    ap.add_argument("--bpm", type=float, default=0)
    ap.add_argument("--key", default="")
    ap.add_argument("--no-sfx", action="store_true")
    ap.add_argument("--report", default="", help="QC 报告(json)")
    args = ap.parse_args(argv)

    board = json.loads(Path(args.storyboard).read_text(encoding="utf-8"))
    duration = float(board.get("duration", 10.0))
    spec = board.get("audio") or {}
    recipe = args.recipe or spec.get("recipe") or "ambient"
    bpm = args.bpm or spec.get("bpm") or None
    key = args.key or spec.get("key") or None

    mix = build_music(recipe, duration, bpm, key)
    added = [] if args.no_sfx else add_sfx(mix, spec, duration)

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    mix.export(str(out), lufs=-14.0, tp=-1.0, analyze=False)

    # QC:用 vendored 的分析器给客观指标
    res = mg_qc.analyze(str(out), expected=duration)
    # 命中点对齐:上游 mgaudio 的 onset 检测依赖 librosa,本机没装时它会静默返回空列表
    # (报告里会变成"全部未命中",那是没有检测器而不是没对齐),
    # 所以优先用不依赖 librosa 的短时能量包络检测器。
    hits = [float(x.get("t", 0)) for x in (spec.get("sfx") or [])]
    alignment: list[dict] = []
    alignment_method = ""
    if hits:
        alignment = hitdetect.envelope_hits(out, hits)
        alignment_method = "energy-envelope(20ms window / 10ms hop, tol 90ms)"
        if all(r.get("peak") is None for r in alignment):
            upstream = mg_qc.hit_alignment(str(out), hits)
            if any(r.get("onset") is not None for r in upstream):
                alignment = upstream
                alignment_method = "mgaudio.librosa-onset"
    report = {
        "recipe": recipe,
        "bpm": bpm,
        "key": key,
        "duration_expected": duration,
        "sfx_added": added,
        "lufs_integrated": res.get("lufs_integrated", res.get("lufs")),
        "true_peak_db": res.get("true_peak_db", res.get("true_peak")),
        "sample_rate": res.get("sample_rate"),
        "duration_actual": res.get("duration"),
        "hit_alignment_method": alignment_method,
        "hit_alignment": alignment,
    }
    rep_path = Path(args.report).resolve() if args.report else out.with_suffix(".qc.json")
    rep_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"[audio] wav -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
