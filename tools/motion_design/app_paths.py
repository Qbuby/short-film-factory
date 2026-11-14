"""Immutable application assets versus writable user data.

Backend and CLI callers may import the constants or call get_paths() after setting
OE_WORKSPACE/OE_CONFIG. Importing this module does not create or migrate files.
Desktop preparation never copies credentials or generated project/media folders.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

try:
    from .app_version import APP_VERSION
except ImportError:  # Direct script execution by the bundled interpreter.
    from app_version import APP_VERSION


# 记着「我们往工作区写过哪些文件、写进去时是什么内容」。
# 有了它才能区分「应用要更新的模板」和「用户自己改过的文件」。
TEMPLATE_MANIFEST = ".template-manifest.json"


@dataclass(frozen=True)
class AppPaths:
    repo: Path
    workspace: Path
    config: Path
    data_root: Path

    @property
    def tools(self) -> Path:
        return self.repo / "tools" / "motion_design"

    @property
    def composer(self) -> Path:
        return self.workspace / "remotion-composer"

    @property
    def projects(self) -> Path:
        return self.workspace / "projects" / "code-first"

    @property
    def final(self) -> Path:
        return self.projects / "final"

    @property
    def public(self) -> Path:
        return self.composer / "public"

    @property
    def src(self) -> Path:
        return self.composer / "src"

    @property
    def rout(self) -> Path:
        return self.composer / "out"

    @property
    def logs(self) -> Path:
        return self.data_root / "logs"


def get_paths(repo: Path | None = None, env: Mapping[str, str] | None = None,
              *, validate: bool = True) -> AppPaths:
    env = os.environ if env is None else env
    repo = Path(repo or env.get("OE_REPO") or Path(__file__).resolve().parents[2]).resolve()
    local = Path(env.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    data = (local / "ShortFilmFactory").resolve()
    # One workspace per installation. Two installs (a developer checkout and a
    # packaged copy) would otherwise fight over the same composer dependency
    # link, and the second one would refuse to start. Model settings stay
    # shared in one config file so a new install keeps the user's model.
    install = hashlib.sha256(str(repo).casefold().encode("utf-8")).hexdigest()[:8]
    workspace = Path(env.get("OE_WORKSPACE") or data / "workspaces" / f"{APP_VERSION}-{install}").resolve()
    default_config = workspace / ".env" if env.get("OE_WORKSPACE") else data / "config" / ".env"
    config = Path(env.get("OE_CONFIG") or default_config).resolve()
    if validate and (workspace == repo or repo in workspace.parents):
        raise ValueError("OE_WORKSPACE must be outside the application installation")
    if validate and (config == repo or repo in config.parents):
        raise ValueError("OE_CONFIG must be outside the application installation")
    return AppPaths(repo, workspace, config, data)


def link_dependencies(source: Path, destination: Path) -> None:
    """Read-only dependency reuse, validated on every launch; never npm install.

    Windows junctions need no developer mode/admin privilege. If junction creation
    is unavailable, a directory symlink is tried. Neither route silently copies
    a dependency tree or accepts an existing link pointing elsewhere.
    """
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise RuntimeError("Composer dependencies are not a directory")
    if os.path.lexists(destination):
        if not destination.is_dir() or destination.resolve() != source:
            raise RuntimeError("Workspace node_modules does not match the installed dependencies")
        return
    if os.name == "nt":
        # cmd expands percent/bang even inside quotes. Reject these rather than
        # interpreting a user-selected path as command text.
        paths = (str(destination.absolute()), str(source))
        if not any(any(c in p for c in '%!"\r\n') for p in paths):
            # A list is escaped by list2cmdline with backslash-quotes, which
            # cmd.exe does not understand. Supply its native /s /c quoting.
            comspec = os.environ.get("COMSPEC", "cmd.exe")
            command = f'"{comspec}" /d /s /c "mklink /J "{paths[0]}" "{paths[1]}""'
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW, check=False,
            )
            if result.returncode == 0 and destination.is_dir() and destination.resolve() == source:
                return
    try:
        destination.symlink_to(source, target_is_directory=True)
    except OSError as exc:
        raise RuntimeError("Cannot link composer dependencies; choose a local NTFS workspace or enable directory symlinks") from exc
    if not destination.is_dir() or destination.resolve() != source:
        raise RuntimeError("Composer dependency link validation failed")


def sync_composer_templates(paths: AppPaths) -> list[str]:
    """把应用自带的渲染模板同步进工作区,保留用户/模型产出的文件。

    以前只在**第一次**准备时拷一次 src/,于是应用升级之后,
    老工作区里的 StickerFilm.tsx 永远是旧版 —— 修了字幕压字、修了文字溢出,
    用户的工作区里根本没生效(这次用户的片子就是这么出来的)。

    规则:只覆盖**应用自己发的**文件;src/generated/ 里模型写的专属画面、
    public/ 里用户产出的媒体、node_modules、out 一律不动。
    """
    source = paths.repo / "remotion-composer"
    if not (source / "src").is_dir():
        return []
    updated: list[str] = []
    src = paths.composer / "src"
    src.mkdir(parents=True, exist_ok=True)
    manifest_path = paths.composer / TEMPLATE_MANIFEST
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            manifest = {}
    except (OSError, ValueError):
        manifest = {}

    def copy_if_changed(relative: str) -> None:
        old = paths.composer / relative
        new = source / relative
        if not new.is_file():
            return
        data = new.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if old.is_file():
            current = hashlib.sha256(old.read_bytes()).hexdigest()
            if current == digest:
                manifest[relative] = digest
                return
            # 这个文件被用户改过(内容 ≠ 我们上次写进去的),不能覆盖。
            recorded = manifest.get(relative)
            if recorded and current != recorded:
                return
        old.parent.mkdir(parents=True, exist_ok=True)
        old.write_bytes(data)
        manifest[relative] = digest
        updated.append(relative)

    # src/ 顶层与子目录里的应用文件(除了 generated:模型产物)
    for path in sorted((source / "src").rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(source).as_posix()
        if rel.startswith("src/generated/"):
            continue
        # 这个注册表是**每个工作区自己的**:里面列的是本工作区出过的片子。
        # 开发者仓库里那份带着他自己的片子,同步过去会让工作区去引用不存在的视频。
        if rel == "src/stickerFilmRegistry.ts":
            continue
        if "__pycache__" in rel:
            continue
        copy_if_changed(rel)
    # 工程配置文件
    for name in ("package.json", "package-lock.json", "tsconfig.json",
                 "remotion.config.ts", "remotion.config.js", "titled_video_props.json"):
        copy_if_changed(name)
    # 静态种子素材:风格样片与字体
    for name in ("styles", "fonts"):
        folder = source / "remotion-composer" / "public" / name
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                copy_if_changed("public/" + path.relative_to(folder).as_posix())
    if (source / "remotion-composer" / "public").is_dir():
        for path in sorted((source / "remotion-composer" / "public").iterdir()):
            if path.is_file() and not path.name.startswith("."):
                copy_if_changed("public/" + path.name)
    try:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return updated


def prepare_workspace(paths: AppPaths) -> None:
    """Seed one release's writable composer once; preserve all user work on reopen.

    Only public/styles, public/fonts and root-level public files are static seed
    assets. Named project folders, voice previews, out and credentials are not
    shipped into a user's workspace. Old version workspaces are never deleted.
    """
    source = paths.repo / "remotion-composer"
    if not (source / "src").is_dir() or not (source / "package.json").is_file():
        raise RuntimeError("Application composer assets are missing")
    if not (source / "node_modules").is_dir():
        raise RuntimeError("Application composer dependencies are missing; repair the installation")
    paths.workspace.mkdir(parents=True, exist_ok=True)
    paths.config.parent.mkdir(parents=True, exist_ok=True)
    # Do not import a developer/package .env. Backend settings start blank and
    # are subsequently saved to this single persistent, explicitly selected file.
    paths.config.touch(exist_ok=True)
    if not paths.composer.exists():
        staging = Path(tempfile.mkdtemp(prefix=".composer-", dir=paths.workspace))
        try:
            shutil.copytree(source / "src", staging / "src", ignore=shutil.ignore_patterns("__pycache__"))
            for name in ("package.json", "package-lock.json", "tsconfig.json",
                         "remotion.config.ts", "remotion.config.js", "titled_video_props.json"):
                if (source / name).is_file():
                    shutil.copy2(source / name, staging / name)
            # Never seed a registry of the developer's existing productions.
            (staging / "src" / "stickerFilmRegistry.ts").write_text(
                "// Workspace registry; rebuilt by film.py.\n"
                "export const STICKER_FILMS: Record<string, { total: number; w: number; h: number; style: string; fps: number }> = {};\n",
                encoding="utf-8",
            )
            public = staging / "public"
            public.mkdir()
            for name in ("styles", "fonts"):
                if (source / "public" / name).is_dir():
                    shutil.copytree(source / "public" / name, public / name)
            if (source / "public").is_dir():
                for file in (source / "public").iterdir():
                    if file.is_file() and not file.name.startswith("."):
                        shutil.copy2(file, public / file.name)
            staging.rename(paths.composer)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    if not (paths.src).is_dir() or not (paths.composer / "package.json").is_file():
        raise RuntimeError("Workspace composer is incomplete; select a new OE_WORKSPACE (existing files were preserved)")
    # 应用升级后,模板必须跟着更新(模型写的 src/generated/ 保留)。
    sync_composer_templates(paths)
    # Shared renderer texture, not a developer project's generated media.
    for index in range(8):
        texture = source / "public" / "ai-bubble" / "grain" / f"{index}.png"
        target = paths.public / "ai-bubble" / "grain" / texture.name
        if texture.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(texture, target)
    link_dependencies(source / "node_modules", paths.composer / "node_modules")
    for directory in (paths.final, paths.public, paths.rout, paths.logs):
        directory.mkdir(parents=True, exist_ok=True)


# Import must remain side-effect free even for a bad environment; desktop main
# validates explicitly so its native startup error can explain a bad path.
_PATHS = get_paths(validate=False)
REPO = _PATHS.repo
TOOLS = _PATHS.tools
WORKSPACE = _PATHS.workspace
CONFIG = _PATHS.config
COMPOSER = _PATHS.composer
SRC = _PATHS.src
PUBLIC = _PATHS.public
ROUT = _PATHS.rout
PROJECTS = _PATHS.projects
FINAL = _PATHS.final
