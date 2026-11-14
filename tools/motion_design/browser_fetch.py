"""浏览器兜底:抖音 / 小红书这类页面服务端只返回 JS 空壳,必须真渲染一次才有正文。

为什么需要它(全是实测,不是猜的):
  * `urllib` 抓 https://www.douyin.com/video/<id> → 72KB,剥完标签**正文 0 字**:
    `<body></body>` 加一段混淆脚本。清洗再狠也没用,内容根本不在服务端响应里。
  * yt-dlp 对抖音报 "Fresh cookies (not necessarily logged in) are needed";
    本机 Edge 的 cookie 被 DPAPI 锁住(`Failed to decrypt with DPAPI`),读不出来。
  * 分享页 `/share/video/<id>/` 只回标题("在抖音记录美好生活…"),没有文案。
  也就是说前三条路都不可能拿到正文,只有真浏览器能。

实现要点(踩过的坑都写在注释里):
  * 用 CDP 自己控制节奏,不用 `--dump-dom`:后者在 SPA 上会随机挂死
    (同样的参数 20 秒成功、80 秒不返回)。
  * 端口用 `--remote-debugging-port=0` 让浏览器自己挑,再读它写的
    `DevToolsActivePort` —— 指定端口时实测有时候根本不监听。
  * **必须轮询**:第 35 秒 body 只有 102 字("视频数据加载中"),第 72 秒才有 879 字。
    "睡 10 秒读一次"必然拿到空壳。
  * profile 用应用自己的固定目录(不在用户浏览器里),进程结束就杀掉。
"""
from __future__ import annotations

import base64
import json
import re
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# 正文长度到这个数就认为页面渲染完了(实测正文页 400~1500 字,空壳 0~120 字)
_ENOUGH = 400


class _WS:
    """CDP 只需要文本帧,自己拼握手和帧头,不引第三方库。"""

    def __init__(self, url: str, timeout: float = 20.0):
        rest = url[5:] if url.startswith("ws://") else url
        host_port, _, path = rest.partition("/")
        host, _, port = host_port.partition(":")
        self.sock = socket.create_connection((host, int(port)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            f"GET /{path} HTTP/1.1\r\nHost: {host_port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n".encode()
        )
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("WebSocket 握手被关闭")
            buf += chunk
        self.buf = buf.split(b"\r\n\r\n", 1)[1]
        self.seq = 0

    def evaluate(self, expression: str, timeout: float = 20.0):
        self.seq += 1
        want = self.seq
        self._send(json.dumps({"id": want, "method": "Runtime.evaluate",
                               "params": {"expression": expression, "returnByValue": True}}))
        end = time.time() + timeout
        while time.time() < end:
            msg = json.loads(self._recv(max(1.0, end - time.time())))
            if msg.get("id") != want:
                continue
            if "error" in msg:
                raise RuntimeError(str(msg["error"].get("message") or msg["error"])[:160])
            return (msg.get("result", {}).get("result") or {}).get("value")
        raise TimeoutError("CDP 求值超时")

    def _send(self, text: str) -> None:
        data = text.encode()
        mask = os.urandom(4)
        head = bytearray([0x81])
        n = len(data)
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head.append(0x80 | 126)
            head += struct.pack(">H", n)
        else:
            head.append(0x80 | 127)
            head += struct.pack(">Q", n)
        head += mask
        self.sock.sendall(bytes(head) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _need(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("WebSocket 已关闭")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _recv(self, timeout: float) -> str:
        self.sock.settimeout(timeout)
        while True:
            head = self._need(2)
            opcode = head[0] & 0x0F
            n = head[1] & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._need(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._need(8))[0]
            mask = self._need(4) if head[1] & 0x80 else b""
            data = self._need(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x8:
                raise RuntimeError("WebSocket 被对端关闭")
            if opcode in (0x9, 0xA):  # ping/pong
                continue
            return data.decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _candidates() -> list[str]:
    """Chrome 优先,其次 Edge。自带 WebView2 不能独立跑页面,所以不算。"""
    out: list[str] = []
    override = os.environ.get("OE_BROWSER_EXE", "").strip()
    if override and Path(override).is_file():
        out.append(override)
    for path in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ):
        if Path(path).is_file():
            out.append(path)
    return out


def available() -> bool:
    return bool(_candidates())


def _profile_dir() -> Path:
    """应用自己维护的渲染 profile,不碰用户的浏览器配置。"""
    base = os.environ.get("OE_RENDER_PROFILE", "").strip()
    if base:
        path = Path(base)
    else:
        local = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        path = local / "ShortFilmFactory" / "render-profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _wait_port(profile: Path, deadline: float) -> int:
    active = profile / "DevToolsActivePort"
    while time.time() < deadline:
        try:
            lines = active.read_text(encoding="utf-8", errors="replace").splitlines()
            if lines and lines[0].strip().isdigit():
                port = int(lines[0].strip())
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2).read()
                return port
        except Exception:  # noqa: BLE001 - 还没写出来就是没起来
            pass
        time.sleep(0.3)
    return 0


def _page_target(port: int, marker: str, deadline: float) -> dict | None:
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=3) as r:
                targets = json.loads(r.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            targets = []
        for t in targets:
            if t.get("type") != "page":
                continue
            cur = (t.get("url") or "").lower()
            if cur.startswith(("about:", "chrome://", "edge://", "chrome-extension://")):
                continue
            if marker and marker not in cur:
                continue
            if t.get("webSocketDebuggerUrl"):
                return t
        time.sleep(0.4)
    return None


# 优先按结构取文案:抖音的标题、正文、章节都有 data-e2e 标记。
# 这样能天然排除评论区(comment-list)和相关推荐(related-video)——
# 评论一句话也是长句,靠"行长/关键词"去猜必然误伤。实测整页 innerText 里
# 混着 10 条评论和 6 条其它视频标题,按结构取就不会。
_SELECTOR_JS = (
    "(() => {"
    "  const info = document.querySelector('[data-e2e=\"detail-video-info\"]');"
    "  const chap = document.querySelector('[data-e2e=\"chapter-container\"]');"
    "  const drop = '[data-e2e=\"comment-list\"],[data-e2e=\"comment-item\"],'"
    "    + '[data-e2e=\"related-video\"],[data-e2e=\"page-footer\"],'"
    "    + '[data-e2e=\"douyin-navigation\"],[data-e2e=\"video-player-share\"],'"
    "    + 'footer,nav';"
    # 用 display:none 临时藏起来,而不是 cloneNode:
    # innerText 依赖布局,离屏克隆出来的节点读出来是空的(实测只回 172 字)。
    "  const hidden = [];"
    "  document.querySelectorAll(drop).forEach(n => {"
    "    hidden.push([n, n.style.display]); n.style.display = 'none';"
    "  });"
    "  const body = document.body ? document.body.innerText : '';"
    "  hidden.forEach(([n, v]) => { n.style.display = v; });"
    "  return document.title + '\u0001'"
    "    + (info ? info.innerText : '') + '\u0002'"
    "    + (chap ? chap.innerText : '') + '\u0002'"
    "    + body;"
    "})()"
)

# 页面上这些是导航、页脚、播放器控件,不是文案
_NOISE = re.compile(
    r"(ICP|公网安备|营业执照|许可证|举报|网络文化经营|信息网络传播|广播电视|宗教信息|"
    r"药品医疗器械|人服证|算法推荐|体育饭圈|违法和不良|网络谣言|用户服务协议|隐私政策|"
    r"账号找回|联系我们|加入我们|友情链接|站点地图|广告投放|下载电脑客户端|下载抖音|"
    r"抖音电商|开启读屏|读屏标签|^\s*\d{2}:\d{2}\s*$|^\s*\d{2}:\d{2} / |"
    r"^精选$|^推荐$|^AI抖音$|^关注$|^朋友$|^我的$|^直播$|^放映厅$|^短剧$|^小游戏$|"
    r"^搜索$|^通知$|^消息$|^投稿$|^登录$|^壁纸$|^客户端$|^充钻石$|^清屏$|^倍速$|"
    r"^智能$|^连播$|^下一章$|^首页$|^下载抖音精选$|^搜索 抖音|^数据中心$|"
    r"打开「抖音|点击左上角|^听抖音$|^作者声明$|^发布时间:|^粉丝[\d.]|扫码|关注我|"
    r"^展开$|^收起$|^回复$|^分享$|^收藏$|^点赞$)")

# 时间戳行(章节列表里的 "00:00")单独识别
_STAMP = re.compile(r"^(?:\d{1,2}:\d{2})(?::\d{2})?$")


def _clean_text(raw: str, title: str) -> str:
    """把渲染出来的 innerText 收拾成可用素材。

    做法是"长的留着":抖音这类页面,正文与章节摘要是长句,
    导航/页脚/播放器控件都是短词。实测这样能干净地剩下文案。
    """
    keep: list[str] = []
    for line in raw.splitlines():
        t = line.strip()
        if len(t) < 12 or _STAMP.match(t) or _NOISE.search(t):
            continue
        if title and t == title.strip():
            continue
        if t in keep:
            continue
        keep.append(t)
    return chr(10).join(keep)


def render(url: str, timeout: float = 150.0) -> dict:
    """真渲染一次页面,返回 {title, text, browser}。

    拿不到内容 → RuntimeError(带每个浏览器的失败原因),调用方继续兜底。
    timeout 是**每个浏览器**的预算,默认 150 秒(实测约 75 秒能拿到正文)。
    """
    host = urllib.request.urlparse(url).hostname or ""
    errors: list[str] = []
    for exe in _candidates():
        started = time.time()
        profile = _profile_dir()
        proc = None
        try:
            proc = subprocess.Popen(
                [exe, "--headless=new", "--disable-gpu", "--no-first-run",
                 "--no-default-browser-check", "--disable-extensions", "--mute-audio",
                 "--disable-background-networking", "--disable-component-update",
                 "--remote-debugging-port=0", f"--user-data-dir={profile}",
                 "--window-size=1280,900", url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            port = _wait_port(profile, time.time() + min(80, timeout * 0.55))
            if not port:
                errors.append(f"{Path(exe).name}: 没拿到调试端口")
                continue
            # 用域名判断"是不是目标页",避免 about:blank 被当成页面
            marker = host.replace("www.", "")
            target = _page_target(port, marker, time.time() + 20)
            if not target:
                errors.append(f"{Path(exe).name}: 目标页没打开")
                continue
            conn = _WS(target["webSocketDebuggerUrl"])
            title = ""
            best = ""
            try:
                deadline = started + timeout
                while time.time() < deadline:
                    value = conn.evaluate(_SELECTOR_JS) or ""
                    t, _, rest = value.partition("\x01")
                    info, _, body = rest.partition("\x02")
                    chapters, _, page = body.partition("\x02")
                    title = title or (t or "").strip()
                    combined = "\n".join(x.strip() for x in (info, chapters, page) if x.strip())
                    if len(combined) > len(best):
                        best = combined
                    # 停止条件只看"真正的内容块":章节摘要或去噪正文。
                    # 不能看标题信息块 —— 它一开始就有标题和发布时间,
                    # 早停会拿到一条只有标题的假结果(实测过)。
                    if len(chapters.strip()) >= 40 or len(page.strip()) >= _ENOUGH:
                        break
                    time.sleep(1.5)
            finally:
                conn.close()
            text = _clean_text(best, title)
            if len(text) < 40:
                errors.append(f"{Path(exe).name}: 渲染后仍无正文")
                continue
            return {"title": title, "text": text, "browser": Path(exe).name}
        except Exception as e:  # noqa: BLE001 - 换下一个浏览器
            errors.append(f"{Path(exe).name}: {type(e).__name__}: {str(e)[:80]}")
        finally:
            if proc is not None:
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
    raise RuntimeError("; ".join(errors) if errors else "没有可用的浏览器")


if __name__ == "__main__":
    try:
        result = render(sys.argv[1])
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)[:300]}, ensure_ascii=False))
        raise SystemExit(2)
    print(json.dumps({"ok": True, "browser": result["browser"], "title": result["title"],
                      "chars": len(result["text"])}, ensure_ascii=False))
