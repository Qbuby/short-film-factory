"""极简 OpenAI 兼容 LLM 客户端(只用于 code-first 管线的文案/节拍生成)。

配置(环境变量或 OpenMontage 的 .env):
    MOTION_LLM_BASE   例如 https://api.example.com/v1
    MOTION_LLM_KEY
    MOTION_LLM_MODEL  例如 deepseek-chat / gpt-4.1-mini

没有配置时 `available()` 返回 False,pipeline 会走 agent 手写节拍的路子,
不会用模板冒充「模型生成」。
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    """把仓库 .env 里的 MOTION_* 读进环境(不覆盖已有值)。"""
    env_file = Path(os.environ.get("OE_CONFIG") or (REPO / ".env"))
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
        "base": os.environ.get("MOTION_LLM_BASE", "").rstrip("/"),
        "key": os.environ.get("MOTION_LLM_KEY", ""),
        "model": os.environ.get("MOTION_LLM_MODEL", ""),
        # 推理强度:默认 low。写稿/改稿/写 TSX 都不需要长推理,
        # 高强度会把 token 额度全花在思考上,正文反而是空的。
        "effort": os.environ.get("MOTION_LLM_EFFORT", "low").strip() or "low",
    }


def available() -> bool:
    c = config()
    return bool(c["base"] and c["key"] and c["model"])


def probe(base: str = "", key: str = "", model: str = "") -> dict:
    """只探端点,不推理。

    连通性检查应该分两步:
      1. 探端点(毫秒级):地址通不通、鉴权过不过、模型名在不在
      2. 试一次推理(可能很慢):模型到底能不能回话
    混在一起做,用户就只能看到一个黑盒的总耗时,分不清是工具慢还是模型慢。

    很多网关不开放 /models,所以探不通不算失败,只是这一段没有结论。
    """
    c = config()
    base = (base or c["base"]).rstrip("/")
    key = key or c["key"]
    model = model or c["model"]
    if not (base and key):
        return {"ok": False, "detail": "未配置地址或 Key"}
    cands = [base + "/models"] if base.endswith("/v1") else [base + "/v1/models", base + "/models"]
    last = ""
    for url in cands:
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers={"authorization": "Bearer " + key})
            with urllib.request.urlopen(req, timeout=15) as r:
                payload = json.loads(r.read().decode("utf-8"))
            ms = int((time.time() - t0) * 1000)
            ids = [m.get("id") for m in (payload.get("data") or []) if isinstance(m, dict)]
            return {"ok": True, "latency_ms": ms, "url": url, "models": len(ids),
                    "model_found": (model in ids) if ids else None}
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
            if exc.code in (401, 403):
                return {"ok": False, "detail": "鉴权失败(Key 不对?)", "latency_ms": int((time.time() - t0) * 1000)}
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {str(exc)[:120]}"
    return {"ok": False, "detail": last or "端点不可达", "available": False}


def complete(system: str, user: str, max_tokens: int = 3000, temperature: float = 0.7,
             timeout: int = 180, retries: int = 2, backoff: float = 5.0) -> str:
    """调一次模型。

    两类要重试的失败,处理方式完全不同:

    * 空 content(带强制思考的模型先把 max_tokens 花在思考过程上)—— 升档重来。
    * **网络瞬时故障**(超时、连接被掐、429 限流、网关 5xx)—— 这不是内容问题,
      等一会儿再打一次通常就好了。以前这里只重试空内容,超时直接往上抛,
      结果就是:专属画面生成在 180 秒处被砍掉(静默退回通用模板),
      复审改稿第 2 轮整个死掉("第 2 轮失败:TimeoutError")。

    写 stderr,界面那边的同一个管道收得到,用户能看到"正在重试"。
    """
    budget = max_tokens
    last = ""
    empty_tries = 0
    transient_tries = 0
    while True:
        try:
            return _complete_once(system, user, budget, temperature, timeout)
        except _EmptyAnswer as e:
            last = str(e)
            empty_tries += 1
            if empty_tries > 3:
                break
            # 20 → 2048 一次到位:带强制思考的模型光"想"就要上千 tokens,
            # 小步翻倍只会多等好几个 30 秒。
            budget = min(max(budget * 4, 2048), 32000)
            print(f"[llm] 空内容,max_tokens 升到 {budget} 重试", file=sys.stderr)
        except (TimeoutError, socket.timeout, ConnectionError, urllib.error.URLError) as e:
            # 兜底:就算调用方自己抛了网络异常,也按瞬时故障重试。
            last = f"{type(e).__name__}: {str(e)[:160]}"
            transient_tries += 1
            if transient_tries > retries:
                break
            wait = backoff * (2 ** (transient_tries - 1))
            print(f"[llm] {last};{wait:.0f} 秒后重试(第 {transient_tries}/{retries} 次)",
                  file=sys.stderr, flush=True)
            time.sleep(wait)
        except _Transient as e:
            last = f"{type(e).__name__}: {str(e)[:160]}"
            transient_tries += 1
            if transient_tries > retries:
                break
            wait = backoff * (2 ** (transient_tries - 1))
            print(f"[llm] {last};{wait:.0f} 秒后重试(第 {transient_tries}/{retries} 次)",
                  file=sys.stderr, flush=True)
            time.sleep(wait)
    raise RuntimeError(last)


class _EmptyAnswer(RuntimeError):
    """模型返回了空 content(通常是思考过程吃光了 max_tokens)。"""


class _Transient(RuntimeError):
    """网络瞬时故障:超时、连接被掐、限流、网关 5xx。等一下重试就能好。"""


# 有些网关不认 reasoning 参数。遇到 400 就记住这件事,以后都不带了。
_NO_REASONING = False


def _effort() -> str:
    """推理强度。

    这一条是实测出来的,不是猜的:本机网关的 group/never-stuck 默认推理强度很高,
    一次"写 60 字"的普通请求,思考过程就吃掉了 1999/2000 的 token 额度,
    正文是空的;写一份专属画面 TSX 要跑 7 分半钟,32000 token 仍然被截断,
    最后语法校验直接失败。

    同一套提示词加上 reasoning.effort=low:11.6 秒返回,正文完整。
    写稿、改稿、画 TSX 都不需要长推理 —— 深度推理留给用户自己的模型设置。
    """
    return str(config().get("effort") or "low")


def _request_body(system: str, user: str, max_tokens: int, temperature: float) -> dict:
    body = {
        "model": config()["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if not _NO_REASONING:
        body["reasoning"] = {"effort": _effort()}
    return body


def _complete_once(system: str, user: str, max_tokens: int, temperature: float, timeout: int) -> str:
    c = config()
    if not (c["base"] and c["key"] and c["model"]):
        raise RuntimeError("未配置 MOTION_LLM_BASE/KEY/MODEL")
    body = _request_body(system, user, max_tokens, temperature)
    req = urllib.request.Request(
        c["base"] + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json", "authorization": "Bearer " + c["key"]},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        # 这个网关不认 reasoning 参数:记住,以后都不带。
        if exc.code == 400 and "reasoning" in detail.lower() and not _NO_REASONING:
            globals()["_NO_REASONING"] = True
            raise _Transient("网关不接受 reasoning 参数,去掉后重试") from exc
        # 429/5xx 是"等会儿再来",4xx 是"这个请求本身不对",重试没有意义。
        if exc.code == 429 or exc.code >= 500:
            raise _Transient(f"HTTP {exc.code}: {detail}") from exc
        raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
    except (TimeoutError, socket.timeout, ConnectionError) as exc:
        raise _Transient(f"{type(e).__name__}: {exc}") from exc
    except urllib.error.URLError as exc:
        raise _Transient(f"URLError: {exc.reason}") from exc
    msg = ((payload.get("choices") or [{}])[0].get("message") or {})
    text = (msg.get("content") or "").strip()
    if not text:
        # 有些网关把思考过程放在 reasoning / reasoning_content 里。
        # 内容为空但有思考痕迹,说明 max_tokens 被思考吃光了。
        reasoning = (msg.get("reasoning") or msg.get("reasoning_content") or "").strip()
        usage = payload.get("usage") or {}
        rt = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
        raise _EmptyAnswer(
            "LLM 返回空内容"
            + (f"(模型思考用了 {rt} tokens,max_tokens={max_tokens} 不够)" if rt else "")
            + (f"(检测到 {len(reasoning)} 字的思考内容)" if reasoning else "")
            + " → 已自动升档重试仍失败,请换不用强制思考的模型或调大 max_tokens"
        )
    return text


def extract_json(text: str) -> dict:
    """容忍 markdown 围栏与前后散文。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.startswith("json"):
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型没有返回 JSON:" + text[:200])
    return json.loads(t[start : end + 1])