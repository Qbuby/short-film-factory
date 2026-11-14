"""复核「人声到底念的是不是这版稿子」。

voiceover.py 曾经只判断 wav 存不存在就复用,改了稿子再合成,成片会出现
「听到的是旧词、字幕是新词」。缓存已经改成内容寻址,但光靠改代码不够 ——
出片前要能拿证据说「这条音轨每个字都对得上」。

做法:用同样的文本/音色/语速再合成一遍,和缓存音轨做互相关。
Edge TTS 对同一输入是逐位确定的(实测 1.0000),所以:

  corr > 0.98  这一段的音频就是这段文字
  corr < 0.5   念的是别的东西,必须重跑

**比较的是 timing.json 里记下的那句 say** —— 那正是当初合成时用的字符串。
不重新从 script.json 推导:推导逻辑一旦和合成那侧不一致(以前就是这样:
合成走 spoken(spoken(x))、校验走 spoken(x)),两边音频就完全对不上,
corr 直接掉到 0.01,校验形同虚设。

同时会检查"稿子是不是在合成之后又改过":把当前 script.json 推导出的朗读形
和 timing.json 记下的 say 比一比,不一样就说明改了稿子没重新合成。

用法:
  python tools/motion_design/verify_voice.py --project projects/code-first/ai-bubble
退出码 0 = 全部通过。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import voiceover as vo  # noqa: E402

CHAIN = (
    "silenceremove=start_periods=1:start_threshold=-42dB,areverse,"
    "silenceremove=start_periods=1:start_threshold=-42dB,areverse,"
    "loudnorm=I=-16:TP=-1.5:LRA=11"
)


def pcm(path: Path) -> np.ndarray:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(out, dtype="<i2").astype(np.float32)


def corr(a: np.ndarray, b: np.ndarray) -> float:
    n = min(len(a), len(b))
    x, y = a[:n] - a[:n].mean(), b[:n] - b[:n].mean()
    return float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y) + 1e-9))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--threshold", type=float, default=0.98)
    args = ap.parse_args()

    proj = Path(args.project).resolve()
    timing = json.loads((proj / "timing.json").read_text(encoding="utf-8"))
    script = {s["id"]: s for s in json.loads((proj / "script.json").read_text(encoding="utf-8"))["segments"]}

    bad: list[str] = []
    out = sys.stderr
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for seg in timing["segments"]:
            sid = seg["id"]
            src = script.get(sid)
            if src is None:
                print(f"{sid:10s} 稿子里没有这一段", file=out)
                bad.append(sid)
                continue
            # 念的那句:优先用 timing.json 记下的 say —— 那就是合成时用的字符串。
            # 老工程没有这个字段时退回稿子推导(推导规则与 voiceover 共用同一个函数)。
            said = seg.get("say")
            if not said:
                said = vo.synthesis_text(src)
            # 稿子是不是在合成之后又改过?改了就得重新合成。
            if vo.synthesis_text(src) != said:
                print(f"{sid:10s} 稿子已改,但人声还是旧的 —— 需要重新合成", file=out)
                bad.append(sid)
                continue
            mp3, wav = tmp / f"{sid}.mp3", tmp / f"{sid}.wav"
            # 合成的是 say(可能和字幕不同,例如「三个点四六」),比的也是它
            vo.synth_edge(said, mp3, voice=timing["voice"],
                          rate=src.get("rate", "+0%"), pitch=src.get("pitch", "+0Hz"))
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp3),
                 "-af", CHAIN, "-ar", "48000", "-ac", "2", str(wav)],
                check=True,
            )
            a, b = pcm(Path(seg["wav"])), pcm(wav)
            c = corr(a, b)
            ok = c >= args.threshold
            if not ok:
                bad.append(sid)
            print(f"{sid:10s} {len(a)/16000:5.2f}s / {len(b)/16000:5.2f}s  corr={c:+.4f}  "
                  f"{'OK' if ok else '!!! 音频与稿子不符'}  {src['text'][:26]}", file=out)

    print(json.dumps({"ok": not bad, "voice": timing["voice"], "bad": bad}, ensure_ascii=False))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())