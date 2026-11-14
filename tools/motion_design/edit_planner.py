"""需求 → 精确锁定素材片段 → edit_decisions_v2 时间轴。

顺序(用户要求):
  1. LLM 把需求拆成 slot,并扩成检索词
  2. 本地素材库的语义索引先召回(LLM 理解阶段已把「只出现 3 秒的办公室」
     切成独立 shot 并打了标签)
  3. 对候选视频做「查询驱动精读」,让 LLM 精确指出那几秒
  4. **本地仍没有符合语义的片段**才联网找(只放行明确可商用/公有领域的
     来源,逐条记录许可与出处)
  5. 组装时间轴,每个 cut 带 reason 与来源,可追溯、可换、可撤销

没配模型时走受限模式,UI 必须显示「按关键词匹配,未做语义规划」,不冒充理解。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from edit_contract import blank_doc, validate, TRANSITIONS
import material_library as lib
import shot_understanding as su

_PLAN_SYSTEM = """你在为一个本地视频剪辑工具做「素材锁定」。用户用中文描述想剪什么,
素材库里是他自己的视频/图片,每条素材已被多模态模型理解成若干语义段,
每段有标题、描述、标签和精确秒数。

输出严格 JSON,不要 markdown、不要解释:
{
  "slots": [
    {"intent": "这一镜要做什么(10字内)",
     "query": "检索关键词,用素材里可能出现的词,空格分隔",
     "duration": 3.0,
     "transition": "淡入淡出",
     "speed": 1.0}
  ]
}

规则:
- slots 数量按目标时长定,每段 2–6 秒,总数不超过 8;总时长贴近目标时长。
- transition 只能从我给的转场名单里选,第一镜必须是「硬切」。
- query 用短词,不要整句;人物/地点/动作/物体名优先。
- 不要编造素材库里没有的内容,也不要输出任何画面描述当事实。
- duration 是数字(秒),speed 是 0.25–4.0 的数字。
"""


def _llm() -> bool:
    try:
        import llm  # noqa: WPS433
        return llm.available()
    except Exception:  # noqa: BLE001
        return False


def _parse_plan(text: str) -> list[dict]:
    m = re.search(r"\{[\s\S]*\}", text or "")
    if not m:
        raise ValueError("模型没有返回 JSON")
    data = json.loads(m.group(0))
    slots = data.get("slots")
    if not isinstance(slots, list) or not slots:
        raise ValueError("模型返回的 slots 为空")
    return [s for s in slots if isinstance(s, dict)][:8]


def plan_slots(requirement: str, target_duration: float, *, model: bool | None = None) -> tuple[list[dict], str]:
    use_model = _llm() if model is None else bool(model)
    if use_model:
        try:
            import llm  # noqa: WPS433
            user = json.dumps({"需求": requirement, "目标时长秒": target_duration,
                               "可用转场": list(TRANSITIONS)}, ensure_ascii=False)
            slots = _parse_plan(llm.complete(_PLAN_SYSTEM, user, max_tokens=1200, temperature=0.2))
            return slots, "model"
        except Exception:  # noqa: BLE001 —— 模型失败如实降级
            pass
    n = max(2, min(6, round(target_duration / 3.5)))
    per = round(target_duration / n, 2)
    slots = [{"intent": f"镜头{i + 1}", "query": requirement, "duration": per,
              "transition": "硬切" if i == 0 else "淡入淡出", "speed": 1.0}
             for i in range(n)]
    return slots, "rules"


def _local_candidates(query: str, *, limit: int = 8) -> list[dict]:
    """先查语义索引;命中不够或都是占位段时,再做查询驱动精读。"""
    hits = lib.search(query, limit=limit)
    # 占位段(还没被 LLM 理解的整片)不算命中;而且必须真的有语义词命中,
    # 否则「雪山」这种本地根本没有的需求会被假召回,联网分支永远不触发。
    good = [h for h in hits
            if h.get("boundary_source") not in ("placeholder", "")
            and h["score"] >= 0.15
            and ("语义命中" in (h.get("reason") or "") or "llm_refine" in (h.get("source") or ""))]
    if good:
        return good
    # 粗召回没结果 → 让 LLM 直接看候选视频的密集帧,精确找那几秒
    if su.available():
        refined = lib.refine(query, limit=4, candidates=3)
        if refined.get("found"):
            return refined["items"]
    return hits  # 可能为空,交给调用方决定是否联网


def _web_candidates(query: str, *, limit: int = 3, allow: bool = True) -> tuple[list[dict], dict]:
    if not allow:
        return [], {"skipped": "用户关闭了联网找素材"}
    try:
        import web_sources  # noqa: WPS433
        r = web_sources.fetch(query, limit=limit)
        return r.get("items") or [], {"rejected": r.get("rejected", []),
                                      "tried": r.get("tried", []),
                                      "sources": r.get("sources", [])}
    except Exception as e:  # noqa: BLE001
        return [], {"error": f"{type(e).__name__}: {e}"}


def _cut_from(i: int, hit: dict, slot: dict, transition: str, used: set[str]) -> dict | None:
    src = hit.get("path")
    if not src:
        return None
    key = f"{src}:{hit.get('in_seconds', 0):.2f}"
    if key in used:
        return None
    used.add(key)
    s0 = float(hit["in_seconds"])
    s1 = float(hit["out_seconds"])
    want = max(0.5, min(float(slot.get("duration") or 3.0), 8.0))
    speed = max(0.25, min(4.0, float(slot.get("speed") or 1.0)))
    if s1 <= s0:
        return None
    # 片段比想要的长就截短,比想要的短就放慢(慢放不超过 0.5x,再慢会糊)
    if s1 - s0 > want * speed:
        s1 = s0 + want * speed
    elif s1 - s0 < want:
        speed = max(0.5, (s1 - s0) / want)
    return {
        "id": f"cut{i + 1}", "source": src,
        "source_in": round(s0, 3), "source_out": round(s1, 3),
        "speed": round(speed, 3), "layer": 0,
        "transition_in": {"type": transition, "duration": 0.4 if transition != "硬切" else 0.0},
        "reason": f"{slot.get('intent', '')}｜{hit.get('reason') or hit.get('description', '')[:80]}｜{hit.get('name', '')}",
        "_thumb": hit.get("thumb", ""),
        "_asset_id": hit.get("asset_id", ""),
        "_origin": hit.get("origin", "local"),
        "_title": hit.get("title", ""),
        "_license": hit.get("license", ""),
        "_source_url": hit.get("source_url", ""),
        "_creator": hit.get("creator", ""),
    }


def build(requirement: str, *, target_duration: float = 15.0,
          output: dict | None = None, model: bool | None = None,
          transition: str | None = None, allow_web: bool = True) -> dict:
    """组装 edit_decisions_v2 + 候选池。"""
    target = max(1.0, min(120.0, float(target_duration)))
    slots, mode = plan_slots(requirement, target, model=model)
    used: set[str] = set()
    cuts: list[dict] = []
    web_used: list[dict] = []
    trace: list[dict] = []
    for i, slot in enumerate(slots):
        query = str(slot.get("query") or requirement)
        local = _local_candidates(query)
        hits = list(local)
        origin = "local"
        if not hits:
            web_hits, meta = _web_candidates(query, limit=2, allow=allow_web)
            hits = web_hits
            origin = "web" if web_hits else "missing"
            web_used += web_hits
            trace.append({"slot": i + 1, "query": query, "local": 0,
                          "web": len(web_hits), "web_meta": meta})
        else:
            trace.append({"slot": i + 1, "query": query, "local": len(local), "web": 0})
        tr = transition if i > 0 and transition in TRANSITIONS else (
            slot.get("transition") if slot.get("transition") in TRANSITIONS else "硬切")
        if i == 0:
            tr = "硬切"
        picked = None
        for h in hits:
            picked = _cut_from(i, h, slot, tr, used)
            if picked:
                break
        if picked:
            if origin == "web":
                picked["reason"] += f"｜联网合规素材:{picked.get('_license', '')}"
            cuts.append(picked)
    doc = blank_doc("剪辑短片", requirement)
    doc["output"] = {"width": int((output or {}).get("width") or 1080),
                     "height": int((output or {}).get("height") or 1920),
                     "fps": int((output or {}).get("fps") or 30)}
    doc.update({"mode": mode, "model": mode == "model", "target_duration": target,
                "slots": slots, "cuts": cuts, "trace": trace,
                "web_used": web_used, "allow_web": allow_web,
                "candidates": lib.search(requirement, limit=12)})
    if not cuts:
        # 本地没命中、联网也没取到:如实留空,不伪造一条无关素材充数。
        # UI 据此显示「没有找到符合需求的素材」并给出原因(含权利闸门拦截)。
        doc["total"] = 0.0
        doc["missing_reason"] = _missing_reason(trace)
        return doc
    try:
        norm, total = validate(doc)
        doc["total"] = total
        doc["cuts"] = [{**c, **{k: v for k, v in n.items()
                                if k in ("source_in", "source_out", "timeline_start",
                                         "timeline_duration", "transition_in", "transform")}}
                       for c, n in zip(cuts, norm["cuts"])]
    except Exception as e:  # noqa: BLE001
        doc["contract_error"] = str(e)
    return doc


def _missing_reason(trace: list[dict]) -> str:
    bits = ["本地素材库没有符合这段需求的语义片段。"]
    for t in trace:
        meta = t.get("web_meta") or {}
        if meta.get("skipped"):
            bits.append("你关闭了联网找素材。")
        elif meta.get("error"):
            bits.append("联网检索出错:" + str(meta["error"])[:120])
        elif meta.get("tried"):
            bits.append("联网来源暂不可用:" + "、".join(str(x) for x in meta["tried"][:3]))
        if meta.get("rejected"):
            bits.append(f"{len(meta['rejected'])} 条候选因权利不明被拦下(不是可商用素材)。")
    return " ".join(dict.fromkeys(bits))[:500]
