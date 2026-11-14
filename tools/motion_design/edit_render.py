"""剪辑模式的 ffmpeg 执行器(与 Remotion / Playwright 生成链完全隔离)。

实测约束(写之前逐条验过):
- `-c:v copy` 与 `-filter_complex` 互斥 → 只要有任何剪辑效果就必须重编码。
- xfade 要求两路输入同分辨率/帧率/pix_fmt/timebase → 每段先统一归一化。
- xfade 的 offset = 下一段的 timeline_start(契约里已扣掉转场重叠)。
- atempo 只接受 0.5–2.0,超出必须串联多个。
- `cmd_render` 完全不碰 ffmpeg,音画合成在 build 阶段由 Remotion 做;
  这里必须自己 mux,沿用 wallstreet 后端验证过的命令。

分三步走,任何一步失败都能单独看日志:
  1) 只出视频(归一化 → 变速 → xfade → 画中画 → 可选 drawtext 文字卡)
  2) 只出音频(逐段 atrim/atempo → acrossfade 或 concat → BGM → loudnorm)
  3) mux(-c:v copy -c:a aac -shortest -movflags +faststart)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from edit_contract import TRANSITIONS, validate

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
FONT_CANDIDATES = [
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
]


class EditError(RuntimeError):
    pass


def _sh(cmd: list[str], *, timeout: int = 1800, cwd: Path | None = None) -> subprocess.CompletedProcess:
    try:
        r = subprocess.run([str(x) for x in cmd], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           cwd=str(cwd) if cwd else None, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired as e:
        raise EditError(f"命令超时({timeout}s): {Path(str(cmd[0])).name}") from e
    if r.returncode:
        raise EditError(f"{Path(str(cmd[0])).name} 退出码 {r.returncode}: {(r.stderr or r.stdout or '')[-900:]}")
    return r


def _esc(s: str) -> str:
    """filter 参数里的路径转义(冒号/反斜杠/单引号)。"""
    return str(s).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def _atempo(speed: float) -> str:
    """atempo 只吃 0.5–2.0,拆成串联。"""
    parts, left = [], float(speed)
    while left > 2.0 + 1e-6:
        parts.append("atempo=2.0")
        left /= 2.0
    while left < 0.5 - 1e-6:
        parts.append("atempo=0.5")
        left /= 0.5
    parts.append(f"atempo={left:.6f}")
    return ",".join(parts)


def _probe_audio(path: Path) -> bool:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                        "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)
    return bool((r.stdout or "").strip())


def _font() -> str | None:
    return next((str(f) for f in FONT_CANDIDATES if f.is_file()), None)


def _video_filter(doc: dict, work: Path) -> tuple[list[str], list[str], str]:
    """返回 (额外输入参数, filter 片段列表, 最终视频标签)。"""
    out = doc["output"]
    W, H, FPS = out["width"], out["height"], out["fps"]
    main = [c for c in doc["cuts"] if c["layer"] == 0]
    pips = [c for c in doc["cuts"] if c["layer"] > 0]
    inputs: list[str] = []
    filters: list[str] = []
    warnings: list[str] = []
    font = _font()

    def branch(i: int, c: dict, tag: str) -> None:
        if c["source"]:
            inputs.extend(["-i", c["source"]])
            raw = c["source_out"] - c["source_in"]
            chain = (f"[{i}:v]trim=start={c['source_in']:.3f}:duration={raw:.3f},"
                     f"setpts=(PTS-STARTPTS)/{c['speed']:.6f}")
        else:
            ov = c["overlay"] or {}
            txt = f"card_{i}.txt"
            (work / txt).write_text(str(ov.get("text") or ""), encoding="utf-8")
            inputs.extend(["-f", "lavfi", "-i",
                           f"color=c={ov.get('backgroundColor', '#101E33')}:s={W}x{H}:r={FPS}:d={c['timeline_duration']:.3f}"])
            chain = f"[{i}:v]setpts=PTS-STARTPTS"
            if font and (work / txt).stat().st_size:
                # 字体复制进 work 用纯文件名:Windows 的 C:/... 在 filter 里
                # 冒号和反斜杠转义非常容易出错,实测 eslint 式转义会被吞掉。
                font_name = "font" + Path(font).suffix
                try:
                    if not (work / font_name).exists():
                        shutil.copyfile(font, work / font_name)
                    chain += (f",drawtext=textfile={txt}:fontfile={font_name}:"
                              f"fontcolor={ov.get('color', '#F1EAD2')}:fontsize={int(H * 0.045)}:"
                              "x=(w-text_w)/2:y=(h-text_h)/2")
                except OSError:
                    warnings.append(f"cuts[{i}] 中文字体复制失败,只输出纯色卡")
            else:
                warnings.append(f"cuts[{i}] 文字卡未找到中文字体,只输出纯色卡")
        if c.get("transform", {}).get("crop"):
            cr = c["transform"]["crop"]
            chain += (f",crop=w=iw*{cr['width']:.4f}:h=ih*{cr['height']:.4f}:"
                      f"x=iw*{cr['x']:.4f}:y=ih*{cr['y']:.4f}")
        sc = c.get("transform", {}).get("scale", 1.0)
        chain += (f",scale={W}:{H}:force_original_aspect_ratio=decrease,"
                  f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
                  f"fps={FPS},format=yuv420p,settb=AVTB")
        if sc != 1.0:
            # 画中画/二次构图:先按 scale 裁中心再铺满
            chain += f",scale={int(W * sc)}:{int(H * sc)},crop={W}:{H}"
        filters.append(chain + f"[{tag}]")

    for i, c in enumerate(main):
        branch(i, c, f"v{i}")
    last = "v0"
    for i in range(1, len(main)):
        c = main[i]
        tr = c["transition_in"]
        tag = f"x{i}"
        if tr["duration"] > 0 and TRANSITIONS.get(tr["type"]):
            filters.append(
                f"[{last}][v{i}]xfade=transition={TRANSITIONS[tr['type']]}:"
                f"duration={tr['duration']:.3f}:offset={c['timeline_start']:.3f}[{tag}]")
        else:
            filters.append(f"[{last}][v{i}]concat=n=2:v=1:a=0[{tag}]")
        last = tag

    for j, c in enumerate(pips):
        idx = len(main) + j
        branch(idx, c, f"p{j}")
        pos = c.get("transform", {}).get("position", [0.5, 0.5])
        # 画中画缩到主画面的 34%,按 position 定位。
        # 关键:overlay 的时间轴是主画面,PiP 必须把自己的 PTS 挪到 pip_start,
        # 否则出现时播的是自己第 pip_start 秒的内容,而且 repeatlast 会把
        # 最后一帧冻结到窗口末端。这里显式 setpts + repeatlast=0。
        pip_w, pip_h = int(W * 0.34), int(H * 0.34)
        start = c["timeline_start"]
        stop = start + c["timeline_duration"]
        filters.append(
            f"[p{j}]setpts=PTS-STARTPTS+{start:.3f}/TB,scale={pip_w}:{pip_h}[ps{j}]")
        x, y = pos[0], pos[1]
        enable = f"between(t\\,{start:.3f}\\,{stop:.3f})"
        nxt = "vout" if j == len(pips) - 1 else f"o{j}"
        filters.append(
            f"[{last}][ps{j}]overlay=x='(W-w)*{x:.4f}':y='(H-h)*{y:.4f}':"
            f"enable='{enable}':eof_action=pass:repeatlast=0[{nxt}]")
        last = nxt
    return inputs, filters, last if pips else last


def _audio_filter(doc: dict, work: Path) -> tuple[list[str], list[str], str] | None:
    main = [c for c in doc["cuts"] if c["layer"] == 0 and c["source"]]
    if not main:
        return None
    audio_cfg = doc.get("audio") or {}
    inputs: list[str] = []
    filters: list[str] = []
    usable: list[int] = []
    for i, c in enumerate(main):
        if not _probe_audio(Path(c["source"])):
            continue
        inputs += ["-i", c["source"]]
        raw = c["source_out"] - c["source_in"]
        usable.append(i)
        filters.append(
            f"[{len(usable) - 1}:a]atrim=start={c['source_in']:.3f}:duration={raw:.3f},"
            f"asetpts=PTS-STARTPTS,{_atempo(c['speed'])},"
            "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
            f"[a{i}]")
    if not usable:
        return None
    labels = [f"a{i}" for i in usable]
    last = labels[0]
    for k, i in enumerate(usable[1:], start=1):
        c = main[i]
        tr = c["transition_in"]
        tag = f"ax{k}"
        if tr["duration"] > 0:
            filters.append(f"[{last}][{labels[k]}]acrossfade=d={min(tr['duration'], 0.6):.3f}:c1=tri:c2=tri[{tag}]")
        else:
            filters.append(f"[{last}][{labels[k]}]concat=n=2:v=0:a=1[{tag}]")
        last = tag
    music = audio_cfg.get("music")
    if music and Path(music).is_file():
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        midx = len(usable)
        filters.append(f"[{midx}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                       f"volume=0.16[bgm]")
        filters.append(f"[{last}][bgm]amix=inputs=2:duration=first:dropout_transition=0[amix]")
        last = "amix"
    filters.append(f"[{last}]loudnorm=I=-14:TP=-1.5:LRA=11,apad,atrim=duration={doc['total']:.3f}[aout]")
    return inputs, filters, "aout"


def render(doc: dict, dest: Path, *, preview: bool = False,
           overwrite: bool = True, keep_work: bool = False) -> dict:
    """把规范文档渲染成 mp4。返回输出信息与警告。"""
    norm, total = validate(doc)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if not overwrite:
            raise EditError(f"输出已存在: {dest}")
        dest.unlink()
    W, H, FPS = norm["output"]["width"], norm["output"]["height"], norm["output"]["fps"]
    if preview:
        scale = 480 / max(1, W)
        W, H = int(W * scale) // 2 * 2, int(H * scale) // 2 * 2
        norm["output"] = {"width": W, "height": H, "fps": FPS}
    work = Path(tempfile.mkdtemp(prefix="sf-edit-", dir=str(dest.parent)))
    warnings: list[str] = []
    try:
        v_inputs, v_filters, v_tag = _video_filter(norm, work)
        if not v_filters:
            raise EditError("没有可渲染的镜头")
        vf = ";".join(v_filters)
        visual = work / "visual.mp4"
        cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y", *v_inputs,
               "-filter_complex", vf, "-map", f"[{v_tag}]", "-an",
               "-c:v", "libx264", "-preset", "ultrafast" if preview else "medium",
               "-crf", "30" if preview else "21", "-pix_fmt", "yuv420p",
               "-r", str(FPS), "-movflags", "+faststart", str(visual)]
        _sh(cmd, cwd=work)
        if not visual.is_file() or visual.stat().st_size < 1000:
            raise EditError("视频轨渲染失败或输出为空")

        af = _audio_filter(norm, work)
        if af:
            a_inputs, a_filters, a_tag = af
            audio = work / "audio.m4a"
            _sh(["ffmpeg", "-hide_banner", "-v", "error", "-y", *a_inputs,
                 "-filter_complex", ";".join(a_filters), "-map", f"[{a_tag}]",
                 "-vn", "-c:a", "aac", "-b:a", "192k", str(audio)], cwd=work)
            _sh(["ffmpeg", "-hide_banner", "-v", "error", "-y",
                 "-i", str(visual), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                 "-movflags", "+faststart", str(dest)], cwd=work)
        else:
            # 没有可用原声:补一条静音轨,避免 review 报「成片没有音轨」
            _sh(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(visual),
                 "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo",
                 "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
                 "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(dest)], cwd=work)
        if not dest.is_file() or dest.stat().st_size < 1000:
            raise EditError("成片输出为空")
        return {
            "ok": True, "video": str(dest), "bytes": dest.stat().st_size,
            "total": total, "cuts": len(norm["cuts"]),
            "transitions": sum(1 for c in norm["cuts"] if c["transition_in"]["duration"] > 0),
            "pips": sum(1 for c in norm["cuts"] if c["layer"] > 0),
            "filter_complex_chars": len(vf), "warnings": warnings,
            "preview": preview,
        }
    finally:
        if not keep_work:
            shutil.rmtree(work, ignore_errors=True)


def render_project(project: Path, dest: Path, *, preview: bool = False) -> dict:
    f = project / "edit_decisions.json"
    if not f.is_file():
        raise EditError(f"缺少 {f.name}")
    return render(json.loads(f.read_text(encoding="utf-8")), dest, preview=preview)
