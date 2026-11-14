"""用户素材库 —— 只登记路径,不复制原文件。

索引落在 %LOCALAPPDATA%\\ShortFilmFactory\\library\\(data_root),不是按版本
隔离的 workspace;用户升级或换安装目录,素材库还在。磁盘上只写可再生的缩略图。

理解顺序(用户定死):**LLM 先整体吃完素材,语义分段与标签都是它理解后的输出**;
ffmpeg/numpy 只负责抽帧、把模型给的秒数对齐到帧,不做任何语义决策。
检索单位是语义段(shot)而不是文件,所以「长片里只出现 3 秒的办公室实拍」
能被单独命中,直接给出 source_in/source_out。

不引入 torch / CLIP / PySceneDetect 等重依赖:视觉理解走用户已配的
多模态 LLM 端点,复用 vision_score.py 的传输层。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

from app_paths import get_paths

VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".ts", ".mpg", ".mpeg", ".wmv", ".flv"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
MEDIA_SUFFIXES = VIDEO_SUFFIXES | IMAGE_SUFFIXES | AUDIO_SUFFIXES

STOP = {"的", "了", "和", "与", "在", "是", "有", "一个", "这个", "那个", "把", "给", "用", "要", "找", "想", "做", "段", "些", "个", "我", "你", "它", "们", "这", "那", "里", "上", "下", "中", "一", "不", "到", "从", "让", "被", "就", "都", "也", "还", "the", "a", "an", "of", "to", "and", "in", "for", "with", "on", "is", "are"}

# 编辑意图词:用户说「剪个片头」「做企业介绍」时,这类词不该被当成
# 画面语义命中 —— 否则素材里任何一张写着「片头」的标题卡都会假命中「雪山」。
GENERIC = {
    "片头", "片尾", "开头", "结尾", "过渡", "镜头", "画面", "视频", "短片", "素材",
    "剪辑", "介绍", "企业", "公司", "宣传", "一条", "剪一", "剪出", "需要", "用来",
    "适合", "可以", "内容", "段落", "场景", "风格", "节奏", "做成", "剪个",
    "企业介绍", "公司宣传", "宣传片", "介绍片",
}

_CREATE = """
CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '',
  size INTEGER NOT NULL,
  mtime REAL NOT NULL,
  fingerprint TEXT NOT NULL,
  duration REAL,
  width INTEGER,
  height INTEGER,
  fps REAL,
  has_audio INTEGER,
  status TEXT NOT NULL DEFAULT 'ready',
  asr_text TEXT NOT NULL DEFAULT '',
  vision_tags TEXT NOT NULL DEFAULT '',
  embedding BLOB,
  created REAL NOT NULL,
  updated REAL NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  global_tags TEXT NOT NULL DEFAULT '',
  content_type TEXT NOT NULL DEFAULT '',
  understanding TEXT NOT NULL DEFAULT 'pending',
  understood_at REAL
);
CREATE INDEX IF NOT EXISTS assets_fp ON assets(fingerprint);
CREATE INDEX IF NOT EXISTS assets_status ON assets(status);
CREATE TABLE IF NOT EXISTS shots (
  id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  idx INTEGER NOT NULL,
  in_seconds REAL NOT NULL,
  out_seconds REAL NOT NULL,
  rep_frame TEXT,
  motion REAL,
  brightness REAL,
  speech REAL,
  keywords TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  tags TEXT NOT NULL DEFAULT '',
  search_terms TEXT NOT NULL DEFAULT '',
  subjects TEXT NOT NULL DEFAULT '',
  scene TEXT NOT NULL DEFAULT '',
  usable_as TEXT NOT NULL DEFAULT '',
  quality TEXT NOT NULL DEFAULT '',
  boundary_source TEXT NOT NULL DEFAULT 'llm',
  llm_boundary REAL,
  tag_source TEXT NOT NULL DEFAULT 'llm',
  FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS shots_asset ON shots(asset_id, idx);
CREATE TABLE IF NOT EXISTS roots (
  path TEXT PRIMARY KEY,
  added REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS web_assets (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  source TEXT NOT NULL,
  source_url TEXT NOT NULL,
  license TEXT NOT NULL,
  creator TEXT NOT NULL,
  query TEXT NOT NULL,
  added REAL NOT NULL
);
"""

_LOCK = threading.RLock()
_JOBS: dict[str, dict] = {}


# ────────────────────────────── 基础设施 ──────────────────────────────
def library_root() -> Path:
    p = get_paths().data_root / "library"
    p.mkdir(parents=True, exist_ok=True)
    return p


def thumbs_root() -> Path:
    p = library_root() / "thumbs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return library_root() / "library.sqlite3"


def connect() -> sqlite3.Connection:
    db = db_path()
    existed = db.exists()
    con = sqlite3.connect(db, timeout=30.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(_CREATE)
    if existed:
        # 兼容旧索引:逐个补列,不重建、不丢已登记的素材。
        cols = {r["name"] for r in con.execute("PRAGMA table_info(assets)")}
        for name, decl in (("summary", "TEXT NOT NULL DEFAULT ''"),
                           ("global_tags", "TEXT NOT NULL DEFAULT ''"),
                           ("content_type", "TEXT NOT NULL DEFAULT ''"),
                           ("understanding", "TEXT NOT NULL DEFAULT 'pending'"),
                           ("understood_at", "REAL")):
            if name not in cols:
                con.execute(f"ALTER TABLE assets ADD COLUMN {name} {decl}")
        cols = {r["name"] for r in con.execute("PRAGMA table_info(shots)")}
        for name, decl in (("title", "TEXT NOT NULL DEFAULT ''"),
                           ("description", "TEXT NOT NULL DEFAULT ''"),
                           ("tags", "TEXT NOT NULL DEFAULT ''"),
                           ("search_terms", "TEXT NOT NULL DEFAULT ''"),
                           ("subjects", "TEXT NOT NULL DEFAULT ''"),
                           ("scene", "TEXT NOT NULL DEFAULT ''"),
                           ("usable_as", "TEXT NOT NULL DEFAULT ''"),
                           ("quality", "TEXT NOT NULL DEFAULT ''"),
                           ("boundary_source", "TEXT NOT NULL DEFAULT 'llm'"),
                           ("llm_boundary", "REAL"),
                           ("tag_source", "TEXT NOT NULL DEFAULT 'llm'")):
            if name not in cols:
                con.execute(f"ALTER TABLE shots ADD COLUMN {name} {decl}")
        con.commit()
    return con


def _run(cmd: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout,
                          creationflags=0x08000000 if os.name == "nt" else 0)


def probe(path: Path) -> dict:
    """ffprobe 一次拿全。失败抛 RuntimeError,不静默登记一个空壳。"""
    r = _run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], timeout=90)
    if r.returncode:
        raise RuntimeError(f"ffprobe 读取失败: {(r.stderr or '')[:160]}")
    data = json.loads(r.stdout or "{}")
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fr = (v or {}).get("avg_frame_rate") or "0/1"
    try:
        num, _, den = fr.partition("/")
        fps = float(num) / float(den or 1)
    except ValueError:
        fps = 0.0
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {
        "duration": round(duration, 3),
        "width": int((v or {}).get("width") or 0),
        "height": int((v or {}).get("height") or 0),
        "fps": round(fps, 3),
        "has_audio": bool(a),
        "has_video": bool(v),
    }


def fingerprint(path: Path) -> str:
    """不做全文件 hash(大素材太慢):size + mtime + 头尾各 64KB。"""
    st = path.stat()
    h = hashlib.sha256()
    h.update(f"{st.st_size}:{int(st.st_mtime)}".encode())
    with path.open("rb") as fh:
        h.update(fh.read(65536))
        if st.st_size > 131072:
            fh.seek(-65536, os.SEEK_END)
            h.update(fh.read(65536))
    return h.hexdigest()


def _kind(path: Path) -> str:
    s = path.suffix.lower()
    if s in VIDEO_SUFFIXES:
        return "video"
    if s in IMAGE_SUFFIXES:
        return "image"
    return "audio"


# ────────────────────────────── 镜头切分 ──────────────────────────────
def detect_shots(path: Path, duration: float, *, sample_fps: float = 4.0) -> list[dict]:
    """32×32 RGB 逐帧差切镜头。

    ffmpeg 的 scdet 在实测中漏掉硬切(纯色测试片 3/6/9s 只报 6s、9s),
    缩到 32×32 的 numpy 帧差三个切点全中,真实片几乎零误报。
    阈值用「中位数 + 6×MAD」自适应,避免固定阈值在不同片型上翻车。
    """
    if duration <= 0:
        return []
    size, px = 32, 32 * 32 * 3
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-an",
         "-vf", f"fps={sample_fps},scale={size}:{size}", "-pix_fmt", "rgb24",
         "-f", "rawvideo", "pipe:1"],
        capture_output=True, timeout=600,
        creationflags=0x08000000 if os.name == "nt" else 0)
    raw = r.stdout
    n = len(raw) // px
    if n < 2:
        return []
    frames = np.frombuffer(raw[:n * px], dtype=np.uint8).reshape(n, size, size, 3).astype(np.int16)
    diffs = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2, 3))
    med = float(np.median(diffs))
    mad = float(np.median(np.abs(diffs - med))) or 0.5
    thresh = max(18.0, med + 6 * mad)
    cuts = [float(i + 1) / sample_fps for i, d in enumerate(diffs) if d > thresh]
    # 去掉过近的重复响应,以及片头片尾 0.25s 内的噪声
    edges: list[float] = []
    for c in cuts:
        if c < 0.25 or duration - c < 0.25:
            continue
        if edges and c - edges[-1] < 0.5:
            continue
        edges.append(round(c, 3))
    bounds = [0.0, *edges, round(duration, 3)]
    rows = []
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        if b - a < 0.3:
            continue
        lo, hi = int(a * sample_fps), max(int(a * sample_fps) + 1, min(int(b * sample_fps), len(diffs)))
        chunk = diffs[lo:hi]
        rows.append({
            "idx": len(rows), "in_seconds": a, "out_seconds": b,
            "motion": round(float(chunk.mean()), 2) if len(chunk) else 0.0,
            "brightness": round(float(frames[min(lo, n - 1)].mean()), 2),
            "speech": 0.0,
        })
    return rows


def make_thumbnails(path: Path, asset_id: str, shots: list[dict], kind: str) -> None:
    """每个 shot 一张代表帧(320px 宽),只写这些可再生的小图。"""
    out = thumbs_root() / asset_id
    out.mkdir(parents=True, exist_ok=True)
    if kind == "image":
        for f in out.glob("*.jpg"):
            f.unlink()
        dst = out / "000.jpg"
        _run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-frames:v", "1",
              "-vf", "scale=320:-2", str(dst)], timeout=90)
        if shots:
            shots[0]["rep_frame"] = str(dst)
        return
    if kind != "video":
        return
    for f in out.glob("*.jpg"):
        f.unlink()
    for s in shots[:24]:  # 上限,防止超长素材生成上千张图
        mid = (s["in_seconds"] + s["out_seconds"]) / 2
        dst = out / f"{s['idx']:03d}.jpg"
        _run(["ffmpeg", "-v", "error", "-y", "-ss", f"{mid:.3f}", "-i", str(path),
              "-frames:v", "1", "-vf", "scale=320:-2", str(dst)], timeout=90)
        if dst.exists():
            s["rep_frame"] = str(dst)


# ────────────────────────────── 可选 ASR ──────────────────────────────
def transcribe(path: Path) -> str:
    """本地 faster-whisper,可选增强;任何缺失/失败都返回空串,不影响登记。

    实测坑:包里的 av 版本不认 metadata_errors 参数,所以先解码成 WAV,
    用 soundfile 读成 float32 数组再喂给 model.transcribe(数组),不走文件路径。
    """
    try:
        import importlib.util
        if importlib.util.find_spec("faster_whisper") is None or importlib.util.find_spec("soundfile") is None:
            return ""
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from faster_whisper import WhisperModel  # type: ignore
        import soundfile as sf  # type: ignore
        wav = Path(os.environ.get("TEMP", ".")) / f"_sf_asr_{os.getpid()}_{int(time.time())}.wav"
        try:
            r = _run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "1",
                      "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], timeout=600)
            if r.returncode or not wav.exists():
                return ""
            data, sr = sf.read(str(wav), dtype="float32")
            if sr != 16000 and len(data) > 1:
                n_out = max(1, round(len(data) * 16000 / sr))
                data = np.interp(np.linspace(0, len(data) - 1, n_out),
                                 np.arange(len(data)), data).astype(np.float32)
            model = WhisperModel("base", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(np.ascontiguousarray(data), language="zh", beam_size=1)
            return " ".join(s.text.strip() for s in segments)[:4000]
        finally:
            try:
                wav.unlink(missing_ok=True)
            except OSError:
                pass
    except Exception:  # noqa: BLE001 —— 可选能力,不能拖垮登记
        return ""


# ────────────────────────────── 登记 ──────────────────────────────
def _iter_files(raw: list[str]) -> list[Path]:
    files: list[Path] = []
    for item in raw:
        p = Path(item).expanduser()
        if not p.exists():
            continue
        if p.is_file():
            if p.suffix.lower() in MEDIA_SUFFIXES and not p.is_symlink():
                files.append(p.resolve())
            continue
        # 目录:只看直属一层 + 一层子目录,防误扫整块盘
        for depth, pattern in ((0, "*"), (1, "*/*")):
            for f in p.glob(pattern):
                try:
                    if f.is_file() and not f.is_symlink() and f.suffix.lower() in MEDIA_SUFFIXES:
                        files.append(f.resolve())
                except OSError:
                    continue
    seen, out = set(), []
    for f in files:
        key = str(f).casefold()
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def understand_asset(asset_id: str, *, force: bool = False) -> dict:
    """让 LLM 整体吃完一条素材,把语义分段 + 标签写进 shots 表。

    这是「先吃完再得到标签/切片」的落地点:段数、边界、标签全部来自模型。
    """
    import shot_understanding as su  # noqa: WPS433
    with connect() as con:
        row = con.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
    if not row:
        raise ValueError("素材未登记")
    p = Path(row["path"])
    if not p.is_file():
        raise RuntimeError("素材文件缺失,先重新定位")
    if row["kind"] != "video":
        return {"ok": True, "skipped": "非视频素材无需语义分段"}
    if row["understanding"] == "ready" and not force:
        return {"ok": True, "cached": True, "segments": row["shots"] if "shots" in row.keys() else 0}
    if not su.available():
        raise RuntimeError("未配置多模态 LLM 端点,无法理解素材(可在模型设置里填支持图片的端点)")
    work = library_root() / "work" / asset_id
    result = su.understand_video(p, work=work, name=row["name"], tags=row["tags"],
                                 duration=float(row["duration"] or 0))
    segs = result["segments"]
    # 模型给的边界 → numpy 帧对齐(只对齐,不重新决定切哪里)
    try:
        aligned = su.align_boundaries(p, [s["end_seconds"] for s in segs[:-1]])
    except Exception:  # noqa: BLE001 —— 对齐失败不丢语义结果
        aligned = {}
    for s in segs:
        if s["end_seconds"] in aligned and aligned[s["end_seconds"]]["confidence"] == "high":
            s["end_seconds"] = aligned[s["end_seconds"]]["aligned"]
            s["boundary_source"] = "llm+frame_diff"
        s["llm_boundary"] = s.get("llm_boundary") or s.get("start_seconds")
    with connect() as con:
        con.execute("""UPDATE assets SET summary=?,global_tags=?,content_type=?,
                       understanding='ready',understood_at=?,updated=? WHERE id=?""",
                    (result["summary"], json.dumps(result["global_tags"], ensure_ascii=False),
                     result["content_type"], time.time(), time.time(), asset_id))
        con.execute("DELETE FROM shots WHERE asset_id=?", (asset_id,))
        for i, s in enumerate(segs):
            mid = (s["start_seconds"] + s["end_seconds"]) / 2
            thumb = thumbs_root() / asset_id / f"{i:03d}.jpg"
            thumb.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-ss", f"{mid:.3f}",
                            "-i", str(p), "-frames:v", "1", "-vf", "scale=320:-2", str(thumb)],
                           capture_output=True, creationflags=0x08000000 if os.name == "nt" else 0,
                           timeout=90)
            con.execute("""INSERT INTO shots
                (id,asset_id,idx,in_seconds,out_seconds,rep_frame,motion,brightness,speech,
                 keywords,title,description,tags,search_terms,subjects,scene,usable_as,
                 quality,boundary_source,llm_boundary,tag_source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (f"{asset_id}:{i:03d}", asset_id, i, s["start_seconds"], s["end_seconds"],
                 str(thumb) if thumb.exists() else "", 0.0, 0.0, 0.0, "",
                 str(s.get("title") or "")[:120], str(s.get("description") or "")[:1000],
                 json.dumps(s.get("tags") or [], ensure_ascii=False),
                 json.dumps(s.get("search_terms") or [], ensure_ascii=False),
                 json.dumps(s.get("subjects") or [], ensure_ascii=False),
                 str(s.get("scene") or "")[:60],
                 json.dumps(s.get("usable_as") or [], ensure_ascii=False),
                 str(s.get("quality") or "")[:30],
                 str(s.get("boundary_source") or "llm")[:30],
                 s.get("llm_boundary"), "llm"))
    return {"ok": True, "segments": len(segs), "summary": result["summary"],
            "global_tags": result["global_tags"], "endpoint": result["endpoint"]}


def register(raw_paths: list[str], *, tag: str = "", asr: bool = False,
             understand: bool = True, progress=None) -> dict:
    """登记一批路径。progress(done, total, name) 可用来刷 UI 进度。"""
    files = _iter_files(raw_paths)
    total, added, updated, skipped, failed = len(files), 0, 0, 0, []
    understood, understand_errors = 0, []
    new_ids: list[str] = []
    with connect() as con:
        for i, f in enumerate(files):
            try:
                info = probe(f)
                if info["duration"] <= 0 and _kind(f) == "video":
                    raise RuntimeError("视频时长为 0")
                fp = fingerprint(f)
                now = time.time()
                by_path = con.execute("SELECT id, tags, created FROM assets WHERE path=?", (str(f),)).fetchone()
                by_fp = con.execute("SELECT id, tags, created FROM assets WHERE fingerprint=? LIMIT 1", (fp,)).fetchone()
                existing = by_path or by_fp
                aid = existing["id"] if existing else hashlib.sha256(str(f).encode()).hexdigest()[:16]
                created = existing["created"] if existing else now
                tags = ",".join(filter(None, [existing["tags"] if existing else "", tag.strip()]))
                kind = _kind(f)
                # 登记阶段**不做语义切分**:只放一条覆盖整片的占位段。
                # 真正的段数/边界/标签由 understand_asset() 让 LLM 吃完之后写回。
                shots = ([{"idx": 0, "in_seconds": 0.0, "out_seconds": info["duration"],
                           "motion": 0.0, "brightness": 0.0, "speech": 0.0}]
                         if kind == "video" else
                         [{"idx": 0, "in_seconds": 0.0, "out_seconds": 3.0,
                           "motion": 0.0, "brightness": 0.0, "speech": 0.0}]
                         if kind == "image" else [])
                if shots:
                    make_thumbnails(f, aid, shots, kind)
                asr_text = ""
                if asr and kind == "video" and info["has_audio"]:
                    asr_text = transcribe(f)
                # 元数据先落库;语义理解放到同一批登记完成后再跑(见下方),
                # 免得每个文件都建一次数据库连接。
                con.execute("""INSERT INTO assets
                    (id,path,name,kind,tags,size,mtime,fingerprint,duration,width,height,fps,has_audio,status,asr_text,created,updated)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                      path=excluded.path,name=excluded.name,tags=excluded.tags,
                      size=excluded.size,mtime=excluded.mtime,fingerprint=excluded.fingerprint,
                      duration=excluded.duration,width=excluded.width,height=excluded.height,
                      fps=excluded.fps,has_audio=excluded.has_audio,status='ready',
                      asr_text=excluded.asr_text,updated=excluded.updated""",
                    (aid, str(f), f.name, kind, tags, f.stat().st_size, f.stat().st_mtime, fp,
                     info["duration"], info["width"], info["height"], info["fps"],
                     int(info["has_audio"]), "ready", asr_text, created, now))
                # 已理解过的素材不要因为重新登记就把语义结果清空。
                already = con.execute(
                    "SELECT understanding FROM assets WHERE id=?", (aid,)).fetchone()
                keep_semantics = bool(already and already["understanding"] == "ready")
                if not keep_semantics:
                    con.execute("DELETE FROM shots WHERE asset_id=?", (aid,))
                    con.executemany("""INSERT INTO shots
                        (id,asset_id,idx,in_seconds,out_seconds,rep_frame,motion,brightness,speech,keywords,boundary_source)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        [(f"{aid}:{s['idx']:03d}", aid, s["idx"], s["in_seconds"], s["out_seconds"],
                          s.get("rep_frame") or "", s.get("motion") or 0.0,
                          s.get("brightness") or 0.0, s.get("speech") or 0.0, asr_text[:500],
                          "placeholder")
                         for s in shots])
                else:
                    con.execute("UPDATE shots SET keywords=? WHERE asset_id=?", (asr_text[:500], aid))
                new_ids.append(aid)
                if existing:
                    updated += 1
                else:
                    added += 1
            except Exception as e:  # noqa: BLE001
                failed.append({"path": str(f), "error": f"{type(e).__name__}: {e}"[:160]})
                skipped += 1
            if progress:
                progress(i + 1, total, f.name)
        for item in raw_paths:
            p = Path(item).expanduser()
            if p.is_dir():
                con.execute("INSERT OR IGNORE INTO roots(path,added) VALUES (?,?)", (str(p.resolve()), time.time()))
    # 元数据落库后,让 LLM 逐个「吃完」这批素材;单个失败不阻塞整批。
    if understand and new_ids:
        import shot_understanding as su  # noqa: WPS433
        if su.available():
            for k, aid in enumerate(dict.fromkeys(new_ids)):
                try:
                    r = understand_asset(aid)
                    if not r.get("cached"):
                        understood += 1
                except Exception as e:  # noqa: BLE001
                    understand_errors.append({"id": aid, "error": f"{type(e).__name__}: {e}"[:160]})
                    with connect() as con:
                        con.execute("UPDATE assets SET understanding='failed' WHERE id=?", (aid,))
                if progress:
                    progress(total, total + len(new_ids), f"理解素材 {k + 1}/{len(new_ids)}")
    return {"ok": True, "total": total, "added": added, "updated": updated,
            "skipped": skipped, "failed": failed[:20], "understood": understood,
            "understand_errors": understand_errors[:10]}


# ────────────────────────────── 状态 / 检索 ──────────────────────────────
def check_status() -> dict:
    """核对每个登记路径:文件还在吗、size/mtime 变了吗。缺失绝不静默跳过。"""
    with connect() as con:
        rows = con.execute("SELECT id,path,size,mtime,status FROM assets").fetchall()
    missing, changed, ready = [], [], 0
    with connect() as con:
        for r in rows:
            p = Path(r["path"])
            status = "ready"
            if not p.is_file():
                status, bucket = "missing", missing
            elif p.stat().st_size != r["size"] or abs(p.stat().st_mtime - r["mtime"]) > 1:
                status, bucket = "changed", changed
            else:
                ready += 1
            if status != "ready":
                bucket.append({"id": r["id"], "path": r["path"], "name": p.name})
                con.execute("UPDATE assets SET status=?, updated=? WHERE id=?", (status, time.time(), r["id"]))
            elif r["status"] != "ready":
                con.execute("UPDATE assets SET status='ready', updated=? WHERE id=?", (time.time(), r["id"]))
    return {"ok": True, "total": len(rows), "ready": ready,
            "missing": missing, "changed": changed}


def relocate(old_prefix: str, new_prefix: str) -> dict:
    """换盘符/整盘搬家后批量重定位。只改索引,不动任何文件。"""
    old, new = old_prefix.strip().rstrip("\\/"), new_prefix.strip().rstrip("\\/")
    if not old or not new or old == new:
        raise ValueError("请填写不同的旧路径与新路径前缀")
    moved, failed = 0, []
    with connect() as con:
        rows = con.execute("SELECT id,path FROM assets").fetchall()
        for r in rows:
            if not str(r["path"]).casefold().startswith(old.casefold()):
                continue
            target = Path(new + str(r["path"])[len(old):])
            if not target.is_file():
                failed.append(str(target))
                continue
            try:
                con.execute("UPDATE assets SET path=?, size=?, mtime=?, status='ready', updated=? WHERE id=?",
                            (str(target), target.stat().st_size, target.stat().st_mtime, time.time(), r["id"]))
                moved += 1
            except sqlite3.IntegrityError:
                failed.append(str(target))
    return {"ok": True, "moved": moved, "failed": failed[:10]}


def remove(asset_id: str) -> dict:
    """移除登记(不删除用户原文件)。缩略图是可再生缓存,顺手清掉。"""
    with connect() as con:
        con.execute("DELETE FROM shots WHERE asset_id=?", (asset_id,))
        con.execute("DELETE FROM assets WHERE id=?", (asset_id,))
    import shutil
    shutil.rmtree(thumbs_root() / asset_id, ignore_errors=True)
    return {"ok": True, "removed": asset_id}


def set_tags(asset_id: str, tags: str) -> dict:
    with connect() as con:
        con.execute("UPDATE assets SET tags=?, updated=? WHERE id=?", (tags[:500], time.time(), asset_id))
    return {"ok": True}


def tokens(text: str) -> set[str]:
    """CJK 双字组 + 英文词,复用 match_style.py::tokens() 的思路,不依赖 jieba。"""
    text = (text or "").lower()
    out = {w for w in re.findall(r"[a-z0-9_]{2,}", text) if w not in STOP}
    cjk = re.findall(r"[\u4e00-\u9fff]+", text)
    for seg in cjk:
        for i in range(len(seg) - 1):
            bg = seg[i:i + 2]
            if bg not in STOP:
                out.add(bg)
        if len(seg) == 1:
            out.add(seg)
    return out


def _overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


def _json_list(v) -> list[str]:
    try:
        arr = json.loads(v or "[]")
        return [str(x) for x in arr if isinstance(x, (str, int, float))]
    except Exception:  # noqa: BLE001
        return []


def _haystack(r) -> tuple[str, str]:
    """一个语义段的全部可检索文字:LLM 标签/描述/检索词优先,文件名/批次标签兜底。"""
    semantic = " ".join([
        r["title"] or "", r["description"] or "",
        " ".join(_json_list(r["tags"])), " ".join(_json_list(r["search_terms"])),
        " ".join(_json_list(r["subjects"])), " ".join(_json_list(r["usable_as"])),
        r["scene"] or "", r["summary"] or "", " ".join(_json_list(r["global_tags"])),
    ])
    fallback = " ".join([Path(r["path"]).stem, r["tags"] or "",
                         (r["asr_text"] or "")[:1500], r["keywords"] or ""])
    return semantic, fallback


def search(query: str, *, limit: int = 12, min_score: float = 0.0,
           expand: bool = True) -> list[dict]:
    """语义检索:LLM 扩词 → 命中 shots 的标题/描述/标签/检索词 → 返回可剪坐标。

    「长片里只出现 3 秒的办公室」能命中,是因为那条 3 秒在理解阶段已被
    模型切成独立 shot 并打了「办公室」标签,不是靠整片一个标签碰运气。
    """
    terms = [query]
    if expand and query.strip():
        try:
            import shot_understanding as su  # noqa: WPS433
            if su.available():
                terms = [query] + su.expand_query(query)
        except Exception:  # noqa: BLE001
            pass
    q = tokens(" ".join(terms))
    ql = (query or "").lower()
    with connect() as con:
        rows = con.execute("""SELECT a.*, s.id AS shot_id, s.idx, s.in_seconds, s.out_seconds,
                     s.rep_frame, s.motion, s.brightness, s.keywords, s.title, s.description,
                     s.tags AS shot_tags, s.search_terms, s.subjects, s.scene, s.usable_as,
                     s.boundary_source, s.tag_source, s.quality,
                     (SELECT COUNT(*) FROM shots x WHERE x.asset_id=a.id) AS shot_count
                     FROM shots s JOIN assets a ON a.id=s.asset_id
                     WHERE a.status='ready'""").fetchall()
    scored = []
    for r in rows:
        semantic, fallback = _haystack(r)
        sem_t, fb_t = tokens(semantic), tokens(fallback)
        hit = q & sem_t
        # 只把「具体名词」算作语义命中;编辑意图词(片头/企业/介绍…)
        # 不算,否则「雪山」会被一张写着「片头」的标题卡假命中。
        content_q = q - GENERIC - STOP
        content_hit = content_q & sem_t
        if not content_hit:
            score = 0.0
        else:
            score = 3.0 * _overlap(content_q, sem_t) + 0.8 * _overlap(q, fb_t)
        if len(content_hit) >= 2:
            score += 0.4
        if ql and ql in semantic.lower():
            score += 0.5
        if r["boundary_source"] == "placeholder":
            score *= 0.35  # 还没被 LLM 理解的占位段,别冒充语义命中
        if r["quality"] in ("模糊", "过曝", "抖动", "无内容"):
            score *= 0.6
        if not q:
            score = 0.1
        if score <= min_score:
            continue
        reason = ("语义命中 " + "、".join(sorted(content_hit)[:5]) if content_hit
                  else "素材库候选")
        scored.append((score, r, reason))
    scored.sort(key=lambda x: (-x[0], x[1]["path"], x[1]["idx"]))
    seen: dict[str, int] = {}
    out = []
    for score, r, reason in scored:
        k = r["path"]
        if seen.get(k, 0) >= 2:
            continue
        seen[k] = seen.get(k, 0) + 1
        out.append({
            "asset_id": r["id"], "shot_id": r["shot_id"], "shot_index": r["idx"],
            "path": r["path"], "name": r["name"], "kind": r["kind"],
            "in_seconds": r["in_seconds"], "out_seconds": r["out_seconds"],
            "duration": round(r["out_seconds"] - r["in_seconds"], 3),
            "motion": r["motion"], "brightness": r["brightness"],
            "has_audio": bool(r["has_audio"]), "tags": r["shot_tags"],
            "title": r["title"], "description": (r["description"] or "")[:200],
            "scene": r["scene"], "boundary_source": r["boundary_source"],
            "understanding": r["understanding"], "shot_count": r["shot_count"],
            "asr": (r["asr_text"] or "")[:200],
            "thumb": f"/media/library/{r['id']}/{Path(r['rep_frame']).name}" if r["rep_frame"] else "",
            "score": round(score, 3), "reason": reason,
        })
        if len(out) >= limit:
            break
    return out


def refine(query: str, *, limit: int = 3, candidates: int = 3) -> dict:
    """查询驱动精读:对粗召回的候选视频发更密的帧,让 LLM 精确指出那几秒。

    返回 {found, items:[精确 in/out], checked, reason}。这是「只出现 3 秒」
    能被精确锁定并直接剪进时间轴的最后一步。
    """
    import shot_understanding as su  # noqa: WPS433
    if not su.available():
        return {"found": False, "reason": "未配置多模态端点,无法精读", "items": [], "checked": 0}
    rough = search(query, limit=candidates * 3, expand=False)
    paths: list[str] = []
    for h in rough:
        if h["path"] not in paths:
            paths.append(h["path"])
        if len(paths) >= candidates:
            break
    items, reasons = [], []
    with connect() as con:
        for p in paths:
            a = con.execute("SELECT * FROM assets WHERE path=?", (p,)).fetchone()
            if not a or not Path(p).is_file():
                continue
            try:
                r = su.refine_for_query(Path(p), query,
                                        work=library_root() / "work" / a["id"],
                                        name=a["name"], duration=float(a["duration"] or 0))
            except Exception as e:  # noqa: BLE001
                reasons.append(f"{Path(p).name}: {type(e).__name__}")
                continue
            reasons.append(f"{Path(p).name}: {r.get('reason', '')}")
            for c in r.get("clips") or []:
                items.append({
                    "asset_id": a["id"], "path": p, "name": a["name"],
                    "in_seconds": c["start_seconds"], "out_seconds": c["end_seconds"],
                    "duration": round(c["end_seconds"] - c["start_seconds"], 3),
                    "title": str(c.get("title") or "")[:120],
                    "description": str(c.get("description") or "")[:300],
                    "tags": json.dumps(c.get("tags") or [], ensure_ascii=False),
                    "confidence": c.get("confidence"),
                    "reason": r.get("reason", ""),
                    "source": "llm_refine",
                    "boundary_source": "llm_refine",
                    "understanding": a["understanding"],
                    "thumb": "",
                })
    items.sort(key=lambda x: -(float(x.get("confidence") or 0)))
    return {"found": bool(items), "items": items[:limit],
            "checked": len(paths), "reason": " | ".join(reasons)[:600]}


def _reason(q: set[str], name_t: set[str], asr_t: set[str]) -> str:
    hit_n, hit_a = q & name_t, q & asr_t
    bits = []
    if hit_n:
        bits.append("文件名/标签命中 " + "、".join(sorted(hit_n)[:4]))
    if hit_a:
        bits.append("口播命中 " + "、".join(sorted(hit_a)[:4]))
    return "；".join(bits) or "素材库候选"


def assets(*, offset: int = 0, limit: int = 60) -> dict:
    with connect() as con:
        total = con.execute("SELECT COUNT(*) AS n FROM assets").fetchone()["n"]
        rows = con.execute("""SELECT a.*, (SELECT COUNT(*) FROM shots s WHERE s.asset_id=a.id) AS shots
                              FROM assets a ORDER BY a.created DESC LIMIT ? OFFSET ?""",
                           (limit, offset)).fetchall()
        by_status = {r["status"]: r["n"] for r in con.execute(
            "SELECT status, COUNT(*) AS n FROM assets GROUP BY status").fetchall()}
        roots = [r["path"] for r in con.execute("SELECT path FROM roots ORDER BY added DESC").fetchall()]
    items = []
    for r in rows:
        items.append({
            "id": r["id"], "path": r["path"], "name": r["name"], "kind": r["kind"],
            "tags": r["tags"], "duration": r["duration"], "width": r["width"],
            "height": r["height"], "fps": r["fps"], "has_audio": bool(r["has_audio"]),
            "status": r["status"], "shots": r["shots"], "asr": bool(r["asr_text"]),
            "understanding": r["understanding"], "summary": (r["summary"] or "")[:160],
            "global_tags": r["global_tags"], "content_type": r["content_type"],
            "thumb": f"/media/library/{r['id']}/000.jpg" if (thumbs_root() / r["id"] / "000.jpg").exists() else "",
        })
    return {"ok": True, "total": total, "by_status": by_status,
            "roots": roots, "items": items, "offset": offset, "limit": limit}


def asset_map() -> dict[str, dict]:
    with connect() as con:
        return {r["path"]: {"duration": r["duration"] or 0.0, "status": r["status"]}
                for r in con.execute("SELECT path,duration,status FROM assets").fetchall()}


# ────────────────────────────── 后台任务 ──────────────────────────────
def start_scan(paths: list[str], *, tag: str = "", asr: bool = False) -> str:
    jid = hashlib.sha256(f"{time.time()}:{paths}".encode()).hexdigest()[:10]
    job = {"id": jid, "status": "running", "done": 0, "total": 0,
           "current": "", "result": None, "error": None, "started": time.time()}
    with _LOCK:
        _JOBS[jid] = job

    def work():
        def progress(done, total, name):
            job.update(done=done, total=total, current=name)
        try:
            job["result"] = register(paths, tag=tag, asr=asr, progress=progress)
            job["status"] = "done"
        except Exception as e:  # noqa: BLE001
            job["status"] = "failed"
            job["error"] = f"{type(e).__name__}: {e}"
        job["ended"] = time.time()

    threading.Thread(target=work, daemon=True).start()
    return jid


def job(jid: str) -> dict | None:
    with _LOCK:
        j = _JOBS.get(jid)
        return dict(j) if j else None
