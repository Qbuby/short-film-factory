"""把一段真人朗读对齐到稿子上,产出 timing.json / subtitles.json。

已经有一条现成人声(别人录的、别家 TTS 出的)时,不能沿用 voiceover.py
「先合成再量时长」的路子 —— 那会重新造一条音轨。这里反过来:
**以人声为准**,把稿子的每个分句落到它的真实起止时刻。

做法:
  1. faster-whisper 拿到词级时间戳(本地跑,不需要任何 key);
  2. 稿子分句 → 字符序列,ASR 词 → 字符序列;
  3. 两者做编辑距离 DTW(允许 ASR 把「黑石」听成「黑市」这类同音错字);
  4. 每个分句的字符区间沿 warp path 投影回时间轴。

段(gap)= 0:一条连续录音里没有"合成间隔"这回事,
两拍交界就是人声换话题的那一刻。

用法:
  python tools/motion_design/align_narration.py \
      --project projects/code-first/ai-bubble \
      --audio D:/path/to/narration.wav --max-len 16 --tail 0.8
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_subs import chunk  # noqa: E402

PUNCT = "，。、！？：；,.!?;:…—-\"'“”‘’()（） \n\t"


def norm(s: str) -> str:
    return "".join(c for c in s if c not in PUNCT)


def load_audio(path: Path) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def transcribe(audio: np.ndarray, cache: Path, model_size: str) -> list[dict]:
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    from faster_whisper import WhisperModel

    m = WhisperModel(model_size, device="cpu", compute_type="int8")
    segs, _ = m.transcribe(audio, language="zh", beam_size=5, word_timestamps=True, vad_filter=False)
    words: list[dict] = []
    for s in segs:
        for w in (s.words or []):
            for ch in norm(w.word):
                words.append({"ch": ch, "s": round(w.start, 3), "e": round(w.end, 3)})
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    return words


def dtw(src: str, dst: str) -> list[tuple[int, int]]:
    """编辑距离 DTW:返回 (src_idx, dst_idx) 单调对齐路径。"""
    n, m = len(src), len(dst)
    INF = float("inf")
    dp = np.full((n + 1, m + 1), INF)
    dp[0, 0] = 0.0
    for i in range(1, n + 1):
        dp[i, 0] = i
    for j in range(1, m + 1):
        dp[0, j] = j
    for i in range(1, n + 1):
        si = src[i - 1]
        row, prev = dp[i], dp[i - 1]
        for j in range(1, m + 1):
            sub = prev[j - 1] + (0.0 if si == dst[j - 1] else 1.0)
            ins = prev[j] + 1.0
            dele = row[j - 1] + 1.0
            row[j] = min(sub, ins, dele)
    # 回溯
    i, j, path = n, m, []
    while i > 0 or j > 0:
        path.append((i - 1, j - 1))
        if i == 0:
            j -= 1
        elif j == 0:
            i -= 1
        else:
            cand = [
                (dp[i - 1][j - 1] + (0.0 if src[i - 1] == dst[j - 1] else 1.0), i - 1, j - 1),
                (dp[i - 1][j] + 1.0, i - 1, j),
                (dp[i][j - 1] + 1.0, i, j - 1),
            ]
            _, i, j = min(cand, key=lambda x: x[0])
    return path[::-1]


def main() -> int:
    ap = argparse.ArgumentParser(description="真人朗读 → 稿子时间轴")
    ap.add_argument("--project", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--max-len", type=int, default=16)
    ap.add_argument("--tail", type=float, default=0.8, help="末句之后留的收尾时长(秒)")
    ap.add_argument("--model", default="small")
    args = ap.parse_args()

    proj = Path(args.project).resolve()
    src = Path(args.audio).resolve()
    audio = load_audio(src)
    dur = len(audio) / 16000
    words = transcribe(audio, proj / "out" / "asr-words.json", args.model)
    if not words:
        print(json.dumps({"ok": False, "error": "ASR 没有识别到任何词"}, ensure_ascii=False))
        return 2

    segs = json.loads((proj / "script.json").read_text(encoding="utf-8"))["segments"]

    # 稿子:每个分句记住它在全文字符串里的区间。
    # 注意 c0/c1 必须是**字符**下标,不能拿 list 的 len 当偏移。
    cues: list[dict] = []
    script_chars: list[str] = []
    char_total = 0
    for seg in segs:
        for piece in chunk(seg["text"], args.max_len):
            body = norm(piece)
            if not body:
                continue
            cues.append({"id": seg["id"], "text": piece, "c0": char_total, "c1": char_total + len(body)})
            script_chars.append(body)
            char_total += len(body)
    script = "".join(script_chars)
    asr = "".join(w["ch"] for w in words)

    path = dtw(script, asr)
    # 每个稿子字符 → ASR 字符区间
    lo: dict[int, int] = {}
    hi: dict[int, int] = {}
    for si, di in path:
        if si < 0 or di < 0:
            continue
        lo.setdefault(si, di)
        hi[si] = di

    def time_at(si: int, edge: str) -> float:
        """稿子第 si 个字符(edge=start 用它对应的第一个 ASR 字符, end 用最后一个)。"""
        di = (lo.get(si) if edge == "start" else hi.get(si))
        if di is None:
            # 落在删除区,取最近的有映射的字符
            for k in range(1, len(script)):
                cand = (lo.get(si + k) if edge == "start" else hi.get(si - k))
                if cand is not None:
                    di = cand
                    break
        if di is None:
            return 0.0 if edge == "start" else dur
        return words[di]["s"] if edge == "start" else words[di]["e"]

    for c in cues:
        c["start"] = round(time_at(c["c0"], "start"), 3)
        c["end"] = round(time_at(c["c1"] - 1, "end"), 3)
        # 单调 + 正长度
        c["end"] = max(c["end"], round(c["start"] + 0.2, 3))

    # 换句处 DTW 常把两句的时间区间咬在一起(前一句的 end 越过后一句的 start)。
    # 字幕一屏只能有一句,所以后一句的起点就是前一句的硬终点。
    for a, b in zip(cues, cues[1:]):
        if b["start"] < a["end"]:
            a["end"] = b["start"]
        if a["end"] <= a["start"]:
            a["end"] = round(a["start"] + 0.2, 3)

    # 段边界 = 相邻两段之间最后一句结束 / 下一段第一句开始的中点
    order: list[str] = []
    by_seg: dict[str, list[dict]] = {}
    for c in cues:
        if c["id"] not in by_seg:
            order.append(c["id"]); by_seg[c["id"]] = []
        by_seg[c["id"]].append(c)
    rows = []
    prev_end = 0.0
    for i, sid in enumerate(order):
        cs = by_seg[sid]
        # 段边界落在「上一段最后一句结束」与「本段第一句开始」的中点,
        # 这样换拍不会抢在观众读完上一屏之前。
        start = cs[0]["start"] if i == 0 else round((prev_end + cs[0]["start"]) / 2, 3)
        start = max(start, prev_end)
        end = cs[-1]["end"]
        rows.append({"id": sid, "start": round(start, 3), "end": round(end, 3)})
        prev_end = end

    total = round(rows[-1]["end"] + args.tail, 3)
    rows[-1]["end"] = total

    timing = {
        "voice": f"human:{src.stem}",
        "source_audio": str(src),
        "speed": 1.0,
        "gap": 0.0,
        "total": total,
        "segments": [
            {
                "id": r["id"],
                "text": "".join(c["text"] for c in by_seg[r["id"]]),
                "start": r["start"],
                "end": r["end"],
                "dur": round(r["end"] - r["start"], 3),
            }
            for r in rows
        ],
    }
    (proj / "timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")

    subs = [{"text": c["text"], "start": c["start"], "end": c["end"],
             "w": min(960, max(300, len(c["text"]) * 46 + 60))} for c in cues]
    (proj / "subtitles.json").write_text(json.dumps(subs, ensure_ascii=False, indent=1), encoding="utf-8")
    (proj / "subs.js").write_text("window.__SUBS__ = " + json.dumps(subs, ensure_ascii=False) + ";\n",
                                  encoding="utf-8", newline="\n")

    print(json.dumps({
        "ok": True, "audio": str(src), "audio_duration": round(dur, 3),
        "aligned_speech_end": rows[-1]["end"], "total_with_tail": total,
        "asr_chars": len(asr), "script_chars": len(script),
        "edit_ratio": round(1 - sum(1 for s, d in path if s >= 0 and d >= 0 and script[s] == asr[d]) / max(1, len(script)), 3),
        "beats": {r["id"]: [r["start"], r["end"]] for r in rows},
        "cues": len(subs),
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())