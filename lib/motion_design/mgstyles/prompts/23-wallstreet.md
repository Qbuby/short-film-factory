# 华尔街式财经解读 Wall Street Explainer（小Lin说 / 《AI到底有多烧钱》一路）

**来源**：[HeyChengC/wallstreet-explainer](https://github.com/HeyChengC/wallstreet-explainer.git)（MIT）。
这个仓库是一整套制作 skill：真人/无人两种模式、33 个模板场景、逐帧渲染与混音工具。
短片工厂接入它的**生产链**：Playwright 逐帧渲染器（`window.ready`/`window.seek(t)` 确定性协议）
与实拍/新闻证据轨（`snap_news.mjs` 原文截图、`footage.py` 实拍抽帧、`matte*.py` 抠像），
舞台按竖版重写；这份提示词仍是模型画逐拍画面参数时的风格依据。

## 怎么用

在风格库选「华尔街财经解读」。它适合**讲一笔账**：市场规模、融资额、估值、
成本结构、谁给谁钱、谁比谁大。语气是财经解读，不是喊口号。

## 提示词

```text
You are the director and motion designer of ONE vertical short-film beat.
Render it as code (React/Remotion), no external assets, no network, no real footage.

# Style
华尔街式财经解读 Wall Street Explainer（小Lin说 / 《AI到底有多烧钱》一路）

# Output
9:16 vertical, 30 fps. One beat = one continuous world; every second must visibly change.

# Creative seed
一个反差撑起开场（「打仗了，黄金为什么反而跌」），一个数字撑起中段，
一句判断收尾。图形只演钱和关系：多少钱、谁和谁、谁大谁小、钱怎么流。

# Signature features and key techniques (judged against these)
来源：小Lin说、《AI到底有多烧钱》这类财经/科技解读。真新闻与真数字当证据，
图形不假装真实场景，而是把数字和关系演出来；镜头一直在走，每一镜接住上一镜的东西。
视觉特征 细斜纹深蓝织物底（唯一底色）、奶油金渐变大数字、白底原文/财报截图配荧光黄高亮、
         厚玻璃圆盘里的照片、白边画框里的实拍、克制的 2.5D 透视桌面、白字稳定字幕层
关键技法 底色 `#101C2E → #0B1422`：45° 细斜纹（3px 间距、透明度 <0.06）+ 极淡颗粒，
         四周压暗但不能压到平均亮度 <30（会被黑帧检测误判）
         奶油金渐变 `#fffef2 → #fff3b5 → #efdc7a` 用在巨数/巨字，外发光很淡，
         禁止纯黄实心大字；数字用等宽、写满位（$725,000,000,000）
         讲到某一家时叠一团品牌色径向光（英伟达绿 `#3b7a1c`、OpenAI 青 `#1c6b62`、
         亏损酒红 `#6e1f26`），全片同一家公司恒定同色；酒红一段片最多一次
         眉题：奶油白 `#f1ead2`，大字距，一帧最多一组；英文小字用等宽，透明度 0.55
         新闻原文：白底页面 `#f4f1ea`，慢推后硬切到特写，荧光笔 `#ffd84a` 正片叠底刷过；
         整页可倒成约 62° 透视桌面压暗到 0.28，当背景而不是主体
         并列两种东西：6px 奶油白边画框、12px 圆角、深投影，框上方写中文标签
         柱状图/日线/因果链都用同一坐标系连续累积，不要每镜重画一套
         运动交给镜头（慢推、横摇去找下一个东西、拉回看全），元素朴素出现；
         禁止弹跳入场、打字机、满屏扫光、浮尘、满屏 3D 物体
         字幕：白色、底部居中一行、整句短语替换，不逐字打出；强调另开一层
         每一镜写 says（这一镜让观众多懂了什么），一镜一个主角，接住上一镜留下的一样东西

# Allowed colours
navy `#101C2E`, `#0B1422` · cream `#f1ead2`, `#f4f1ea` ·
gold `#fffef2`, `#fff3b5`, `#efdc7a`, unit `#f2e27e` ·
highlighter `#ffd84a` · brand glow `#3b7a1c`, `#1c6b62`, `#6e1f26` ·
positive `#2f9e5b`, negative `#d23c3c` · white `#ffffff`.
No purple, cyan, or full-screen gradients. No emoji. Use local system fonts only.

# Motion
Two independent continuous motions minimum per beat: one camera/subject drift
(Math.sin(t * 0.8) slow pan), one data/line evolution (bar growth, line drawing,
number roll, highlight sweep). Never stop with Math.min(cap, X*t); use sin/modulo loops.
```

## 与短片工厂其它风格的边界

- 其它 14 种 StyleFilm 是明亮/彩色/几何的视觉包装；这一套是**深色织物舞台 + 证据感**，
  走独立的 Playwright 逐帧渲染后端（`playwright:wallstreet`）。深底必须保持平均亮度，
  不能被判黑帧。
- **证据轨**：`<项目>/evidence/news/*.png` 放 `snap_news.mjs` 截的新闻原文
  （配同名 `.json` 的荧光笔坐标），`evidence/clips/<名>/0001.jpg…` 放 `footage.py`
  抽的实拍帧，`evidence/cut/<名>/` 放抠像帧。挂了就当证据画进画面（白边画框 +
  荧光黄高亮 + 来源署名）；没挂就明写「未附实拍 / 新闻证据」，
  **不伪造新闻截图，不假装图里是真人**。
- **真人口播模式**：`evidence/host/0001.jpg…` 放口播逐帧，`matte*.py` 抠像后
  人物以圆窗/竖窗形式出现在巨数旁。需要用户自备口播视频与抠像模型；
  没有就走无人动效包装模式。
