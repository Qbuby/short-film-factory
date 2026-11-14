"""视觉评委:把关键帧 + 评审 rubric 交给一个视觉模型,拿回 7 维打分与修复清单。

**能力门禁**:本机没有配置视觉端点时不会伪造评分 —— 明确返回 `not_configured`,
由 pipeline 决定是回落给人/agent 评审,还是直接失败。

配置(环境变量或 .env):
    MOTION_VISION_BASE   端点根地址,例如 http://127.0.0.1:3425/v1
    MOTION_VISION_KEY    API Key
    MOTION_VISION_MODEL  视觉模型 id(必须支持图片输入)
    MOTION_VISION_API    接口风格:openai | anthropic | auto(默认 auto,失败时互退)

本机当前用的是 **magpie** 路由组:
    provider magpie → http://127.0.0.1:3425,api=anthropic-messages
    model    group/never-stuck(「永不卡住」routing group,支持 text+image 输入)

注意:magpie 是**推理模型**,回复里会先来一段 thinking 块再给正文。
取答案必须按 type=="text" 找,不能直接取 content[0];max_tokens 也要给够,
否则思考过程会把 token 吃光、正文为空(那种情况要报错,不能当成"模型没看懂")。

用法:
    python tools/motion_design/vision_score.py --frames a.png b.png --out review.json
    python tools/motion_design/vision_score.py --frames ... --mock http://127.0.0.1:39998/v1
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

RUBRIC = """You are a senior motion-design jury member (Motionographer editor / Buck / ManvsMachine level).
You did NOT make this film. Judge harshly and precisely. Kindness is useless; specificity is everything.

Score 1-10 on each dimension (5 = competent student, 6 = decent template, 7 = solid professional,
8 = high-end agency, 9 = award shortlist). Do not inflate; most first renders deserve 5-7.
  style_fidelity, concept_wow, motion_craft, design_typography, finish_texture, sound_sync, technical

Then give 5-10 fixes ordered by impact. Each fix: timecode(s), what is wrong (observable), why it matters,
and a concrete how-to (curve, frame count, px, colour, font, layout). At least one fix must raise the wow factor.

Return ONLY JSON:
{"scores": {"style_fidelity": n, ...}, "critical": ["..."], "fixes": [{"t": "1.2s", "what": "...", "why": "...", "how": "..."}]}
"""

# 推理模型:正文前的思考块要跳过
MAX_TOKENS = 8000


def _load_dotenv() -> None:
    """把仓库 .env 里的 MOTION_* 读进环境(不覆盖已有值)。"""
    env_file = REPO / ".env"
    if not env_file.exists():
        return
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k.startswith("MOTION_") and k not in os.environ:
                os.environ[k] = v
    except OSError:
        pass


def config() -> dict:
    _load_dotenv()
    return {
        "base": os.environ.get("MOTION_VISION_BASE", "").rstrip("/"),
        "key": os.environ.get("MOTION_VISION_KEY", ""),
        "model": os.environ.get("MOTION_VISION_MODEL", ""),
        "api": (os.environ.get("MOTION_VISION_API", "auto") or "auto").lower(),
    }


def available() -> bool:
    c = config()
    return bool(c["base"] and c["key"] and c["model"])


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def _post(url: str, body: dict, key: str, timeout: int, anthropic: bool) -> dict:
    headers = {"content-type": "application/json"}
    if anthropic:
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["authorization"] = "Bearer " + key
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}") from exc


def _anthropic_text(payload: dict) -> str:
    """Anthropic Messages 的 content 是块数组,推理模型会先给 thinking 块。"""
    blocks = payload.get("content") or []
    texts = [b.get("text") or "" for b in blocks if b.get("type") == "text"]
    if not texts:
        # 没有 text 块 —— 极可能是 max_tokens 被思考过程吃光了
        usage = payload.get("usage") or {}
        raise RuntimeError(
            "模型只返回了思考块、没有正文(max_tokens 可能被推理吃光):"
            f" usage={json.dumps(usage, ensure_ascii=False)[:200]}"
        )
    return "\n".join(texts)


def _openai_text(payload: dict) -> str:
    msg = ((payload.get("choices") or [{}])[0].get("message") or {})
    content = msg.get("content") or ""
    if isinstance(content, list):  # 少数网关会返回块数组
        content = "\n".join(
            (b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return content or ""


def extract_json_object(text: str) -> dict:
    """从模型回复里取出第一个完整 JSON 对象。

    不能用 text.find("{") / text.rfind("}") —— 修复建议里常带大括号、
    字符串里也可能有引号,那样会切错位置。改成按括号配对扫描,
    并跳过字符串字面量里的括号与转义引号。
    """
    start = text.find("{")
    if start < 0:
        raise ValueError("模型没有返回 JSON:" + text[:200])
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("模型返回的 JSON 不完整(可能被截断):" + text[start : start + 200])


def call_vision(frames: list[Path], context: str, base: str, key: str, model: str,
                api: str = "auto", timeout: int = 300) -> dict:
    prompt = RUBRIC + ("\n\nProduction context:\n" + context if context else "")
    root = base[:-3] if base.endswith("/v1") else base

    def try_anthropic() -> dict:
        body = {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "system": prompt,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _b64(p)}}
                for p in frames
            ] + [{"type": "text", "text": prompt + "\n\nReturn ONLY the JSON described above."}]}],
        }
        payload = _post(root + "/v1/messages", body, key, timeout, anthropic=True)
        return _anthropic_text(payload)

    def try_openai() -> dict:
        content: list[dict] = [{"type": "text", "text": prompt}]
        for p in frames:
            content.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + _b64(p)}})
        body = {"model": model, "messages": [{"role": "user", "content": content}],
                "max_tokens": MAX_TOKENS, "temperature": 0.2}
        payload = _post(base + "/chat/completions", body, key, timeout, anthropic=False)
        return _openai_text(payload)

    order = {
        "anthropic": [try_anthropic],
        "openai": [try_openai],
        "auto": [try_anthropic, try_openai],
    }.get(api, [try_anthropic, try_openai])

    last: Exception | None = None
    for fn in order:
        try:
            text = fn()
            if not text.strip():
                raise RuntimeError("模型返回空内容")
            return extract_json_object(text)
        except Exception as exc:  # 换一种接口风格再试
            last = exc
    raise RuntimeError(str(last) if last else "视觉端点调用失败")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="视觉评委(需要视觉模型端点)")
    ap.add_argument("--frames", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--context", default="")
    ap.add_argument("--api", default="", help="openai | anthropic | auto(默认读 MOTION_VISION_API)")
    ap.add_argument("--mock", default="", help="测试用:指向本地 mock 端点,跳过环境变量检查")
    args = ap.parse_args(argv)

    frames = [Path(f) for f in args.frames if Path(f).exists()]
    if not frames:
        print(json.dumps({"status": "no_frames"}, ensure_ascii=False))
        return 2

    if args.mock:
        base, key, model, api = args.mock, "mock", "mock-vision", "openai"
    else:
        c = config()
        base, key, model = c["base"], c["key"], c["model"]
        api = args.api or c["api"]
    if not (base and key and model):
        result = {
            "status": "not_configured",
            "detail": "未配置 MOTION_VISION_BASE/KEY/MODEL,不生成评分(避免伪造评审)",
            "frames": [str(f) for f in frames],
        }
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0

    try:
        scores = call_vision(frames, args.context, base, key, model, api=api)
        scores["status"] = "ok"
        scores["model"] = model
        scores["api"] = api
        scores["frames"] = [str(f) for f in frames]
    except Exception as exc:
        scores = {"status": "error", "detail": str(exc)[:400], "frames": [str(f) for f in frames]}
    Path(args.out).write_text(json.dumps(scores, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: scores.get(k) for k in ("status", "model", "scores", "critical")}, ensure_ascii=False)[:600])
    return 0 if scores.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
