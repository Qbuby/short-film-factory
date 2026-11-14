"""联网补素材 —— 只用明确可商用/公有领域/CC0 的来源,不拉别人的视频。

用户要求「素材库里没有符合语义的片段时,去网上实时找素材,但不要那种
明显是别人的素材」。这里的落地口径:

  1. 白名单只允许仓库里已写明「Public domain / CC0 / free commercial use,
     no attribution required」的适配器(见各 stock_sources/*.py 的 _LICENSE)。
  2. 逐条**按权利文本再判一次**:含 verify per item / educational / attribution
     required / with caveats / 许可不明 的一律拒绝,不把「适配器标了能用」
     当成「这条素材能用」。
  3. 绝不启用 video_downloader / yt-dlp:那是参考视频分析工具,不是素材来源。
  4. 每条落库都带 source / source_url / license / creator,成片的
     edit_decisions 里也带同样字段,能追溯、能出 CREDITS。

依赖只有 requests(打包 runtime 已有)。bs4 不在包里,所以网页抓取型
适配器(Mixkit/NOAA/ESA/JAXA/Dareful)默认不启用,即使它们权利合规。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

from app_paths import get_paths
import material_library as lib

# 权利文本里出现这些词 = 不能保证「不是别人的素材 / 可商用 / 免署名」
REJECT_WORDS = (
    "verify per item", "verify per-file", "with caveats",
    # 不要写裸的 "attribution required":它是 "no attribution required" 的子串,
    # 会把 Pexels/Pixabay/Coverr 这类明确免署名的许可全部误拒。
    "attribution is required", "requires attribution", "attribution needed",
    "cc by 3.0", "cc by 4.0", "cc by-sa",
    "educational", "informational use", "rights status varies", "permission",
    "all rights reserved", "editorial", "non-commercial", "nc-",
    "hotlinked", "use returned",
)
ACCEPT_WORDS = (
    "public domain", "cc0", "no attribution required", "free for commercial",
    "free, no attribution", "cc0-like", "cc0 equivalent",
)

# 只列仓库里权利文本明确、且不需要 bs4 的适配器。
# 需要 API key 的(Pexels/Pixabay)也保留:用户配了才可用,不配自动跳过。
ALLOWED = {
    "pexels": ("Pexels", "PEXELS_API_KEY"),
    "pixabay_video": ("Pixabay", "PIXABAY_API_KEY"),
    "coverr": ("Coverr", ""),
    "pond5_pd": ("Pond5 Public Domain", ""),
    "nara": ("NARA", ""),
    "nasa": ("NASA", ""),          # 逐条会被 "with caveats" 拦下,留着做兜底
    "loc": ("Library of Congress", ""),  # 逐条按 rights 判定
    "archive_org": ("Archive.org", ""),  # 只放 Prelinger
}

# 明确禁用:别人的平台内容 / 需署名 / 仅教育用途 / 许可不明
DENIED = {"unsplash", "wikimedia", "esa", "dareful", "videvo", "jaxa",
          "mixkit", "noaa", "video_downloader", "youtube", "tiktok"}


def rights_ok(license_text: str, *, source: str = "") -> tuple[bool, str]:
    """结构化判断一条候选的权利文本。宁可拒,不可猜。"""
    t = (license_text or "").strip().lower()
    if not t:
        return False, "缺少许可信息"
    for w in REJECT_WORDS:
        if w in t:
            return False, f"许可含「{w}」,不能保证可商用/免署名"
    if source == "archive_org" and "prelinger" not in t:
        return False, "Archive.org 仅放行 Prelinger 公有领域子集"
    if not any(w in t for w in ACCEPT_WORDS):
        return False, f"许可未明确可商用/公有领域:{license_text[:80]}"
    return True, ""


def _sources_module():
    """按路径加载仓库里的 stock_sources 包(不在打包 runtime 里也能用)。"""
    repo = get_paths().repo / "tools" / "video"
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    import stock_sources  # type: ignore  # noqa: WPS433
    return stock_sources


def available_sources() -> list[dict]:
    out = []
    try:
        mod = _sources_module()
        found = {s.name: s for s in mod.all_sources()}
    except Exception:  # noqa: BLE001
        return []
    for name, (label, key_env) in ALLOWED.items():
        s = found.get(name)
        if not s or name in DENIED:
            continue
        key_ok = not key_env or bool(os.environ.get(key_env))
        try:
            runtime_ok = bool(s.is_available())
        except Exception:  # noqa: BLE001
            runtime_ok = False
        out.append({"name": name, "label": label, "key_configured": key_ok,
                    "runtime_ok": runtime_ok, "enabled": key_ok and runtime_ok,
                    "key_env": key_env})
    return out


def _download(url: str, dest: Path, *, timeout: int = 120) -> None:
    """下载到独立临时文件再原子改名;不接受任意路径。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "ShortFilmFactory/1.3"})
    with urllib.request.urlopen(req, timeout=timeout) as r, tmp.open("wb") as f:
        f.write(r.read())
    if tmp.stat().st_size < 10240:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("下载内容过小,疑似不是视频")
    tmp.replace(dest)


def fetch(query: str, *, limit: int = 3, on_progress=None) -> dict:
    """检索并下载合规素材。返回可直接进 edit_decisions 的条目。

    注意:这些是**别人上传但明确放弃权利/公有领域的素材**,不是「别人的
    视频平台内容」。每条都带出处与许可,成片可出 CREDITS。
    """
    results, tried, rejected = [], [], []
    try:
        mod = _sources_module()
        found = {s.name: s for s in mod.all_sources()}
        filters_cls = getattr(mod, "SearchFilters", None)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"素材适配器不可用: {e}", "items": []}
    store = lib.library_root() / "web"
    store.mkdir(parents=True, exist_ok=True)
    for meta in available_sources():
        if not meta["enabled"] or len(results) >= limit:
            continue
        src = found.get(meta["name"])
        if not src:
            continue
        try:
            f = mod.SearchFilters(kind="video", per_page=8) if hasattr(mod, "SearchFilters") else None
            cands = src.search(query, f)
        except Exception as e:  # noqa: BLE001
            tried.append(f"{meta['name']}: 检索失败 {type(e).__name__}")
            continue
        for c in cands:
            if len(results) >= limit:
                break
            lic = str(getattr(c, "license", "") or "")
            ok, why = rights_ok(lic, source=meta["name"])
            if not ok:
                rejected.append({"source": meta["name"], "license": lic[:100], "why": why})
                continue
            url = str(getattr(c, "download_url", "") or "")
            if not url.startswith(("http://", "https://")):
                continue
            cid = hashlib.sha256(url.encode()).hexdigest()[:16]
            dest = store / f"{cid}.mp4"
            try:
                if not dest.is_file():
                    _download(url, dest)
                if on_progress:
                    on_progress(meta["name"], dest.name)
                info = lib.probe(dest)
                if info["duration"] <= 0:
                    dest.unlink(missing_ok=True)
                    continue
                with lib.connect() as con:
                    con.execute("""INSERT OR REPLACE INTO web_assets
                        (id,path,source,source_url,license,creator,query,added)
                        VALUES (?,?,?,?,?,?,?,?)""",
                        (cid, str(dest), meta["name"], str(getattr(c, "source_url", "") or ""),
                         lic, str(getattr(c, "creator", "") or ""), query, time.time()))
                results.append({
                    "asset_id": cid, "path": str(dest), "name": dest.name,
                    "in_seconds": 0.0, "out_seconds": min(info["duration"], 8.0),
                    "duration": min(info["duration"], 8.0),
                    "title": f"联网素材 · {meta['label']}",
                    "description": query,
                    "tags": json.dumps([query, meta["label"]], ensure_ascii=False),
                    "source": meta["name"], "source_url": str(getattr(c, "source_url", "") or ""),
                    "license": lic, "creator": str(getattr(c, "creator", "") or ""),
                    "reason": f"本地素材库未命中,联网取自 {meta['label']}({lic})",
                    "origin": "web",
                })
            except Exception as e:  # noqa: BLE001
                tried.append(f"{meta['name']}: {type(e).__name__}: {e}"[:160])
    return {"ok": True, "items": results, "tried": tried[:10],
            "rejected": rejected[:10], "sources": available_sources()}


def credits(items: list[dict]) -> str:
    """给出片附带的 CREDITS 文本,追溯每条联网素材。"""
    rows = ["# 素材来源", ""]
    for x in items:
        if x.get("origin") != "web":
            continue
        rows.append(f"- {x['name']} · {x.get('source')} · {x.get('license')}")
        if x.get("creator"):
            rows.append(f"  作者:{x['creator']}")
        if x.get("source_url"):
            rows.append(f"  出处:{x['source_url']}")
    return "\n".join(rows) + "\n"
