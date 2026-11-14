"""为风格库生成「样张图」——让人一眼看懂风格长什么样。

文字描述("白描边贴纸、大字报")对普通人没有画面感。这里给每个风格渲染
一张真实的预览帧:用该风格的配色、字体气质和质感,画一个代表性的画面。

做法:每个风格一段 HTML/CSS 片段 → 拼成一张大图 → 用 harness 的 Chrome 截�� →
按风格切成 PNG。图片是渲出来的,不是手画的示意图。

用法:
    python tools/motion_design/style_preview.py            # 生成到 remotion-composer/public/styles
    python tools/motion_design/style_preview.py --only mg-paperclip
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools" / "motion_design"
OUT = REPO / "remotion-composer" / "public" / "styles"
HARNESS = REPO / "lib" / "motion_design" / "mgstyles" / "harness"

W, H = 540, 960  # 单张样张尺寸(竖版 9:16)


def _frame(body: str, bg: str, extra: str = "") -> str:
    return f"""
    <div class="frame" style="background:{bg};{extra}">
      {body}
    </div>"""


# ── 各风格的画面配方。body 用绝对定位,风格特征写死在 CSS 里 ──────────────
STYLES: dict[str, dict] = {
    "mg-paperclip": {
        "bg": "#E8EDF0",
        "html": """
      <div class="grid"></div>
      <div class="sticker" style="left:44px;top:120px;width:452px;background:#FAF4E8">
        <div class="t1">你的脸</div>
        <div class="t2">正在替你下单</div>
      </div>
      <div class="note" style="left:44px;top:600px;width:452px">白描边 · 图章 · 纸纹</div>
      <div class="stamp" style="left:60px;top:760px">可你根本不在场</div>""",
        "css": """
      .sticker{border:9px solid #fff;outline:2px solid rgba(23,40,56,.5);outline-offset:9px;border-radius:12px;
               padding:26px 22px;box-shadow:0 12px 26px rgba(23,40,56,.18)}
      .t1{font-size:52px;font-weight:900;color:#172838;line-height:1.05}
      .t2{font-size:46px;font-weight:900;color:#F04438;line-height:1.1;margin-top:6px}
      .stamp{border:6px solid #F04438;color:#F04438;font-size:34px;font-weight:900;padding:8px 18px;
             background:rgba(255,255,255,.8);transform:rotate(-6deg);border-radius:8px}
      .note{background:#fff;border:4px solid #172838;border-radius:8px;padding:14px 16px;font-size:24px;
            font-weight:700;color:#172838}
      .grid{position:absolute;inset:0;background-image:
            linear-gradient(#AFC0CB 1px,transparent 1px),linear-gradient(90deg,#AFC0CB 1px,transparent 1px);
            background-size:40px 40px;opacity:.4}""",
    },
    "mg-collage": {
        "bg": "#D9CDB8",
        "html": """
      <div class="tear" style="left:30px;top:90px;width:300px;height:250px;transform:rotate(-4deg)">
        <div class="news">旧报纸剪贴</div></div>
      <div class="tear2" style="left:250px;top:300px;width:270px;height:230px;transform:rotate(3deg)">
        <div class="news2">财经剪报</div></div>
      <div class="seal" style="left:60px;top:660px">剪报</div>""",
        "css": """
      .tear{background:#F3EBDD;border:1px solid #B7A88D;box-shadow:6px 8px 0 rgba(0,0,0,.14);padding:20px}
      .tear2{background:#E8DCC6;border:1px solid #B7A88D;box-shadow:6px 8px 0 rgba(0,0,0,.14);padding:20px}
      .news{font-family:"SimSun",serif;font-size:30px;font-weight:700;color:#3A3226;text-align:center;line-height:1.5}
      .news2{font-family:"SimSun",serif;font-size:26px;color:#4A4034;text-align:center;line-height:1.5}
      .seal{border:5px solid #B03A2E;color:#B03A2E;font-size:40px;font-weight:900;padding:8px 20px;
            transform:rotate(-12deg);border-radius:6px;font-family:"SimHei"}""",
    },
    "mg-hud": {
        "bg": "#04121A",
        "html": """
      <div class="ring"></div>
      <div class="hud-t">−3.46%</div>
      <div class="hud-s">NASDAQ · 10/30</div>
      <div class="bars"><i style="height:36%"></i><i style="height:58%"></i><i style="height:44%"></i>
        <i style="height:80%"></i><i style="height:66%"></i><i style="height:92%"></i></div>
      <div class="scan"></div>""",
        "css": """
      .ring{position:absolute;left:120px;top:180px;width:300px;height:300px;border:2px solid #17E0C4;
            border-radius:50%;box-shadow:0 0 40px rgba(23,224,196,.35) inset}
      .hud-t{position:absolute;top:280px;left:0;right:0;text-align:center;font-family:Consolas,monospace;
             font-size:64px;font-weight:700;color:#17E0C4;text-shadow:0 0 24px rgba(23,224,196,.6)}
      .hud-s{position:absolute;top:400px;left:0;right:0;text-align:center;font-family:Consolas,monospace;
             font-size:24px;letter-spacing:6px;color:#4FD1C5}
      .bars{position:absolute;left:60px;right:60px;bottom:170px;display:flex;gap:12px;align-items:flex-end;height:170px}
      .bars i{flex:1;background:linear-gradient(#17E0C4,#0E7C74);box-shadow:0 0 12px rgba(23,224,196,.4)}
      .scan{position:absolute;inset:0;background:repeating-linear-gradient(0deg,rgba(23,224,196,.07) 0 2px,transparent 2px 5px)}""",
    },
    "mg-flat-vector": {
        "bg": "#FFFFFF",
        "html": """
      <div class="blob" style="left:60px;top:140px;background:#2F6BFF"></div>
      <div class="blob" style="left:280px;top:300px;background:#FFB020"></div>
      <div class="blob" style="left:120px;top:460px;background:#00C08B"></div>
      <div class="flat-t">一句话讲清楚</div>
      <div class="flat-s">纯色块 · 几何 · 弹性入退场</div>""",
        "css": """
      .blob{position:absolute;width:180px;height:180px;border-radius:40px}
      .flat-t{position:absolute;left:56px;top:690px;font-size:52px;font-weight:900;color:#14213D}
      .flat-s{position:absolute;left:56px;top:790px;font-size:24px;color:#6B7A8F}""",
    },
    "mg-line-art": {
        "bg": "#FBFBF8",
        "html": """
      <svg class="la" viewBox="0 0 540 520">
        <circle cx="270" cy="240" r="150" fill="none" stroke="#1B1B1B" stroke-width="3"/>
        <path d="M120 240 Q270 90 420 240" fill="none" stroke="#1B1B1B" stroke-width="3"/>
        <path d="M150 330 Q270 250 390 330" fill="none" stroke="#1B1B1B" stroke-width="2"/>
        <circle cx="220" cy="215" r="7" fill="#1B1B1B"/><circle cx="320" cy="215" r="7" fill="#1B1B1B"/>
      </svg>
      <div class="la-t">慢慢讲清楚</div>
      <div class="la-s">白描线 · 纸面 · 逐笔生长</div>""",
        "css": """
      .la{position:absolute;left:20px;top:120px;width:500px;height:480px}
      .la-t{position:absolute;left:56px;top:660px;font-size:50px;font-weight:700;color:#1B1B1B;font-family:"SimSun",serif}
      .la-s{position:absolute;left:56px;top:760px;font-size:24px;color:#6B6B6B}""",
    },
    "mg-isometric": {
        "bg": "#EAF0F6",
        "html": """
      <svg class="iso" viewBox="0 0 540 420">
        <polygon points="270,60 470,170 270,280 70,170" fill="#8FB8E8" stroke="#3A5A80" stroke-width="2"/>
        <polygon points="70,170 270,280 270,360 70,250" fill="#6E9BD1" stroke="#3A5A80" stroke-width="2"/>
        <polygon points="470,170 270,280 270,360 470,250" fill="#5C88C4" stroke="#3A5A80" stroke-width="2"/>
      </svg>
      <div class="iso-t">流程讲清楚</div>
      <div class="iso-s">2.5D 等距 · 小场景 · 流程感</div>""",
        "css": """
      .iso{position:absolute;left:10px;top:140px;width:520px;height:404px}
      .iso-t{position:absolute;left:56px;top:640px;font-size:50px;font-weight:800;color:#2A3F55}
      .iso-s{position:absolute;left:56px;top:740px;font-size:24px;color:#6B7A8F}""",
    },
    "mg-3d-render": {
        "bg": "#F2F0EE",
        "html": """
      <div class="cube" style="left:170px;top:180px"></div>
      <div class="sphere" style="left:330px;top:420px"></div>
      <div class="t3d">质感拉满</div>
      <div class="s3d">PBR 材质 · 软胶质感 · 棚拍光</div>""",
        "css": """
      .cube{position:absolute;width:200px;height:200px;border-radius:36px;
            background:radial-gradient(circle at 32% 28%,#fff,#FF8A65 42%,#D84315);
            box-shadow:0 34px 60px rgba(216,67,21,.32)}
      .sphere{position:absolute;width:150px;height:150px;border-radius:50%;
            background:radial-gradient(circle at 32% 28%,#fff,#7FD8FF 45%,#0288D1);
            box-shadow:0 26px 46px rgba(2,136,209,.3)}
      .t3d{position:absolute;left:56px;top:680px;font-size:50px;font-weight:900;color:#21242A}
      .s3d{position:absolute;left:56px;top:780px;font-size:24px;color:#7A8090}""",
    },
    "mg-cel-boil": {
        "bg": "#FDF3E3",
        "html": """
      <svg class="cb" viewBox="0 0 540 460">
        <path d="M120 380 Q120 150 270 150 Q420 150 420 380 Z" fill="#FFD9A0" stroke="#3A2E22" stroke-width="5"/>
        <circle cx="215" cy="250" r="10" fill="#3A2E22"/><circle cx="325" cy="250" r="10" fill="#3A2E22"/>
        <path d="M200 320 Q270 360 340 320" fill="none" stroke="#3A2E22" stroke-width="6" stroke-linecap="round"/>
      </svg>
      <div class="cb-t">讲个故事</div>
      <div class="cb-s">手绘线条 · 赛璐璐上色</div>""",
        "css": """
      .cb{position:absolute;left:10px;top:130px;width:520px;height:442px}
      .cb-t{position:absolute;left:56px;top:660px;font-size:50px;font-weight:900;color:#3A2E22}
      .cb-s{position:absolute;left:56px;top:760px;font-size:24px;color:#8A7660}""",
    },
    "mg-liquid": {
        "bg": "#0E1030",
        "html": """
      <div class="liq"></div>
      <div class="liq2"></div>
      <div class="liq-t">变化的情绪</div>
      <div class="liq-s">流体 · 形变 · 高光</div>""",
        "css": """
      .liq{position:absolute;left:40px;top:160px;width:260px;height:260px;border-radius:58% 42% 47% 53%;
           background:radial-gradient(circle at 34% 30%,#7CF3FF,#3B6BF5 55%,#1B1F6B);filter:blur(2px)}
      .liq2{position:absolute;left:250px;top:330px;width:250px;height:250px;border-radius:42% 58% 55% 45%;
            background:radial-gradient(circle at 40% 35%,#FF9DE2,#8A3BFF 55%,#2B0F5E);filter:blur(2px)}
      .liq-t{position:absolute;left:56px;top:700px;font-size:50px;font-weight:900;color:#EAF6FF}
      .liq-s{position:absolute;left:56px;top:800px;font-size:24px;color:#8FA8D8}""",
    },
    "mg-morph": {
        "bg": "#FFF8EE",
        "html": """
      <div class="m1">A</div>
      <div class="arrow">→</div>
      <div class="m2">B</div>
      <div class="mo-t">连续形变</div>
      <div class="mo-s">A → B 的转化过程</div>""",
        "css": """
      .m1{position:absolute;left:60px;top:220px;width:170px;height:170px;border-radius:50%;background:#FF7043;
          display:grid;place-items:center;font-size:70px;font-weight:900;color:#fff}
      .m2{position:absolute;left:310px;top:220px;width:170px;height:170px;border-radius:26px;background:#26C6DA;
          display:grid;place-items:center;font-size:70px;font-weight:900;color:#fff}
      .arrow{position:absolute;left:240px;top:250px;font-size:60px;color:#9A8C80}
      .mo-t{position:absolute;left:56px;top:640px;font-size:50px;font-weight:900;color:#3E2F25}
      .mo-s{position:absolute;left:56px;top:740px;font-size:24px;color:#8B7869}""",
    },
    "mg-bauhaus": {
        "bg": "#F2EDE4",
        "html": """
      <div class="bc" style="left:60px;top:140px;background:#D8352A"></div>
      <div class="bc" style="left:290px;top:140px;background:#1B4B8F;border-radius:50%"></div>
      <div class="bc" style="left:60px;top:330px;background:#F2B705;height:140px"></div>
      <div class="bc" style="left:290px;top:330px;background:#1B1B1B;width:70px"></div>
      <div class="bu-t">设计的原则</div>
      <div class="bu-s">原色 · 几何 · 构成</div>""",
        "css": """
      .bc{position:absolute;width:150px;height:150px}
      .bu-t{position:absolute;left:56px;top:640px;font-size:50px;font-weight:900;color:#1B1B1B}
      .bu-s{position:absolute;left:56px;top:740px;font-size:24px;color:#6B6152}""",
    },
    "mg-synthwave": {
        "bg": "#150B2E",
        "html": """
      <div class="sun"></div>
      <div class="grid2"></div>
      <div class="sw-t">NEON</div>
      <div class="sw-s">霓虹 · 网格 · 落日</div>""",
        "css": """
      .sun{position:absolute;left:120px;top:200px;width:300px;height:300px;border-radius:50%;
           background:linear-gradient(#FF2E9A,#FFB03A 60%,#7A2BD4);filter:blur(1px)}
      .grid2{position:absolute;left:0;right:0;bottom:0;height:380px;background-image:
            linear-gradient(rgba(255,46,154,.55) 2px,transparent 2px),
            linear-gradient(90deg,rgba(120,80,255,.4) 2px,transparent 2px);background-size:60px 44px;
            transform:perspective(340px) rotateX(58deg)}
      .sw-t{position:absolute;left:0;right:0;top:420px;text-align:center;font-size:78px;font-weight:900;
            color:#25F4EE;letter-spacing:12px;text-shadow:0 0 30px rgba(37,244,238,.8)}
      .sw-s{position:absolute;left:0;right:0;top:540px;text-align:center;font-size:24px;color:#B79BFF;letter-spacing:4px}""",
    },
    "mg-aurora-glass": {
        "bg": "#101426",
        "html": """
      <div class="au1"></div><div class="au2"></div><div class="au3"></div>
      <div class="glass">
        <div class="au-t">质感与氛围</div>
        <div class="au-s">大色斑 · 磨砂玻璃卡片</div>
      </div>""",
        "css": """
      .au1{position:absolute;left:-60px;top:80px;width:420px;height:420px;border-radius:50%;
           background:#3E7BFA;filter:blur(90px);opacity:.75}
      .au2{position:absolute;left:220px;top:280px;width:400px;height:400px;border-radius:50%;
           background:#B15CFF;filter:blur(100px);opacity:.6}
      .au3{position:absolute;left:60px;top:520px;width:340px;height:340px;border-radius:50%;
           background:#26E0C4;filter:blur(90px);opacity:.5}
      .glass{position:absolute;left:56px;top:600px;width:428px;padding:30px 26px;border-radius:18px;
             background:rgba(255,255,255,.13);border:1px solid rgba(255,255,255,.28);
             backdrop-filter:blur(16px)}
      .au-t{font-size:44px;font-weight:800;color:#fff}
      .au-s{font-size:22px;color:#C6D2F0;margin-top:8px}""",
    },
    "mg-hanazi": {
        "bg": "#F5EFE2",
        "html": """
      <div class="hz">稳</div>
      <div class="hz-line"></div>
      <div class="hz-t">说人话</div>
      <div class="hz-s">大字报 · 笔画拆解 · 印章</div>
      <div class="hz-seal">印</div>""",
        "css": """
      .hz{position:absolute;left:70px;top:120px;font-size:260px;font-weight:900;color:#1A1A1A;
          font-family:"SimHei","Microsoft YaHei",sans-serif;line-height:1}
      .hz-line{position:absolute;left:70px;top:410px;width:400px;height:6px;background:#C8352B}
      .hz-t{position:absolute;left:70px;top:470px;font-size:46px;font-weight:900;color:#1A1A1A}
      .hz-s{position:absolute;left:70px;top:560px;font-size:23px;color:#6B6152}
      .hz-seal{position:absolute;left:360px;top:640px;width:96px;height:96px;border:6px solid #C8352B;
               color:#C8352B;font-size:52px;font-weight:900;display:grid;place-items:center;border-radius:8px;
               transform:rotate(-8deg)}""",
    },
    "mg-pixel": {
        "bg": "#1A1A2E",
        "html": """
      <div class="px-grid"></div>
      <div class="px-heart"></div>
      <div class="px-t">像素冒险</div>
      <div class="px-s">像素画 · 扫描线 · 8bit</div>""",
        "css": """
      .px-grid{position:absolute;inset:0;background-image:
            linear-gradient(rgba(255,255,255,.07) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.07) 1px,transparent 1px);
            background-size:24px 24px}
      .px-heart{position:absolute;left:150px;top:180px;width:240px;height:200px;
            background:#FF4D6D;clip-path:polygon(0 25%,25% 0,50% 22%,75% 0,100% 25%,100% 60%,50% 100%,0 60%);
            filter:drop-shadow(0 0 22px rgba(255,77,109,.65))}
      .px-t{position:absolute;left:0;right:0;top:480px;text-align:center;font-size:52px;font-weight:900;
            color:#4ECDC4;letter-spacing:6px;font-family:Consolas,monospace;text-shadow:4px 4px 0 #101020}
      .px-s{position:absolute;left:0;right:0;top:570px;text-align:center;font-size:23px;color:#8B87A8}""",
    },
    # 16 华尔街财经解读:深蓝斜纹织物 + 奶油金巨数 + 白底原文卡
    "mg-wallstreet": {
        "bg": "#101C2E",
        "html": """
      <div class="ws-twill"></div>
      <div class="ws-brow">一笔账</div>
      <div class="ws-en">FOLLOW THE MONEY / STYLE DEMO</div>
      <div class="ws-num">$725B</div>
      <div class="ws-unit">一年的算力开支</div>
      <div class="ws-card">
        <div class="ws-card-h">ILLUSTRATIVE LAYOUT / 示意</div>
        <div class="ws-row">资本开支同比 +218%</div>
        <div class="ws-row">推理成本下降 41%</div>
        <div class="ws-mark"></div>
      </div>
      <div class="ws-bars"><i></i><i></i><i></i><i class="on"></i><i></i></div>
      <div class="ws-foot">数字为示意 · 非真实数据</div>""",
        "css": """
      .ws-twill{position:absolute;inset:0;background:
            repeating-linear-gradient(45deg,rgba(241,234,210,.06) 0 1px,transparent 1px 5px),
            repeating-linear-gradient(-45deg,rgba(0,0,0,.18) 0 1px,transparent 1px 6px),
            radial-gradient(circle at 48% 36%,rgba(59,122,28,.22),transparent 62%)}
      .ws-brow{position:absolute;left:44px;top:52px;font-size:27px;font-weight:800;color:#EFDC7A;letter-spacing:7px}
      .ws-en{position:absolute;left:44px;top:98px;font-size:13px;color:#9AA8BD;letter-spacing:3px;font-family:Consolas,monospace}
      .ws-num{position:absolute;left:0;right:0;top:160px;text-align:center;font-size:118px;font-weight:900;
            color:#FFF0B8;font-family:Consolas,monospace;letter-spacing:-6px;
            text-shadow:0 4px 24px rgba(239,220,122,.25)}
      .ws-unit{position:absolute;left:0;right:0;top:292px;text-align:center;font-size:19px;
            color:#F2E27E;letter-spacing:5px}
      .ws-card{position:absolute;left:44px;right:44px;top:360px;height:230px;background:#F4F1EA;
            border:6px solid #F4F1EA;border-radius:10px;box-shadow:0 14px 30px rgba(0,0,0,.5);overflow:hidden}
      .ws-card-h{height:32px;background:#DFD9CB;color:#3C4149;font:12px Consolas,monospace;
            letter-spacing:2px;padding:9px 14px}
      .ws-row{color:#2A3038;font-size:21px;font-weight:700;margin:22px 18px 0}
      .ws-mark{position:absolute;left:0;top:96px;width:100%;height:26px;
            background:linear-gradient(90deg,transparent,rgba(255,216,74,.85),transparent)}
      .ws-bars{position:absolute;left:44px;right:44px;top:630px;height:150px;display:flex;
            align-items:flex-end;gap:22px;border-bottom:2px solid rgba(241,234,210,.4)}
      .ws-bars i{flex:1;background:rgba(241,234,210,.42);border-radius:3px 3px 0 0}
      .ws-bars i:nth-child(1){height:38%}.ws-bars i:nth-child(2){height:62%}
      .ws-bars i:nth-child(3){height:50%}.ws-bars i:nth-child(4){height:88%}
      .ws-bars i:nth-child(5){height:72%}
      .ws-bars i.on{background:#EFDC7A}
      .ws-foot{position:absolute;left:0;right:0;top:830px;text-align:center;font-size:20px;color:#F1EAD2}""",
    },
}


def build_html(ids: list[str]) -> str:
    blocks = []
    for sid in ids:
        st = STYLES[sid]
        blocks.append(
            f'<div class="cell" id="cell-{sid}">{_frame(st["html"], st["bg"], "")}</div>'
        )
    css = "\n".join(STYLES[sid]["css"] for sid in ids)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      *{{box-sizing:border-box;margin:0}}
      body{{background:#222;font-family:"Microsoft YaHei",sans-serif}}
      .cell{{width:{W}px;height:{H}px;position:relative;overflow:hidden;display:inline-block;
             vertical-align:top;margin:10px}}
      .frame{{position:absolute;inset:0;overflow:hidden}}
      {css}
    </style></head><body>{''.join(blocks)}</body></html>"""


SNAP_JS = """
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
(async () => {
  const chrome = process.env.CHROME_PATH ||
    'C:/Program Files/Google/Chrome/Application/chrome.exe';
  const htmlPath = process.argv[2];
  const outDir = process.argv[3];
  const ids = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
  const b = await puppeteer.launch({executablePath: chrome, headless: 'new', args: ['--no-sandbox']});
  const pg = await b.newPage({viewport: {width: 1400, height: 1100}, deviceScaleFactor: 1});
  await pg.goto('file://' + path.resolve(htmlPath), {waitUntil: 'networkidle0'});
  await new Promise(r => setTimeout(r, 600));
  fs.mkdirSync(outDir, {recursive: true});
  for (const id of ids) {
    const el = await pg.$('#cell-' + id);
    await el.screenshot({path: path.join(outDir, id + '.png')});
    console.log('  ' + id + '.png');
  }
  await b.close();
})().catch(e => { console.error(e.message); process.exit(1); });
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="只生成某些风格(逗号分隔)")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ids = [s.strip() for s in args.only.split(",") if s.strip()] or list(STYLES)
    missing = [i for i in ids if i not in STYLES]
    if missing:
        print("未知风格:", missing)
        return 2
    tmp = REPO / ".tmp" / "style-preview"
    tmp.mkdir(parents=True, exist_ok=True)
    html = tmp / "gallery.html"
    html.write_text(build_html(ids), encoding="utf-8")
    (tmp / "ids.json").write_text(json.dumps(ids), encoding="utf-8")
    js = tmp / "snap.js"
    js.write_text(SNAP_JS, encoding="utf-8")
    node = shutil.which("node")
    if not node:
        print("找不到 node")
        return 3
    print(f"[样张] 渲染 {len(ids)} 个风格 → {out}")
    # puppeteer-core 装在 harness/node_modules 下,脚本要放在那里才能 require 到
    js_run = HARNESS / "_style_preview_snap.cjs"
    shutil.copy2(js, js_run)
    try:
        r = subprocess.run([node, str(js_run), str(html), str(out), str(tmp / "ids.json")], cwd=str(HARNESS))
    finally:
        js_run.unlink(missing_ok=True)
    if r.returncode:
        return r.returncode
    print(json.dumps({"ok": True, "count": len(ids), "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
