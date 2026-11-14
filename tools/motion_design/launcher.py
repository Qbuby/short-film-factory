"""Thin EXE entry point; the bundled CPython owns the real desktop window.

No browser launch, guessed port, backend monkeypatching or dependency installs.
Keep pywebview out of the frozen interpreter: all desktop/backend code executes
under runtime/python, not inside PyInstaller's PYZ archive.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import sys

APP_NAME = "短片工厂"


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def bundled_python(root: Path) -> Path | None:
    for candidate in (root / "runtime" / "python" / "python.exe",
                      root / "runtime" / "python" / "bin" / "python3"):
        if candidate.is_file():
            return candidate
    return None


def launcher_command(root: Path) -> tuple[list[str], dict[str, str]]:
    tools = root / "tools" / "motion_design"
    if not (tools / "desktop_app.py").is_file():
        tools = root / "_internal" / "tools" / "motion_design"
    if not (tools / "desktop_app.py").is_file():
        raise RuntimeError("找不到桌面组件,请修复安装。")
    python = bundled_python(root)
    if python is None:
        if getattr(sys, "frozen", False):
            raise RuntimeError("找不到内置 Python 运行时,请修复安装。")
        python = Path(sys.executable)
    env = dict(os.environ)
    env.update(OE_REPO=str(root), OE_APP_ROOT=str(root), OE_RUNTIME=str(root / "runtime"),
               PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    # -I prevents cwd/PYTHONPATH imports; add only our immutable script directory.
    code = ("import sys,runpy;sys.path.insert(0,sys.argv[1]);"
            "runpy.run_path(sys.argv[2],run_name='__main__')")
    return [str(python), "-I", "-c", code, str(tools), str(tools / "desktop_app.py")], env


def main() -> int:
    process = None
    try:
        root = app_root()
        command, env = launcher_command(root)
        process = subprocess.Popen(command, cwd=str(root), env=env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        return process.wait()
    except KeyboardInterrupt:
        if process and process.poll() is None:
            # Terminate only this handle. Desktop's job closes with its process,
            # which cleans up its explicitly owned backend and render workers.
            process.terminate()
            process.wait(timeout=5)
        return 0
    except Exception as exc:
        # Never expose arbitrary exception text, which can contain environment
        # values or command lines. These two messages are our own safe strings.
        message = str(exc) if type(exc) is RuntimeError else "桌面启动失败,请修复安装。"
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(0, message, APP_NAME, 0x10)
        elif sys.stderr:
            print(message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
