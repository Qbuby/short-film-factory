"""Private EdgeChromium host. No exposed Python JS API, browser fallback or installs.

Readiness: backend atomically writes {port,pid,api_version,version} after binding
127.0.0.1:0. /api/health must match the shared release/protocol and expose an
integer active_tasks. Only the owned service process tree is ever terminated.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

try:
    from .app_paths import AppPaths, get_paths, prepare_workspace
    from .app_version import API_VERSION, APP_NAME, APP_VERSION
except ImportError:
    from app_paths import AppPaths, get_paths, prepare_workspace
    from app_version import API_VERSION, APP_NAME, APP_VERSION


class StartupError(RuntimeError):
    """Safe, user-displayable error; never include request URLs or child output."""


def lifecycle_logger(directory: Path) -> logging.Logger:
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("shortfilm.desktop")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(directory / "desktop.log", maxBytes=256_000,
                                      backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
    return logger


def show_error(message: str, log_path: Path | None = None) -> None:
    text = message + (f"\n\n启动日志: {log_path}" if log_path else "")
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(0, text, APP_NAME, 0x10)
    elif sys.stderr:
        print(text, file=sys.stderr)


def validate_health(value: object) -> dict:
    if not isinstance(value, dict):
        raise StartupError("服务健康检查格式不正确。")
    if (type(value.get("api_version")) is not int or value["api_version"] != API_VERSION
            or value.get("version") != APP_VERSION):
        raise StartupError(f"桌面与服务版本不一致,请修复安装 (需要 {APP_VERSION} / API {API_VERSION})。")
    tasks = value.get("active_tasks")
    if type(tasks) is not int or tasks < 0:
        raise StartupError("服务未提供有效的运行任务数量。")
    return value


def read_ready(path: Path, pid: int) -> int | None:
    try:
        with path.open("rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise StartupError("服务就绪文件过大。")
        value = json.loads(raw)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(value, dict):
        raise StartupError("服务就绪文件格式错误。")
    if type(value.get("pid")) is not int or value["pid"] != pid:
        raise StartupError("服务就绪文件进程不匹配。")
    if type(value.get("api_version")) is not int or value["api_version"] != API_VERSION or value.get("version") != APP_VERSION:
        raise StartupError("服务就绪版本与桌面版本不匹配。")
    port = value.get("port")
    if type(port) is not int or not 1 <= port <= 65535:
        raise StartupError("服务未报告实际绑定端口。")
    return port


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise StartupError("服务健康检查不允许重定向。")


def fetch_health(port: int, token: str) -> dict:
    request = Request(f"http://127.0.0.1:{port}/api/health",
                      headers={"Authorization": f"Bearer {token}"})
    # Ignore system proxies; never leak the internal token to a proxy/redirect.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=1.0) as response:
        raw = response.read(16385)
        if len(raw) > 16384:
            raise StartupError("服务健康检查响应过大。")
        try:
            return validate_health(json.loads(raw))
        except (ValueError, UnicodeDecodeError) as exc:
            raise StartupError("服务健康检查响应格式错误。") from exc


def wait_ready(process, ready_file: Path, token: str, timeout: float = 45.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise StartupError("本地服务在启动期间退出,请检查安装是否完整。")
        port = read_ready(ready_file, process.pid)
        if port is not None:
            try:
                fetch_health(port, token)
                return port
            except StartupError:
                raise
            except OSError:
                pass
        time.sleep(0.1)
    raise StartupError("本地服务启动超时,请重试或修复安装。")


def child_environment(paths: AppPaths, ready_file: Path, token: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(OE_DESKTOP="1", OE_WORKSPACE=str(paths.workspace), OE_CONFIG=str(paths.config),
               OE_READY_FILE=str(ready_file), OE_UI_TOKEN=token, OE_REPO=str(paths.repo),
               OE_APP_ROOT=str(paths.repo), OE_RUNTIME=str(paths.repo / "runtime"),
               PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    # Prevent PyInstaller's bootloader environment contaminating ordinary Python.
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    runtime = paths.repo / "runtime"
    if (runtime / "bin").is_dir():
        env["PATH"] = str(runtime / "bin") + os.pathsep + env.get("PATH", "")
    if (runtime / "node" / "node.exe").is_file():
        env["OE_NODE_DIR"] = str(runtime / "node")
    return env


class WindowsJob:
    """Kill-on-close Job Object; assignment occurs before the backend can run."""
    def __init__(self):
        from ctypes import wintypes as wt
        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                        ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wt.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wt.DWORD), ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                         "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wt.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
        self.kernel.CloseHandle.argtypes = [wt.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise StartupError("无法创建受管服务进程。")
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.close()
            raise StartupError("无法设置服务进程清理策略。")

    def assign(self, process) -> None:
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise StartupError("无法隔离服务进程;已取消启动,不会结束其它进程。")

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class OwnedService:
    def __init__(self, python: Path, paths: AppPaths, ready_file: Path, token: str):
        self.process = None
        self.job = WindowsJob() if os.name == "nt" else None
        script = paths.tools / "film_ui.py"
        # The stdin gate prevents a service from spawning descendants before it
        # belongs to our job. No PID search, taskkill, port kill or global cleanup.
        bootstrap = (
            "import sys,runpy;"
            "assert sys.stdin.buffer.read(1)==b'1';"
            "sys.path.insert(0,sys.argv[1]);"
            "script=sys.argv[2];sys.argv=sys.argv[2:];"
            "runpy.run_path(script,run_name='__main__')"
        )
        try:
            self.process = subprocess.Popen(
                [str(python), "-I", "-c", bootstrap, str(paths.tools), str(script),
                 "--port", "0", "--no-browser", "--ready-file", str(ready_file)],
                cwd=str(paths.workspace), env=child_environment(paths, ready_file, token),
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            if self.job:
                self.job.assign(self.process)
            self.process.stdin.write(b"1")
            self.process.stdin.flush()
            self.process.stdin.close()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self.job:
            self.job.close()  # Closes only our explicitly assigned process tree.
        elif self.process and self.process.poll() is None:
            import signal
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if self.process:
            try:
                self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                if self.job is None and os.name != "nt":
                    import signal
                    try:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    # If assignment failed, the gated child has no descendants.
                    self.process.kill()
                self.process.wait(timeout=4)


class SingleInstance:
    """Per-user/session named mutex and activation event; no public HTTP bridge."""
    def __init__(self, data_root: Path):
        from ctypes import wintypes as wt
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
        self.kernel.CreateMutexW.restype = wt.HANDLE
        self.kernel.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
        self.kernel.CreateEventW.restype = wt.HANDLE
        self.kernel.OpenEventW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
        self.kernel.OpenEventW.restype = wt.HANDLE
        self.kernel.SetEvent.argtypes = [wt.HANDLE]
        self.kernel.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
        self.kernel.CloseHandle.argtypes = [wt.HANDLE]
        suffix = hashlib.sha256(str(data_root).casefold().encode()).hexdigest()[:24]
        name = "Local\\ShortFilmFactory-" + suffix
        self.mutex = self.kernel.CreateMutexW(None, False, name)
        if not self.mutex:
            raise StartupError("无法检查桌面程序实例。")
        self.primary = ctypes.get_last_error() != 183
        self.event = None
        self.stopped = threading.Event()
        self.thread = None
        if self.primary:
            self.event = self.kernel.CreateEventW(None, False, False, name + "-activate")
            if not self.event:
                self.close()
                raise StartupError("无法创建窗口激活事件。")
        else:
            for _ in range(50):
                handle = self.kernel.OpenEventW(2, False, name + "-activate")
                if handle:
                    self.kernel.SetEvent(handle)
                    self.kernel.CloseHandle(handle)
                    break
                time.sleep(0.1)
            else:
                self.close()
                raise StartupError("已有实例仍在启动,请稍后重试。")

    def listen(self, activate) -> None:
        def run():
            while not self.stopped.is_set():
                if self.kernel.WaitForSingleObject(self.event, 200) == 0:
                    activate()
        self.thread = threading.Thread(target=run, daemon=True, name="desktop-activation")
        self.thread.start()

    def close(self) -> None:
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=1)
        for name in ("event", "mutex"):
            handle = getattr(self, name, None)
            if handle:
                self.kernel.CloseHandle(handle)
                setattr(self, name, None)


def is_internal_url(url: str, port: int) -> bool:
    try:
        parsed = urlsplit(str(url))
        return (parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
                and parsed.port == port and parsed.username is None and parsed.password is None)
    except ValueError:
        return False


def guard_core_navigation(core, port: int) -> None:
    """Native WebView2 events, not JS hooks or an exposed Python API."""
    def navigating(sender, args):
        if not is_internal_url(args.Uri, port):
            args.Cancel = True
    def new_window(sender, args):
        args.Handled = True  # Never hand an external URL to the system browser.
    core.NavigationStarting += navigating
    core.NewWindowRequested += new_window
    # Keep Python delegates alive as long as the CoreWebView2 instance.
    _NATIVE_HANDLERS.append((core, navigating, new_window))


_NATIVE_HANDLERS = []


def attach_navigation_guard(window, port: int, initialized_callback) -> None:
    """Called on the UI thread before showing the initially blank WebView2."""
    def walk(control):
        if control.GetType().FullName == "Microsoft.Web.WebView2.WinForms.WebView2":
            return control
        for child in control.Controls:
            found = walk(child)
            if found is not None:
                return found
        return None
    control = walk(window.native)
    if control is None:
        raise StartupError("无法初始化 EdgeChromium 安全导航。")
    def configure():
        core = control.CoreWebView2
        guard_core_navigation(core, port)
        browser = window.native.browser
        # Replace, rather than append after, pywebview's default handlers: the
        # default download handler opens SaveFileDialog before later listeners.
        core.NewWindowRequested -= browser.on_new_window_request
        core.DownloadStarting -= browser.on_download_starting
        def download(sender, args):
            if not is_internal_url(args.DownloadOperation.Uri, port):
                args.Cancel = True
                return
            browser.on_download_starting(sender, args)
        core.DownloadStarting += download
        _NATIVE_HANDLERS.append((core, download))
        initialized_callback()

    if control.CoreWebView2 is not None:
        configure()
    else:
        def initialized(sender, args):
            if args.IsSuccess:
                configure()
        control.CoreWebView2InitializationCompleted += initialized
        _NATIVE_HANDLERS.append((control, initialized))


def run_window(webview, service: OwnedService, port: int, token: str,
               instance: SingleInstance, paths: AppPaths, logger: logging.Logger) -> None:
    runtime = paths.repo / "runtime" / "WebView2"
    packaged = (paths.repo / "runtime" / "python" / "python.exe").is_file()
    if (runtime / "msedgewebview2.exe").is_file():
        # pywebview 6.1 maps this to BrowserExecutableFolder. Validate first:
        # it would otherwise silently fall back when the folder is absent.
        webview.settings["WEBVIEW2_RUNTIME_PATH"] = str(runtime.resolve())
    elif packaged:
        raise StartupError("缺少内置 Edge WebView2 Runtime,请修复安装 (不使用系统浏览器)。")
    else:
        # Source development may use an already installed WebView2 runtime.
        webview.settings["WEBVIEW2_RUNTIME_PATH"] = None
    # Its popup handler must never open a system browser. Downloads from the
    # authenticated backend use pywebview's native SaveFileDialog.
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    webview.settings["ALLOW_DOWNLOADS"] = True
    window = webview.create_window(APP_NAME, url="about:blank", width=1280, height=840,
                                  min_size=(960, 640), js_api=None, text_select=True)
    armed = threading.Event()
    pending_activation = threading.Event()
    def activate():
        if not armed.is_set():
            pending_activation.set()
            return
        try:
            window.restore()
            window.show()
        except Exception:
            logger.warning("window activation failed")
    instance.listen(activate)

    def before_show():
        try:
            attach_navigation_guard(window, port, armed.set)
        except Exception:
            logger.error("native navigation guard failed")
            show_error("无法启用 EdgeChromium 安全导航,已取消启动。", paths.logs / "desktop.log")
            window.destroy()
            return

    def load_initial():
        # pywebview Window methods wait for its shown event. Calling load_url
        # inside before_show would deadlock the UI thread in some releases.
        if armed.wait(timeout=30):
            window.load_url(f"http://127.0.0.1:{port}/?{urlencode({'token': token})}")
            if pending_activation.is_set():
                activate()
        else:
            logger.error("native window initialization timed out")
            show_error("Edge WebView2 初始化失败或超时,请修复 Runtime 后重试。", paths.logs / "desktop.log")
            window.destroy()

    def closing():
        try:
            tasks = fetch_health(port, token)["active_tasks"]
            if tasks == 0:
                return True
            message = f"仍有 {tasks} 个任务正在运行。退出将停止任务,是否退出?"
        except Exception:
            message = "无法确认任务状态。退出会停止本程序的所有任务,是否退出?"
        # MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2: safe default is stay open.
        return ctypes.windll.user32.MessageBoxW(0, message, APP_NAME, 0x134) == 6

    window.events.before_show += before_show
    window.events.closing += closing
    stopped = threading.Event()
    def monitor():
        while not stopped.wait(0.5):
            if service.process.poll() is not None:
                logger.error("owned backend exited unexpectedly")
                show_error("本地服务意外退出。请重新启动程序。", paths.logs / "desktop.log")
                window.destroy()
                return
    thread = threading.Thread(target=monitor, daemon=True, name="desktop-backend-monitor")
    thread.start()
    try:
        storage = paths.data_root / "webview" / APP_VERSION
        storage.mkdir(parents=True, exist_ok=True)
        # Never fallback to IE/MSHTML or an ordinary browser. Private mode keeps
        # the ephemeral origin cookie out of the next run's persistent state.
        webview.start(load_initial, gui="edgechromium", debug=False, private_mode=True,
                      storage_path=str(storage))
    finally:
        stopped.set()
        thread.join(timeout=1)
        _NATIVE_HANDLERS.clear()


def main() -> int:
    instance = None
    service = None
    logger = None
    try:
        if os.name != "nt":
            raise StartupError("桌面版需要 Windows 和 Microsoft Edge WebView2 Runtime。")
        paths = get_paths()
        logger = lifecycle_logger(paths.logs)
        instance = SingleInstance(paths.data_root)
        if not instance.primary:
            return 0
        logger.info("desktop starting release=%s api=%s", APP_VERSION, API_VERSION)
        try:
            prepare_workspace(paths)
        except RuntimeError as exc:
            raise StartupError(str(exc)) from exc
        except OSError as exc:
            raise StartupError("无法写入工作区或配置目录,请选择可写的本地 OE_WORKSPACE / OE_CONFIG。") from exc
        try:
            import webview
        except ImportError as exc:
            raise StartupError("桌面组件缺失 (pywebview/pythonnet),请修复安装。") from exc
        # gui=edgechromium below is an explicit renderer requirement. Do not
        # depend on pywebview's private detection helpers or silently fall back.
        runtime_python = paths.repo / "runtime" / "python" / "python.exe"
        # Windows venv python.exe is a redirector: Popen.pid would identify
        # its wrapper, not the interpreter writing readiness. Launch the base
        # interpreter directly for this stdlib-only service so ownership remains
        # exact; backend pipeline workers still select the repo venv themselves.
        python = runtime_python if runtime_python.is_file() else Path(
            getattr(sys, "_base_executable", None) or sys.executable
        )
        with tempfile.TemporaryDirectory(prefix="shortfilm-ready-") as directory:
            ready_file = Path(directory) / "ready.json"
            token = secrets.token_urlsafe(32)
            service = OwnedService(python, paths, ready_file, token)
            port = wait_ready(service.process, ready_file, token)
            logger.info("owned backend ready")
            run_window(webview, service, port, token, instance, paths, logger)
        logger.info("desktop closed")
        return 0
    except Exception as exc:
        if logger:
            # Do not log exception text/traceback: third-party errors may contain
            # bearer tokens, request URLs, dotenv values or production content.
            logger.error("startup failed type=%s", type(exc).__name__)
        message = str(exc) if isinstance(exc, StartupError) else "桌面启动失败,请修复安装并检查 WebView2 Runtime。"
        show_error(message, paths.logs / "desktop.log" if logger else None)
        return 2
    finally:
        if service:
            service.close()
        if instance:
            instance.close()
        _NATIVE_HANDLERS.clear()


if __name__ == "__main__":
    raise SystemExit(main())
