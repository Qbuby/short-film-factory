"""把一个链接变成可用的素材正文。

普通人手上的是链接,不是稿子。所以入口必须能吃链接:
  公众号(mp.weixin.qq.com)  移动端 UA + 正文抽取
  抖音 / B站 / 小红书 / 视频号 / YouTube …  交给 yt-dlp 拿标题、简介、字幕

四条策略按顺序尝试,谁先成功用谁:
  1) 公众号链接 → 自带的正文抽取(带移动端 UA,绕过「环境异常」)
  2) 其它视频平台 → yt-dlp(取描述/字幕;没字幕就取标题和简介)
  3) 普通网页 → 直接抓正文,剥标签
  4) 前三者都失败(服务端只回 JS 空壳,如抖音) → 用本机 Chrome/Edge 真渲染一次

产出:纯文本 + 标题 + 来源 URL,写进 source.txt 供后续起草使用。

用法:
    python tools/motion_design/fetch_source.py --url https://mp.weixin.qq.com/s/xxx
    python tools/motion_design/fetch_source.py --url ... --out projects/x/source.txt
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1 MicroMessenger/8.0.40")
DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")

# 各平台的中文名(给用户看的)
PLATFORMS = [
    (r"mp\.weixin\.qq\.com", "微信公众号"),
    (r"channels\.weixin\.qq\.com|weixin\.qq\.com/sph", "微信视频号"),
    (r"douyin\.com|iesdouyin\.com|v\.douyin\.com", "抖音"),
    (r"bilibili\.com|b23\.tv", "哔哩哔哩"),
    (r"xiaohongshu\.com|xhslink\.com", "小红书"),
    (r"kuaishou\.com", "快手"),
    (r"youtube\.com|youtu\.be", "YouTube"),
    (r"weibo\.com", "微博"),
    (r"zhihu\.com", "知乎"),
    (r"toutiao\.com", "今日头条"),
]


def platform_of(url: str) -> str:
    for pat, name in PLATFORMS:
        if re.search(pat, url):
            return name
    return "网页"


def _fetch(url: str, ua: str, timeout: int = 45) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        enc = (r.headers.get("Content-Encoding") or "").lower()
    if "gzip" in enc or raw[:2] == b"\x1f\x8b":
        import gzip
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    for enc_try in ("utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(enc_try)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _strip_tags(fragment: str) -> str:
    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", fragment)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</section>|</h[1-6]>", "\n", t)
    t = re.sub(r"(?s)<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\xa0]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def fetch_wechat(url: str) -> dict:
    """公众号文章:移动端 UA 能拿到正文(桌面 UA 会被「环境异常」拦)。"""
    page = _fetch(url, MOBILE_UA)
    if "环境异常" in page[:4000] or "参数错误" in page[:4000]:
        # 再试一次桌面 UA,有的文章桌面端反而能过
        page = _fetch(url, DESKTOP_UA)
    m = re.search(r"var msg_title\s*=\s*['\"](.+?)['\"]", page)
    title = m.group(1) if m else ""
    if not title:
        m = re.search(r"<h1[^>]*id=\"activity-name\"[^>]*>(.*?)</h1>", page, re.S)
        title = _strip_tags(m.group(1)) if m else ""
    if not title:
        m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', page)
        title = html.unescape(m.group(1)) if m else ""
    if not title:
        m = re.search(r'<h1[^>]*>(.*?)</h1>', page, re.S)
        title = _strip_tags(m.group(1)) if m else ""
    if not title:
        m = re.search(r"<title>(.*?)</title>", page, re.S)
        title = _strip_tags(m.group(1)) if m else ""
    body_m = re.search(r'(?s)<div[^>]*id="js_content".*?(?=<div[^>]*id="js_sg_bar")', page)
    if not body_m:
        body_m = re.search(r'(?s)<div[^>]*id="publish_area".*?(?=<div[^>]*id="js_sg_bar")', page)
    body = _strip_tags(body_m.group(0)) if body_m else ""
    body = _clean_wechat(body)
    if len(body) < 30:
        # 正文可能被反爬挡了,但标题通常还在 —— 标题+整页兜底也比直接失败强
        if not title:
            raise RuntimeError("公众号正文和标题都没取到(文章可能已删除、需登录或被反爬拦截)")
        body = _clean_wechat(_strip_tags(page))
        if len(body) < 50:
            raise RuntimeError("公众号正文没取到(文章可能已删除、需登录或被反爬拦截)")
    return {"title": title.strip(), "text": body, "platform": "微信公众号"}


NOISE_LINES = re.compile(
    r"^(关注[\u4e00-\u9fa5A-Za-z]{0,10}|视频|小程序|赞|轻点两下取消赞|在看|轻点两下取消在看|分享|留言|收藏|"
    r"听过|在小说阅读器读本章|去阅读|在公众号小说中沉浸阅读|扫码关注|微信扫一扫|IP属地|编辑|朗读|"
    r"\d+人?读过|海量资讯|举报|投诉|赞赏|喜欢|在看)$")


def _clean_wechat(body: str) -> str:
    """去掉公众号正文里混进来的导航/互动按钮文案。"""
    keep = []
    for ln in body.split("\n"):
        t = ln.strip()
        if not t or NOISE_LINES.match(t):
            continue
        keep.append(t)
    return re.sub(r"\n{2,}", "\n", "\n".join(keep)).strip()


def fetch_yt_dlp(url: str) -> dict:
    """视频平台:用 yt-dlp 取元数据和字幕。"""
    exe = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if not exe:
        raise RuntimeError("没装 yt-dlp,解析不了这个链接")
    meta = subprocess.run([exe, "--dump-json", "--no-warnings", "--skip-download", url],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    if meta.returncode or not meta.stdout.strip():
        raise RuntimeError(f"yt-dlp 解析失败:{(meta.stderr or '').strip()[:200]}")
    info = json.loads(meta.stdout.strip().splitlines()[0])
    title = info.get("title") or ""
    desc = (info.get("description") or "").strip()
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    langs = list(subs.keys()) or list(auto.keys())
    text = desc
    # 有字幕就用字幕,那才是"他讲了什么"
    for lang in ("zh-Hans", "zh-CN", "zh", "zh-Hant", "zh-TW", "en"):
        if lang in subs or lang in auto:
            src = subs.get(lang) or auto.get(lang) or []
            for s in src:
                if s.get("ext") in ("vtt", "srt"):
                    r = subprocess.run([exe, "--skip-download", "--write-auto-subs" if lang in auto else "--write-subs",
                                        "--sub-langs", lang, "--sub-format", "vtt", "-o", "-", url],
                                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
                    got = r.stdout or ""
                    if got.strip():
                        text = _strip_vtt(got)
                        break
            if text and text != desc:
                break
            break
    if not text or text.strip() in ("-", "none", "None", "null"):
        text = desc if desc.strip() not in ("-", "") else title
    if not text or text.strip() in ("-", "none"):
        raise RuntimeError("这个链接没有可用的字幕或简介(可能需要登录或开了会员)")
    return {"title": title, "text": text.strip(), "platform": platform_of(url),
            "duration": info.get("duration"), "author": info.get("uploader") or info.get("channel")}


def _strip_vtt(vtt: str) -> str:
    out = []
    for line in vtt.splitlines():
        line = line.strip()
        if not line or line.startswith("WEBVTT") or "-->" in line:
            continue
        if re.fullmatch(r"\d+", line):
            continue
        if re.search(r"<[^>]+>", line) and "c=" not in line:
            line = re.sub(r"<[^>]+>", "", line)
        if not out or out[-1] != line:
            out.append(line)
    return "\n".join(out)


def fetch_webpage(url: str) -> dict:
    """普通网页 / 公众号兜底。

    公众号的桌面 UA 有时能过、有时被「环境异常」拦;被拦时正文拿不到,
    但整页里仍有内容 —— 所以兜底路径要能清洗掉导航噪声后用。
    """
    page = _fetch(url, DESKTOP_UA)
    is_wechat = bool(re.search(r"mp\.weixin\.qq\.com", url))
    if is_wechat:
        # 公众号优先用移动端 UA 拿正文,拿不到再退回整页
        try:
            return fetch_wechat(url)
        except Exception:
            page = _fetch(url, MOBILE_UA)
    m = re.search(r"(?is)<article[^>]*>(.*?)</article>", page)
    body = _strip_tags(m.group(1)) if m else _strip_tags(page)
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
    title = _strip_tags(m.group(1)) if m else ""
    title = re.sub(r"^\s*微信公众平台\s*$", "", title).strip()
    if is_wechat:
        body = _clean_wechat(body)
        # 去掉开头重复的标题行
        if title and body.startswith(title):
            body = body[len(title):].lstrip("\n")
    if len(body) < 50:
        raise RuntimeError("网页正文太短,可能需要登录或有反爬")
    return {"title": title, "text": body[:60000], "platform": platform_of(url)}


def fetch_via_browser(url: str, timeout: float = 80.0) -> dict:
    """让本机浏览器真的渲染一次页面再取正文。

    抖音这类页面服务端只回 JS 空壳(实测 72KB 里正文 0 字),
    yt-dlp 又要求"新鲜 cookies",所以前三种方式都不可能成功。
    只有让浏览器执行完 JS,正文才存在于 DOM 里。
    """
    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    import browser_fetch  # noqa: WPS433

    if not browser_fetch.available():
        raise RuntimeError("本机没有 Chrome/Edge,无法渲染这个页面")
    r = browser_fetch.render(url, timeout=timeout)
    return {"title": r.get("title", ""), "text": r.get("text", ""),
            "platform": platform_of(url), "browser": r.get("browser", "")}


def fetch(url: str) -> dict:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise RuntimeError("这不是一个 http(s) 链接")
    if re.search(r"mp\.weixin\.qq\.com", url):
        try:
            return fetch_wechat(url)
        except Exception as e:
            print(f"[公众号解析失败] {e};改试通用方式", file=sys.stderr)
    try:
        return fetch_yt_dlp(url)
    except Exception as e:
        yerr = str(e)
    try:
        return fetch_webpage(url)
    except Exception as e:
        perr = str(e)
    # 第四种:真渲染。抖音/小红书这类站点,服务端响应里根本没有正文,
    # 前面三条路注定失败,只有浏览器执行完 JS 才有内容。
    try:
        return fetch_via_browser(url)
    except Exception as e:
        raise RuntimeError(
            f"四种方式都没成功。yt-dlp:{yerr[:100]} / 网页:{perr[:100]} / 浏览器:{str(e)[:120]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="把链接变成素材正文")
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", default="", help="写入的 txt 路径")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而不是文本")
    args = ap.parse_args()
    try:
        r = fetch(args.url)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 2
    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"{r['title']}\n\n{r['text']}\n", encoding="utf-8")
    if args.json:
        print(json.dumps({"ok": True, **r}, ensure_ascii=False))
    else:
        print(f"# {r.get('title') or '(无标题)'}\n# 来源:{r['platform']} {args.url}\n\n{r['text']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
