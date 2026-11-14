# 短片工厂 · Short Film Factory

Windows 桌面端的短视频生产工具，版本 **1.3.0**。同一个客户端里有两种生产模式：

- **生成模式**：把文字/链接变成 16 种代码绘制风格的短片（Remotion 逐帧渲染；第 16 种 `mg-wallstreet` 走独立的 Playwright 逐帧后端 + 实拍/新闻证据轨）。
- **剪辑模式**：登记本机素材路径 → 多模态 LLM 整体理解素材（语义分段与标签都是它理解后的输出）→ 输入需求锁定片段 → 转场 / 变速 / 画中画 / 文字卡 → 剪辑成片。本地没有符合语义的片段时，可联网找明确可商用 / 公有领域的素材，逐条记录许可与出处。

## 快速开始

发行包请双击 `短片工厂.exe`，在独立 WebView2 窗口中使用；不要只移动 EXE。
从源码运行：

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python tools\motion_design\film_ui.py
```

桌面壳、模型配置、出片参数、数据位置与完整操作说明见 [docs/短片工厂-使用指南.md](docs/短片工厂-使用指南.md)。

模型配置写在 `%LOCALAPPDATA%\ShortFilmFactory\config\.env`（**不要提交**）：

```
MOTION_LLM_BASE=https://your-openai-compatible-endpoint/v1
MOTION_LLM_KEY=...
MOTION_LLM_MODEL=...
```

视觉理解优先读 `MOTION_VISION_*`；没配时复用同一套 `MOTION_LLM_*`（若端点支持图片输入）。两者都没配时，剪辑模式会明确进入「受限模式」，不冒充语义理解。

## 剪辑模式怎么工作

1. **登记**：只登记本机文件/文件夹路径与元数据，不复制、不移动原文件。索引在 `%LOCALAPPDATA%\ShortFilmFactory\library\`，跨版本保留；原文件缺失会显式告警并提供批量重定位。
2. **理解**：按 1 帧/秒抽成带时间码的接触表，交给多模态 LLM 整体看完，输出整片摘要、全局标签和**语义分段**（起止秒、标题、描述、具体名词标签）。段数与边界由内容转折决定，不是像素差；numpy 帧差只把模型给的秒数对齐到帧。**一个视频里只出现 3 秒的画面也会单独成段**。
3. **锁定**：需求先扩成检索词，命中语义索引；粗召回不够时对候选视频做「查询驱动精读」，让模型精确指出那几秒。每条命中都带 `reason` 与 `source_in/source_out`，可解释、可替换、可撤销。
4. **联网补素材**：本地确实没有符合语义的片段时才触发。只启用明确写了 Public domain / CC0 / 免费商用且免署名的来源，逐条做权利闸门（拦掉 `verify per item`、需署名、仅教育用途、许可不明）；**不下载别人视频平台的内容**。联网素材的出处与许可写进 `CREDITS.md`。
5. **出片**：ffmpeg 直出，归一化 → 变速 → xfade 转场 → 画中画 → 文字卡 → 音画 mux。预览走低分辨率快速路径，成片走标准路径。

剪辑决策用 `edit_decisions_v2` 契约（`tools/motion_design/edit_contract.py`），把 `source_in/source_out`、`timeline_start`、`speed`、`layer` 的语义一次钉死，与生成类视频的 `edit_decisions` 隔离。

## 目录

| 路径 | 内容 |
|---|---|
| `tools/motion_design/` | 桌面后端、CLI、UI、渲染后端、剪辑模式全部代码 |
| `tools/motion_design/wallstreet/` | Playwright 逐帧渲染器与 vendored skill 工具 |
| `tools/video/stock_sources/` | 合规联网素材适配器 |
| `lib/motion_design/mgstyles/` | 风格提示词与程序化音频 |
| `remotion-composer/` | Remotion 工程源码、配置与版本化风格样片 |
| `licenses/` | 第三方组件许可与归属说明 |
| `docs/` | 使用指南与风格样片验收说明 |

## 许可与归属

本项目主体为 **AGPL-3.0**，见 [LICENSE](LICENSE)。

- `mg-styles-15` 风格语言（MIT，Vincentwei1021）：`lib/motion_design/NOTICE.md`、`lib/motion_design/mgstyles/LICENSE`
- `wallstreet-explainer` 的 Playwright 逐帧渲染器与实拍/新闻工具（MIT，HeyChengC）：`licenses/wallstreet-explainer-NOTICE.md`、`licenses/wallstreet-explainer-LICENSE.txt`
- Remotion、字体、WebView2 等各自的许可按原组件条款保留

上游 skill 的字体不随包分发；新闻截图与实拍下载需要联网；逐帧抠像需要用户自备 rembg 模型。**不伪造新闻来源，不把代码绘制的画面冒充真人实拍。**

## 边界

- 素材与作品留在用户本机；索引只存路径与元数据。
- 没有配置模型时，写稿与素材理解都走明确标注的受限模式，不伪造结果。
- 客观检查（死场 / 黑帧 / 静音 / 响度）通过只说明技术指标通过，不代表美术质量通过。
- 联网素材仅为权利明确可商用的来源；使用者仍应自行核对具体条目的最新条款。
