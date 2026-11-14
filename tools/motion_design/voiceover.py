"""把口播稿逐段合成成音频,用实测时长反过来定节拍。

画面跟着人声走,而不是先定 45 秒再硬塞字:
  1. 每段文本单独合成(带一点首尾留白);
  2. 用 ffprobe 量出真实时长;
  3. 输出 beats.json(每拍 dur = 该段语音时长 + 呼吸间隔)与 timing.json。

MiniMax T2A v2 返回的是 hex 编码的 mp3,要解出来再转 wav。

**朗读形在合成边界统一生成**(`spoken_text`):字幕写「1亿℃」,但送给 TTS 的
永远是「一亿摄氏度」,而且按口播单元断句 —— 一行念不完的长句会被切成几段,
每段都是完整的词("EAST" 不会被切成 "EAS"+"T")。放在边界而不是调用方,
是因为 verify_voice.py / 别家脚本也会直接调 synth_*,它们必须听到同一份文本。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_subs import SPEECH_RULES_VERSION, speak  # noqa: E402


def spoken_text(text: str) -> str:
    """字幕文本 → 真正送去合成的文本。

    - 数字/单位转朗读形:1亿℃ → 一亿摄氏度,1066秒 → 一千零六十六秒;
    - 过长的一句切成口播单元,单元之间补句号(让 TTS 真的停顿);
    - 括号里的补充说明丢掉(字幕仍然保留);
    - 幂等:已经是朗读形的文本再过一遍不会变。

    整段都在括号里时朗读形会变成空串 —— 那就退回原文。合成空串只会得到
    一条 0 秒的空音频,后面必然炸在「疑似空音频」上,不如老老实实念出来。
    """
    raw = str(text or "").strip()
    out = speak(raw)
    return out or raw


def synthesis_text(seg: dict) -> str:
    """一段稿子真正送去合成的文本 —— **整个流程里只算一次**。

    规则:
      - 稿子里**显式写了 say** → 那是作者自己定的读法,原样念,不再改写
        (例:字幕写「三点四六」,say 写「三个点四六」,免得读成「三点四十六」);
      - 没写 say → 由字幕文本推出朗读形:数字/单位说人话、长句按口播单元断句、
        括号里的补充说明丢掉。

    之前这里和 synth_edge() 内部各算了一遍:合成的是 spoken(spoken(x)),
    verify_voice 合成的是 spoken(x)。两份文本只要有一丁点差别,
    音频就完全不同,互相关校验直接掉到 0.01。
    现在唯一的算点在 synthesis_text(),合成与校验都从它取同一个字符串。
    """
    explicit = seg.get("say")
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    return spoken_text(seg.get("text", ""))


# 内置稿子:《焦虑的公式》(八拍)。新片子在自己的工程目录放 script.json 覆盖它。
DEFAULT_SEGMENTS = [
    ("hook",       "很多人一直在对抗焦虑,但很少有人看懂,焦虑其实有一条公式。"),
    ("formula",    "焦虑,等于执着的期望,除以,认知清晰度,乘以胸怀容量。"),
    ("molecule",   "先说分子,执着的期望。不是说不能有期待,而是别把夸奖、回报、别人的认可,绑定成你值不值得的唯一答案。"),
    ("clarity",    "再看分母第一项,认知清晰度。格物致知,就是分清一件事:什么我能掌控,什么再用力也左右不了。边界看清了,内耗就少一半。"),
    ("capacity",   "分母第二项,胸怀容量。把自己放回天地之间,别把自我无限放大。虚怀若谷,不是看轻自己,是把塞满执念的心,腾出空间。"),
    ("contrast",   "这里有一句很关键的区分。自卑,是认定我很差;觉悟,是明白,我没那么重要。"),
    ("empty",      "我们不用强迫自己,瞬间消除焦虑。"),
    ("end",        "只需要慢慢做到:期望少执念一点,事理看通透一点,内心放空一点,人自然就静下来了。"),
]

VOICE_CANDIDATES = ["audiobook_male_1", "presenter_male", "male-qn-qingse"]

DEFAULT_ROLES = {
    "hook": "HOOK", "formula": "BUILD", "molecule": "BUILD", "clarity": "BUILD",
    "capacity": "BUILD", "contrast": "HERO", "empty": "BUILD", "end": "END",
}
DEFAULT_TITLES = {
    "hook": "焦虑藏在这条公式里", "formula": "公式自己写出来", "molecule": "分子:执着的期望",
    "clarity": "分母一:认知清晰度", "capacity": "分母二:胸怀容量",
    "contrast": "自卑 vs 觉悟", "empty": "虚怀若谷,把心腾空", "end": "落回公式",
}


def load_script(proj: Path, length_scale: float = 0.95):
    """工程目录里有 script.json 就用它,否则用内置的《焦虑的公式》。

    script.json 结构:
      {"segments": [{"id": "hook", "role": "HOOK", "title": "...", "text": "..."}]}
    这样新片子不必改这个文件,复用同一套「合成→实测→反推节拍」的流程。
    """
    f = proj / "script.json"
    if not f.exists():
        rows = [{"id": i, "text": t} for i, t in DEFAULT_SEGMENTS]
        return rows, DEFAULT_ROLES, DEFAULT_TITLES
    data = json.loads(f.read_text(encoding="utf-8"))
    segs = data["segments"]
    rows = [
        {
            "id": x["id"],
            "text": x["text"],
            # say 只影响"合成什么音",不影响字幕。
            # 例:字幕要「三点四六」,但 TTS 得写「三个点四六」才不会读成「三点四十六」。
            # 关键:没有显式 say 时必须留空。默认成原文会被 synthesis_text 当成
            # "作者指定读法"而整段跳过朗读规则 —— 数字单位、去引号、断句全失效,
            # 成片里「1亿℃」会被念成「一 亿 ℃」,还会和校验用的文本对不上。
            "say": x.get("say") or "",
            # 逐句的语气参数(只在 piper 下生效):短句放慢、数据句加快,
            # noise_w 调高让节奏有自然起伏,而不是匀速念稿。
            "speed": float(x.get("speed", length_scale)),
            "noise_w": float(x.get("noise_w", 0.8)),
            "silence": float(x.get("silence", 0.12)),
            "rate": str(x.get("rate", "+0%")),
            "pitch": str(x.get("pitch", "+0Hz")),
        }
        for x in segs
    ]
    roles = {x["id"]: x.get("role", "BUILD") for x in segs}
    titles = {x["id"]: x.get("title", "") for x in segs}
    return rows, roles, titles


def _load_dotenv() -> None:
    env = REPO / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k not in os.environ:
            os.environ[k] = v


def synth(text: str, voice: str, speed: float, key: str, timeout: int = 120) -> bytes:
    """合成一段文本。**text 就是要念的内容**,这里不再做任何改写。

    改写只发生在 synthesis_text() 一处 —— 之前这里又改写了一遍,
    导致合成的是 spoken(spoken(x))、校验用的是 spoken(x),音频对不上。
    """
    body = {
        "model": "speech-02-hd",
        "text": text,
        "voice_setting": {"voice_id": voice, "speed": speed, "vol": 1.0, "pitch": 0},
        "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3"},
    }
    req = urllib.request.Request(
        "https://api.minimax.chat/v1/t2a_v2",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.loads(r.read().decode("utf-8"))
    br = payload.get("base_resp") or {}
    if br.get("status_code") not in (0, None):
        raise RuntimeError(f"TTS 失败 {br.get('status_code')}: {br.get('status_msg')}")
    hexaudio = (payload.get("data") or {}).get("audio")
    if not hexaudio:
        raise RuntimeError("TTS 没有返回音频: " + json.dumps(payload, ensure_ascii=False)[:300])
    return bytes.fromhex(hexaudio)


# Piper:本机离线 TTS,不需要 key。中文模型通常放在 ~/.piper/models/。
PIPER_DEFAULT_MODEL = Path.home() / ".piper" / "models" / "zh_CN-huayan-medium.onnx"


def piper_bin() -> str | None:
    """找 piper 可执行文件:环境变量 > 虚拟环境 > PATH。"""
    env = os.environ.get("PIPER_BIN")
    if env and Path(env).exists():
        return env
    for cand in (REPO / ".venv" / "Scripts" / "piper.exe", REPO / ".venv" / "bin" / "piper"):
        if cand.exists():
            return str(cand)
    return shutil.which("piper")


def synth_piper(
    text: str,
    out_wav: Path,
    length_scale: float = 0.95,
    noise_scale: float = 0.667,
    noise_w_scale: float = 0.8,
    sentence_silence: float = 0.12,
) -> None:
    """用 Piper 合成一段中文语音。

    Piper 是单音色、匀速输出的,听感容易"念稿"。三个参数可以拉开语气:

      length_scale    音素时长。<1 更快。给短句慢、给数据快,就有轻重缓急。
      noise_scale     生成噪声。高一点音色变化更明显(过高会发毛发虚)。
      noise_w_scale   音素宽度噪声。这个最影响**节奏起伏** —— 默认 0.8 偏平,
                      提到 1.0~1.1 会有自然的拖长与收紧。
      sentence_silence 句内句间的停顿时长,给情绪留白。

    text 就是要念的内容,这里不再做任何改写(改写只在 synthesis_text() 一处)。
    """
    exe = piper_bin()
    if not exe:
        raise RuntimeError("找不到 piper,可设置 PIPER_BIN 指向可执行文件")
    model = Path(os.environ.get("PIPER_MODEL", str(PIPER_DEFAULT_MODEL)))
    if not model.exists():
        raise RuntimeError(f"找不到 Piper 中文模型:{model}")
    proc = subprocess.run(
        [exe, "-m", str(model), "-f", str(out_wav),
         "--length-scale", str(length_scale),
         "--noise-scale", str(noise_scale),
         "--noise-w-scale", str(noise_w_scale),
         "--sentence-silence", str(sentence_silence)],
        input=text.encode("utf-8"), capture_output=True,
    )
    if proc.returncode != 0 or not out_wav.exists() or out_wav.stat().st_size == 0:
        raise RuntimeError("Piper 合成失败:" + proc.stderr.decode("utf-8", "replace")[-300:])


# ── Edge TTS:微软的免费神经音色,不需要 key ──
# 比 Piper 自然得多(有真语调曲线),而且支持逐句 rate/pitch,
# 可以做出轻重缓急,而不是匀速念稿。
EDGE_DEFAULT_VOICE = "zh-CN-YunjianNeural"


def synth_edge(
    text: str,
    out_mp3: Path,
    voice: str = EDGE_DEFAULT_VOICE,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    volume: str = "+0%",
) -> None:
    """用 edge-tts 合成。rate/pitch 是逐句做语气的手段:

      rate  "-10%"  放慢,用在结论句
      rate  "+6%"   加快,用在数据罗列
      pitch "-4Hz"  压低,用在沉重的地方

    text 就是要念的内容,这里不再做任何改写(改写只在 synthesis_text() 一处)。
    """
    import asyncio

    import edge_tts

    # 新版 edge-tts 要求这几个参数必须带正负号("0Hz" 会抛 ValueError),
    # 老版接受 "0Hz"。统一成带符号形式,两个版本都能跑。
    def _signed(v: str) -> str:
        v = str(v).strip()
        return v if (not v or v[0] in "+-") else "+" + v

    rate, pitch, volume = _signed(rate), _signed(pitch), _signed(volume)

    async def _run() -> None:
        comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume)
        await comm.save(str(out_mp3))

    asyncio.run(asyncio.wait_for(_run(), timeout=180))


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def voice_sig(seg: dict, provider: str, voice: str) -> str:
    """把"这段音频到底该念什么"折成一个短哈希,拼进文件名。

    以前只判断 wav 是否存在就复用 —— 改了稿子再合成,人声还是旧的,
    而 timing/subtitles 写的是新文本,成片就会出现「听到的」和「看到的」不一致。
    内容寻址之后,文本/音色/语速任何一项变了,文件名就变,旧文件自然失效。

    折叠的是**真正送去合成的文本**(synthesis_text 之后),不是字幕文本:
    朗读规则一改(1亿℃ → 一亿摄氏度),同样的稿子也该重新合成。
    rules 版本号把这个变化也带进哈希 —— 否则规则升级后旧缓存会被当成"还是对的"。
    """
    blob = json.dumps(
        {
            "text": synthesis_text(seg),
            "voice": voice,
            "rate": seg.get("rate", "+0%"),
            "pitch": seg.get("pitch", "+0Hz"),
            "provider": provider,
            "speed": round(float(seg.get("speed", 0)), 4),
            "rules": SPEECH_RULES_VERSION,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="口播合成 → 实测时长 → beats.json")
    ap.add_argument("--project", required=True)
    ap.add_argument("--speed", type=float, default=1.02)
    ap.add_argument("--gap", type=float, default=0.42, help="每段之间留的呼吸")
    ap.add_argument("--voice", default="")
    ap.add_argument("--provider", choices=["auto", "minimax", "piper", "edge"], default="auto",
                    help="TTS 供应商。auto = 先试 minimax,额度不够就退回本地 piper")
    ap.add_argument("--length-scale", type=float, default=0.95,
                    help="Piper 语速(<1 更快)")
    args = ap.parse_args(argv)

    _load_dotenv()
    key = os.environ.get("MINIMAX_API_KEY", "")
    provider = args.provider
    if provider == "auto":
        # 优先级:minimax(有额度时音质最好)→ edge(免费且自然)→ piper(离线兜底)
        provider = "minimax" if key else "edge"
    if provider == "minimax" and not key:
        if args.provider == "minimax":
            print(json.dumps({"ok": False, "error": "没有 MINIMAX_API_KEY"}, ensure_ascii=False))
            return 2
        provider = "piper"
    print(f"[tts] provider = {provider}", file=sys.stderr)

    proj = Path(args.project).resolve()
    vo = proj / "out" / "voice"
    vo.mkdir(parents=True, exist_ok=True)

    # 选一个能用的音色(仅 minimax 需要)
    voice = args.voice
    if not voice:
        if provider == "piper":
            voice = "piper:" + PIPER_DEFAULT_MODEL.stem
        elif provider == "edge":
            voice = EDGE_DEFAULT_VOICE
    if provider == "minimax" and not voice:
        for cand in VOICE_CANDIDATES:
            try:
                blob = synth("测试。", cand, args.speed, key, timeout=60)
                if blob:
                    voice = cand
                    break
            except Exception as exc:
                print(f"[voice] {cand} 不可用: {exc}", file=sys.stderr)
    if not voice:
        print(json.dumps({"ok": False, "error": "没有可用音色"}, ensure_ascii=False))
        return 3
    print(f"[voice] 使用 {voice}", file=sys.stderr)

    segments, roles, titles = load_script(proj, args.length_scale)
    rows = []
    for seg in segments:
        sid, text = seg["id"], seg["text"]
        # 真正要念出来的字:稿子里显式给了 say 就尊重它(人工润色过读音),
        # 否则统一走朗读形(数字/单位说人话 + 按口播单元断句)。
        # 这里算一次就够了 —— synth_* 不再改写,verify_voice 也从 timing.json
        # 读同一份 say,两边合成的字符串完全一致。
        say = synthesis_text(seg)
        sig = voice_sig(seg, provider, voice)
        mp3 = vo / f"{sid}.{sig}.mp3"
        wav = vo / f"{sid}.{sig}.wav"
        raw = vo / f"{sid}.{sig}.raw.wav"
        if provider == "edge":
            if not wav.exists() or wav.stat().st_size == 0:
                synth_edge(
                    say, mp3,
                    voice=voice,
                    rate=seg.get("rate", "+0%"),
                    pitch=seg.get("pitch", "+0Hz"),
                )
                subprocess.run(
                    ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp3),
                     "-af", "silenceremove=start_periods=1:start_threshold=-42dB,areverse,silenceremove=start_periods=1:start_threshold=-42dB,areverse,loudnorm=I=-16:TP=-1.5:LRA=11",
                     "-ar", "48000", "-ac", "2", str(wav)],
                    check=True,
                )
            d = duration(wav)
            if d < 0.4:
                raise RuntimeError(f"段 {sid} 时长 {d:.2f}s,疑似空音频")
            rows.append({"id": sid, "text": text, "say": say, "wav": str(wav), "dur": round(d, 3), "sig": sig})
            print(f"[tts] {sid:9s} {d:6.2f}s  {text[:24]}", file=sys.stderr)
            continue
        if provider == "piper":
            if not wav.exists() or wav.stat().st_size == 0:
                synth_piper(
                    say, raw,
                    length_scale=seg.get("speed", args.length_scale),
                    noise_w_scale=seg.get("noise_w", 0.8),
                    sentence_silence=seg.get("silence", 0.12),
                )
                subprocess.run(
                    ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
                     "-af", "silenceremove=start_periods=1:start_threshold=-42dB,areverse,silenceremove=start_periods=1:start_threshold=-42dB,areverse,loudnorm=I=-16:TP=-1.5:LRA=11",
                     "-ar", "48000", "-ac", "2", str(wav)],
                    check=True,
                )
                raw.unlink(missing_ok=True)
            d = duration(wav)
            if d < 0.4:
                raise RuntimeError(f"段 {sid} 时长 {d:.2f}s,疑似空音频")
            rows.append({"id": sid, "text": text, "say": say, "wav": str(wav), "dur": round(d, 3), "sig": sig})
            print(f"[tts] {sid:9s} {d:6.2f}s  {text[:24]}", file=sys.stderr)
            continue
        if not mp3.exists() or mp3.stat().st_size == 0:
            mp3.write_bytes(synth(say, voice, args.speed, key))
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp3),
             "-af", "silenceremove=start_periods=1:start_threshold=-42dB,areverse,silenceremove=start_periods=1:start_threshold=-42dB,areverse,loudnorm=I=-16:TP=-1.5:LRA=11",
             "-ar", "48000", "-ac", "2", str(wav)],
            check=True,
        )
        d = duration(wav)
        if d < 0.4:
            raise RuntimeError(f"段 {sid} 时长 {d:.2f}s,疑似空音频 —— TTS 可能没真的出声")
        rows.append({"id": sid, "text": text, "say": say, "wav": str(wav), "dur": round(d, 3), "sig": sig})
        print(f"[tts] {sid:9s} {d:6.2f}s  {text[:24]}", file=sys.stderr)

    # 拼成一条连续音轨:每段后面补 gap
    total = sum(r["dur"] + args.gap for r in rows)
    print(f"[tts] 口播合计 {sum(r['dur'] for r in rows):.2f}s,含间隔 {total:.2f}s", file=sys.stderr)

    timing = {"voice": voice, "speed": args.speed, "gap": args.gap, "total": round(total, 3), "segments": rows}
    (proj / "timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")

    # 用实测时长写 beats.json(视觉节拍跟着人声走)
    beats = []
    for r in rows:
        beats.append({
            "id": r["id"], "role": roles.get(r["id"], "BUILD"), "dur": round(r["dur"] + args.gap, 3),
            "title": titles.get(r["id"], ""),
            "visual": r["text"][:40],
            "code": "画面节拍由该段口播实测时长驱动",
            "sfx": [],
        })
    (proj / "beats.json").write_text(json.dumps(beats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"ok": True, "voice": voice, "total": round(total, 3), "segments": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())