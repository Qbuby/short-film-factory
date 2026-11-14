"""短片工厂 · 本地图形界面。

打开浏览器就能用:选风格 → 贴素材/传录音 → 点生成 → 在页面里看成片。
背后调用 film.py 的同一条管线(已验收),这里只负责界面、任务队列和预览。

启动:
    python tools/motion_design/film_ui.py          # 自动开浏览器
    python tools/motion_design/film_ui.py --no-browser --port 37975

只监听 127.0.0.1,不对外网开放。
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import hmac
import os
from http.cookies import SimpleCookie
import re
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from app_version import APP_VERSION, API_VERSION

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools" / "motion_design"
WORKSPACE = Path(os.environ.get("OE_WORKSPACE") or REPO).resolve()
FILM = TOOLS / "film.py"
PROJECTS = WORKSPACE / "projects" / "code-first"
FINAL = PROJECTS / "final"
ROUT = WORKSPACE / "remotion-composer" / "out"
PUBLIC = WORKSPACE / "remotion-composer" / "public"
UI_TOKEN = os.environ.get("OE_UI_TOKEN", "")
SETTINGS_LOCK = threading.RLock()
PREVIEW_LOCK = threading.Lock()
PY = REPO / ".venv" / "Scripts" / "python.exe"
if not PY.exists():
    PY = Path(sys.executable)
HTML = TOOLS / "film_ui.html"
PORT = 37975

TASKS: dict[str, dict] = {}
LOCK = threading.Lock()
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# ───────────────────────────── helpers ─────────────────────────────
def jsonresp(h: BaseHTTPRequestHandler, obj, code=200):
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    h.send_response(code)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(raw)))
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.wfile.write(raw)


def safe_name(s: str) -> str:
    s = re.sub(r"[^\w.\-]+", "_", s or "upload")
    return s[:80]


def project_meta(p: Path) -> dict | None:
    f = p / "project.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


# ─────────────────── 模型设置(写进程序目录的 .env) ───────────────────
def env_file() -> Path:
    return Path(os.environ.get("OE_CONFIG") or (REPO / ".env"))


def redact(value: str) -> str:
    text = str(value)
    for key in (_read_env().get("MOTION_LLM_KEY", ""), os.environ.get("MOTION_LLM_KEY", ""), UI_TOKEN):
        if key:
            text = text.replace(key, "[已隐藏]")
    return re.sub(r"(?i)(Bearer\s+)[^\s\"']+", r"\1[已隐藏]", text)


def _read_env() -> dict:
    vals: dict[str, str] = {}
    p = env_file()
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def read_settings() -> dict:
    v = _read_env()
    base = v.get("MOTION_LLM_BASE", "")
    key = v.get("MOTION_LLM_KEY", "")
    model = v.get("MOTION_LLM_MODEL", "")
    usable = bool(base and key and model)
    hint = ""
    if key:
        hint = "已保存"
    return {"base": base, "model": model, "hasKey": bool(key), "keyHint": hint,
            "configured": usable}


def write_settings(base: str, key: str, model: str) -> dict:
    """只改这三行,保留其它配置。空 key 表示不改动已有 key。"""
    p = env_file()
    old = p.read_text(encoding="utf-8", errors="replace").splitlines() if p.exists() else []
    keep = [l for l in old
            if not l.strip().startswith(("MOTION_LLM_BASE=", "MOTION_LLM_KEY=", "MOTION_LLM_MODEL="))]
    if any("\n" in str(v) or "\r" in str(v) for v in (base, key, model)):
        raise ValueError("模型设置不能包含换行")
    if base and urlparse(base).scheme not in ("http", "https"):
        raise ValueError("模型地址必须使用 http 或 https")
    if key:
        keep.append(f"MOTION_LLM_KEY={key}")
    elif any(l.startswith("MOTION_LLM_KEY=") for l in old):
        keep += [l for l in old if l.startswith("MOTION_LLM_KEY=")]
    if base:
        keep.append(f"MOTION_LLM_BASE={base.rstrip('/')}")
    if model:
        keep.append(f"MOTION_LLM_MODEL={model}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join([l for l in keep if l.strip()]) + "\n", encoding="utf-8")
    # 立即生效:llm._load_dotenv 只在"环境里没有"时才写入,所以这里显式覆盖
    if base:
        os.environ["MOTION_LLM_BASE"] = base.rstrip("/")
    if key:
        os.environ["MOTION_LLM_KEY"] = key
    if model:
        os.environ["MOTION_LLM_MODEL"] = model
    return read_settings()


def test_llm(base: str = "", key: str = "", model: str = "") -> dict:
    """测模型连通性 —— 分两段,让耗时可解释。

    优先用界面上"当前填着的"配置 —— 用户填对了却没点保存就测,也应当测到
    他填的那套,而不是偷偷去测上一次存下来的旧配置。

    第一段 探端点(毫秒级):地址通不通、鉴权过不过、模型名在不在。
    第二段 试一次推理:这个模型带思考、且可能在远端,可能几秒到十几秒。

    以前这里只发一次 20-token 的请求,带思考的模型必然返回空,
    于是又升档重发一次 —— 慢一倍还看不出慢在哪。现在只发一次,给够额度。
    """
    import time as tm
    overrides = {"MOTION_LLM_BASE": base.rstrip("/"), "MOTION_LLM_KEY": key, "MOTION_LLM_MODEL": model}
    overrides = {k: v for k, v in overrides.items() if v}
    saved = {k: os.environ.get(k) for k in overrides}
    try:
        if str(TOOLS) not in sys.path:
            sys.path.insert(0, str(TOOLS))
        import llm  # noqa: WPS433
        os.environ.update(overrides)
        pr = llm.probe()
        t0 = tm.time()
        out = llm.complete("只回复 OK", "ping", max_tokens=2048, temperature=0)
        infer_ms = int((tm.time() - t0) * 1000)
        note = ""
        if infer_ms > 4000:
            note = "该模型响应偏慢(带思考或远端转发),写一稿通常要几十秒"
        return {"ok": True, "latency_ms": infer_ms,
                "probe_ms": pr.get("latency_ms"), "probe_ok": pr.get("ok"),
                "model_found": pr.get("model_found"), "models": pr.get("models"),
                "sample": (out or "")[:40], "note": note}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


PREVIEW_DIR = PUBLIC / "voice-preview"
PREVIEW_TEXT = "这是一段试听,用来判断这个音色合不合适。语气、语速、情绪都在这儿。"


def voice_preview(voice: str) -> dict:
    """合成一句样音给用户试听。

    Edge TTS 是网络合成,一次要一两秒;同一个音色缓存成文件,
    反复试听就不用每次都等。
    """
    import asyncio
    import hashlib

    voice = (voice or "").strip()
    if not voice:
        return {"error": "没有指定音色"}
    key = hashlib.sha256((voice + "|" + PREVIEW_TEXT).encode("utf-8")).hexdigest()[:12]
    voices = json.loads((TOOLS / "voices.json").read_text(encoding="utf-8"))
    if voice not in {row["id"] for row in voices}:
        return {"error": "请选择列表中的音色"}
    mp3 = PREVIEW_DIR / f"{key}.mp3"
    try:
        with PREVIEW_LOCK:
            if not mp3.exists():
                import edge_tts  # noqa: WPS433

                PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
                tmp = mp3.with_suffix(".tmp.mp3")
                asyncio.run(edge_tts.Communicate(PREVIEW_TEXT, voice).save(str(tmp)))
                tmp.replace(mp3)
    except Exception as e:  # noqa: BLE001
        return {"error": f"试听合成失败:{type(e).__name__}: {redact(str(e))[:160]}"}
    return {"ok": True, "url": f"/voice-preview/{mp3.name}", "voice": voice,
            "text": PREVIEW_TEXT}


def find_video(meta: dict) -> dict:
    """成片可能在 final/(归档后)或 remotion-composer/out/(渲染后)。"""
    title, slug = meta.get("title", ""), meta.get("slug", "")
    out = ROUT / f"{slug}.mp4"
    if FINAL.exists():
        hits = sorted(FINAL.glob(f"*{title}*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
        if hits:
            v = hits[0]
            # 封面是 ship 时按「-风格中文名-封面.png」写出来的。中文名随风格变
            # (粗描边贴纸科普 / 电影感 / 孟菲斯…),不能写死某一种。
            base = re.sub(r"-mg-[A-Za-z0-9_-]+$", "", v.stem)
            cov = v.with_name(base + "-封面.png")
            if not cov.exists():
                near = sorted(v.parent.glob(base + "-*封面.png"),
                              key=lambda p: p.stat().st_mtime, reverse=True)
                cov = near[0] if near else cov
            return {"video": f"/media/final/{v.name}", "video_path": str(v),
                    "cover": f"/media/final/{cov.name}" if cov.exists() else "",
                    "cover_path": str(cov) if cov.exists() else ""}
    if out.exists():
        return {"video": f"/media/out/{out.name}", "video_path": str(out),
                "cover": "", "cover_path": ""}
    return {"video": "", "video_path": "", "cover": "", "cover_path": ""}


def review_info(p: Path) -> dict | None:
    f = p / "out" / "review" / "review-evidence.json"
    if not f.exists():
        return None
    try:
        e = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(e, dict):
        return {"verdict": "INCOMPLETE", "issues": ["评审证据格式无效，请重新评审。"]}
    required = ("dead_spans", "black_frames", "silence", "hit_alignment", "objective_issues")
    complete = (all(isinstance(e.get(key), list) for key in required)
                and isinstance(e.get("spec"), dict) and bool(e["spec"].get("duration"))
                and isinstance(e.get("audio_qc"), dict) and bool(e["audio_qc"]))
    if not complete:
        return {"verdict": "INCOMPLETE", "issues": ["评审证据不完整，请重新评审；不能据此判断通过。"]}
    dead = e.get("dead_spans") or []
    black = e.get("black_frames") or []
    silent = e.get("silence") or []
    issues = e.get("objective_issues") or []
    hits = e.get("hit_alignment") or []
    return {
        "verdict": "PASS" if not (dead or black or silent or issues) else "FAIL",
        "dead": len(dead), "black": len(black), "silence": len(silent),
        "sfx": f"{sum(1 for h in hits if h.get('ok'))}/{len(hits)}",
        "lufs": e.get("audio_qc", {}).get("lufs"),
        "issues": issues,
        # 成片的**真实**时长与尺寸。目标时长只是当初的意图,成片多长要看这个。
        "actual_duration": (e.get("spec") or {}).get("duration"),
        "actual_size": [(e.get("spec") or {}).get("width"), (e.get("spec") or {}).get("height")],
    }


def project_detail(p: Path) -> dict:
    meta = project_meta(p) or {"name": p.name, "slug": p.name, "title": p.name, "style": ""}
    vname = ""
    try:
        vs = json.loads((TOOLS / "voices.json").read_text(encoding="utf-8"))
        vname = next((v["cn"] for v in vs if v["id"] == meta.get("voice")), meta.get("voice", ""))
    except Exception:
        vname = meta.get("voice", "")
    tier_zh = ""
    try:
        rows = json.loads((TOOLS / "quality.json").read_text(encoding="utf-8"))["tiers"]
        tier_zh = (rows.get(meta.get("tier") or "standard") or {}).get("zh", "")
    except Exception:
        pass
    d = {
        "name": p.name, "title": meta.get("title", p.name), "slug": meta.get("slug", p.name),
        "style": meta.get("style", ""), "voice_mode": meta.get("voice_mode", ""),
        "duration": meta.get("duration", ""), "ratio": meta.get("ratio", "9:16"),
        "resolution": meta.get("resolution", "1080p"), "fps": meta.get("fps", 30),
        "voice": meta.get("voice", ""), "voice_cn": vname,
        "tier": meta.get("tier", ""), "tier_zh": tier_zh,
        "tier_review": meta.get("tier_review") or {},
        "scene": meta.get("scene") or {},
        "review": review_info(p), "files": {},
    }
    d.update(find_video(meta))
    preview = ROUT / f"{meta.get('slug', p.name)}-预览.mp4"
    d["preview"] = f"/media/out/{preview.name}" if preview.is_file() else ""
    if meta.get("mode") == "edit":
        ed = p / "edit_decisions.json"
        if ed.is_file():
            try:
                doc = json.loads(ed.read_text(encoding="utf-8"))
                d["edit"] = {"total": doc.get("total"), "cuts": len(doc.get("cuts") or []),
                             "mode": doc.get("mode")}
                d["files"]["edit_decisions.json"] = ed.read_text(encoding="utf-8")
            except Exception:
                pass
        ev = p / "out" / f"{p.name}-剪辑预览.mp4"
        if ev.is_file():
            d["preview"] = f"/media/project/{p.name}/out/{ev.name}"
        return d
    for k in ("script.json", "film.json", "timing.json"):
        f = p / k
        if f.exists():
            d["files"][k] = f.read_text(encoding="utf-8")
    rep = p / "REPORT.md"
    if rep.exists():
        d["report"] = f"/media/project/{p.name}/REPORT.md"
    return d


def _stage_marker(text: str) -> dict | None:
    """识别子进程打印的阶段标记行 {"stage":…}。

    只认这一个形状:必须是可解析的 JSON、且恰好含 stage 键、且 stage 是
    非空字符串。普通的日志行(中文、命令回显、ffmpeg 输出)都不匹配。
    """
    line = text.strip()
    if not line.startswith("{") or '"stage"' not in line:
        return None
    try:
        data = json.loads(line)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("stage")
    if not isinstance(name, str) or not name.strip():
        return None
    note = data.get("note")
    return {"name": name.strip()[:40], "note": str(note or "")[:80]}


def run_task(project: str, argv: list[str], label: str, *, script: str = "film.py") -> str:
    """script 默认 film.py(生成类);剪辑模式传 edit_mode.py,阶段追踪不变。"""
    tid = uuid.uuid4().hex[:10]
    task = {"id": tid, "project": project, "label": label, "status": "running",
            "logs": [], "rc": None, "started": time.time(), "ended": None,
            # 阶段轨迹:由子进程打印的 {"stage":…} 行累积而来,每一项都对应
            # 一次真实发生的工作,不是前端编出来的进度条。
            "stages": [], "stage": None}
    with LOCK:
        TASKS[tid] = task

    def worker():
        # 生成类默认走 FILM(可被测试/patch 替换);只有剪辑模式显式传
        # script="edit_mode.py" 时才换成同目录的另一个入口。
        runner = FILM if script == "film.py" else TOOLS / script
        cmd = [str(PY), str(runner), *argv]
        child_env = dict(os.environ)
        child_env.update(_read_env())
        task["logs"].append("$ " + redact(" ".join(cmd)))
        try:
            proc = subprocess.Popen(cmd, cwd=str(REPO), env=child_env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                    errors="replace", creationflags=NO_WINDOW)
            assert proc.stdout is not None
            for line in proc.stdout:
                text = line.rstrip("\n")
                stage = _stage_marker(text)
                if stage:
                    # 一键出片会调用各子命令,同一个阶段可能被报告两次
                    # (make 报告一次、子命令再报告一次)。同名相邻的只保留一条,
                    # 阶段轨迹里出现「配音、配音」会让进度看起来是坏的。
                    previous = task["stages"][-1]["name"] if task["stages"] else None
                    if previous != stage["name"]:
                        task["stages"].append({**stage, "at": round(time.time() - task["started"], 1)})
                        if len(task["stages"]) > 200:
                            del task["stages"][:-200]
                    task["stage"] = stage
                    continue  # 标记行不进入日志:它是结构化数据,不是给人读的正文
                task["logs"].append(redact(text))
                if len(task["logs"]) > 4000:
                    task["logs"] = task["logs"][-3000:]
            task["rc"] = proc.wait()
        except Exception as e:  # noqa: BLE001
            task["logs"].append(f"! {type(e).__name__}: {e}")
            task["rc"] = -1
        task["status"] = "done" if task["rc"] == 0 else "failed"
        task["ended"] = time.time()
        p = PROJECTS / project
        if p.exists():
            task["detail"] = project_detail(p)

    threading.Thread(target=worker, daemon=True).start()
    return tid


def new_project(project: str, title: str, style: str, panel: dict | None = None) -> None:
    p = PROJECTS / project
    if p.exists():
        # 已存在:把面板参数写回去(用户中途改了设置)
        if panel:
            try:
                m = json.loads((p / "project.json").read_text(encoding="utf-8"))
                m.update({"duration": panel.get("duration", m.get("duration")),
                          "ratio": panel.get("ratio", m.get("ratio")),
                          "voice": panel.get("voice", m.get("voice")),
                          "resolution": panel.get("resolution", m.get("resolution")),
                          "fps": panel.get("fps", m.get("fps")),
                          "tier": panel.get("tier", m.get("tier")),
                          "narration": panel.get("narration", m.get("narration")),
                          "video_type": panel.get("type", m.get("video_type"))})
                (p / "project.json").write_text(json.dumps(m, ensure_ascii=False, indent=2),
                                                encoding="utf-8")
            except Exception:
                pass
        return
    cmd = [str(PY), str(FILM), "new", "--name", project, "--style", style, "--title", title, "--force"]
    if panel:
        cmd += ["--duration", str(panel.get("duration", 30)),
                "--ratio", str(panel.get("ratio", "9:16")),
                "--voice", str(panel.get("voice", "zh-CN-YunjianNeural")),
                "--type", str(panel.get("type", "explain")),
                "--narration", str(panel.get("narration", "voice")),
                "--resolution", str(panel.get("resolution", "1080p")),
                "--fps", str(panel.get("fps", 30)),
                "--tier", str(panel.get("tier", "standard"))]
    subprocess.run(cmd, cwd=str(REPO), check=True,
                   capture_output=True, text=True, encoding="utf-8", errors="replace",
                   creationflags=NO_WINDOW)


# ───────────────────────────── HTTP ─────────────────────────────
class Handler(BaseHTTPRequestHandler):
    server_version = "FilmFactory/1.0"

    def log_message(self, fmt, *args):  # 安静一点
        pass

    def _json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _authorized(self, bootstrap=False):
        host = self.headers.get("Host", "")
        expected = f"127.0.0.1:{self.server.server_port}"
        if host not in (expected, f"localhost:{self.server.server_port}"):
            jsonresp(self, {"error": "无效的本机服务地址"}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://{expected}", f"http://localhost:{self.server.server_port}"):
            jsonresp(self, {"error": "仅允许客户端同源访问"}, 403)
            return False
        if not UI_TOKEN:
            return True
        if bootstrap:
            token = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
            if hmac.compare_digest(token, UI_TOKEN):
                self.send_response(303)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", f"film_session={UI_TOKEN}; HttpOnly; SameSite=Strict; Path=/")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return False
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            value = cookie["film_session"].value if "film_session" in cookie else ""
        except Exception:
            value = ""
        bearer = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if hmac.compare_digest(value, UI_TOKEN) or hmac.compare_digest(bearer, UI_TOKEN):
            return True
        jsonresp(self, {"error": "客户端会话已失效，请重新打开应用"}, 403)
        return False

    def do_GET(self):  # noqa: N802
        try:
            if self._authorized(bootstrap=urlparse(self.path).path == "/"):
                return self._get()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            return jsonresp(self, {"error": redact(f"界面数据加载失败: {type(exc).__name__}: {exc}")}, 500)

    def _get(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/api/health":
            return jsonresp(self, {"api_version": API_VERSION, "version": APP_VERSION,
                "active_tasks": sum(t["status"] == "running" for t in TASKS.values())})
        if u.path in ("/ui/film_ui.css", "/ui/film_ui.js", "/ui/style_preview_player.js",
                      "/ui/film_ui_edit.js"):
            file = TOOLS / u.path.rsplit("/", 1)[1]
            raw = file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8" if file.suffix == ".css" else "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)
            return
        if u.path in ("/", "/index.html"):
            raw = HTML.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if u.path == "/api/voice-preview":
            q = parse_qs(u.query)
            return jsonresp(self, voice_preview((q.get("voice") or [""])[0]))

        if u.path.startswith("/voice-preview/"):
            # 试听音频存在 Remotion 的 public/voice-preview 下,走同一套静态服务
            return self._media("voice-preview/" + u.path[len("/voice-preview/"):])

        if u.path == "/api/styles":
            cat = json.loads((TOOLS / "film_styles.json").read_text(encoding="utf-8"))
            return jsonresp(self, cat)
        if u.path == "/api/qualities":
            import quality as qc
            return jsonresp(self, {
                "resolutions": list(qc.RESOLUTIONS.values()),
                "fps": list(qc.FPS_CHOICES.values()),
                "tiers": list(qc.TIERS.values()),
                "default_tier": qc.DEFAULT_TIER,
                "max_duration": qc.MAX_DURATION,
                "min_duration": qc.MIN_DURATION,
            })

        if u.path == "/api/presets":
            def _load(name):
                f = TOOLS / name
                return json.loads(f.read_text(encoding="utf-8"))
            # 前端要的是数组;视频类型/比例在 JSON 里是以 id 为键的字典。
            # 这里统一摊平成数组(带 id),否则前端第一行 .map 就抛,
            # 整个参数面板(时长/比例/音色/类型)都渲染不出来。
            types = _load("video_types.json")
            ratios = _load("ratios.json")
            type_rows = [dict(v, id=k) for k, v in (types or {}).items()] if isinstance(types, dict) else list(types or [])
            ratio_rows = [dict(v, id=k) for k, v in (ratios or {}).items()] if isinstance(ratios, dict) else list(ratios or [])
            voices = _load("voices.json")
            voice_rows = list(voices or []) if isinstance(voices, list) else [dict(v, id=k) for k, v in (voices or {}).items()]
            import quality as qc
            return jsonresp(self, {
                "types": type_rows,
                "voices": voice_rows,
                "ratios": ratio_rows,
                "resolutions": list(qc.RESOLUTIONS.values()),
                "fps": list(qc.FPS_CHOICES.values()),
                "tiers": list(qc.TIERS.values()),
                "default_tier": qc.DEFAULT_TIER,
                "max_duration": qc.MAX_DURATION,
                "min_duration": qc.MIN_DURATION,
            })
        if u.path == "/api/settings":
            return jsonresp(self, read_settings())
        if u.path == "/api/projects":
            rows = []
            if PROJECTS.exists():
                for p in PROJECTS.iterdir():
                    if p.is_dir() and project_meta(p):
                        d = project_detail(p)
                        rows.append({k: d[k] for k in ("name", "title", "style", "video", "cover", "review", "voice_mode")})
            rows.sort(key=lambda r: (PROJECTS / r["name"]).stat().st_mtime, reverse=True)
            return jsonresp(self, {"projects": rows})
        if u.path == "/api/project":
            name = (q.get("name") or [""])[0]
            p = PROJECTS / safe_name(name)
            if not p.exists():
                return jsonresp(self, {"error": "项目不存在"}, 404)
            return jsonresp(self, project_detail(p))
        if u.path == "/api/task":
            tid = (q.get("id") or [""])[0]
            t = TASKS.get(tid)
            if not t:
                return jsonresp(self, {"error": "任务不存在"}, 404)
            return jsonresp(self, t)
        if u.path == "/api/edit/library":
            import material_library as ml  # noqa: WPS433
            return jsonresp(self, ml.assets(offset=int((q.get("offset") or [0])[0]),
                                           limit=min(200, int((q.get("limit") or [60])[0]))))
        if u.path == "/api/edit/status":
            import material_library as ml  # noqa: WPS433
            return jsonresp(self, ml.check_status())
        if u.path == "/api/edit/scan":
            import material_library as ml  # noqa: WPS433
            job = ml.job((q.get("id") or [""])[0])
            return jsonresp(self, job or {"error": "任务不存在"}, 404 if not job else 200)
        if u.path == "/api/edit/search":
            import material_library as ml  # noqa: WPS433
            return jsonresp(self, {"items": ml.search((q.get("q") or [""])[0],
                                                     limit=min(30, int((q.get("limit") or [12])[0])))})
        if u.path == "/api/edit/doc":
            name = safe_name((q.get("project") or [""])[0])
            f = PROJECTS / name / "edit_decisions.json"
            if not f.is_file():
                return jsonresp(self, {"doc": None})
            return jsonresp(self, {"doc": json.loads(f.read_text(encoding="utf-8"))})
        if u.path == "/api/edit/video":
            name = safe_name((q.get("project") or [""])[0])
            p = PROJECTS / name
            hits = []
            for pat in ("*剪辑预览.mp4", f"{name}.mp4"):
                hits += list((p / "out").glob(pat)) if (p / "out").exists() else []
            if not hits:
                return jsonresp(self, {"error": "还没有剪辑成片"}, 404)
            v = max(hits, key=lambda f: f.stat().st_mtime)
            return jsonresp(self, {"url": f"/media/project/{name}/out/{v.name}"})
        if u.path.startswith("/media/"):
            return self._media(u.path[len("/media/"):])
        # 顶层静态资源(风格样张):/styles/mg-paperclip.png → public/styles/...
        if u.path.startswith("/styles/"):
            return self._media("styles" + u.path[len("/styles"):])
        return jsonresp(self, {"error": "not found"}, 404)

    def _media(self, rel: str):
        # 中文文件名走 URL 时是百分号编码的,必须先解码
        rel = unquote(rel).replace("\\", "/").strip("/")
        parts = [x for x in rel.split("/") if x and x not in (".", "..")]
        if not parts:
            return jsonresp(self, {"error": "bad path"}, 400)
        root = parts[0]
        if root == "final":
            base, rest = FINAL, parts[1:]
        elif root == "out":
            base, rest = ROUT, parts[1:]
        elif root == "project" and len(parts) >= 2:
            base, rest = PROJECTS / safe_name(parts[1]), parts[2:]
        elif root == "styles":
            # The catalog is a versioned app asset, not a user's generated film.
            # Read installed samples directly so an existing workspace never
            # pins stale posters or misses newly shipped preview videos.
            base, rest = REPO / "remotion-composer" / "public" / "styles", parts[1:]
        elif root == "voice-preview":
            base, rest = PREVIEW_DIR, parts[1:]
        elif root == "library":
            # 素材库缩略图是本地可再生缓存,只按 asset_id 目录放行。
            import material_library as ml  # noqa: WPS433
            base, rest = ml.thumbs_root(), parts[1:]
        else:
            return jsonresp(self, {"error": "bad path"}, 400)
        f = base.joinpath(*rest)
        try:
            f.resolve().relative_to(base.resolve())
        except Exception:
            return jsonresp(self, {"error": "bad path"}, 400)
        if not f.is_file():
            return jsonresp(self, {"error": "not found"}, 404)
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if f.suffix.lower() == ".md":
            ctype = "text/plain; charset=utf-8"
        size = f.stat().st_size
        # 视频必须支持 Range,否则浏览器里拖不动进度条
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        partial = False
        if rng and rng.startswith("bytes="):
            try:
                a, _, b = rng[len("bytes="):].partition("-")
                if a:
                    start = int(a)
                    end = int(b) if b else size - 1
                elif b:
                    start = max(0, size - int(b))
                start = max(0, min(start, size - 1))
                end = max(start, min(end, size - 1))
                partial = True
            except Exception:
                partial = False
        length = end - start + 1
        with f.open("rb") as fh:
            fh.seek(start)
            data = fh.read(length)
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):  # noqa: N802
        try:
            if self._authorized():
                with SETTINGS_LOCK:
                    return self._post()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except ValueError as exc:
            return jsonresp(self, {"error": redact(str(exc))}, 400)
        except Exception as exc:
            return jsonresp(self, {"error": redact(f"操作失败: {type(exc).__name__}: {exc}")}, 500)

    def _post(self):
        u = urlparse(self.path)
        try:
            body = self._json_body()
        except Exception:
            return jsonresp(self, {"error": "bad json"}, 400)

        if u.path == "/api/parse":
            url = (body.get("url") or "").strip()
            if not url:
                return jsonresp(self, {"error": "没给链接"}, 400)
            try:
                sys.path.insert(0, str(TOOLS))
                import fetch_source  # noqa: WPS433
                r = fetch_source.fetch(url)
            except Exception as e:  # noqa: BLE001
                return jsonresp(self, {"error": str(e)[:300]}, 400)
            return jsonresp(self, {"ok": True, "title": r.get("title", ""),
                                  "text": r.get("text", ""), "platform": r.get("platform", ""),
                                  "chars": len(r.get("text", ""))})

        if u.path == "/api/settings":
            return jsonresp(self, write_settings(
                (body.get("base") or "").strip(),
                (body.get("key") or "").strip(),
                (body.get("model") or "").strip(),
            ))
        if u.path == "/api/settings/test":
            return jsonresp(self, test_llm(
                (body.get("base") or "").strip(),
                (body.get("key") or "").strip(),
                (body.get("model") or "").strip()))

        if u.path == "/api/make":
            title = (body.get("title") or "").strip() or "未命名短片"
            style = body.get("style") or "mg-paperclip"
            project = safe_name(body.get("project") or f"film-{datetime.now():%m%d-%H%M%S}")
            source = body.get("source") or ""
            audio = body.get("audio") or None
            narration = body.get("narration") or "voice"
            if narration not in ("voice", "silent"):
                raise ValueError("请选择有口播或无口播")
            if narration == "silent":
                audio = None
            import quality as qc
            duration = float(body.get("duration") or 30)
            if not 1 <= duration <= 120 or not duration.is_integer():
                raise ValueError("时长请输入 1–120 的整数秒")
            from film import resolve_ratio
            resolve_ratio(body.get("ratio") or "9:16")
            res = body.get("resolution") or qc.DEFAULT_RESOLUTION
            if res not in qc.RESOLUTIONS:
                res = qc.DEFAULT_RESOLUTION
            try:
                fps = int(body.get("fps") or qc.DEFAULT_FPS)
            except (TypeError, ValueError):
                fps = int(qc.DEFAULT_FPS)
            if str(fps) not in qc.FPS_CHOICES:
                fps = int(qc.DEFAULT_FPS)
            tier = body.get("tier") or qc.DEFAULT_TIER
            if tier not in qc.TIERS:
                tier = qc.DEFAULT_TIER
            panel = {
                "duration": int(qc.clamp_duration(body.get("duration") or 30)),
                "ratio": body.get("ratio") or "9:16",
                "voice": body.get("voice") or "zh-CN-YunjianNeural",
                "type": body.get("video_type") or "explain",
                "narration": (body.get("narration") or "voice"),
                "resolution": res,
                "fps": fps,
                "tier": tier,
            }
            try:
                new_project(project, title, style, panel)
            except subprocess.CalledProcessError as e:
                return jsonresp(self, {"error": f"建项目失败: {e.stderr or e}"}, 500)
            p = PROJECTS / project
            args = ["make", "--project", project,
                    "--duration", str(panel.get("duration", 30)),
                    "--ratio", str(panel.get("ratio", "9:16")),
                    "--voice", str(panel.get("voice", "zh-CN-YunjianNeural")),
                    "--type", str(panel.get("type", "explain")),
                    "--narration", str(panel.get("narration", "voice")),
                    "--resolution", str(panel.get("resolution", qc.DEFAULT_RESOLUTION)),
                    "--fps", str(panel.get("fps", qc.DEFAULT_FPS)),
                    "--tier", str(panel.get("tier", qc.DEFAULT_TIER))]
            if source.strip():
                sp = p / "source.txt"
                sp.write_text(source, encoding="utf-8")
                args += ["--source", str(sp)]
            elif not body.get("force_empty"):
                # 没有素材也没稿子:不要闷头渲一条占位片骗人
                try:
                    scr = json.loads((p / "script.json").read_text(encoding="utf-8"))
                    empty = any(not s.get("text") for s in scr.get("segments", []))
                except Exception:
                    empty = True
                if empty:
                    return jsonresp(self, {"error":
                        "还没有内容可讲。请在上面的素材框里贴一段文字,"
                        "或到「设置」里配置模型让它帮你写稿。"}, 400)
            if body.get("offline"):
                args += ["--offline"]
            if audio and audio.get("b64"):
                try:
                    raw = base64.b64decode(audio["b64"].split(",")[-1])
                except Exception:
                    return jsonresp(self, {"error": "音频解码失败"}, 400)
                if len(raw) > 60 * 1024 * 1024:
                    return jsonresp(self, {"error": "音频超过 60MB"}, 400)
                up = p / "out" / "uploads"
                up.mkdir(parents=True, exist_ok=True)
                ap = up / safe_name(audio.get("name") or "voice.wav")
                ap.write_bytes(raw)
                args += ["--audio", str(ap)]
            tid = run_task(project, args, "生成短片")
            return jsonresp(self, {"task": tid, "project": project})

        if u.path == "/api/action":
            project = safe_name(body.get("project") or "")
            p = PROJECTS / project
            if not p.exists():
                return jsonresp(self, {"error": "项目不存在"}, 404)
            action = body.get("action")
            if action == "voice":
                args = ["voice", "--project", project]
            elif action == "build":
                args = ["build", "--project", project]
            elif action == "render":
                args = ["render", "--project", project]
            elif action == "stills":
                args = ["render", "--project", project, "--stills", body.get("times") or "1.5,8,15"]
            elif action == "preview":
                args = ["render", "--project", project, "--preview"]
            elif action == "check":
                # 「重新评审」要的是结论,不是命令出错:FAIL 也是有效结果,
                # 所以走 report-only,让任务显示「已完成 + FAIL」并列出客观问题。
                args = ["check", "--project", project, "--report-only"]
            elif action == "ship":
                args = ["ship", "--project", project]
            else:
                return jsonresp(self, {"error": "未知操作"}, 400)
            tid = run_task(project, args, action)
            return jsonresp(self, {"task": tid})

        # ───────────── 剪辑模式 ─────────────
        if u.path == "/api/edit/register":
            import material_library as ml  # noqa: WPS433
            paths = body.get("paths") or []
            if not isinstance(paths, list) or not paths:
                return jsonresp(self, {"error": "请给出素材文件或文件夹路径"}, 400)
            for s in paths:
                if not isinstance(s, str) or len(s) > 4096:
                    return jsonresp(self, {"error": "路径格式不合法"}, 400)
            jid = ml.start_scan(paths, tag=str(body.get("tag") or "")[:200],
                                asr=bool(body.get("asr")))
            return jsonresp(self, {"task": jid})

        if u.path == "/api/edit/relocate":
            import material_library as ml  # noqa: WPS433
            try:
                return jsonresp(self, ml.relocate(str(body.get("old") or ""),
                                                  str(body.get("new") or "")))
            except ValueError as e:
                return jsonresp(self, {"error": str(e)}, 400)

        if u.path == "/api/edit/remove":
            import material_library as ml  # noqa: WPS433
            return jsonresp(self, ml.remove(safe_name(str(body.get("id") or ""))))

        if u.path == "/api/edit/tags":
            import material_library as ml  # noqa: WPS433
            return jsonresp(self, ml.set_tags(safe_name(str(body.get("id") or "")),
                                             str(body.get("tags") or "")[:500]))

        if u.path == "/api/edit/understand":
            import material_library as ml  # noqa: WPS433
            try:
                return jsonresp(self, ml.understand_asset(
                    safe_name(str(body.get("id") or "")), force=bool(body.get("force"))))
            except (ValueError, RuntimeError) as e:
                return jsonresp(self, {"error": str(e)}, 400)

        if u.path == "/api/edit/plan":
            project = safe_name(body.get("project") or f"edit-{datetime.now():%m%d-%H%M%S}")
            p = PROJECTS / project
            p.mkdir(parents=True, exist_ok=True)
            (p / "project.json").write_text(json.dumps({
                "name": project, "slug": project,
                "title": str(body.get("title") or "剪辑短片")[:160],
                "style": "edit-mode", "mode": "edit", "duration": float(body.get("duration") or 15),
                "ratio": "9:16", "resolution": "1080p", "fps": 30,
                "created": datetime.now().isoformat(timespec="seconds"),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            args = ["plan", "--project", project,
                    "--requirement", str(body.get("requirement") or "")[:2000],
                    "--duration", str(float(body.get("duration") or 15)),
                    "--width", str(int(body.get("width") or 1080)),
                    "--height", str(int(body.get("height") or 1920)),
                    "--fps", str(int(body.get("fps") or 30))]
            if not body.get("allow_web", True):
                args.append("--no-web")
            tid = run_task(project, args, "锁定素材", script="edit_mode.py")
            return jsonresp(self, {"task": tid, "project": project})

        if u.path == "/api/edit/save":
            project = safe_name(body.get("project") or "")
            p = PROJECTS / project
            if not p.exists():
                return jsonresp(self, {"error": "项目不存在"}, 404)
            doc = body.get("doc")
            if not isinstance(doc, dict):
                return jsonresp(self, {"error": "doc 必须是对象"}, 400)
            try:
                from edit_contract import validate  # noqa: WPS433
                import material_library as ml  # noqa: WPS433
                validate(doc, asset_paths=ml.asset_map())
            except ValueError as e:
                return jsonresp(self, {"error": f"时间轴不合法: {e}"}, 400)
            (p / "edit_decisions.json").write_text(
                json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            return jsonresp(self, {"ok": True})

        if u.path == "/api/edit/render":
            project = safe_name(body.get("project") or "")
            p = PROJECTS / project
            if not p.exists():
                return jsonresp(self, {"error": "项目不存在"}, 404)
            args = ["render", "--project", project]
            if body.get("preview"):
                args.append("--preview")
            tid = run_task(project, args, "剪辑预览" if body.get("preview") else "剪辑成片",
                           script="edit_mode.py")
            return jsonresp(self, {"task": tid, "project": project})

        if u.path == "/api/save":
            project = safe_name(body.get("project") or "")
            p = PROJECTS / project
            if not p.exists():
                return jsonresp(self, {"error": "项目不存在"}, 404)
            for key, fname in (("script", "script.json"), ("film", "film.json")):
                txt = body.get(key)
                if txt:
                    try:
                        json.loads(txt)
                    except Exception as e:
                        return jsonresp(self, {"error": f"{fname} 不是合法 JSON: {e}"}, 400)
                    (p / fname).write_text(txt, encoding="utf-8")
            return jsonresp(self, {"ok": True})

        return jsonresp(self, {"error": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--ready-file", default=os.environ.get("OE_READY_FILE", ""))
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    PROJECTS.mkdir(parents=True, exist_ok=True)
    FINAL.mkdir(parents=True, exist_ok=True)
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    except OSError:
        print("本机端口不可用，请关闭重复实例或重新启动客户端")
        return 2
    port = srv.server_port
    if a.ready_file:
        ready = Path(a.ready_file)
        ready.parent.mkdir(parents=True, exist_ok=True)
        temp = ready.with_suffix(".tmp")
        temp.write_text(json.dumps({"port": port, "pid": os.getpid(),
            "api_version": API_VERSION, "version": APP_VERSION}), encoding="utf-8")
        temp.replace(ready)
    url = f"http://127.0.0.1:{port}"
    print(f"短片工厂已启动: {url}")
    print("按 Ctrl+C 停止。")
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        srv.server_close()
        if a.ready_file:
            Path(a.ready_file).unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())