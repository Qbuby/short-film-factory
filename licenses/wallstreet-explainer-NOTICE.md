# wallstreet-explainer · 逐帧渲染器与实拍/新闻能力来源

短片工厂的 **mg-wallstreet（华尔街财经解读）** 模板，核心生产链来自：

- 仓库：https://github.com/HeyChengC/wallstreet-explainer.git
- 许可：MIT（见同目录 `wallstreet-explainer-LICENSE.txt`）

## 接入的内容（`tools/motion_design/wallstreet/`）

- **Playwright 逐帧渲染器**：移植它的 `window.ready` / `window.seek(t)` 确定性逐帧协议、
  JPEG 流喂 ffmpeg、多 worker 分段编码、空画面自检（`render_playwright.mjs`）。
  原仓库没有最后一环音画合成，短片工厂补上，直接出带 AAC 的成片。
- **实拍与新闻能力**：vendor 保留并接入原版 `snap_news.mjs`（新闻/报告原文截图 + 荧光笔坐标）、
  `footage.py`（实拍抽帧）、`matte*.py`（逐帧抠像）、`host_timeline.py`（口播逐词对齐）、
  `mix.py` / `sfx_synth.py` / `strip.py` / `motion_check.py`。
  产物挂进 `<project>/evidence/`，由逐帧舞台按 `(t-t0)*fps` 取帧显示。
- **舞台坐标**：按短片工厂竖版（9:16）重写（原版舞台是 1920×1080 横版）；
  画面主体由代码绘制（织物底、巨数、柱子、折线），实拍/新闻只作证据层。

## 边界（如实声明）

- **字体不随包分发**：原 skill 的 MiSans / 阿里妈妈数黑体 / Bebas Neue / Montserrat
  是用户自备文件（原仓库也不随仓库给）。缺字体时退系统字体，不影响出片。
- **外部依赖**：新闻截图与实拍下载需要联网 + Playwright；逐帧抠像需要
  `~/.rembg` 的 ONNX 模型与 onnxruntime。缺哪条就明确缺哪条，
  画面用代码图解并标注「未附实拍 / 新闻证据」，**不伪造新闻截图、不假装图里是真人**。
- Playwright npm 包（19MB）随包携带；浏览器优先用本机 Chrome/Edge，
  不背 400MB 的 Chromium 缓存。

样片里的金额与财报文字均使用**经多源核实的公开披露口径**（微软 FY2025 资本开支指引、
四巨头 2025 指引合计），画面上标注数据来源；引用的新闻截图保留真实来源署名。
