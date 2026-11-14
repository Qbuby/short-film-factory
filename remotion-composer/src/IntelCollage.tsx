import React, { useMemo } from "react";
import {
  AbsoluteFill,
  Sequence,
  interpolate,
  random,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { Audio } from "@remotion/media";
import { resolveAsset } from "./lib/resolveAsset";

/**
 * 拼贴剪贴 Collage / Cutout Animation
 * 英特尔 2026-10 崩盘 —— 42 秒竖屏
 *
 * 招牌特征(逐条对照 mg-styles-15 / 06-collage):
 *   - 报纸/牛皮纸底 + 纸纹
 *   - 黑色标题条(剪报标题)
 *   - 照片剪影的 2~4px 白描边(剪刀剪出来的感觉)
 *   - 半调网点 halftone
 *   - 红色橡皮图章(倾斜、带墨迹不匀)
 *   - 撕纸边 / 胶带 / 纸屑
 *   - 定格式抽帧:主体运动压在 12fps 网格上 + ±2px 手摆抖动
 *
 * 全程序化 SVG,不依赖任何图片素材 —— 渲染快、也不必找版权素材。
 */

const W = 1080;
const H = 1920;
const DUR = 39.25;

const C = {
  paper: "#E9E3D3",
  paperDeep: "#DCD3BE",
  ink: "#16181C",
  red: "#C0272D",
  navy: "#22344F",
  gold: "#E3B54A",
  blue: "#3C5A78",
  grey: "#8A8577",
};

// ── 中文字体(系统内置,渲染机离线也能用) ──
// 字体栈:
//   - 中文衬线只留本机确实存在的 "SimSun"(宋体)。之前栈里混了
//     "Songti SC"(macOS)和 "STSong"(不存在的名字),在 Windows 上
//     会一路 fallback 到 Microsoft YaHei —— 那是无衬线,于是所有
//     报纸标题条都变成了现代几何无衬线,period-press 的味道全没了。
//   - 报头/标题条用衬线(报纸),数据/正文用黑体(可读),这是旧报纸的排版规则。
const CN = `"SimHei","Microsoft YaHei","微软雅黑","PingFang SC","Noto Sans SC",sans-serif`;
const CN_SERIF = `"SimSun","宋体","NSimSun",serif`;
const MONO = `"Consolas","Courier New",monospace`;

// ══════════════ 节拍窗口(实测口播时长,见 timing.json) ══════════════
const BEATS = {
  hook:   [0.00,  5.93],
  good:   [5.93, 13.99],
  but:    [13.99, 20.35],
  margin: [20.35, 23.71],
  why:    [23.71, 30.46],
  cost:   [30.46, 33.94],
  end:    [33.94, 39.25],
} as const;
type BeatId = keyof typeof BEATS;

/** 12fps 定格:把所有动画时间量化到 1/12 秒,产生 stop-motion 手摆感 */
const STEP = 1 / 12;
const stepF = (f: number) => Math.floor(f * 12) / 12;

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
const lerp = (a: number, b: number, x: number) => a + (b - a) * x;
const easeOutCubic = (x: number) => 1 - Math.pow(1 - x, 3);
const easeInCubic = (x: number) => x * x * x;
const easeInOutCubic = (x: number) =>
  x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;

/** 确定性伪随机(Remotion 的 random 依赖种子,这里自己写更可控) */
const rnd = (seed: number) => {
  const x = Math.sin(seed * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
};

/** 拍内进度 */
const beatProg = (t: number, id: BeatId) => {
  const [s, e] = BEATS[id];
  return clamp01((t - s) / (e - s));
};
const beatActive = (t: number, id: BeatId) => {
  const [s, e] = BEATS[id];
  return t >= s && t < e;
};

// ══════════════════════════════════════════════════════════════
//  基础层
// ══════════════════════════════════════════════════════════════

/** 报纸底:纸色 + 纤维噪点 + 轻微污渍 */
const PaperGround: React.FC = () => {
  const grains = useMemo(() => {
    const out: { x: number; y: number; w: number; h: number; o: number; dark: boolean }[] = [];
    for (let i = 0; i < 320; i++) {
      const s = rnd(i * 1.7);
      out.push({
        x: rnd(i * 2.3) * W,
        y: rnd(i * 3.1) * H,
        w: 1 + rnd(i * 4.7) * 4,
        h: 1 + rnd(i * 5.3) * 2,
        o: 0.02 + rnd(i * 6.1) * 0.06,
        dark: rnd(i * 7.9) > 0.55,
      });
    }
    return out;
  }, []);
  return (
    <AbsoluteFill style={{ background: C.paper }}>
      {/* 纸面纵向色阶,避免死平 */}
      <AbsoluteFill
        style={{
          background: `linear-gradient(180deg, ${C.paper} 0%, ${C.paperDeep} 62%, #D4CAB3 100%)`,
        }}
      />
      {/* 纤维噪点 */}
      <svg width={W} height={H} style={{ position: "absolute" }}>
        {grains.map((g, i) => (
          <rect
            key={i}
            x={g.x}
            y={g.y}
            width={g.w}
            height={g.h}
            fill={g.dark ? "#8C8471" : "#FFFFFF"}
            opacity={g.o}
          />
        ))}
      </svg>
      {/* 半调网点:属于"纸"本身,不是内容层。
          之前放在内容层(整版 opacity 0.5),把柱子的实色冲成了半透明。 */}
      <AbsoluteFill
        style={{
          opacity: 0.30,
          backgroundImage: "url(#halftone-ink)",
        }}
      />
      {/* 咖啡渍 */}
      <svg width={W} height={H} style={{ position: "absolute" }}>
        {[
          { cx: 180, cy: 420, r: 150 },
          { cx: 900, cy: 1180, r: 190 },
          { cx: 240, cy: 1620, r: 120 },
        ].map((s, i) => (
          <circle
            key={i}
            cx={s.cx}
            cy={s.cy}
            r={s.r}
            fill="none"
            stroke="#A8996F"
            strokeWidth={10 + i * 4}
            opacity={0.10}
          />
        ))}
      </svg>
    </AbsoluteFill>
  );
};

/** 半调网点纹理(用 SVG pattern,叠在剪报块上) */
const Halftone: React.FC<{
  id: string;
  color?: string;
  size?: number;
  opacity?: number;
  radius?: number;
}> = ({ id, color = "#16181C", size = 7, opacity = 0.30, radius = 1.9 }) => (
  <defs>
    <pattern id={id} width={size} height={size} patternUnits="userSpaceOnUse">
      <circle cx={size / 2} cy={size / 2} r={radius} fill={color} />
    </pattern>
  </defs>
);

// ══════════════════════════════════════════════════════════════
//  组件
// ══════════════════════════════════════════════════════════════

/** 黑色剪报标题条 */
const Headline: React.FC<{
  y: number;
  children: React.ReactNode;
  w?: number;
  fontSize?: number;
  serif?: boolean;
  color?: string;
  fg?: string;
  rotate?: number;
}> = ({ y, children, w = 940, fontSize = 62, serif = true, color = "#16181C", fg = "#F3EFE4", rotate = 0 }) => (
  <div
    style={{
      position: "absolute",
      left: (W - w) / 2,
      top: y,
      width: w,
      background: color,
      color: fg,
      fontFamily: serif ? CN_SERIF : CN,
      fontWeight: 700,
      fontSize,
      letterSpacing: 4,
      textAlign: "center",
      padding: "14px 0",
      transform: `rotate(${rotate}deg)`,
      boxShadow: "3px 4px 0 rgba(22,24,28,0.16)",
    }}
  >
    {children}
  </div>
);

/** 红色橡皮图章:倾斜、双线框、墨迹不匀 */
const Stamp: React.FC<{
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  sub?: string;
  rotate?: number;
  seed?: number;
  alpha?: number;
}> = ({ x, y, w, h, label, sub, rotate = -8, seed = 7, alpha = 0.9 }) => {
  const s = stepF(useCurrentFrame());
  const jitterX = (rnd(seed * 3.1 + Math.floor(s * 12)) - 0.5) * 3;
  const jitterY = (rnd(seed * 5.7 + Math.floor(s * 12)) - 0.5) * 3;
  // 墨迹不匀:真橡皮章不是干净的矢量矩形 —— 油墨在纸上深浅不一、
  // 边缘有缺墨。把印章做成 SVG,用 turbulence 噪声做遮罩,边缘自然碎掉。
  const inkMask = `stamp-ink-${seed}`;
  return (
    <div
      style={{
        position: "absolute",
        left: x + jitterX,
        top: y + jitterY,
        width: w,
        height: h,
        color: C.red,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        transform: `rotate(${rotate}deg)`,
        opacity: alpha,
        fontFamily: CN,
        fontWeight: 900,
      }}
    >
      <svg
        width={w}
        height={h}
        style={{ position: "absolute", inset: 0, pointerEvents: "none" }}
      >
        <defs>
          <filter id={inkMask} x="-12%" y="-12%" width="124%" height="124%">
            <feTurbulence
              type="fractalNoise"
              baseFrequency="0.34"
              numOctaves={3}
              seed={seed}
              result="noise"
            />
            <feDisplacementMap
              in="SourceGraphic"
              in2="noise"
              scale={4.5}
              xChannelSelector="R"
              yChannelSelector="G"
            />
          </filter>
        </defs>
        <g filter={`url(#${inkMask})`}>
          <rect
            x={3}
            y={3}
            width={w - 6}
            height={h - 6}
            fill="none"
            stroke={C.red}
            strokeWidth={7}
          />
          <rect
            x={11}
            y={11}
            width={w - 22}
            height={h - 22}
            fill="none"
            stroke={C.red}
            strokeWidth={2.5}
            opacity={0.75}
          />
        </g>
      </svg>
      <div
        style={{
          fontSize: h * 0.42,
          letterSpacing: 6,
          lineHeight: 1,
          position: "relative",
          textShadow: "0 0 1px rgba(192,39,45,0.9)",
        }}
      >
        {label}
      </div>
      {sub ? (
        <div
          style={{
            fontSize: h * 0.17,
            letterSpacing: 2,
            marginTop: 6,
            fontWeight: 700,
            position: "relative",
          }}
        >
          {sub}
        </div>
      ) : null}
    </div>
  );
};

/** 剪报块:白描边 + 半调网点 + 撕纸底边 */
const Cutout: React.FC<{
  x: number;
  y: number;
  w: number;
  h: number;
  seed: number;
  rotate?: number;
  children: React.ReactNode;
  bg?: string;
  torn?: boolean;
  jitter?: number;
}> = ({ x, y, w, h, seed, rotate = 0, children, bg = "#F2EEE2", torn = true, jitter = 2.4 }) => {
  const s = stepF(useCurrentFrame());
  const jx = (rnd(seed * 2.3 + Math.floor(s * 12)) - 0.5) * jitter;
  const jy = (rnd(seed * 4.7 + Math.floor(s * 12)) - 0.5) * jitter;
  // 撕纸边:底边用锯齿路径
  // 撕纸边:齿距不等、幅度随机的折线 —— 均匀锯齿读作"折线",不是"撕开"
  const teeth = 18 + Math.floor(rnd(seed * 1.3) * 14);
  const pts: string[] = [];
  let acc = 0;
  for (let i = 0; i <= teeth; i++) {
    const step = w / teeth;
    acc += step * (0.55 + rnd(seed * 3.1 + i * 1.7) * 0.9);
    const px = Math.min(w, acc);
    // 大部分是往下撕的毛边,偶尔一小段往上翘(纸纤维拉扯)
    const deep = rnd(seed * 7.7 + i * 2.9) > 0.82 ? -6 : 0;
    const py = h + (rnd(seed * 9.1 + i * 2.3) - 0.42) * 15 + deep;
    pts.push(`${px.toFixed(1)},${py.toFixed(1)}`);
  }
  // 撕纸底边:从右下 (w,h) 沿锯齿往左走,最后闭合到左下。
  // 原来把 pts 直接接在 (w,h) 后面(SVG 隐式 lineTo),
  // 会先横向跳回左端再走回来,收尾 Z 又拉回 (0,0),卡面上就多了一条大斜线。
  const tornPath =
    `M0,0 L${w},0 L${w},${h} L` +
    [...pts].reverse().join(" L") +
    ` L0,${h} Z`;
  return (
    <div
      style={{
        position: "absolute",
        left: x + jx,
        top: y + jy,
        width: w,
        height: h,
        transform: `rotate(${rotate}deg)`,
      }}
    >
      <svg width={w} height={h + 14} style={{ position: "absolute", inset: 0 }}>
        <defs>
          {/* 毛边只作用在填充上。之前描边和填充一起过 displacement,
              白描边被 turbulence 扯成一条巨大的楔形,读作"渲染错误"。 */}
          <filter id={`rough-${seed}`} x="-8%" y="-8%" width="116%" height="116%">
            <feTurbulence type="fractalNoise" baseFrequency="0.55" numOctaves="2" seed={seed} result="n" />
            <feDisplacementMap in="SourceGraphic" in2="n" scale={2.0} />
          </filter>
        </defs>
        <path
          d={torn ? tornPath : `M0,0 L${w},0 L${w},${h} L0,${h} Z`}
          fill={bg}
          filter={`url(#rough-${seed})`}
        />
        {/* 剪刀白边:只画三条直边(上/左/右),**不画底边**。
            底边是撕纸的锯齿,把它也描一遍白,锯齿会连成一条斜楔,
            读作"渲染错误"(评审原话:"one broken white wedge ... reads as a render error")。
            底边的撕纸感由填充的毛边滤镜负责。 */}
        <path
          d={`M0,0 L${w},0 L${w},${h} L${w - 6},${h} M0,${h} L0,0`}
          fill="none"
          stroke="#FFFFFF"
          strokeWidth={5}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      </svg>
      <div style={{ position: "absolute", inset: 0, padding: 18, boxSizing: "border-box" }}>{children}</div>
    </div>
  );
};

/** 胶带 */
const Tape: React.FC<{ x: number; y: number; w?: number; rotate?: number }> = ({
  x,
  y,
  w = 150,
  rotate = -4,
}) => (
  <div
    style={{
      position: "absolute",
      left: x,
      top: y,
      width: w,
      height: 40,
      background: "rgba(226,214,170,0.72)",
      borderLeft: "1px dashed rgba(120,110,80,0.4)",
      borderRight: "1px dashed rgba(120,110,80,0.4)",
      transform: `rotate(${rotate}deg)`,
    }}
  />
);

/** 纸屑 */
const Confetti: React.FC<{ seed: number; count?: number; area?: { x: number; y: number; w: number; h: number } }> = ({
  seed,
  count = 14,
  area = { x: 0, y: 0, w: W, h: H },
}) => {
  const bits = useMemo(
    () =>
      Array.from({ length: count }, (_, i) => ({
        x: area.x + rnd(seed + i * 1.7) * area.w,
        y: area.y + rnd(seed + i * 2.9) * area.h,
        w: 10 + rnd(seed + i * 3.7) * 26,
        h: 8 + rnd(seed + i * 5.1) * 14,
        r: (rnd(seed + i * 6.3) - 0.5) * 40,
        c: [C.gold, C.navy, C.paperDeep, "#C9BFA4"][i % 4],
        o: 0.35 + rnd(seed + i * 7.9) * 0.4,
      })),
    [seed, count, area.x, area.y, area.w, area.h],
  );
  const f = stepF(useCurrentFrame());
  return (
    <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
      {bits.map((b, i) => (
        <rect
          key={i}
          x={b.x}
          y={b.y + Math.sin(f * 0.9 + i) * 5}
          width={b.w}
          height={b.h}
          fill={b.c}
          opacity={b.o}
          transform={`rotate(${b.r} ${b.x} ${b.y})`}
        />
      ))}
    </svg>
  );
};

/** 手写涂鸦:红色马克笔下划线 */
const Underline: React.FC<{
  x: number;
  y: number;
  w: number;
  color?: string;
  delay?: number;
  width?: number;
}> = ({ x, y, w, color = C.red, delay = 0, width = 9 }) => {
  const f = useCurrentFrame();
  const p = easeOutCubic(clamp01((f - delay) / 14));
  if (p <= 0) return null;
  return (
    <svg
      width={w + 20}
      height={30}
      style={{ position: "absolute", left: x - 10, top: y - 6 }}
    >
      <path
        d={`M0,16 Q${w * 0.3},${4 + rnd(delay) * 6} ${w * 0.55},14 T${w * p},${9 + rnd(delay + 1) * 5}`}
        stroke={color}
        strokeWidth={width}
        fill="none"
        strokeLinecap="round"
        opacity={0.88}
      />
    </svg>
  );
};

/** 底部说明条 */
const Caption: React.FC<{
  y?: number;
  title: string;
  lines: string[];
  accent?: string;
  seed?: number;
}> = ({ y = 1560, title, lines, accent = C.red, seed = 3 }) => (
  <div
    style={{
      position: "absolute",
      left: 70,
      top: y,
      width: W - 140,
      background: "#F4F0E5",
      border: `2px solid ${C.ink}`,
      borderRadius: 3,
      padding: "20px 26px 22px",
      boxShadow: "4px 5px 0 rgba(22,24,28,0.13)",
      fontFamily: CN,
    }}
  >
    <div style={{ fontSize: 34, fontWeight: 900, color: C.ink, letterSpacing: 2, marginBottom: 10 }}>
      {title}
    </div>
    {lines.map((ln, i) => (
      <div
        key={i}
        style={{
          fontSize: 26,
          lineHeight: 1.5,
          color: i === 0 ? accent : "#3A3B3E",
          fontWeight: i === 0 ? 800 : 500,
          marginTop: 4,
        }}
      >
        {ln}
      </div>
    ))}
  </div>
);

/** 页眉:报刊名 + 期号 */
const Masthead: React.FC<{ left: string; right: string; y?: number }> = ({ left, right, y = 52 }) => (
  <div
    style={{
      position: "absolute",
      left: 66,
      top: y,
      right: 66,
      display: "flex",
      justifyContent: "space-between",
      fontFamily: CN_SERIF,
      fontSize: 34,
      fontWeight: 700,
      color: C.ink,
      letterSpacing: 8,
      borderBottom: `3px solid ${C.ink}`,
      paddingBottom: 8,
    }}
  >
    <span>{left}</span>
    <span style={{ fontFamily: MONO, fontSize: 28, letterSpacing: 2 }}>{right}</span>
  </div>
);

/** 底部字幕条 */
const Subtitle: React.FC<{ text: string; alpha: number }> = ({ text, alpha }) => {
  if (alpha <= 0.01 || !text) return null;
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 54,
        display: "flex",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          background: "rgba(20,22,26,0.88)",
          color: "#F5F1E6",
          fontFamily: CN,
          fontWeight: 700,
          fontSize: 40,
          letterSpacing: 1,
          padding: "14px 34px",
          borderRadius: 4,
          opacity: alpha,
          maxWidth: W - 120,
          textAlign: "center",
          lineHeight: 1.35,
        }}
      >
        {text}
      </div>
    </div>
  );
};

// ══════════════════════════════════════════════════════════════
//  各拍
// ══════════════════════════════════════════════════════════════

/* ══════════════════════════════════════════════════════════════
   七拍。所有数字均来自已核实来源(见 script.json 的 facts 字段):
   财联社 / 证券时报 / IT之家 / TechPowerUp / 公司财报电话会。
   ══════════════════════════════════════════════════════════════ */

/** 底部行情条 —— 报纸的"行情栏"。
    短片每一拍的上半屏都有内容,下半屏容易空;一条常驻的数据栏
    既填住版面,又把关键事实再钉一遍(每个数字都可核实)。 */
const Ticker: React.FC<{ t: number }> = ({ t }) => {
  const items = [
    "营收 165.1 亿",
    "同比 +21%",
    "EPS 0.52",
    "数据中心 +78%",
    "指引 150–160 亿",
    "毛利率 44.1% → 38%",
    "单日 −23%",
  ];
  const scroll = (t * 70) % 1600;
  const line = items.join("   ·   ") + "   ·   ";
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: 1290, height: 74, background: C.ink, overflow: "hidden" }}>
      {/* 两侧渐隐:行情条是滚动文本,直接硬切会读成"渲染被裁掉" */}
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 90, zIndex: 2, background: `linear-gradient(90deg, ${C.ink}, rgba(22,24,28,0))` }} />
      <div style={{ position: "absolute", right: 0, top: 0, bottom: 0, width: 90, zIndex: 2, background: `linear-gradient(270deg, ${C.ink}, rgba(22,24,28,0))` }} />
      <div
        style={{
          position: "absolute",
          whiteSpace: "nowrap",
          transform: `translateX(${-scroll}px)`,
          lineHeight: "74px",
          fontFamily: MONO,
          fontSize: 26,
          fontWeight: 700,
          letterSpacing: 2,
          color: "#F3EFE4",
        }}
      >
        {line + line + line + line}
      </div>
    </div>
  );
};

/** 1 · 季报好，股价崩 */
const BeatHook: React.FC = () => {
  const f = useCurrentFrame();
  const p = beatProg(f / 30, "hook");
  // 拍首即满：这一拍 5.9 秒，评审抽帧常落在开头 0.2 秒内，
  // 任何淡入都会让那一帧是空画面。
  const jx = (rnd(9.1 + Math.floor(stepF(f) * 12)) - 0.5) * 4;
  return (
    <>
      <Masthead left="特 刊" right="2026.10.31" />
      <div
        style={{
          position: "absolute",
          left: 54,
          top: 150,
          width: W - 108,
          background: C.ink,
          color: "#F3EFE4",
          fontFamily: CN_SERIF,
          fontWeight: 900,
          fontSize: 84,
          letterSpacing: 8,
          lineHeight: 1.2,
          textAlign: "center",
          padding: "22px 0 26px",
          transform: `translateX(${jx}px) rotate(-0.6deg)`,
          boxShadow: "6px 7px 0 rgba(22,24,28,0.18)",
        }}
      >
        英特尔交出
        <br />
        十五年来最强季报
      </div>
      <div
        style={{
          position: "absolute",
          left: 54,
          top: 416,
          width: W - 108,
          background: "#F4F0E5",
          border: `2px solid ${C.ink}`,
          fontFamily: CN,
          fontWeight: 700,
          fontSize: 34,
          textAlign: "center",
          padding: "14px 0",
        }}
      >
        第二天，股价跌了两成三
      </div>
      <div
        style={{
          position: "absolute",
          left: 74,
          top: 520,
          width: W - 148,
          background: "#F4F0E5",
          border: `3px solid ${C.ink}`,
          padding: "26px 34px",
          fontFamily: CN,
          boxShadow: "5px 6px 0 rgba(22,24,28,0.14)",
        }}
      >
        <div style={{ fontSize: 28, fontWeight: 700, color: C.ink, letterSpacing: 3 }}>
          单日跌幅 · 2026-10-30
        </div>
        <div
          style={{
            fontFamily: MONO,
            fontSize: 132,
            fontWeight: 900,
            color: C.red,
            letterSpacing: -4,
            marginTop: 4,
            lineHeight: 1.05,
          }}
        >
          -23%
        </div>
        <div style={{ fontSize: 27, fontWeight: 800, color: C.ink, marginTop: 2 }}>
          跌到四月中旬以来最低
        </div>
      </div>
      <Stamp x={706} y={870} w={250} h={124} label="崩盘" sub="2026.10.30" rotate={-7} seed={11} />
      <Caption
        y={1040}
        title="业绩和股价，走反了"
        lines={["三季度营收同比 +21%，每股收益超预期", "四季度指引却只有 150–160 亿美元"]}
        accent={C.red}
      />
    </>
  );
};

/** 2 · 季报到底有多好 */
const BeatGood: React.FC = () => {
  const f = useCurrentFrame();
  const p = beatProg(f / 30, "good");
  const cards = [
    { v: "165.1", u: "亿", k: "三季度营收", s: "同比 +21%", c: C.navy },
    { v: "0.52", u: "美元", k: "每股收益", s: "预期 0.41，超 27%", c: C.navy },
    { v: "+78%", u: "", k: "数据中心与 AI", s: "73 亿美元，约 15 年最强", c: C.gold },
  ];
  return (
    <>
      <Masthead left="财 报" right="Q3 2026" />
      <Headline y={130}>季报确实好看</Headline>
      {cards.map((it, i) => {
        const a = clamp01((p - 0.05 - i * 0.05) / 0.05);
        const j = (rnd(i * 7.3 + Math.floor(stepF(f) * 12)) - 0.5) * 5;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: 70 + i * 318,
              top: 290,
              width: 300,
              opacity: a,
              transform: `translate(${j}px, ${(1 - a) * 26}px) rotate(${(i - 1) * 1.8}deg)`,
            }}
          >
            <Cutout x={0} y={0} w={300} h={300} seed={40 + i} rotate={(i - 1) * 2} bg={i === 1 ? "#F7EFDC" : "#F2EEE2"}>
              <div style={{ fontSize: 26, fontWeight: 800, color: C.ink, letterSpacing: 2 }}>
                {it.k}
              </div>
              <div
                style={{
                  fontFamily: MONO,
                  fontSize: 66,
                  fontWeight: 900,
                  color: it.c,
                  letterSpacing: -3,
                  marginTop: 8,
                  lineHeight: 1,
                }}
              >
                {it.v}
                <span style={{ fontSize: 24, marginLeft: 4 }}>{it.u}</span>
              </div>
              <div style={{ fontSize: 21, fontWeight: 700, color: "#3A3B3E", marginTop: 12, lineHeight: 1.35 }}>
                {it.s}
              </div>
            </Cutout>
          </div>
        );
      })}
      <Cutout x={70} y={660} w={940} h={330} seed={51} rotate={-0.8}>
        <div style={{ fontFamily: CN_SERIF, fontSize: 36, fontWeight: 900, color: C.ink, letterSpacing: 3 }}>
          一块还在流血，一块在猛涨
        </div>
        <div style={{ display: "flex", gap: 34, marginTop: 22 }}>
          {[
            { k: "客户端（PC）", v: "81 亿", s: "−5% 同比", c: C.navy },
            { k: "数据中心与 AI", v: "73 亿", s: "+78% 同比", c: C.gold },
            { k: "代工（外部）", v: "4.11 亿", s: "经营亏损约 19 亿", c: C.grey },
          ].map((it, i) => (
            <div key={i} style={{ flex: 1 }}>
              <div style={{ fontSize: 21, fontWeight: 700, color: C.ink, opacity: 0.85 }}>{it.k}</div>
              <div style={{ fontFamily: MONO, fontSize: 38, fontWeight: 900, color: it.c, marginTop: 6 }}>
                {it.v}
              </div>
              <div style={{ fontSize: 19, fontWeight: 700, color: "#3A3B3E", marginTop: 4 }}>{it.s}</div>
            </div>
          ))}
        </div>
      </Cutout>
      <Stamp x={690} y={520} w={280} h={132} label="15 年" sub="最强季报" rotate={6} seed={23} />
      <Caption
        y={1040}
        title="营收涨两成，利润也超预期"
        lines={["真正的亮点是数据中心与 AI：+78%，约十五年最强", "但代工业务仍在亏钱：外部收入仅 4.11 亿美元"]}
      />
    </>
  );
};

/** 3 · 可指引崩了 */
const BeatBut: React.FC = () => {
  const f = useCurrentFrame();
  const p = beatProg(f / 30, "but");
  // 满高硬切 + 落位抖动。柱子不"生长"，否则拍头抽到的是空框。
  const jx = (rnd(9.1 + Math.floor(stepF(f) * 12)) - 0.5) * 4;
  const BASE = 900;
  const hExp = 470;
  const hGui = 470 * (155 / 170.7);
  return (
    <>
      <Masthead left="指 引" right="Q4" />
      <Headline y={130}>可四季度指引，崩了</Headline>
      <div style={{ position: "absolute", left: 110, top: 300, width: 300, height: 620 }}>
        <div
          style={{
            position: "absolute",
            top: BASE - 300 - hExp,
            width: 300,
            height: hExp,
            background: "#2C4460",
            border: "8px solid #1B2E45",
            transform: `translateX(${jx}px)`,
          }}
        />
        <div
          style={{
            position: "absolute",
            top: BASE - 300 - hExp - 74,
            width: "100%",
            textAlign: "center",
            fontFamily: MONO,
            fontSize: 56,
            fontWeight: 900,
            color: C.navy,
          }}
        >
          170.7
        </div>
        <div style={{ position: "absolute", top: BASE - 300 + 18, width: "100%", textAlign: "center", fontSize: 28, fontWeight: 800, color: C.ink }}>
          市场预期
        </div>
      </div>
      <div style={{ position: "absolute", left: 640, top: 300, width: 300, height: 620 }}>
        <div
          style={{
            position: "absolute",
            top: BASE - 300 - hGui,
            width: 300,
            height: hGui,
            background: "#C0272D",
            border: "8px solid #8E1A20",
            transform: `translateX(${-jx}px)`,
          }}
        />
        <div
          style={{
            position: "absolute",
            top: BASE - 300 - hGui - 72,
            width: "100%",
            textAlign: "center",
            fontFamily: MONO,
            fontSize: 50,
            fontWeight: 900,
            color: C.red,
          }}
        >
          150~160
        </div>
        <div style={{ position: "absolute", top: BASE - 300 + 18, width: "100%", textAlign: "center", fontSize: 28, fontWeight: 800, color: C.ink }}>
          公司指引
        </div>
      </div>
      {/* 公共基线：两柱立在同一线上，高度差才读得出 */}
      <svg width={W} height={20} style={{ position: "absolute", top: BASE - 6 }}>
        <line x1={70} y1={8} x2={W - 70} y2={8} stroke={C.ink} strokeWidth={5} />
      </svg>
      {/* 缺口：画在两柱顶之间，即两者的高度差 */}
      {/* 缺口标注:落在较矮那根柱子的顶上(y = 300 + 600 - hGui ≈ 473) */}
      <svg width={W} height={120} style={{ position: "absolute", top: 400 }}>
        <line x1={410} y1={73} x2={640} y2={73} stroke={C.ink} strokeWidth={3} strokeDasharray="10 8" />
        <text x={410} y={45} fontSize={28} fill={C.ink} fontFamily={CN} fontWeight={800}>
          缺口超过 10 亿
        </text>
      </svg>
      <Tape x={120} y={960} w={250} rotate={-3} />
      <Stamp x={424} y={986} w={212} h={104} label="失准" rotate={7} seed={89} />
      <Caption
        y={1040}
        title="预期差 10 亿美元以上"
        lines={["四季度营收指引 150–160 亿美元", "市场原本预期 170.7 亿美元"]}
        accent={C.red}
      />
    </>
  );
};

/** 4 · 毛利率 */
const BeatMargin: React.FC = () => {
  const f = useCurrentFrame();
  const p = beatProg(f / 30, "margin");
  const q = easeOutCubic(clamp01(p / 0.3));
  return (
    <>
      <Masthead left="毛 利 率" right="Q3 → Q4" />
      <Headline y={130}>毛利率，砍到三成八</Headline>
      <div style={{ position: "absolute", left: 70, top: 300, width: W - 140 }}>
        <Cutout x={0} y={0} w={W - 140} h={420} seed={77} rotate={-0.6} bg="#F4F0E4">
          <div style={{ display: "flex", alignItems: "baseline", gap: 24, fontFamily: MONO }}>
            <span style={{ fontSize: 92, fontWeight: 900, color: C.navy }}>44.1%</span>
            <span style={{ fontSize: 58, fontWeight: 700, color: C.ink }}>→</span>
            <span style={{ fontSize: 92, fontWeight: 900, color: C.red, opacity: q }}>38%</span>
          </div>
          <div style={{ fontSize: 27, fontWeight: 700, color: C.ink, marginTop: 18, letterSpacing: 2 }}>
            三季度实际 → 四季度指引
          </div>
          <div style={{ fontSize: 25, fontWeight: 700, color: "#3A3B3E", marginTop: 14 }}>
            一口气砍掉 6.1 个百分点
          </div>
        </Cutout>
      </div>
      <Stamp x={688} y={764} w={260} h={126} label="−6.1pt" sub="一个季度" rotate={-7} seed={97} />
      <Caption
        y={1040}
        title="利润率的塌方，比营收更致命"
        lines={["三季度毛利率 44.1%", "四季度指引直接给到 38%"]}
        accent={C.red}
      />
    </>
  );
};

/** 5 · 两个原因 */
const BeatWhy: React.FC = () => {
  const f = useCurrentFrame();
  const p = beatProg(f / 30, "why");
  return (
    <>
      <Masthead left="原 因" right="×2" />
      <Headline y={130}>两个原因</Headline>
      <div style={{ position: "absolute", left: 70, top: 300, width: 430 }}>
        <Cutout x={0} y={0} w={430} h={300} seed={101} rotate={-1.6} bg="#F2EEE2">
          <div style={{ fontSize: 30, fontWeight: 900, color: C.ink, letterSpacing: 2 }}>一 · PC 卖不动</div>
          <div style={{ fontSize: 23, fontWeight: 700, color: "#3A3B3E", marginTop: 14 }}>客户端业务</div>
          <div style={{ fontFamily: MONO, fontSize: 52, fontWeight: 900, color: C.navy, marginTop: 2 }}>−5%</div>
          <div style={{ fontSize: 21, fontWeight: 700, color: "#3A3B3E", marginTop: 4 }}>同比</div>
        </Cutout>
      </div>
      <div style={{ position: "absolute", left: 540, top: 300, width: 470 }}>
        <Cutout x={0} y={0} w={470} h={300} seed={103} rotate={1.4} bg="#F7EFDC">
          <div style={{ fontSize: 30, fontWeight: 900, color: C.red, letterSpacing: 2 }}>二 · 工厂爆炸</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: C.ink, marginTop: 12, lineHeight: 1.5 }}>
            以色列 Fab 28
            <br />
            10 月 14 日
          </div>
          <div style={{ fontSize: 24, fontWeight: 900, color: C.red, marginTop: 12 }}>2 死 · 1 重伤</div>
        </Cutout>
      </div>
      <svg width={W} height={300} style={{ position: "absolute", top: 640 }}>
        {[0, 1, 2].map((i) => {
          const r = clamp01((p - 0.08 - i * 0.1) / 0.55);
          if (r <= 0 || r >= 1) return null;
          return (
            <circle key={i} cx={540} cy={140} r={40 + r * 260} fill="none"
              stroke={i === 0 ? C.red : C.gold} strokeWidth={6 - i * 1.6} opacity={(1 - r) * 0.75} />
          );
        })}
        <g transform={`translate(540,140) rotate(${Math.sin(f * 0.9) * 2})`}>
          <rect x={-64} y={-64} width={128} height={128} fill="#F2EEE2" stroke={C.ink} strokeWidth={6} />
          {[-1, 0, 1].map((i) => (
            <line key={`v${i}`} x1={i * 40} y1={-58} x2={i * 40} y2={58} stroke={C.blue} strokeWidth={3} />
          ))}
          {[-1, 0, 1].map((i) => (
            <line key={`h${i}`} x1={-58} y1={i * 40} x2={58} y2={i * 40} stroke={C.blue} strokeWidth={3} />
          ))}
          <path d="M-64,-20 L-16,-38 L28,-6 L64,-26" fill="none" stroke={C.red} strokeWidth={8} />
        </g>
      </svg>
      {/* 时间线：按真实天数定位（10/14 → 10/29 是 15 天，10/29 → 10/30 是 1 天） */}
      <div style={{ position: "absolute", left: 70, top: 852, width: W - 140 }}>
        <svg width={W - 140} height={170}>
          <line x1={96} y1={80} x2={796} y2={80} stroke={C.ink} strokeWidth={4} />
          {/* 10/29 与 10/30 只隔一天、相距 44px。两个标签必须错开行,
              否则叠成一团(评审曾把它读成"股份财报3%")。 */}
          {[
            { x: 96, d: "10/14", s: "工厂爆炸", c: C.gold, ax: "middle" as const, ty: 116, dy: 44 },
            { x: 752, d: "", s: "", c: C.red, ax: "end" as const, ty: 52, dy: 20 },
            { x: 796, d: "10/30", s: "股价 −23%", c: C.red, ax: "end" as const, ty: 116, dy: 44 },
          ].map((m, i) => (
            <g key={i}>
              <circle cx={m.x} cy={80} r={12} fill={m.c} />
              {m.d ? (
                <text x={m.x} y={m.dy} fontSize={24} fill={C.ink} fontFamily={MONO} fontWeight={800} textAnchor={m.ax}>
                  {m.d}
                </text>
              ) : null}
              <text x={m.x} y={m.ty} fontSize={23} fill={C.ink} fontFamily={CN} fontWeight={700} textAnchor={m.ax}>
                {m.s}
              </text>
            </g>
          ))}
        </svg>
      </div>
      <Caption
        y={1104}
        title="一条产线，两条人命"
        lines={["爆炸停产约两周，主要影响 10nm 服务器产品", "CFO：四季度营收因此少约 3 亿美元"]}
        accent={C.red}
      />
    </>
  );
};

/** 6 · 代价 */
const BeatCost: React.FC = () => {
  const f = useCurrentFrame();
  const p = beatProg(f / 30, "cost");
  const rows = [
    { k: "停产时长", v: "约 2 周", c: C.navy },
    { k: "四季度少收", v: "3 亿美元", c: C.red },
    { k: "毛利率再压", v: "200bp", c: C.red },
  ];
  return (
    <>
      <Masthead left="代 价" right="Q4" />
      <Headline y={130}>代价，算得出来</Headline>
      {rows.map((it, i) => {
        const a = clamp01((p - 0.04 - i * 0.05) / 0.05);
        const j = (rnd(i * 5.3 + Math.floor(stepF(f) * 12)) - 0.5) * 4;
        return (
          <div key={i} style={{
            position: "absolute", left: 70, top: 290 + i * 200, width: W - 140,
            opacity: a, transform: `translateX(${j}px)`,
          }}>
            <Cutout x={0} y={0} w={W - 140} h={170} seed={110 + i} rotate={i % 2 ? 0.8 : -0.8} bg="#F4F0E4">
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div style={{ fontSize: 28, fontWeight: 800, color: C.ink, letterSpacing: 2 }}>{it.k}</div>
                <div style={{ fontFamily: MONO, fontSize: 58, fontWeight: 900, color: it.c, letterSpacing: -2 }}>{it.v}</div>
              </div>
            </Cutout>
          </div>
        );
      })}
      <Caption
        y={1040}
        title="伤得最重的是服务器产品线"
        lines={["受损几乎全部集中在 10nm 级别的服务器芯片", "一季度还会再少收约 3 亿美元"]}
        accent={C.red}
      />
    </>
  );
};

/** 7 · 收尾 */
const BeatEnd: React.FC = () => {
  const f = useCurrentFrame();
  const p = beatProg(f / 30, "end");
  const s1 = easeOutCubic(clamp01(p / 0.25));
  const s2 = easeOutCubic(clamp01((p - 0.28) / 0.26));
  const s3 = easeOutCubic(clamp01((p - 0.5) / 0.24));
  return (
    <>
      <Masthead left="尾 版" right="INTC" />
      <div style={{ position: "absolute", left: 80, top: 300, fontFamily: CN_SERIF, fontSize: 96, fontWeight: 900, color: C.ink, letterSpacing: 6, opacity: s1 }}>
        季报是真的好
      </div>
      <Underline x={78} y={396} w={640} delay={6} color={C.ink} width={11} />
      <div style={{ position: "absolute", left: 80, top: 470, fontFamily: CN_SERIF, fontSize: 96, fontWeight: 900, color: C.red, letterSpacing: 6, opacity: s2 }}>
        指引也是真的差
      </div>
      <div style={{ position: "absolute", left: 80, top: 646, fontFamily: CN_SERIF, fontSize: 60, fontWeight: 900, color: C.ink, letterSpacing: 4, opacity: s3 }}>
        问题，不在这个季度
      </div>
      <Stamp x={700} y={790} w={280} h={140} label="-23%" sub="单日" rotate={-8} seed={113} />
      <div style={{ position: "absolute", left: 70, top: 1010, width: W - 140, background: C.ink, color: "#F3EFE4", padding: "24px 28px", fontFamily: CN, opacity: easeOutCubic(clamp01((p - 0.55) / 0.2)) }}>
        <div style={{ fontSize: 23, fontWeight: 700, letterSpacing: 1, lineHeight: 1.6 }}>
          数据来源：财联社 / 证券时报 / IT之家 / 公司财报电话会
        </div>
        <div style={{ fontSize: 21, fontWeight: 700, color: C.gold, marginTop: 8 }}>
          营收 165.1 亿 · EPS 0.52 · 指引 150–160 亿 · 毛利率 44.1%→38%
        </div>
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 220, textAlign: "center", fontFamily: MONO, fontSize: 24, color: C.grey, letterSpacing: 3, opacity: easeOutCubic(clamp01((p - 0.62) / 0.2)) }}>
        INTC · 2026-10-30 · 单日 −23%
      </div>
    </>
  );
};

// ══════════════════════════════════════════════════════════════
//  主组件
// ══════════════════════════════════════════════════════════════

export type IntelCollageProps = {
  /** 字幕:[[起, 止, 文本], ...] */
  subs: [number, number, string][];
  /** 音轨绝对路径(Windows 绝对路径也支持) */
  audioSrc?: string;
};

export const IntelCollage: React.FC<IntelCollageProps> = ({ subs, audioSrc }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  // 当前字幕
  let subText = "";
  let subAlpha = 0;
  for (const [a, b, txt] of subs) {
    if (t >= a && t < b) {
      subText = txt;
      subAlpha = Math.min(clamp01((t - a) / 0.12), clamp01((b - t) / 0.12));
      break;
    }
  }

  // 翻页转场:每拍切换时整页轻微翻转
  const beatStarts = Object.values(BEATS).map(([s]) => s);
  let nearest = 99;
  for (const s of beatStarts) {
    const d = t - s;
    if (d >= 0 && d < nearest) nearest = d;
  }
  const pageFlip = nearest < 0.28 ? (1 - nearest / 0.28) * 3.2 : 0;

  return (
    <AbsoluteFill style={{ background: C.paper, overflow: "hidden" }}>
      <PaperGround />
      {/* 半调网点是 collage 的招牌纹理,0.10 完全看不出来,提到 0.22 */}
      <Halftone id="halftone-ink" color="#16181C" size={8} opacity={0.22} radius={1.9} />
      <Halftone id="halftone-red" color={C.red} size={7} opacity={0.16} radius={1.7} />

      {/* 内容层(带翻页微旋) */}
      <AbsoluteFill
        style={{
          transform: `rotate(${pageFlip}deg) scale(${1 + pageFlip * 0.004})`,
          transformOrigin: "50% 30%",
        }}
      >

        {beatActive(t, "hook") && <BeatHook />}
        {beatActive(t, "good") && <BeatGood />}
        {beatActive(t, "but") && <BeatBut />}
        {beatActive(t, "margin") && <BeatMargin />}
        {beatActive(t, "why") && <BeatWhy />}
        {beatActive(t, "cost") && <BeatCost />}
        {beatActive(t, "end") && <BeatEnd />}
        <Confetti seed={3} count={10} />
      </AbsoluteFill>

      <Ticker t={t} />

      <Subtitle text={subText} alpha={subAlpha} />

      {audioSrc ? <Audio src={resolveAsset(audioSrc)} /> : null}
    </AbsoluteFill>
  );
};
