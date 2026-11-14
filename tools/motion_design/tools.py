"""motion_plan / motion_audio / motion_render / motion_review —— Code-first 管线的四个工具。

它们都是本地、免费、确定性的:分镜装配、音频合成、逐帧渲染、评审证据。
实现各自委托给同目录的脚本(单一实现来源),这里只做 OpenMontage 工具契约的适配。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)

HERE = Path(__file__).resolve().parent


def _run_script(script: str, argv: list[str], timeout: int) -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, str(HERE / script), *argv],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out


def _tail_json(text: str) -> dict[str, Any]:
    """脚本最后会打印一段 JSON;取最外层那个对象。"""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


class MotionPlan(BaseTool):
    name = "motion_plan"
    version = "1.0.0"
    tier = ToolTier.CORE
    capability = "planning"
    provider = "openmontage"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["python:yaml"]
    install_instructions = "pip install pyyaml(OpenMontage 已内置)"
    capabilities = ["storyboard_assembly", "beat_validation", "style_injection"]
    supports = {"offline": True, "deterministic": True}
    best_for = [
        "把 agent 写好的节拍表装配成可执行的 storyboard.json",
        "校验 hook ≤1.2s / hero 60–75% / 结尾 hold ≥0.8s",
    ]
    not_good_for = ["替 agent 想创意(创意由 agent 负责)"]

    input_schema = {
        "type": "object",
        "required": ["brief", "style", "out"],
        "properties": {
            "brief": {"type": "string"},
            "style": {"type": "string", "description": "styles/mg-*.yaml 的名字"},
            "beats": {"type": "string", "description": "agent 写好的 beats.json 路径"},
            "scaffold": {"type": "boolean"},
            "llm": {"type": "boolean", "description": "让 LLM 从 brief 生成节拍表(需要 MOTION_LLM_*)"},
            "duration": {"type": "number", "default": 10.0},
            "width": {"type": "integer", "default": 1080},
            "height": {"type": "integer", "default": 1920},
            "fps": {"type": "integer", "default": 30},
            "recipe": {"type": "string", "default": "ambient"},
            "motion_blur": {"type": "integer", "default": 1, "description": "运动模糊采样数(1=关闭)"},
            "out": {"type": "string"},
        },
    }

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        argv = ["--brief", str(inputs["brief"]), "--style", str(inputs["style"]), "--out", str(inputs["out"])]
        if inputs.get("beats"):
            argv += ["--beats", str(inputs["beats"])]
        if inputs.get("scaffold"):
            argv += ["--scaffold"]
        if inputs.get("llm"):
            argv += ["--llm"]
        for key, flag in (
            ("duration", "--duration"), ("width", "--width"), ("height", "--height"),
            ("fps", "--fps"), ("recipe", "--recipe"), ("motion_blur", "--motion-blur"),
        ):
            if inputs.get(key) not in (None, ""):
                argv += [flag, str(inputs[key])]
        ok, out = _run_script("plan.py", argv, 180)
        data = _tail_json(out)
        return ToolResult(success=ok, data=data, error=None if ok else out[-800:])


class MotionMatchStyle(BaseTool):
    """brief → 风格候选:把一句话 brief 映射到 mg-* playbook 库。"""

    name = "motion_match_style"
    version = "1.0.0"
    tier = ToolTier.CORE
    capability = "planning"
    provider = "openmontage"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["python:yaml"]
    install_instructions = "pip install pyyaml(OpenMontage 已内置)"
    capabilities = ["style_recommendation", "palette_lookup", "technique_lookup"]
    supports = {"offline": True, "deterministic": True}
    best_for = [
        "一句话 brief 选出最合适的 mg-* 风格(中文 bigram + 题材词 + 内容词)",
        "拿到候选风格的色板、设计要点与关键技法",
    ]
    not_good_for = ["生成风格本身(风格卡要手写或从 mg-styles-15 导入)"]

    input_schema = {
        "type": "object",
        "required": ["brief"],
        "properties": {
            "brief": {"type": "string"},
            "top": {"type": "integer", "default": 3},
        },
    }

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        argv = ["--brief", str(inputs["brief"])]
        if inputs.get("top"):
            argv += ["--top", str(inputs["top"])]
        ok, out = _run_script("match_style.py", argv, 60)
        data = _tail_json(out)
        return ToolResult(success=ok, data=data, error=None if ok else out[-800:])


class MotionFetchSamples(BaseTool):
    """下载 mg audio 的 CC0 采样库(按需,不进版本库)。"""

    name = "motion_fetch_samples"
    version = "1.0.0"
    tier = ToolTier.SOURCE
    capability = "audio"
    provider = "openmontage"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.SEEDED
    runtime = ToolRuntime.LOCAL

    dependencies = ["cmd:python3"]
    install_instructions = "需要能访问 GitHub raw(采样来自 mg-styles-15 仓库,CC0)"
    capabilities = ["sample_download", "manifest_verification"]
    supports = {"offline": False, "deterministic": True}
    best_for = ["把 mg audio 的采样补齐,让合成配方用到真实采样而不是纯振荡器"]
    not_good_for = ["离线环境(采样已下载过时不需要再跑)"]

    input_schema = {
        "type": "object",
        "properties": {
            "dest": {"type": "string", "description": "采样落盘目录,默认 lib/motion_design/mgstyles/audio/samples"},
            "check": {"type": "boolean", "description": "只校验现有文件,不下载"},
            "limit": {"type": "integer"},
        },
    }

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        argv = []
        if inputs.get("dest"):
            argv += ["--dest", str(inputs["dest"])]
        if inputs.get("check"):
            argv += ["--check"]
        if inputs.get("limit"):
            argv += ["--limit", str(inputs["limit"])]
        ok, out = _run_script("fetch_samples.py", argv, 900)
        data = _tail_json(out)
        return ToolResult(success=ok, data=data, error=None if ok else out[-800:])


class MotionAudio(BaseTool):
    name = "motion_audio"
    version = "1.0.0"
    tier = ToolTier.VOICE
    capability = "audio"
    provider = "mgaudio"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["python:numpy", "python:scipy", "python:numba", "python:soundfile", "python:pedalboard", "python:pyloudnorm"]
    install_instructions = "pip install numpy scipy numba soundfile pedalboard pyloudnorm"
    capabilities = ["music_synthesis", "sfx_synthesis", "loudness_master", "audio_qc"]
    supports = {"offline": True, "no_api_key": True}
    best_for = ["按分镜生成音乐与音效并母带到 −14 LUFS", "不需要任何 API Key 的配乐"]
    not_good_for = ["人声旁白(用 tts_selector)"]

    input_schema = {
        "type": "object",
        "required": ["storyboard", "out"],
        "properties": {
            "storyboard": {"type": "string"},
            "out": {"type": "string"},
            "recipe": {"type": "string"},
            "bpm": {"type": "number"},
            "key": {"type": "string"},
            "no_sfx": {"type": "boolean"},
        },
    }

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        argv = ["--storyboard", str(inputs["storyboard"]), "--out", str(inputs["out"])]
        for key, flag in (("recipe", "--recipe"), ("bpm", "--bpm"), ("key", "--key")):
            if inputs.get(key) not in (None, ""):
                argv += [flag, str(inputs[key])]
        if inputs.get("no_sfx"):
            argv += ["--no-sfx"]
        ok, out = _run_script("audio.py", argv, 600)
        data = _tail_json(out)
        return ToolResult(success=ok, data=data, error=None if ok else out[-1200:])


class MotionRender(BaseTool):
    name = "motion_render"
    version = "1.0.0"
    tier = ToolTier.GENERATE
    capability = "render"
    provider = "mg-harness"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    # Chrome 不在 PATH 里也算可用:render.py 会按常见安装路径探测,或读 MG_CHROME
    dependencies = ["cmd:node", "cmd:ffmpeg"]
    install_instructions = (
        "需要 Node + ffmpeg + Chrome。\n"
        "  npm install(在 lib/motion_design/mgstyles/harness 下)\n"
        "  Chrome 路径可用 MG_CHROME 指定"
    )
    capabilities = ["frame_by_frame_render", "keyframe_stills", "audio_mux"]
    supports = {"offline": True, "deterministic": True}
    best_for = ["把 window.renderAt(t) 的 HTML 页面逐帧渲成 MP4", "出关键帧给评审"]
    not_good_for = ["需要 GPU 的三维重负载(用 threejs_world / blender_world)"]

    input_schema = {
        "type": "object",
        "required": ["project"],
        "properties": {
            "project": {"type": "string"},
            "page": {"type": "string", "default": "index.html"},
            "out": {"type": "string"},
            "audio": {"type": "string"},
            "stills": {"type": "string"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "fps": {"type": "integer"},
            "duration": {"type": "number"},
            "scale": {"type": "number"},
            "mb": {"type": "integer"},
        },
    }

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        argv = ["--project", str(inputs["project"])]
        for key, flag in (
            ("page", "--page"), ("out", "--out"), ("audio", "--audio"), ("stills", "--stills"),
            ("width", "--width"), ("height", "--height"), ("fps", "--fps"),
            ("duration", "--duration"), ("scale", "--scale"), ("mb", "--mb"),
        ):
            if inputs.get(key) not in (None, ""):
                argv += [flag, str(inputs[key])]
        ok, out = _run_script("render.py", argv, 3600)
        return ToolResult(
            success=ok,
            data={"project": inputs["project"], "out": inputs.get("out"), "log_tail": out[-600:]},
            error=None if ok else out[-1200:],
        )


class MotionReview(BaseTool):
    name = "motion_review"
    version = "1.0.0"
    tier = ToolTier.ANALYZE
    capability = "analysis"
    provider = "openmontage"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["cmd:ffmpeg", "python:numpy"]
    install_instructions = "需要 ffmpeg"
    capabilities = ["spec_check", "contact_sheet", "keyframe_extraction", "audio_qc", "black_frame_detection"]
    supports = {"offline": True}
    best_for = ["给独立评审提供客观证据(规格/帧/音频)", "自动检出黑帧、静音、响度偏离"]
    not_good_for = ["替代评委打分(评分由 agent 依证据写)"]

    input_schema = {
        "type": "object",
        "required": ["video", "out"],
        "properties": {
            "video": {"type": "string"},
            "audio": {"type": "string"},
            "out": {"type": "string"},
            "stills": {"type": "string"},
            "duration": {"type": "number"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "fps": {"type": "number"},
        },
    }

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        argv = ["--video", str(inputs["video"]), "--out", str(inputs["out"])]
        for key, flag in (
            ("audio", "--audio"), ("stills", "--stills"), ("duration", "--duration"),
            ("width", "--width"), ("height", "--height"), ("fps", "--fps"),
        ):
            if inputs.get(key) not in (None, ""):
                argv += [flag, str(inputs[key])]
        ok, out = _run_script("review.py", argv, 600)
        data = _tail_json(out)
        return ToolResult(success=ok, data=data, error=None if ok else out[-1200:])


class MotionVisionScore(BaseTool):
    """视觉评委:关键帧 → 7 维打分 + 带时间码的修复清单。"""

    name = "motion_vision_score"
    version = "1.0.0"
    tier = ToolTier.ANALYZE
    capability = "analysis"
    provider = "magpie"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.SEEDED
    runtime = ToolRuntime.LOCAL

    dependencies = []
    install_instructions = (
        "需要一个支持图片输入的视觉端点。本机默认走 magpie 路由组"
        "(http://127.0.0.1:3425/v1,Anthropic Messages 风格,model=group/never-stuck);"
        "未配置时工具返回 not_configured,不会编造分数。"
    )
    capabilities = ["rubric_scoring", "fix_list_generation"]
    supports = {"offline": False, "deterministic": False}
    best_for = ["给成片做独立的 7 维主观评审", "产出可执行的修复清单"]
    not_good_for = ["客观指标(黑帧/死场/命中点用 motion_review)"]

    input_schema = {
        "type": "object",
        "required": ["frames", "out"],
        "properties": {
            "frames": {"type": "array", "items": {"type": "string"}},
            "out": {"type": "string"},
            "context": {"type": "string", "description": "生产上下文(题材/风格/时长),帮评委判断"},
            "api": {"type": "string", "description": "openai | anthropic | auto"},
        },
    }

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        argv = ["--out", str(inputs["out"])]
        for f in inputs.get("frames") or []:
            argv += ["--frames", str(f)]
        if inputs.get("context"):
            argv += ["--context", str(inputs["context"])]
        if inputs.get("api"):
            argv += ["--api", str(inputs["api"])]
        ok, out = _run_script("vision_score.py", argv, 900)
        data = _tail_json(out)
        return ToolResult(success=ok, data=data, error=None if ok else out[-1200:])


class MotionRenderHyperFrames(BaseTool):
    name = "motion_render_hyperframes"
    version = "1.0.0"
    tier = ToolTier.GENERATE
    capability = "render"
    provider = "hyperframes"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["cmd:npx", "cmd:ffmpeg"]
    install_instructions = "需要 Node/npx 与 ffmpeg;首次使用会通过 npx 拉取 hyperframes CLI"
    capabilities = ["html_render", "gsap_timeline", "layout_check"]
    supports = {"offline": False, "deterministic": True}
    best_for = ["排版叙事 / 大字号 / 图文混排", "HTML+CSS+GSAP 时间轴"]
    not_good_for = ["需要自己写逐帧纯函数渲染的场合(用 motion_render)"]

    input_schema = {
        "type": "object",
        "required": ["project"],
        "properties": {
            "project": {"type": "string"},
            "out": {"type": "string"},
            "audio": {"type": "string", "description": "音轨路径;HyperFrames 自身不出声,渲染后由本工具 mux 进去"},
            "fps": {"type": "integer"},
            "quality": {"type": "string"},
            "check": {"type": "boolean"},
        },
    }

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        argv = ["--project", str(inputs["project"])]
        for key, flag in (("out", "--out"), ("audio", "--audio"), ("fps", "--fps"), ("quality", "--quality")):
            if inputs.get(key) not in (None, ""):
                argv += [flag, str(inputs[key])]
        if inputs.get("check"):
            argv += ["--check"]
        ok, out = _run_script("render_hyperframes.py", argv, 2400)
        data = _tail_json(out)
        return ToolResult(success=ok and bool(data.get("ok", ok)), data=data, error=None if ok else out[-800:])


TOOLS = [
    MotionPlan(),
    MotionMatchStyle(),
    MotionAudio(),
    MotionFetchSamples(),
    MotionRender(),
    MotionRenderHyperFrames(),
    MotionReview(),
    MotionVisionScore(),
]
