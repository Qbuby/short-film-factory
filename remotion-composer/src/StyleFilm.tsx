import React from "react";
import {
  AbsoluteFill,
  Audio,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { resolveAsset } from "./lib/resolveAsset";

/**
 * StyleFilm —— 短片工厂的「全风格」通用模板。
 *
 * 之前只有 mg-paperclip 有模板,其余 14 种风格选进去出不了片。
 * 这里用同一份 film.json 节拍数据,画出 15 套真正不同的视觉语言:
 * 背景、字体、卡片形态、装饰图形、动效签名都不一样 ——
 * 不是给贴纸模板换个底色。
 *
 * 每种风格的"画面配方"来自 style_preview.py 的样张(用户选风格时看到的那张图),
 * 保证「选的样子」和「出的片子」是同一个东西。
 */

type Beat = {
  id: string;
  kind: "hook" | "flow" | "compare" | "verdict" | "checklist" | "cta" | "quote";
  title?: string | string[];
  note?: string;
  stamp?: string;
  n?: string;
  face?: boolean;
  visual?: string;
  phone?: string;
  spec?: [string, string][];
  steps?: { label: string }[];
  items?: { n?: string; title: string; sub?: string }[];
  big?: string;
  bigSub?: string;
  left?: { label?: string };
  right?: { label?: string };
  lines?: string[];
  statement?: string;
};

type Film = {
  theme?: Record<string, string>;
  header?: string;
  footer?: { label?: string };
  beats: Beat[];
  timing: Record<string, [number, number]>;
  split: number;
  total: number;
  /** 输出规格:分辨率/帧率推出的精细度(见 tools/motion_design/quality.json) */
  quality?: {
    resolution?: string;
    fps?: number;
    density?: number;
    transition?: "cut" | "slide" | "slam";
    polish?: boolean;
  };
};

export type StyleFilmProps = {
  subs: [number, number, string][];
  audioSrc?: string;
  film?: Film | null;
  styleId?: string;
};

const SANS = `"Noto Sans SC","Microsoft YaHei","PingFang SC","SimHei",sans-serif`;
const SERIF = `"Noto Serif SC","SimSun","Songti SC",serif`;
const MONO = `"Consolas","Courier New",monospace`;

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
const lerp = (a: number, b: number, x: number) => a + (b - a) * x;
const easeOut = (x: number) => 1 - Math.pow(1 - x, 3);
const easeInCubic = (x: number) => x * x * x;
const easeInOut = (x: number) =>
  x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;

/** 每拍进场:统一用 spring,但不同风格给不同的位移/旋转签名。 */
function enter(frame: number, f0: number, fps: number, dist: number, kind: "y" | "x" | "scale" = "y") {
  const f = frame - f0;
  if (f < 0) return { v: dist, x: 0, s: 0.94, o: 0 };
  const p = spring({ frame: f, fps, config: { damping: 16, mass: 0.7 } });
  return {
    v: kind === "y" ? lerp(dist, 0, p) : 0,
    x: kind === "x" ? lerp(dist, 0, p) : 0,
    s: kind === "scale" ? lerp(0.94, 1, p) : 1,
    o: clamp01(f / 6),
  };
}

function beatLines(b: Beat): string[] {
  if (Array.isArray(b.title)) return b.title.filter(Boolean);
  if (typeof b.title === "string" && b.title.trim()) return [b.title];
  if (b.statement) return [b.statement];
  return [];
}

// ─────────────────────────────── 通用排版骨架 ───────────────────────────────

type SkinCtx = {
  t: number;
  frame: number;
  fps: number;
  rel: number;      // 0..1 本拍进度
  f0: number;
  w: number;
  h: number;
  wide: boolean;
  k: number;        // 版式缩放
  vw: number;       // 画面主体的显示宽度
};

type Skin = {
  id: string;
  zh: string;
  /** 底色层(必须常亮:深色底会让 blackdetect 判黑帧) */
  backdrop: (c: SkinCtx) => React.ReactNode;
  /** 每拍的装饰层(风格签名图形) */
  deco?: (c: SkinCtx, b: Beat, i: number) => React.ReactNode;
  /** 主文字 */
  title: (c: SkinCtx) => React.CSSProperties;
  /** 强调色(用于 stamp/编号/关键词) */
  accent: string;
  ink: string;
  muted: string;
  /** 小标签(eyebrow/编号) */
  tag: (c: SkinCtx) => React.CSSProperties;
  /** 卡片(步骤/清单/对照面板) */
  panel: (c: SkinCtx, i: number) => React.CSSProperties;
  /** 图章 */
  seal: (c: SkinCtx) => React.CSSProperties;
  /** 字幕底板 */
  sub: (c: SkinCtx) => React.CSSProperties;
  /** 内容整体进场 */
  body: (c: SkinCtx) => React.CSSProperties;
};

const subtitleBox = (bg: string, color: string, border: string): React.CSSProperties => ({
  background: bg, color, border, borderRadius: 8, padding: "10px 22px",
  fontFamily: SANS, fontWeight: 800, fontSize: 40, lineHeight: 1.3,
  display: "inline-block", maxWidth: "100%",
});

// ─────────────────────────────── 15 套风格 ───────────────────────────────

const SKINS: Record<string, Skin> = {
  // 01 平面矢量科普
  "mg-flat-vector": {
    id: "mg-flat-vector", zh: "平面矢量科普", accent: "#E63946", ink: "#14213D", muted: "#6B7A8F",
    backdrop: ({ t }) => (
      <>
        <AbsoluteFill style={{ background: "#FFFFFF" }} />
        <AbsoluteFill style={{
          background: `radial-gradient(circle at ${28 + Math.sin(t * 0.8) * 6}% ${22 + Math.cos(t * 0.6) * 5}%, #EEF3FF 0%, rgba(255,255,255,0) 55%)`,
        }} />
        {/* 扁平的几何色块持续缓慢旋转/呼吸 */}
        {[
          { x: 6, y: 8, s: 210, c: "#F4A261", r: 0.1, d: 22 },
          { x: 66, y: 20, s: 150, c: "#2A9D8F", r: 0.4, d: 18 },
          { x: 12, y: 74, s: 170, c: "#457B9D", r: 0.7, d: 26 },
          { x: 74, y: 78, s: 130, c: "#E63946", r: 0.2, d: 16 },
        ].map((q, i) => (
          <div key={i} style={{
            position: "absolute", left: `${q.x}%`, top: `${q.y}%`, width: q.s, height: q.s,
            background: q.c, opacity: 0.16,
            borderRadius: i % 2 ? "50%" : 26,
            transform: `translate(${Math.sin(t * 0.9 + i) * q.d}px, ${Math.cos(t * 0.7 + i) * q.d}px) rotate(${t * 12 + i * 40}deg)`,
          }} />
        ))}
      </>
    ),
    deco: (c) => (
      <div style={{
        position: "absolute", right: c.wide ? 80 : 50, top: c.wide ? c.h * 0.5 : c.h * 0.62,
        width: 120, height: 120, background: "#E63946", borderRadius: 60,
        transform: `scale(${1 + Math.sin(c.t * 2) * 0.08})`, opacity: 0.9,
      }} />
    ),
    title: ({ k }) => ({ fontFamily: SANS, fontWeight: 900, fontSize: 82 * k, lineHeight: 1.12, color: "#14213D", letterSpacing: -1 }),
    tag: ({ k }) => ({ fontFamily: SANS, fontWeight: 800, fontSize: 26 * k, color: "#E63946", letterSpacing: 4, textTransform: "uppercase" }),
    panel: ({ k }, i) => ({
      background: ["#EEF3FF", "#FFF0F0", "#F0FFF8"][i % 3], borderRadius: 18,
      border: "3px solid #14213D", padding: 26 * k,
    }),
    seal: ({ k, t }) => ({
      background: "#E63946", color: "#fff", fontFamily: SANS, fontWeight: 900,
      fontSize: 34 * k, padding: "10px 22px", borderRadius: 30,
      transform: `rotate(${-4 + Math.sin(t * 2) * 2}deg)`,
    }),
    sub: (c) => subtitleBox("#14213D", "#fff", "none"),
    body: (c) => {
      const e = enter(c.frame, c.f0, c.fps, 46, "y");
      return { transform: `translateY(${e.v}px)`, opacity: e.o };
    },
  },

  // 02 线稿手绘
  "mg-line-art": {
    id: "mg-line-art", zh: "线稿手绘", accent: "#1B1B1B", ink: "#1B1B1B", muted: "#6B6B6B",
    backdrop: ({ t }) => (
      <>
        <AbsoluteFill style={{ background: "#FBFBF8" }} />
        <AbsoluteFill style={{
          backgroundImage: "repeating-linear-gradient(45deg, rgba(0,0,0,.028) 0 1px, transparent 1px 7px)",
        }} />
        {/* 手绘的辅助线:慢慢生长/擦除 */}
        <svg width="100%" height="100%" style={{ position: "absolute", opacity: 0.5 }}>
          {Array.from({ length: 9 }).map((_, i) => (
            <line key={i} x1={0} y1={i * 120 + 40} x2={1080} y2={i * 120 + 40 - 30}
              stroke="#1B1B1B" strokeWidth={i % 3 === 0 ? 1.6 : 0.7}
              strokeDasharray="300 1200" strokeDashoffset={-((t * 40 + i * 90) % 1500)} />
          ))}
        </svg>
      </>
    ),
    deco: (c) => (
      <svg width={c.wide ? 420 : 520} height={c.wide ? 300 : 360} viewBox="0 0 520 360"
        style={{ position: "absolute", right: c.wide ? 70 : 40, top: c.wide ? c.h * 0.2 : c.h * 0.56 }}>
        {/* 一笔一笔画出来的圆 + 阴影线 */}
        <circle cx="260" cy="180" r="120" fill="none" stroke="#1B1B1B" strokeWidth="4"
          strokeDasharray="754" strokeDashoffset={754 * (1 - clamp01(c.rel * 2.4))} />
        {Array.from({ length: 14 }).map((_, i) => (
          <line key={i} x1={150 + i * 14} y1={292} x2={210 + i * 14} y2={250}
            stroke="#1B1B1B" strokeWidth="2" opacity={0.35} />
        ))}
      </svg>
    ),
    title: ({ k }) => ({ fontFamily: SERIF, fontWeight: 700, fontSize: 78 * k, lineHeight: 1.3, color: "#1B1B1B" }),
    tag: ({ k }) => ({ fontFamily: SERIF, fontSize: 24 * k, color: "#6B6B6B", letterSpacing: 3 }),
    panel: ({ k }) => ({
      background: "rgba(255,255,255,.72)", border: "3px solid #1B1B1B", padding: 22 * k,
      borderRadius: 2,
    }),
    seal: ({ k, t }) => ({
      border: "3px solid #1B1B1B", color: "#1B1B1B", fontFamily: SERIF, fontSize: 30 * k,
      padding: "8px 18px", transform: `rotate(${-3 + Math.sin(t) * 1.5}deg)`,
    }),
    sub: () => subtitleBox("rgba(251,251,248,.92)", "#1B1B1B", "2px solid #1B1B1B"),
    body: (c) => ({ transform: `translateY(${enter(c.frame, c.f0, c.fps, 30).v}px)`, opacity: enter(c.frame, c.f0, c.fps, 30).o }),
  },

  // 03 等距场景
  "mg-isometric": {
    id: "mg-isometric", zh: "等距场景", accent: "#2A9D8F", ink: "#2A3F55", muted: "#6B7A8F",
    backdrop: ({ t }) => {
      const oy = (t * 26) % 84;
      return (
        <>
          <AbsoluteFill style={{ background: "#EAF0F6" }} />
          <svg width="100%" height="100%" style={{ position: "absolute", opacity: 0.55 }}>
            {Array.from({ length: 14 }).map((_, i) => (
              <line key={i} x1={0} y1={i * 84 + oy} x2={1080} y2={i * 84 + oy}
                stroke="#B7C7D6" strokeWidth="1" />
            ))}
          </svg>
        </>
      );
    },
    deco: (c) => {
      const bob = Math.sin(c.t * 1.4) * 12;
      const cube = (x: number, y: number, s: number, col: string) => (
        <g key={x + "-" + y}>
          <path d={`M${x} ${y - s / 2} l${s / 2} ${s / 4} l${-s / 2} ${s / 4} l${-s / 2} ${-s / 4} z`} fill={col} />
          <path d={`M${x - s / 2} ${y - s / 4} l${s / 2} ${s / 4} l0 ${s / 2} l${-s / 2} ${-s / 4} z`} fill="#000" opacity={0.14} />
          <path d={`M${x + s / 2} ${y - s / 4} l${-s / 2} ${s / 4} l0 ${s / 2} l${s / 2} ${-s / 4} z`} fill="#fff" opacity={0.26} />
        </g>
      );
      return (
        <svg width="100%" height="100%" style={{ position: "absolute" }}>
          <g transform={`translate(${c.wide ? 1180 : 300}, ${(c.wide ? 210 : c.h * 0.6) + bob})`}>
            {cube(0, 0, 120, "#2A9D8F")}
            {cube(150, 40, 90, "#E9C46A")}
            {cube(-150, 60, 70, "#457B9D")}
          </g>
        </svg>
      );
    },
    title: ({ k }) => ({ fontFamily: SANS, fontWeight: 800, fontSize: 78 * k, lineHeight: 1.2, color: "#2A3F55" }),
    tag: ({ k }) => ({ fontFamily: SANS, fontWeight: 700, fontSize: 24 * k, color: "#2A9D8F", letterSpacing: 3 }),
    panel: ({ k }, i) => ({
      background: "#FFFFFF", padding: 24 * k,
      clipPath: "polygon(0 12px, 100% 0, 100% calc(100% - 12px), 0 100%)",
      boxShadow: "0 12px 26px rgba(42,63,85,.14)",
      borderTop: `5px solid ${["#2A9D8F", "#E9C46A", "#457B9D"][i % 3]}`,
    }),
    seal: ({ k }) => ({
      background: "#2A3F55", color: "#fff", fontFamily: SANS, fontWeight: 800, fontSize: 30 * k,
      padding: "10px 20px", clipPath: "polygon(0 8px,100% 0,100% calc(100% - 8px),0 100%)",
    }),
    sub: () => subtitleBox("rgba(234,240,246,.94)", "#2A3F55", "2px solid #B7C7D6"),
    body: (c) => ({ transform: `translateX(${enter(c.frame, c.f0, c.fps, 60, "x").x}px)`, opacity: 1 }),
  },

  // 04 3D 渲染
  "mg-3d-render": {
    id: "mg-3d-render", zh: "3D 渲染", accent: "#D84315", ink: "#21242A", muted: "#7A8090",
    backdrop: ({ t }) => (
      <>
        <AbsoluteFill style={{ background: "#F2F0EE" }} />
        <AbsoluteFill style={{
          background: `radial-gradient(circle at ${72 + Math.sin(t * 0.5) * 4}% 18%, #FFE0D4 0%, rgba(242,240,238,0) 46%)`,
        }} />
      </>
    ),
    deco: (c) => {
      const bob = Math.sin(c.t * 1.1) * 14;
      return (
        <>
          <div style={{
            position: "absolute", right: c.wide ? 120 : 60, top: (c.wide ? c.h * 0.22 : c.h * 0.56) + bob,
            width: 190, height: 190, borderRadius: 36,
            background: "radial-gradient(circle at 32% 28%,#fff,#FF8A65 42%,#D84315)",
            boxShadow: "0 34px 60px rgba(216,67,21,.32)",
            transform: `rotate(${Math.sin(c.t) * 8}deg)`,
          }} />
          <div style={{
            position: "absolute", right: c.wide ? 290 : 330, top: (c.wide ? c.h * 0.5 : c.h * 0.78) - bob,
            width: 130, height: 130, borderRadius: "50%",
            background: "radial-gradient(circle at 32% 28%,#fff,#7FD8FF 45%,#0288D1)",
            boxShadow: "0 26px 46px rgba(2,136,209,.3)",
          }} />
        </>
      );
    },
    title: ({ k }) => ({ fontFamily: SANS, fontWeight: 900, fontSize: 80 * k, lineHeight: 1.14, color: "#21242A" }),
    tag: ({ k }) => ({ fontFamily: SANS, fontWeight: 700, fontSize: 24 * k, color: "#D84315", letterSpacing: 3.5 }),
    panel: ({ k }) => ({
      background: "#fff", padding: 26 * k, borderRadius: 22,
      boxShadow: "0 22px 44px rgba(33,36,42,.14), inset 0 1px 0 #fff",
    }),
    seal: ({ k, t }) => ({
      background: "linear-gradient(#FF8A65,#D84315)", color: "#fff", fontFamily: SANS, fontWeight: 900,
      fontSize: 30 * k, padding: "12px 24px", borderRadius: 16,
      boxShadow: "0 12px 24px rgba(216,67,21,.35)", transform: `translateY(${Math.sin(t * 1.6) * 5}px)`,
    }),
    sub: () => subtitleBox("rgba(255,255,255,.94)", "#21242A", "none"),
    body: (c) => ({ transform: `scale(${enter(c.frame, c.f0, c.fps, 0, "scale").s})`, opacity: enter(c.frame, c.f0, c.fps, 0, "scale").o }),
  },

  // 05 手绘 boiling
  "mg-cel-boil": {
    id: "mg-cel-boil", zh: "手绘 boiling", accent: "#C8352B", ink: "#3A2E22", muted: "#8A7660",
    backdrop: ({ t, frame }) => (
      <>
        <AbsoluteFill style={{ background: "#FDF3E3" }} />
        {/* 纸纹 + 逐帧抖动的"手绘"横线(boiling) */}
        <AbsoluteFill style={{
          backgroundImage: "repeating-linear-gradient(0deg, rgba(58,46,34,.05) 0 1px, transparent 1px 5px)",
          transform: `translate(${Math.sin(frame * 7) * 1.5}px, ${Math.cos(frame * 9) * 1.5}px)`,
        }} />
        <AbsoluteFill style={{
          background: `radial-gradient(circle at 50% 40%, rgba(255,255,255,.9), rgba(253,243,227,0) 62%)`,
        }} />
      </>
    ),
    deco: (c) => {
      const j = (n: number) => Math.sin(c.frame * 11 + n) * 3;
      return (
        <svg width="100%" height="100%" style={{ position: "absolute" }}>
          <g transform={`translate(${(c.wide ? 1150 : 300) + j(1)}, ${(c.wide ? 240 : c.h * 0.6) + j(2)})`}>
            <path d="M-120 0 q60 -130 120 0 q-60 130 -120 0" fill="none" stroke="#3A2E22" strokeWidth="6" />
            <path d="M-96 10 q48 -96 96 0" fill="#fff" stroke="#3A2E22" strokeWidth="3" opacity={0.9} />
            <circle cx="-30" cy="-24" r="7" fill="#3A2E22" />
            <circle cx="30" cy="-24" r="7" fill="#3A2E22" />
          </g>
        </svg>
      );
    },
    title: ({ k, frame }) => ({
      fontFamily: SANS, fontWeight: 900, fontSize: 80 * k, lineHeight: 1.2, color: "#3A2E22",
      transform: `rotate(${Math.sin(frame * 12) * 0.35}deg)`,
    }),
    tag: ({ k }) => ({ fontFamily: SANS, fontWeight: 800, fontSize: 24 * k, color: "#C8352B", letterSpacing: 3 }),
    panel: ({ k, frame }, i) => ({
      background: "#FFF8EC", padding: 24 * k, borderRadius: 10,
      border: "4px solid #3A2E22",
      transform: `rotate(${Math.sin(frame * 13 + i) * 0.7}deg)`,
      boxShadow: "6px 7px 0 rgba(58,46,34,.18)",
    }),
    seal: ({ k, frame }) => ({
      border: "5px solid #C8352B", color: "#C8352B", fontFamily: SANS, fontWeight: 900,
      fontSize: 32 * k, padding: "8px 20px", borderRadius: 6,
      transform: `rotate(${-7 + Math.sin(frame * 14) * 2}deg)`,
    }),
    sub: () => subtitleBox("rgba(253,243,227,.95)", "#3A2E22", "3px solid #3A2E22"),
    body: (c) => ({ transform: `translateY(${enter(c.frame, c.f0, c.fps, 22).v}px) rotate(${Math.sin(c.frame * 10) * 0.4}deg)` }),
  },

  // 06 剪报拼贴
  "mg-collage": {
    id: "mg-collage", zh: "剪报拼贴", accent: "#B03A2E", ink: "#3A3226", muted: "#4A4034",
    backdrop: ({ t }) => (
      <>
        <AbsoluteFill style={{ background: "#D9CDB8" }} />
        <AbsoluteFill style={{
          backgroundImage: "repeating-linear-gradient(0deg, rgba(58,50,38,.07) 0 1px, transparent 1px 4px)",
        }} />
        {/* 背景里的旧报纸条,缓慢偏移 */}
        {[
          { r: -3, x: -4, y: 6, w: 62 },
          { r: 4, x: 48, y: 26, w: 58 },
          { r: -2, x: 8, y: 68, w: 70 },
        ].map((p, i) => (
          <div key={i} style={{
            position: "absolute", left: `${p.x}%`, top: `${p.y}%`, width: `${p.w}%`, padding: 18,
            background: "rgba(243,235,221,.75)", transform: `rotate(${p.r + Math.sin(t * 0.4 + i) * 0.6}deg)`,
            boxShadow: "4px 5px 0 rgba(0,0,0,.09)",
            backgroundImage: "repeating-linear-gradient(0deg, rgba(58,50,38,.06) 0 1px, transparent 1px 22px)",
          }} />
        ))}
      </>
    ),
    deco: (c) => (
      <div style={{
        position: "absolute", right: c.wide ? 70 : 56, top: c.wide ? c.h * 0.16 : c.h * 0.62,
        border: "4px solid #B03A2E", color: "#B03A2E", padding: "6px 16px",
        fontFamily: SANS, fontWeight: 900, fontSize: 26,
        transform: `rotate(${-14 + Math.sin(c.t) * 2}deg)`,
      }}>剪报</div>
    ),
    title: ({ k }) => ({ fontFamily: SERIF, fontWeight: 900, fontSize: 76 * k, lineHeight: 1.4, color: "#3A3226" }),
    tag: ({ k }) => ({ fontFamily: SERIF, fontSize: 22 * k, color: "#4A4034", letterSpacing: 2 }),
    panel: ({ k, frame }, i) => ({
      background: i % 2 ? "#E8DCC6" : "#F3EBDD", padding: 22 * k,
      border: "1px solid #B7A88D",
      boxShadow: "6px 8px 0 rgba(0,0,0,.14)",
      // 撕纸边缘:不规则 clip-path
      clipPath: "polygon(0 3%,6% 0,22% 2%,40% 0,58% 3%,76% 0,92% 2%,100% 0,100% 96%,88% 100%,70% 97%,50% 100%,30% 97%,12% 100%,0 96%)",
      transform: `rotate(${(i - 1) * 2.2 + Math.sin(frame * 9 + i) * 0.5}deg)`,
    }),
    seal: ({ k, t }) => ({
      border: "5px solid #B03A2E", color: "#B03A2E", fontFamily: SANS, fontWeight: 900,
      fontSize: 36 * k, padding: "8px 20px", borderRadius: 6,
      transform: `rotate(${-12 + Math.sin(t * 1.4) * 3}deg)`,
    }),
    sub: () => subtitleBox("rgba(243,235,221,.95)", "#3A3226", "2px solid #B7A88D"),
    body: (c) => ({ transform: `rotate(${Math.sin(c.t * 0.9) * 0.5}deg)` }),
  },

  // 07 液态流动
  "mg-liquid": {
    id: "mg-liquid", zh: "液态流动", accent: "#7CF3FF", ink: "#EAF6FF", muted: "#8FA8D8",
    backdrop: ({ t }) => (
      <>
        <AbsoluteFill style={{ background: "linear-gradient(160deg,#141A3E,#0E1030 48%,#1A1440)" }} />
        {[
          { x: 4, y: 14, s: 420, c: "#3B6BF5", d: 40 },
          { x: 46, y: 30, s: 380, c: "#8A3BFF", d: 32 },
          { x: 20, y: 66, s: 440, c: "#26E0C4", d: 46 },
        ].map((b, i) => (
          <div key={i} style={{
            position: "absolute", left: `${b.x}%`, top: `${b.y}%`, width: b.s, height: b.s, opacity: 0.5,
            background: b.c, filter: "blur(52px)",
            borderRadius: `${54 + Math.sin(t * 0.9 + i) * 12}% ${46 - Math.sin(t * 0.9 + i) * 12}% 48% 52%`,
            transform: `translate(${Math.sin(t * 0.7 + i) * b.d}px, ${Math.cos(t * 0.6 + i) * b.d}px)`,
          }} />
        ))}
        {/* 深底上必须有常亮的东西:否则黑帧检测会命中 */}
        <AbsoluteFill style={{ background: "radial-gradient(circle at 50% 42%, rgba(124,243,255,.12), transparent 62%)" }} />
      </>
    ),
    deco: (c) => (
      <div style={{
        position: "absolute", right: c.wide ? 120 : 60, top: c.wide ? c.h * 0.2 : c.h * 0.56,
        width: 240, height: 240,
        borderRadius: `${58 + Math.sin(c.t * 1.6) * 10}% ${42 - Math.sin(c.t * 1.6) * 10}% ${47 + Math.cos(c.t * 1.2) * 10}% ${53 - Math.cos(c.t * 1.2) * 10}%`,
        background: "radial-gradient(circle at 34% 30%,#7CF3FF,#3B6BF5 55%,#1B1F6B)",
        filter: "blur(2px)", boxShadow: "0 0 80px rgba(59,107,245,.5)",
        transform: `scale(${1 + Math.sin(c.t * 1.1) * 0.07})`,
      }} />
    ),
    title: ({ k }) => ({ fontFamily: SANS, fontWeight: 900, fontSize: 78 * k, lineHeight: 1.2, color: "#EAF6FF", textShadow: "0 0 40px rgba(124,243,255,.25)" }),
    tag: ({ k }) => ({ fontFamily: SANS, fontWeight: 700, fontSize: 24 * k, color: "#7CF3FF", letterSpacing: 4 }),
    panel: ({ k }) => ({
      background: "rgba(255,255,255,.09)", border: "1px solid rgba(124,243,255,.35)",
      borderRadius: 18, padding: 24 * k, backdropFilter: "blur(10px)",
      boxShadow: "0 18px 44px rgba(0,0,0,.35)",
    }),
    seal: ({ k, t }) => ({
      background: "linear-gradient(120deg,#7CF3FF55,#8A3BFF66)", color: "#EAF6FF",
      border: "1px solid rgba(124,243,255,.6)", borderRadius: 30, padding: "10px 24px",
      fontFamily: SANS, fontWeight: 800, fontSize: 30 * k,
      boxShadow: "0 0 30px rgba(124,243,255,.35)", transform: `translateY(${Math.sin(t * 1.3) * 6}px)`,
    }),
    sub: () => subtitleBox("rgba(14,16,48,.86)", "#EAF6FF", "1px solid rgba(124,243,255,.4)"),
    body: (c) => ({ transform: `translateY(${enter(c.frame, c.f0, c.fps, 50).v}px) scale(${enter(c.frame, c.f0, c.fps, 0, "scale").s})`, opacity: enter(c.frame, c.f0, c.fps, 50).o }),
  },

  // 08 形变
  "mg-morph": {
    id: "mg-morph", zh: "形变", accent: "#FF7043", ink: "#3E2F25", muted: "#8B7869",
    backdrop: ({ t }) => (
      <>
        <AbsoluteFill style={{ background: "#FFF8EE" }} />
        <AbsoluteFill style={{
          background: `radial-gradient(circle at ${50 + Math.sin(t * 0.6) * 8}% 30%, #FFE9D6, rgba(255,248,238,0) 58%)`,
        }} />
      </>
    ),
    deco: (c) => {
      const p = 0.5 + 0.5 * Math.sin(c.t * 1.4);
      return (
        <div style={{
          position: "absolute", right: c.wide ? 130 : 70, top: c.wide ? c.h * 0.2 : c.h * 0.58,
          width: 220, height: 220,
          // 圆形 → 方形 → 圆形:radius 在插值,这就是"形变"的签名动效
          borderRadius: `${lerp(50, 12, p)}%`,
          background: `linear-gradient(135deg,#FF7043,#FFB03A)`,
          boxShadow: "0 22px 44px rgba(255,112,67,.28)",
          transform: `rotate(${lerp(0, 90, p)}deg)`,
        }} />
      );
    },
    title: ({ k }) => ({ fontFamily: SANS, fontWeight: 900, fontSize: 80 * k, lineHeight: 1.18, color: "#3E2F25" }),
    tag: ({ k }) => ({ fontFamily: SANS, fontWeight: 800, fontSize: 24 * k, color: "#FF7043", letterSpacing: 3 }),
    panel: ({ k, t }, i) => ({
      background: i % 2 ? "#26C6DA" : "#FF7043", color: "#fff", padding: 24 * k,
      borderRadius: `${lerp(50, 16, 0.5 + 0.5 * Math.sin(t * 1.2 + i))}% / ${lerp(40, 18, 0.5 + 0.5 * Math.cos(t * 1.2 + i))}%`,
      minHeight: 130 * k, display: "flex", alignItems: "center", justifyContent: "center",
    }),
    seal: ({ k, t }) => ({
      background: "#3E2F25", color: "#FFF8EE", fontFamily: SANS, fontWeight: 900, fontSize: 30 * k,
      padding: "10px 22px", borderRadius: 24, transform: `scale(${1 + Math.sin(t * 1.8) * 0.05})`,
    }),
    sub: () => subtitleBox("rgba(255,248,238,.95)", "#3E2F25", "2px solid #FF7043"),
    body: (c) => ({ transform: `scale(${enter(c.frame, c.f0, c.fps, 0, "scale").s})`, opacity: enter(c.frame, c.f0, c.fps, 0, "scale").o }),
  },

  // 09 包豪斯几何
  "mg-bauhaus": {
    id: "mg-bauhaus", zh: "包豪斯几何", accent: "#D62828", ink: "#1B1B1B", muted: "#6B6152",
    backdrop: ({ t }) => (
      <>
        <AbsoluteFill style={{ background: "#F2EDE4" }} />
        {/* 包豪斯:圆 / 方 / 三角 三原色的不对称构图 */}
        <div style={{ position: "absolute", left: "58%", top: "7%", width: 250, height: 250, borderRadius: "50%", background: "#1D3557", opacity: 0.85, transform: `scale(${1 + Math.sin(t * 0.8) * 0.04})` }} />
        <div style={{ position: "absolute", left: "6%", top: "76%", width: 200, height: 200, background: "#E9C46A", transform: `rotate(${45 + t * 6}deg)` }} />
        <div style={{ position: "absolute", left: "72%", top: "68%", width: 0, height: 0, borderLeft: "90px solid transparent", borderRight: "90px solid transparent", borderBottom: "150px solid #D62828", opacity: 0.85, transform: `rotate(${Math.sin(t * 0.5) * 6}deg)` }} />
        <div style={{ position: "absolute", left: 0, top: "52%", width: "100%", height: 10, background: "#1B1B1B", opacity: 0.55 }} />
      </>
    ),
    deco: (c) => (
      <div style={{
        position: "absolute", right: c.wide ? 90 : 50, top: 0, writingMode: "vertical-rl",
        fontFamily: SANS, fontWeight: 900, fontSize: 30, color: "#1B1B1B", opacity: 0.5, letterSpacing: 6,
      }}>BAUHAUS · 1919</div>
    ),
    title: ({ k }) => ({ fontFamily: SANS, fontWeight: 900, fontSize: 84 * k, lineHeight: 1.08, color: "#1B1B1B", letterSpacing: -2 }),
    tag: ({ k }) => ({ fontFamily: MONO, fontWeight: 700, fontSize: 22 * k, color: "#D62828", letterSpacing: 6 }),
    panel: ({ k }, i) => ({
      background: ["#FFFFFF", "#1B1B1B", "#E9C46A"][i % 3],
      color: i % 2 ? "#F2EDE4" : "#1B1B1B",
      padding: 24 * k, borderRadius: 0, border: "4px solid #1B1B1B",
    }),
    seal: ({ k }) => ({
      background: "#D62828", color: "#fff", fontFamily: SANS, fontWeight: 900, fontSize: 30 * k,
      padding: "10px 20px", borderRadius: 0, letterSpacing: 2,
    }),
    sub: () => subtitleBox("#1B1B1B", "#F2EDE4", "none"),
    body: (c) => ({ transform: `translateX(${enter(c.frame, c.f0, c.fps, -70, "x").x}px)`, opacity: enter(c.frame, c.f0, c.fps, 0).o }),
  },

  // 10 霓虹复古
  "mg-synthwave": {
    id: "mg-synthwave", zh: "霓虹复古", accent: "#FF2E9A", ink: "#EAF6FF", muted: "#B79BFF",
    backdrop: ({ t }) => (
      <>
        <AbsoluteFill style={{ background: "linear-gradient(#1B1038,#150B2E 55%,#2A0F45)" }} />
        {/* 落日 + 横向扫描线 */}
        <div style={{
          position: "absolute", left: "50%", top: "10%", width: 460, height: 460, marginLeft: -230,
          borderRadius: "50%",
          background: "linear-gradient(#FF2E9A,#FFB03A 60%,#7A2BD4)",
          filter: "blur(1px)", opacity: 0.9,
        }} />
        <div style={{
          position: "absolute", left: "50%", top: "10%", width: 460, height: 460, marginLeft: -230,
          backgroundImage: "repeating-linear-gradient(0deg, rgba(21,11,46,.55) 0 8px, transparent 8px 20px)",
          transform: `translateY(${(t * 30) % 28}px)`, borderRadius: "50%",
        }} />
        {/* 透视地板 */}
        <div style={{
          position: "absolute", left: -200, right: -200, bottom: 0, height: "42%",
          backgroundImage: "linear-gradient(rgba(255,46,154,.55) 2px,transparent 2px),linear-gradient(90deg,rgba(120,80,255,.4) 2px,transparent 2px)",
          backgroundSize: "60px 44px",
          backgroundPositionY: `${(t * 60) % 44}px`,
          transform: "perspective(340px) rotateX(58deg)",
        }} />
      </>
    ),
    deco: (c) => (
      <div style={{
        position: "absolute", right: c.wide ? 110 : 50, top: c.wide ? c.h * 0.2 : c.h * 0.58,
        fontFamily: MONO, fontSize: 22, color: "#25F4EE", letterSpacing: 5, opacity: 0.8,
        textShadow: "0 0 18px rgba(37,244,238,.8)",
        transform: `translateX(${Math.sin(c.t * 1.2) * 6}px)`,
      }}>SYS.1986 // ONLINE</div>
    ),
    title: ({ k }) => ({
      fontFamily: SANS, fontWeight: 900, fontSize: 82 * k, lineHeight: 1.14,
      color: "#25F4EE", letterSpacing: 4,
      textShadow: "-4px 0 #FF2E9A, 4px 0 #7A2BD4, 0 0 34px rgba(37,244,238,.7)",
    }),
    tag: ({ k }) => ({ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k, color: "#FF2E9A", letterSpacing: 6 }),
    panel: ({ k }) => ({
      background: "rgba(21,11,46,.72)", border: "2px solid #FF2E9A", padding: 24 * k, borderRadius: 4,
      boxShadow: "0 0 26px rgba(255,46,154,.35)",
    }),
    seal: ({ k, t }) => ({
      border: "2px solid #25F4EE", color: "#25F4EE", fontFamily: MONO, fontWeight: 700, fontSize: 28 * k,
      padding: "8px 18px", boxShadow: "0 0 24px rgba(37,244,238,.5)",
      transform: `skewX(-8deg) translateY(${Math.sin(t * 1.5) * 4}px)`,
    }),
    sub: () => ({ ...subtitleBox("rgba(21,11,46,.9)", "#25F4EE", "2px solid #FF2E9A"), textShadow: "0 0 18px rgba(37,244,238,.6)" }),
    body: (c) => ({ transform: `translateY(${enter(c.frame, c.f0, c.fps, 40).v}px)`, opacity: enter(c.frame, c.f0, c.fps, 40).o }),
  },

  // 12 极光玻璃
  "mg-aurora-glass": {
    id: "mg-aurora-glass", zh: "极光玻璃", accent: "#26E0C4", ink: "#FFFFFF", muted: "#C6D2F0",
    backdrop: ({ t }) => (
      <>
        <AbsoluteFill style={{ background: "#101426" }} />
        {[
          { x: -6, y: 6, s: 430, c: "#3E7BFA", d: 34 },
          { x: 40, y: 22, s: 400, c: "#B15CFF", d: 26 },
          { x: 8, y: 52, s: 360, c: "#26E0C4", d: 40 },
        ].map((b, i) => (
          <div key={i} style={{
            position: "absolute", left: `${b.x}%`, top: `${b.y}%`, width: b.s, height: b.s,
            borderRadius: "50%", background: b.c, filter: "blur(72px)", opacity: 0.72,
            transform: `translate(${Math.sin(t * 0.55 + i) * b.d}px, ${Math.cos(t * 0.45 + i) * b.d}px)`,
          }} />
        ))}
        <AbsoluteFill style={{ background: "radial-gradient(circle at 50% 40%, rgba(255,255,255,.10), transparent 60%)" }} />
      </>
    ),
    deco: (c) => (
      <div style={{
        position: "absolute", right: c.wide ? 120 : 56, top: c.wide ? c.h * 0.2 : c.h * 0.56,
        width: 210, height: 210, borderRadius: 24,
        background: "rgba(255,255,255,.10)", border: "1px solid rgba(255,255,255,.34)",
        backdropFilter: "blur(18px)",
        boxShadow: "inset 0 1px 0 rgba(255,255,255,.5), 0 24px 60px rgba(0,0,0,.4)",
        transform: `rotate(${Math.sin(c.t * 0.7) * 4}deg) translateY(${Math.sin(c.t) * 8}px)`,
      }} />
    ),
    title: ({ k }) => ({
      fontFamily: SANS, fontWeight: 800, fontSize: 78 * k, lineHeight: 1.2,
      background: "linear-gradient(120deg,#fff,#BFD0FF 45%,#8FF7E6)",
      WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
    }),
    tag: ({ k }) => ({ fontFamily: SANS, fontWeight: 700, fontSize: 24 * k, color: "#8FF7E6", letterSpacing: 4 }),
    panel: ({ k }) => ({
      background: "rgba(255,255,255,.12)", border: "1px solid rgba(255,255,255,.28)",
      borderRadius: 18, padding: 24 * k, backdropFilter: "blur(16px)",
      boxShadow: "inset 0 1px 0 rgba(255,255,255,.42)",
    }),
    seal: ({ k, t }) => ({
      background: "rgba(255,255,255,.16)", border: "1px solid rgba(255,255,255,.4)",
      color: "#fff", borderRadius: 30, padding: "10px 24px", fontFamily: SANS, fontWeight: 800,
      fontSize: 30 * k, backdropFilter: "blur(12px)",
      transform: `translateY(${Math.sin(t * 1.2) * 6}px)`,
    }),
    sub: () => subtitleBox("rgba(16,20,38,.75)", "#FFFFFF", "1px solid rgba(255,255,255,.28)"),
    body: (c) => ({ transform: `translateY(${enter(c.frame, c.f0, c.fps, 44).v}px)`, opacity: enter(c.frame, c.f0, c.fps, 44).o }),
  },

  // 18 汉字视觉
  "mg-hanazi": {
    id: "mg-hanazi", zh: "汉字视觉", accent: "#C8352B", ink: "#1A1A1A", muted: "#6B6152",
    backdrop: ({ t }) => (
      <>
        <AbsoluteFill style={{ background: "#F5EFE2" }} />
        <AbsoluteFill style={{
          backgroundImage: "repeating-linear-gradient(0deg, rgba(26,26,26,.045) 0 1px, transparent 1px 6px)",
        }} />
        {/* 背景大字:汉字视觉的签名 */}
        <div style={{
          position: "absolute", left: "52%", top: "-2%", fontFamily: SANS, fontWeight: 900,
          fontSize: 340, color: "rgba(26,26,26,.07)", lineHeight: 1,
          transform: `translateX(${Math.sin(t * 0.5) * 10}px)`,
        }}>改</div>
      </>
    ),
    deco: (c) => (
      <>
        <div style={{ position: "absolute", left: c.wide ? 80 : 60, top: c.wide ? 56 : 120, width: 140, height: 12, background: "#C8352B", opacity: 0.85 }} />
        <div style={{
          position: "absolute", right: c.wide ? 120 : 60, top: c.wide ? c.h * 0.16 : c.h * 0.6,
          width: 96, height: 96, border: "6px solid #C8352B", color: "#C8352B",
          display: "grid", placeItems: "center", fontFamily: SANS, fontWeight: 900, fontSize: 44,
          transform: `rotate(${-9 + Math.sin(c.t) * 2}deg)`,
        }}>证</div>
      </>
    ),
    title: ({ k }) => ({ fontFamily: SANS, fontWeight: 900, fontSize: 84 * k, lineHeight: 1.22, color: "#1A1A1A", letterSpacing: 2 }),
    tag: ({ k }) => ({ fontFamily: SANS, fontWeight: 800, fontSize: 22 * k, color: "#C8352B", letterSpacing: 5 }),
    panel: ({ k }) => ({
      background: "#FBF7EE", borderLeft: "8px solid #C8352B", padding: 22 * k,
      boxShadow: "0 10px 26px rgba(26,26,26,.08)",
    }),
    seal: ({ k, t }) => ({
      border: "5px solid #C8352B", color: "#C8352B", fontFamily: SANS, fontWeight: 900,
      fontSize: 34 * k, padding: "8px 20px", transform: `rotate(${-8 + Math.sin(t * 1.3) * 2}deg)`,
    }),
    sub: () => subtitleBox("rgba(245,239,226,.95)", "#1A1A1A", "2px solid #C8352B"),
    body: (c) => ({ transform: `translateY(${enter(c.frame, c.f0, c.fps, 34).v}px)`, opacity: enter(c.frame, c.f0, c.fps, 34).o }),
  },

  // 20 像素
  "mg-pixel": {
    id: "mg-pixel", zh: "像素", accent: "#FF4D6D", ink: "#EAF6FF", muted: "#8B87A8",
    backdrop: ({ t, frame }) => {
      // 像素风的核心:动画必须"跳",不能滑。所有位移量化到 6px 网格。
      const step = 6;
      const q = (v: number) => Math.round(v / step) * step;
      return (
        <>
          <AbsoluteFill style={{ background: "#1A1A2E" }} />
          <AbsoluteFill style={{
            backgroundImage: "linear-gradient(rgba(255,255,255,.07) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.07) 1px,transparent 1px)",
            backgroundSize: "24px 24px",
            backgroundPosition: `${q(frame * 2)}px ${q(-t * 60)}px`,
          }} />
          {/* 像素星星,逐格闪烁 */}
          {Array.from({ length: 22 }).map((_, i) => {
            const on = (Math.floor(frame / 6) + i) % 5 === 0;
            return (
              <div key={i} style={{
                position: "absolute", left: (i * 137) % 1080, top: (i * 211) % 1920,
                width: 6, height: 6, background: on ? "#4ECDC4" : "#2E2E4E",
              }} />
            );
          })}
        </>
      );
    },
    deco: (c) => (
      <div style={{
        position: "absolute", right: c.wide ? 140 : 80, top: c.wide ? c.h * 0.2 : c.h * 0.58,
        width: 210, height: 180,
        background: "#FF4D6D",
        clipPath: "polygon(0 25%,25% 0,50% 22%,75% 0,100% 25%,100% 60%,50% 100%,0 60%)",
        filter: "drop-shadow(0 0 22px rgba(255,77,109,.65))",
        transform: `translateY(${Math.round(Math.sin(c.t * 2) * 3) * 8}px)`,
      }} />
    ),
    title: ({ k }) => ({ fontFamily: MONO, fontWeight: 700, fontSize: 76 * k, lineHeight: 1.18, color: "#4ECDC4", letterSpacing: 2, textShadow: "5px 5px 0 #101020" }),
    tag: ({ k }) => ({ fontFamily: MONO, fontWeight: 700, fontSize: 22 * k, color: "#FF4D6D", letterSpacing: 5 }),
    panel: ({ k }) => ({
      background: "#22223A", padding: 22 * k, borderRadius: 0,
      border: "4px solid #4ECDC4", boxShadow: "6px 6px 0 #101020",
    }),
    seal: ({ k }) => ({
      background: "#FF4D6D", color: "#101020", fontFamily: MONO, fontWeight: 700, fontSize: 28 * k,
      padding: "8px 18px", borderRadius: 0, boxShadow: "5px 5px 0 #4ECDC4", letterSpacing: 2,
    }),
    sub: () => ({ ...subtitleBox("#22223A", "#4ECDC4", "4px solid #4ECDC4"), fontFamily: MONO, boxShadow: "5px 5px 0 #101020" }),
    body: (c) => ({ transform: `translateY(${Math.round(enter(c.frame, c.f0, c.fps, 48).v / 6) * 6}px)`, opacity: 1 }),
  },

  // 22 科技 HUD
  "mg-hud": {
    id: "mg-hud", zh: "科技 HUD", accent: "#17E0C4", ink: "#17E0C4", muted: "#4FD1C5",
    backdrop: ({ t, frame }) => (
      <>
        <AbsoluteFill style={{ background: "linear-gradient(#0B2233,#04121A 60%,#061A24)" }} />
        {/* HUD 网格 + 扫描线 + 常亮的雷达环(深底不能全黑) */}
        <AbsoluteFill style={{
          backgroundImage: "linear-gradient(rgba(23,224,196,.10) 1px,transparent 1px),linear-gradient(90deg,rgba(23,224,196,.10) 1px,transparent 1px)",
          backgroundSize: "54px 54px", opacity: 0.9,
        }} />
        <AbsoluteFill style={{
          backgroundImage: "repeating-linear-gradient(0deg,rgba(23,224,196,.07) 0 2px,transparent 2px 5px)",
          transform: `translateY(${(frame * 3) % 5}px)`,
        }} />
        <div style={{
          position: "absolute", left: "50%", top: "50%", width: 620, height: 620, marginLeft: -310, marginTop: -310,
          borderRadius: "50%", border: "2px solid rgba(23,224,196,.22)",
          transform: `scale(${1 + Math.sin(t * 0.8) * 0.06})`,
        }} />
        <div style={{
          position: "absolute", left: "50%", top: "50%", width: 400, height: 400, marginLeft: -200, marginTop: -200,
          borderRadius: "50%",
          background: "conic-gradient(from 0deg, rgba(23,224,196,.18), transparent 32%)",
          transform: `rotate(${t * 42}deg)`,
        }} />
      </>
    ),
    deco: (c) => (
      <>
        {/* 四角括号 */}
        {[[0, 0, 1, 1], [1, 0, -1, 1], [0, 1, 1, -1], [1, 1, -1, -1]].map(([ax, ay, sx, sy], i) => (
          <div key={i} style={{
            position: "absolute",
            left: ax ? undefined : 40, right: ax ? 40 : undefined,
            top: ay ? undefined : 40, bottom: ay ? 40 : undefined,
            width: 90, height: 90,
            borderTop: sy > 0 ? "2px solid #17E0C4" : undefined,
            borderBottom: sy < 0 ? "2px solid #17E0C4" : undefined,
            borderLeft: sx > 0 ? "2px solid #17E0C4" : undefined,
            borderRight: sx < 0 ? "2px solid #17E0C4" : undefined,
            opacity: 0.6,
          }} />
        ))}
        <div style={{
          position: "absolute", right: 60, bottom: 200, fontFamily: MONO, fontSize: 20,
          color: "#17E0C4", opacity: 0.75, lineHeight: 1.6, textAlign: "right",
        }}>
          SYS // {(100 * c.rel).toFixed(0)}%<br />
          DATA {(Math.floor(c.t * 8) % 997).toString().padStart(3, "0")}<br />
          {Math.floor(c.t * 30).toString().padStart(5, "0")}f
        </div>
      </>
    ),
    title: ({ k }) => ({ fontFamily: MONO, fontWeight: 700, fontSize: 72 * k, lineHeight: 1.2, color: "#17E0C4", letterSpacing: 1, textShadow: "0 0 26px rgba(23,224,196,.55)" }),
    tag: ({ k }) => ({ fontFamily: MONO, fontWeight: 700, fontSize: 22 * k, color: "#4FD1C5", letterSpacing: 6 }),
    panel: ({ k }) => ({
      background: "rgba(4,18,26,.72)", padding: 22 * k, borderRadius: 2,
      border: "1px solid rgba(23,224,196,.5)",
      boxShadow: "inset 0 0 30px rgba(23,224,196,.12)",
    }),
    seal: ({ k, t }) => ({
      border: "2px solid #17E0C4", color: "#17E0C4", fontFamily: MONO, fontWeight: 700, fontSize: 26 * k,
      padding: "7px 16px", boxShadow: "0 0 20px rgba(23,224,196,.35), inset 0 0 14px rgba(23,224,196,.15)",
      transform: `translateY(${Math.sin(t * 2) * 3}px)`,
    }),
    sub: () => ({ ...subtitleBox("rgba(4,18,26,.9)", "#17E0C4", "1px solid rgba(23,224,196,.55)"), fontFamily: MONO }),
    body: (c) => ({ transform: `translateY(${enter(c.frame, c.f0, c.fps, 26).v}px)`, opacity: clamp01((c.frame - c.f0) / 3) }),
  },
  // 16 华尔街财经解读(wallstreet-explainer,MIT)
  // 规则来自原 skill:细斜纹深蓝织物是**唯一**底色,奶油金巨数只演钱,
  // 白底原文/白边画框承担证据感,运动交给镜头而不是元素弹跳。
  // 深底必须保持平均亮度,否则黑帧检测会把每一帧判成黑。
  "mg-wallstreet": {
    id: "mg-wallstreet", zh: "华尔街财经解读", accent: "#EFDC7A", ink: "#F1EAD2", muted: "#9AA8BD",
    backdrop: ({ t, frame }) => (
      <>
        <AbsoluteFill style={{ background: "linear-gradient(160deg,#16243B 0%,#101C2E 45%,#0B1422 100%)" }} />
        {/* 45° 细斜纹织物:两条错位的斜线织出布纹,极淡,不抢字 */}
        <AbsoluteFill style={{
          backgroundImage: "repeating-linear-gradient(45deg,rgba(241,234,210,.055) 0 1px,transparent 1px 4px)",
          opacity: 0.95,
        }} />
        <AbsoluteFill style={{
          backgroundImage: "repeating-linear-gradient(-45deg,rgba(10,16,28,.16) 0 1px,transparent 1px 5px)",
          opacity: 0.8,
        }} />
        {/* 一团品牌色的径向光,慢速漂移 —— 讲到"某一家"时的色光 */}
        <AbsoluteFill style={{
          background: `radial-gradient(circle at ${46 + Math.sin(t * 0.42) * 9}% ${38 + Math.cos(t * 0.36) * 7}%, rgba(59,122,28,.20) 0%, rgba(28,107,98,.10) 32%, rgba(0,0,0,0) 68%)`,
        }} />
        {/* 四周压暗,但中心保持可读亮度 */}
        <AbsoluteFill style={{
          background: "radial-gradient(ellipse at 50% 45%,rgba(0,0,0,0) 42%,rgba(4,9,18,.45) 100%)",
        }} />
        {/* 极淡颗粒:逐帧变化,安静的读字段也不会被判死场 */}
        <AbsoluteFill style={{
          backgroundImage: "repeating-linear-gradient(0deg,rgba(255,255,255,.022) 0 1px,transparent 1px 3px)",
          transform: `translateY(${(frame * 2) % 3}px)`,
        }} />
      </>
    ),
    deco: (c) => (
      <>
        {/* 眉题下的一道金线,和奶油金大数字同一套语言 */}
        <div style={{
          position: "absolute", left: 64, right: 64, top: 96,
          height: 1, background: "linear-gradient(90deg,rgba(239,220,122,.55),rgba(239,220,122,0))",
        }} />
        <div style={{
          position: "absolute", left: 64, bottom: 210, fontFamily: MONO, fontSize: 19,
          color: "#9AA8BD", opacity: 0.6, letterSpacing: 3,
        }}>
          MARKET NOTE // {(100 * c.rel).toFixed(0)}%
        </div>
      </>
    ),
    title: ({ k }) => ({
      fontFamily: SANS, fontWeight: 900, fontSize: 76 * k, lineHeight: 1.14,
      color: "#F1EAD2", letterSpacing: 1,
      textShadow: "0 2px 14px rgba(0,0,0,.55)",
    }),
    tag: ({ k }) => ({
      fontFamily: SANS, fontWeight: 800, fontSize: 24 * k, color: "#F2E27E",
      letterSpacing: 8, textTransform: "uppercase",
    }),
    panel: ({ k }, i) => ({
      // 白边画框 / 白底原文卡:证据感来自这两样,不是彩色卡片
      background: i === 1 ? "rgba(244,241,234,.96)" : "rgba(244,241,234,.10)",
      padding: 22 * k, borderRadius: 12,
      border: "3px solid #F4F1EA",
      boxShadow: "0 14px 34px rgba(0,0,0,.42)",
    }),
    seal: ({ k, t }) => ({
      border: "2px solid #EFDC7A", color: "#F1EAD2", fontFamily: MONO, fontWeight: 700,
      fontSize: 25 * k, padding: "7px 16px", letterSpacing: 2,
      transform: `translateY(${Math.sin(t * 1.6) * 2}px)`,
      boxShadow: "inset 0 0 18px rgba(239,220,122,.12)",
    }),
    sub: () => subtitleBox("rgba(8,14,26,.88)", "#FFFFFF", "none"),
    body: (c) => ({
      transform: `translateY(${enter(c.frame, c.f0, c.fps, 22).v}px)`,
      opacity: clamp01((c.frame - c.f0) / 4),
    }),
  },
};

const FALLBACK_SKIN = SKINS["mg-flat-vector"];

/**
 * 画质档位 → 画多少、怎么转。
 * 只认 id,其余参数在 Python 侧(quality.json)控制渲染。
 */
const QLV: { density: number; trans: "cut" | "slide" | "slam"; polish: boolean } = {
  density: 1, trans: "slide", polish: false,
};

/** score-slam:从 2.3 倍砸到 0.965 再回弹(shotcraft 的 B 式砸落)。 */
function slamIn(fIn: number, fps: number) {
  if (fIn < 0) return { s: 2.3, o: 0, blur: 14 };
  if (fIn < 9) return { s: lerp(2.3, 2.05, clamp01(fIn / 9)), o: clamp01(fIn / 3) * 0.9, blur: 14 };
  if (fIn < 15) {
    const land = easeInCubic(clamp01((fIn - 9) / 6));
    return { s: lerp(2.05, 0.965, land), o: 1, blur: lerp(12, 0, land) };
  }
  const back = spring({ frame: fIn - 15, fps, config: { damping: 14, mass: 0.6 } });
  return { s: lerp(0.965, 1, back), o: 1, blur: 0 };
}

/** 深底风格:颗粒用 screen 叠加(同时避免黑帧检测把整帧判成纯黑)。 */
const DARK_STYLES = new Set([
  "mg-hud", "mg-liquid", "mg-synthwave", "mg-aurora-glass", "mg-pixel", "mg-wallstreet",
]);

// ─────────────────────────────── 通用排版 ───────────────────────────────

const Eyebrow: React.FC<{ s: Skin; c: SkinCtx; text: string }> = ({ s, c, text }) => (
  <div style={{ ...s.tag(c), marginBottom: 18 }}>{text}</div>
);

const Headline: React.FC<{ s: Skin; c: SkinCtx; lines: string[] }> = ({ s, c, lines }) => {
  // 纯文字排版(quote)会把整句话塞进 title。固定字号下 20+ 字会折成 4 行,
  // 实测华尔街样片里挤成一团读不了。按"总字数"预算缩字号,让整拍最多两行:
  // 竖屏 9:16 的正文宽约 900px,76px 字一行约 11 个汉字。
  // 一行能装下的字数:76px 基准字号下约 11 个汉字(900px 正文宽)。
  // 目标 = 让每一行都不要再折行;取最长一行而不是总字数。
  const longest = lines.reduce((n, l) => Math.max(n, Array.from(l).length), 0);
  const base = (s.title(c).fontSize as number) || 76;
  const shrink = Math.min(1, Math.max(0.5, 11 / Math.max(1, longest)));
  const size = base * shrink;
  return (
    <>
      {lines.map((ln, i) => (
        <div key={i} style={{ ...s.title(c), fontSize: size, marginBottom: 8 }}>{ln}</div>
      ))}
    </>
  );
};

const Stamp: React.FC<{ s: Skin; c: SkinCtx; text?: string }> = ({ s, c, text }) =>
  text ? <div style={{ ...s.seal(c), display: "inline-block", marginTop: 26 }}>{text}</div> : null;

/**
/** 在字幕里找出与当前拍标题重合的片段,做关键词强调。 */
function markKeywords(sub: string, titles: string[]): boolean[] {
  const mask = new Array(sub.length).fill(false);
  if (!sub) return mask;
  for (const tt of titles) {
    if (!tt) continue;
    const direct = sub.indexOf(tt);
    if (direct >= 0) {
      for (let j = 0; j < tt.length; j++) mask[direct + j] = true;
      continue;
    }
    // 退而求其次:找最长公共片段(至少 3 个字)
    const m = Math.min(sub.length, tt.length);
    for (let L = m; L >= 3; L--) {
      let hit = false;
      for (let i = 0; i + L <= sub.length; i++) {
        const seg = sub.substr(i, L);
        if (tt.indexOf(seg) >= 0) {
          for (let j = 0; j < L; j++) mask[i + j] = true;
          hit = true;
          break;
        }
      }
      if (hit) break;
    }
  }
  return mask;
}

/**
 * 每种风格的招牌图形 —— 模板库样张里最显眼的那一笔。
 *
 * 之前所有风格共用一个红三角 + 同心圆,于是模板库看起来"都一样",
 * 用户根本分不出风格。这里按各自的视觉语言各画各的:
 * 线稿是手绘圆、等距是立方体、像素是方块心、汉字是笔画、赛博是霓虹山脊…
 */
const SignatureGraphic: React.FC<{ s: Skin; c: SkinCtx; dense: boolean }> = ({ s, c, dense }) => {
  const A = s.accent;
  const I = s.ink;
  const W = 360;
  const t = c.t;
  const svg = (h: number, kids: React.ReactNode) => (
    <svg width={c.vw} viewBox={`0 0 ${W} ${h}`} style={{ height: "auto", maxWidth: "100%" }}>{kids}</svg>
  );
  const cx = W / 2, cy = W * 0.36;

  // 平面矢量:叠色圆角方块 + 弹性位移
  if (s.id === "mg-flat-vector") {
    return svg(W * 0.72, <>
      <rect x={cx - 96} y={cy - 96} width={128} height={128} rx={34} fill="#2F6BFF"
        transform={`translate(${Math.sin(t * 1.4) * 12}px, ${Math.cos(t * 1.1) * 10}px) rotate(${Math.sin(t * 0.8) * 8}deg)`} />
      <rect x={cx - 24} y={cy - 46} width={104} height={104} rx={26} fill="#FFB020"
        transform={`translate(${Math.cos(t * 1.2) * 12}px, ${Math.sin(t * 0.9) * 10}px) rotate(${-Math.sin(t * 0.7) * 9}deg)`} />
      <circle cx={cx + 44} cy={cy + 58} r={44} fill="#00C08B" opacity={0.95}
        transform={`scale(${1 + Math.sin(t * 1.8) * 0.07})`} />
    </>);
  }

  // 线稿手绘:一笔画出的圆 + 排线阴影
  if (s.id === "mg-line-art") {
    const p = clamp01(c.rel * 2.2);
    return svg(W * 0.66, <>
      <circle cx={cx} cy={cy} r={92} fill="none" stroke={I} strokeWidth={4}
        strokeDasharray={578} strokeDashoffset={578 * (1 - p)} strokeLinecap="round" />
      <path d={`M${cx - 58} ${cy + 26} q30 -46 58 -12 q28 34 58 -12`} fill="none" stroke={I} strokeWidth={3.5}
        strokeLinecap="round" opacity={0.75} strokeDasharray={170} strokeDashoffset={170 * (1 - p)} />
      {Array.from({ length: 12 }).map((_, i) => (
        <line key={i} x1={cx - 74 + i * 13} y1={cy + 62} x2={cx - 52 + i * 13} y2={cy + 40}
          stroke={I} strokeWidth={2} opacity={0.32} />
      ))}
    </>);
  }

  // 等距场景:三块立方体(顶面菱形朝上,左右两面有明暗)
  if (s.id === "mg-isometric") {
    const cube = (x: number, y: number, sz: number, col: string) => (
      <g key={`${x}-${y}`}>
        {/* 顶面 */}
        <path d={`M${x} ${y - sz / 2} l${sz / 2} ${sz / 4} l${-sz / 2} ${sz / 4} l${-sz / 2} ${-sz / 4} z`} fill={col} />
        {/* 左面(暗) */}
        <path d={`M${x - sz / 2} ${y - sz / 4} l${sz / 2} ${sz / 4} l0 ${sz / 2} l${-sz / 2} ${-sz / 4} z`} fill="#000" opacity={0.16} />
        {/* 右面(亮) */}
        <path d={`M${x + sz / 2} ${y - sz / 4} l${-sz / 2} ${sz / 4} l0 ${sz / 2} l${sz / 2} ${-sz / 4} z`} fill="#fff" opacity={0.3} />
      </g>
    );
    const bob = Math.sin(t * 1.5) * 10;
    return svg(W * 0.68, <g transform={`translate(${cx - 118}, ${cy - 30 + bob})`}>
      {cube(52, 44, 76, "#2A9D8F")}
      {cube(132, 76, 58, "#E9C46A")}
      {cube(-32, 78, 50, "#457B9D")}
    </g>);
  }

  // 3D 渲染:软胶立方 + 高光球
  if (s.id === "mg-3d-render") {
    const bob = Math.sin(t * 1.2) * 11;
    return svg(W * 0.66, <>
      <rect x={cx - 108} y={cy - 96 + bob} width={124} height={124} rx={30}
        fill="url(#g3d)" transform={`rotate(${Math.sin(t * 0.9) * 9}deg ${cx - 46} ${cy - 34})`} />
      <circle cx={cx + 62} cy={cy + 46 - bob} r={48}
        fill="url(#s3d)" />
      <defs>
        <radialGradient id="g3d" cx="32%" cy="28%"><stop offset="0%" stopColor="#fff" /><stop offset="42%" stopColor="#FF8A65" /><stop offset="100%" stopColor="#D84315" /></radialGradient>
        <radialGradient id="s3d" cx="32%" cy="28%"><stop offset="0%" stopColor="#fff" /><stop offset="45%" stopColor="#7FD8FF" /><stop offset="100%" stopColor="#0288D1" /></radialGradient>
      </defs>
    </>);
  }

  // 手绘 boiling:歪线圆脸
  if (s.id === "mg-cel-boil") {
    const j = (n: number) => Math.sin(c.frame * 9 + n) * 4;
    return svg(W * 0.62, <g transform={`translate(${cx + j(1)}, ${cy + j(2)})`}>
      <path d={`M${-86} 6 q${86 + j(3)} -${104 + j(4)} ${172} 0`} fill="#FFD9A0" stroke={I} strokeWidth={5}
        strokeLinejoin="round" />
      <circle cx={-34} cy={-24} r={8} fill={I} />
      <circle cx={34} cy={-24} r={8} fill={I} />
      <path d={`M${-32} 26 q32 ${30 + j(5)} 64 0`} fill="none" stroke={I} strokeWidth={5} strokeLinecap="round" />
    </g>);
  }

  // 剪报拼贴:撕角报纸块
  if (s.id === "mg-collage") {
    return svg(W * 0.66, <>
      <g transform={`rotate(-5 ${cx} ${cy})`}>
        <path d="M40 20 h170 v40 l-14 8 l16 10 l-16 10 l14 10 l-12 10 l12 10 l-14 8 l14 8 h-170 z"
          fill="#F3EBDD" stroke="#B7A88D" strokeWidth={2} />
        <text x={54} y={62} fontSize={22} fill="#3A3226" fontFamily={SANS} fontWeight={800}>旧 日 报</text>
        {Array.from({ length: 6 }).map((_, i) => (
          <rect key={i} x={54} y={78 + i * 15} width={i % 3 === 2 ? 92 : 142} height={5} fill="#8C7F6A" opacity={0.55} />
        ))}
      </g>
      <g transform={`rotate(6 ${cx + 40} ${cy + 60})`}>
        <rect x={cx + 10} y={cy + 26} width={118} height={86} fill="#E8DCC6" stroke="#B7A88D" strokeWidth={2} />
        <rect x={cx + 24} y={cy + 44} width={62} height={54} fill={A} opacity={0.8} />
      </g>
    </>);
  }

  // 液态流动:两团流体互相挤压(平滑闭合曲线的边缘,不是硬多边形)
  if (s.id === "mg-liquid") {
    const p = 0.5 + 0.5 * Math.sin(t * 1.5);
    const blob = (cx0: number, cy0: number, rx: number, ry: number, col: string, seed: number) => {
      const N = 8;
      const pt = (i: number) => {
        const ang = (i / N) * Math.PI * 2;
        const wob = 1 + Math.sin(t * 1.6 + seed + i * 1.7) * 0.12 + p * 0.05;
        return [cx0 + Math.cos(ang) * rx * wob, cy0 + Math.sin(ang) * ry * wob] as const;
      };
      // Catmull-Rom → 三次贝塞尔,闭合曲线,边缘才像流体
      const pts = Array.from({ length: N }, (_, i) => pt(i));
      let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
      for (let i = 0; i < N; i++) {
        const p0 = pts[(i - 1 + N) % N], p1 = pts[i], p2 = pts[(i + 1) % N], p3 = pts[(i + 2) % N];
        const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
        const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
        d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
      }
      return <path key={`${col}-${seed}`} d={d + " Z"} fill={col} />;
    };
    return svg(W * 0.66, <>
      {blob(cx - 46, cy - 6, 74, 88, "#3B6BF5", 0)}
      {blob(cx + 50, cy + 16, 70, 82, "#8A3BFF", 2.2)}
      {blob(cx + 2, cy - 34, 46, 32, "#7CF3FF", 4.1)}
    </>);
  }

  // 形变:圆 → 方 连续变形
  if (s.id === "mg-morph") {
    const p = 0.5 + 0.5 * Math.sin(t * 1.4);
    return svg(W * 0.64, <>
      <rect x={cx - 92} y={cy - 62} width={104} height={104} rx={lerp(52, 10, p)}
        fill="#FF7043" transform={`rotate(${lerp(0, 90, p)} ${cx - 40} ${cy - 10})`} />
      <circle cx={cx + 52} cy={cy + 18} r={56} fill="#26C6DA" opacity={0.92}
        transform={`scale(${1 + Math.sin(t * 2.1) * 0.06})`} />
    </>);
  }

  // 包豪斯:圆 / 方 / 三角 三原色构成
  if (s.id === "mg-bauhaus") {
    return svg(W * 0.64, <>
      <circle cx={cx - 78} cy={cy - 34} r={54} fill="#1D3557" />
      <rect x={cx + 6} y={cy - 78} width={104} height={104} fill="#E9C46A"
        transform={`rotate(${18 + t * 8}deg ${cx + 58} ${cy - 26})`} />
      <polygon points={`${cx - 34},${cy + 92} ${cx + 38},${cy + 92} ${cx + 2},${cy + 6}`} fill="#D62828" />
      <rect x={cx - 118} y={cy + 104} width={236} height={8} fill="#1B1B1B" opacity={0.75} />
    </>);
  }

  // 霓虹复古:霓虹山脊 + 落日
  if (s.id === "mg-synthwave") {
    const sun = 56 - ((t * 22) % 44);
    return svg(W * 0.64, <>
      <circle cx={cx} cy={cy + 20 - sun * 0.4} r={52} fill="none" stroke="#25F4EE" strokeWidth={3}
        strokeOpacity={0.85} />
      <path d={`M20 ${cy + 66} L${cx - 40} ${cy - 4} L${cx + 16} ${cy + 30} L${cx + 62} ${cy - 30} L${W - 20} ${cy + 66} Z`}
        fill="none" stroke="#FF2E9A" strokeWidth={4} strokeLinejoin="round" />
      <path d={`M20 ${cy + 88} L${cx - 30} ${cy + 26} L${cx + 24} ${cy + 56} L${cx + 66} ${cy + 8} L${W - 20} ${cy + 88} Z`}
        fill="none" stroke="#7A2BD4" strokeWidth={3} strokeOpacity={0.75} />
    </>);
  }

  // 极光玻璃:磨砂玻璃卡片叠色斑
  if (s.id === "mg-aurora-glass") {
    return svg(W * 0.64, <>
      <circle cx={cx - 74} cy={cy - 40} r={62} fill="#3E7BFA" opacity={0.55} filter="blur(26px)" />
      <circle cx={cx + 62} cy={cy - 12} r={54} fill="#B15CFF" opacity={0.5} filter="blur(26px)" />
      <circle cx={cx - 10} cy={cy + 56} r={48} fill="#26E0C4" opacity={0.42} filter="blur(26px)" />
      <rect x={cx - 88} y={cy - 54} width={176} height={116} rx={16}
        fill="rgba(255,255,255,.16)" stroke="rgba(255,255,255,.34)" strokeWidth={2}
        transform={`translateY(${Math.sin(t * 1.3) * 7}px)`} />
    </>);
  }

  // 华尔街财经解读:奶油金巨数 + 同坐标系的柱子 + 荧光黄高亮刷过。
  // 三样东西都在动,而且都在演"一笔账",不是装饰。
  if (s.id === "mg-wallstreet") {
    const bars = [0.42, 0.68, 0.53, 0.88, 0.74];
    const glow = (t * 130) % 420;
    return svg(W * 0.82, <>
      <defs>
        <linearGradient id="ws-gold" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#FFFEF2" />
          <stop offset="52%" stopColor="#FFF3B5" />
          <stop offset="100%" stopColor="#EFDC7A" />
        </linearGradient>
        <linearGradient id="ws-hl" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="rgba(255,216,74,0)" />
          <stop offset="45%" stopColor="rgba(255,216,74,.85)" />
          <stop offset="100%" stopColor="rgba(255,216,74,0)" />
        </linearGradient>
      </defs>
      {/* 奶油金巨数 */}
      <text x={cx} y={cy - 34} textAnchor="middle" fontFamily={MONO} fontWeight={900}
        fontSize={112} fill="url(#ws-gold)" letterSpacing={-3}
        transform={`translate(${Math.sin(t * 0.7) * 4}px,0)`}>
        $725B
      </text>
      {/* 单位:数黑体气质的中文小字 */}
      <text x={cx} y={cy + 4} textAnchor="middle" fontFamily={SANS} fontWeight={800}
        fontSize={22} fill="#F2E27E" letterSpacing={6}>算力开支 / 一年</text>
      {/* 同一坐标系的柱子:连续累积,不重画 */}
      {bars.map((v, i) => {
        const x = 34 + i * 62;
        const h = 96 * v * (0.82 + 0.18 * Math.sin(t * 1.1 + i * 0.7));
        return (
          <g key={i}>
            <rect x={x} y={196 - h} width={40} height={h} rx={3}
              fill={i === 3 ? "#EFDC7A" : "rgba(241,234,210,.42)"} />
            <line x1={x} y1={196} x2={x + 40} y2={196} stroke="#F1EAD2" strokeOpacity={0.35} strokeWidth={2} />
          </g>
        );
      })}
      {/* 荧光笔:正片叠底的一道光横刷过 */}
      <rect x={glow - 150} y={222} width={300} height={13} rx={6} fill="url(#ws-hl)" opacity={0.75} />
      <line x1={30} y1={228} x2={W - 30} y2={228} stroke="#F1EAD2" strokeOpacity={0.25} strokeWidth={2} />
      {dense && (
        <text x={W - 30} y={254} textAnchor="end" fontFamily={MONO} fontSize={16}
          fill="#9AA8BD" letterSpacing={2}>FY 2026 · USD</text>
      )}
    </>);
  }

  // 汉字视觉:大字 + 朱红印
  if (s.id === "mg-hanazi") {
    return svg(W * 0.64, <>
      <text x={cx} y={cy + 46} textAnchor="middle" fontSize={186} fill={I}
        fontFamily={SANS} fontWeight={900}>稳</text>
      <rect x={cx + 44} y={cy + 58} width={54} height={54} fill="none" stroke={A} strokeWidth={5}
        transform={`rotate(-8 ${cx + 71} ${cy + 85})`} />
      <text x={cx + 71} y={cy + 95} textAnchor="middle" fontSize={30} fill={A}
        fontFamily={SANS} fontWeight={900}>印</text>
    </>);
  }

  // 像素:方块拼的心 + 扫描线
  if (s.id === "mg-pixel") {
    // 心形由 7x5 方块位图定义,位置是整数格,才不会拼歪
    const heart: string[] = [
      ".XX.XX.",
      "XXXXXXX",
      "XXXXXXX",
      ".XXXXX.",
      "..XXX..",
    ];
    const cell = 26;
    const gw = heart[0].length * cell;
    const gh = heart.length * cell;
    const gx = cx - gw / 2, gy = cy - gh / 2;
    return svg(W * 0.62, <>
      {heart.map((row, r) => row.split("").map((ch, c) => ch !== "X" ? null : (
        <rect key={`${r}-${c}`} x={gx + c * cell} y={gy + r * cell} width={cell} height={cell}
          fill={(r + c) % 3 === 0 ? "#FF4D6D" : "#FF7D95"} />
      )))}
      {dense && Array.from({ length: 7 }).map((_, i) => (
        <rect key={i} x={gx} y={gy - 14 + i * 22} width={gw} height={3} fill="#4ECDC4" opacity={0.2} />
      ))}
    </>);
  }

  // 科技 HUD:雷达环 + 扫描线
  if (s.id === "mg-hud") {
    const sweep = (t * 62) % 360;
    return svg(W * 0.64, <>
      <circle cx={cx} cy={cy} r={94} fill="none" stroke={A} strokeWidth={2} strokeOpacity={0.55} />
      <circle cx={cx} cy={cy} r={64} fill="none" stroke={A} strokeWidth={1.5} strokeOpacity={0.34} />
      <circle cx={cx} cy={cy} r={34} fill="none" stroke={A} strokeWidth={1.5} strokeOpacity={0.24} />
      <path d={`M${cx} ${cy} L${cx + Math.cos((sweep * Math.PI) / 180) * 92} ${cy + Math.sin((sweep * Math.PI) / 180) * 92}`}
        stroke={A} strokeWidth={2.5} strokeOpacity={0.85} />
      <circle cx={cx} cy={cy} r={5} fill={A} />
      {dense && [[-62, -40], [44, -58], [58, 44], [-46, 56]].map(([x, y], i) => (
        <circle key={i} cx={cx + x} cy={cy + y} r={3.5} fill={A} opacity={0.9} />
      ))}
    </>);
  }

  // 兜底:与原实现一致的环 + 三角
  const R = 92 + Math.sin(t * 1.6) * 6;
  return svg(W * 0.72, <>
    {Array.from({ length: 12 }).map((_, i) => {
      const ang = (i / 12) * Math.PI * 2 + t * 0.22;
      const r1 = R + 26, r2 = R + 52 + (i % 3) * 12;
      return (
        <line key={i}
          x1={cx + Math.cos(ang) * r1} y1={cy + Math.sin(ang) * r1}
          x2={cx + Math.cos(ang) * r2} y2={cy + Math.sin(ang) * r2}
          stroke={A} strokeWidth={4} strokeOpacity={0.35} strokeLinecap="round" />
      );
    })}
    <circle cx={cx} cy={cy} r={R} fill="none" stroke={A} strokeWidth={3} strokeOpacity={0.55} />
    <polygon points={`${cx},${cy - 46} ${cx + 44},${cy + 30} ${cx - 44},${cy + 30}`} fill={A} opacity={0.92} />
  </>);
};

/** 每拍的「画面主体」——画出来的东西,不是又一张文字卡。
 * 之前 14 种风格全是「标题+注释+文字卡」,所以像 PPT;
 * 这里给每一拍一个真正的图形构图,风格只换配色与质感。
 */
const VisualBody: React.FC<{ b: Beat; c: SkinCtx; s: Skin; density: number }> = ({ b, c, s, density }) => {
  if (density <= 0) return null;
  const A = s.accent;
  const I = s.ink;
  const W = 360;                       // 内部坐标系
  const DW = c.vw;                     // 显示宽度(等比放大)
  const dense = density >= 2;
  // 内部画 360 宽,按显示宽度等比放大 —— 竖屏给足存在感,横屏收敛一点
  const svg = (h: number, kids: React.ReactNode) => (
    <svg width={DW} viewBox={`0 0 ${W} ${h}`} style={{ height: "auto", maxWidth: "100%" }}>{kids}</svg>
  );

  if (b.kind === "flow" && b.steps?.length) {
    const n = b.steps.length;
    const y = 70;
    const gap = (W - 80) / Math.max(1, n - 1);
    return (
      svg(140, <>
        <line x1={40} y1={y} x2={W - 40} y2={y} stroke={I} strokeOpacity={0.22} strokeWidth={3} />
        {dense && (
          <line x1={40} y1={y - 26} x2={W - 40} y2={y - 26} stroke={I} strokeOpacity={0.1} strokeWidth={2} />
        )}
        {b.steps.map((_, i) => {
          const x = 40 + i * gap;
          return (
            <g key={i}>
              <rect x={x - 24} y={y - 24} width={48} height={48} rx={11} fill={A} opacity={0.92} />
              <circle cx={x} cy={y} r={8} fill="#fff" opacity={0.95} />
              {dense && <text x={x} y={y + 54} textAnchor="middle" fontSize="19" fill={I} opacity={0.6} fontFamily={MONO}>{String(i + 1).padStart(2, "0")}</text>}
            </g>
          );
        })}
        {/* 沿线流动的光点:流程是「在走」的,不是静态图 */}
        <circle cx={40 + ((c.t * 0.42) % 1) * (W - 80)} cy={y} r={13} fill={A} opacity={0.45} />
      </>)
    );
  }

  if (b.kind === "compare" || (b.left && b.right)) {
    return (
      svg(130, <>
        <rect x={6} y={26} width={128} height={78} rx={12} fill={I} opacity={0.13} />
        <rect x={W - 134} y={26} width={128} height={78} rx={12} fill={A} opacity={0.92} />
        <path d={`M${W / 2 - 34} 65 L${W / 2 + 18} 65`} stroke={I} strokeWidth={5} strokeLinecap="round" />
        <path d={`M${W / 2 + 12} 53 L${W / 2 + 34} 65 L${W / 2 + 12} 77 Z`} fill={I} />
        {dense && (
          <>
            <circle cx={W / 2} cy={65} r={46} fill="none" stroke={A} strokeWidth={2} strokeOpacity={0.5} />
            <circle cx={W / 2} cy={65} r={58} fill="none" stroke={A} strokeWidth={1.5} strokeOpacity={0.28} />
          </>
        )}
      </>)
    );
  }

  if (b.kind === "checklist" && b.items?.length) {
    const prog = clamp01(c.rel * 1.15);
    return (
      svg(110, <>
        <rect x={0} y={38} width={W} height={16} rx={8} fill={I} opacity={0.15} />
        <rect x={0} y={38} width={W * prog} height={16} rx={8} fill={A} opacity={0.95} />
        {b.items.map((_, i) => {
          const x = 14 + i * ((W - 28) / Math.max(1, b.items!.length - 1));
          const on = prog > (i + 0.35) / b.items!.length;
          return (
            <g key={i}>
              <rect x={x - 9} y={32} width={18} height={28} rx={4}
                fill={on ? A : "none"} stroke={A} strokeWidth={3} opacity={on ? 1 : 0.5} />
              <path d={`M${x - 4} 45 L${x - 1} 49 L${x + 6} 41`} stroke="#fff" strokeWidth={3}
                fill="none" opacity={on ? 1 : 0} />
            </g>
          );
        })}
        {dense && (
          <text x={W} y={92} textAnchor="end" fontSize="20" fill={I} opacity={0.55} fontFamily={MONO}>
            {Math.round(prog * 100)}%
          </text>
        )}
      </>)
    );
  }

  if (b.kind === "cta" || b.kind === "hook") {
    // 每种风格有自己的招牌图形。共用一个三角形会让所有风格看起来一样,
    // 模板库里就分不出风格了 —— 这里按风格各画各的。
    return <SignatureGraphic s={s} c={c} dense={dense} />;
  }

  // verdict / quote:引号构图 + 分割线
  return (
    svg(120, <>
      <text x={4} y={66} fontSize={92} fill={A} opacity={0.5} fontFamily={SANS} fontWeight={900}>「</text>
      <line x1={78} y1={70} x2={W - 8} y2={70} stroke={I} strokeWidth={3} strokeOpacity={0.3} />
      {dense && Array.from({ length: 5 }).map((_, i) => (
        <rect key={i} x={78 + i * 22} y={82} width={12} height={12} fill={A} opacity={0.5 - i * 0.07} />
      ))}
    </>)
  );
};

/** 每拍的内容体:按 kind 组织,但视觉全部走当前风格的 skin。 */
const BeatBody: React.FC<{ s: Skin; c: SkinCtx; b: Beat }> = ({ s, c, b }) => {
  const lines = beatLines(b);
  const k = c.k;

  if (b.kind === "flow" && b.steps?.length) {
    return (
      <>
        {b.n && <Eyebrow s={s} c={c} text={b.n} />}
        <Headline s={s} c={c} lines={lines} />
        <div style={{ display: "flex", flexDirection: c.wide ? "row" : "column", gap: 16 * k, marginTop: 34 }}>
          {(b.steps || []).slice(0, 3).map((stp, i) => (
            <div key={i} style={{ ...s.panel(c, i), display: "flex", alignItems: "center", gap: 18, flex: 1 }}>
              <div style={{
                fontFamily: MONO, fontWeight: 800, fontSize: 40 * k, color: s.accent,
                minWidth: 48 * k,
              }}>{String(i + 1).padStart(2, "0")}</div>
              <div style={{ fontFamily: SANS, fontWeight: 800, fontSize: 34 * k, lineHeight: 1.3 }}>{stp.label}</div>
            </div>
          ))}
        </div>
        {b.note && <div style={{ fontFamily: SANS, fontSize: 26 * k, opacity: 0.8, marginTop: 22 * k, color: s.muted }}>{b.note}</div>}
      </>
    );
  }

  if (b.kind === "compare" || (b.left && b.right)) {
    return (
      <>
        {b.n && <Eyebrow s={s} c={c} text={b.n} />}
        <Headline s={s} c={c} lines={lines} />
        <div style={{ display: "flex", flexDirection: "row", gap: 16 * k, marginTop: 34, alignItems: "stretch" }}>
          {[{ l: b.left?.label || "", a: false }, { l: b.right?.label || "", a: true }].map((x, i) => (
            <div key={i} style={{ ...s.panel(c, i), flex: 1, display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center", minHeight: 150 * k }}>
              <div style={{
                fontFamily: SANS, fontWeight: 900, fontSize: 42 * k,
                color: x.a ? s.accent : s.ink,
              }}>{x.l}</div>
            </div>
          ))}
        </div>
        {b.note && <div style={{ fontFamily: SANS, fontSize: 26 * k, opacity: 0.8, marginTop: 22 * k, color: s.muted }}>{b.note}</div>}
        <Stamp s={s} c={c} text={b.stamp} />
      </>
    );
  }

  if (b.kind === "checklist" && b.items?.length) {
    return (
      <>
        {b.n && <Eyebrow s={s} c={c} text={b.n} />}
        <Headline s={s} c={c} lines={lines} />
        <div style={{ display: "flex", flexDirection: "column", gap: 14 * k, marginTop: 30 }}>
          {(b.items || []).slice(0, 3).map((it, i) => (
            <div key={i} style={{ ...s.panel(c, i), display: "flex", gap: 16, alignItems: "center" }}>
              <div style={{
                width: 52 * k, height: 52 * k, borderRadius: 8, background: s.accent,
                display: "flex", alignItems: "center", justifyContent: "center",
                color: "#fff", fontFamily: MONO, fontWeight: 900, fontSize: 24 * k, flexShrink: 0,
              }}>{it.n || i + 1}</div>
              <div>
                <div style={{ fontFamily: SANS, fontWeight: 800, fontSize: 36 * k, lineHeight: 1.25 }}>{it.title}</div>
                {it.sub && <div style={{ fontFamily: SANS, fontSize: 24 * k, color: s.muted, marginTop: 4 }}>{it.sub}</div>}
              </div>
            </div>
          ))}
        </div>
      </>
    );
  }

  // hook / verdict / cta / quote:一句话大字 + 支撑信息
  return (
    <>
      {b.n && <Eyebrow s={s} c={c} text={b.n} />}
      <Headline s={s} c={c} lines={lines.length ? lines : [b.statement || ""]} />
      {b.big && (
        <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginTop: 26 }}>
          <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 96 * k, color: s.accent, lineHeight: 1 }}>{b.big}</div>
          {b.bigSub && <div style={{ fontFamily: SANS, fontSize: 28 * k, color: s.muted }}>{b.bigSub}</div>}
        </div>
      )}
      {b.note && (
        <div style={{ fontFamily: SANS, fontSize: 28 * k, lineHeight: 1.5, marginTop: 24, color: s.muted }}>
          {b.note}
        </div>
      )}
      {b.spec && b.spec.length > 0 && (
        <div style={{ ...s.panel(c, 0), marginTop: 30 }}>
          {b.spec.slice(0, 4).map(([a, v], i) => (
            <div key={i} style={{
              display: "flex", justifyContent: "space-between", gap: 20,
              padding: `${10 * k}px 0`, borderBottom: i < b.spec!.length - 1 ? "1px solid rgba(128,128,128,.25)" : "none",
            }}>
              <span style={{ fontFamily: SANS, fontSize: 26 * k, color: s.muted }}>{a}</span>
              <span style={{ fontFamily: MONO, fontWeight: 800, fontSize: 28 * k, color: s.accent }}>{v}</span>
            </div>
          ))}
        </div>
      )}
      <Stamp s={s} c={c} text={b.stamp} />
    </>
  );
};

// ─────────────────────────────── 主组件 ───────────────────────────────

const DEMO: Film = {
  header: "短片工厂 · 全风格模板",
  footer: { label: "示例" },
  beats: [{ id: "hook", kind: "hook", title: ["十五种风格", "每一种都能出片"], stamp: "示例" }],
  timing: { hook: [0, 4] },
  split: 2,
  total: 4,
};

export const StyleFilm: React.FC<StyleFilmProps> = ({ subs, audioSrc, film, styleId }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const t = frame / fps;
  const data: Film = film && film.beats?.length ? film : DEMO;
  const skin = SKINS[styleId || "mg-flat-vector"] || FALLBACK_SKIN;
  // 画质由后端算好传进来:分辨率决定画多少细节,帧率决定要不要开精修层
  const qspec = data.quality || {};
  const ql = {
    density: qspec.density ?? QLV.density,
    trans: qspec.transition ?? QLV.trans,
    polish: !!qspec.polish,
  };
  const wide = width > height;
  const k = wide ? Math.min(1, height / 1080) * 0.94 : width / 1080;

  const timing = data.timing || {};
  const beatAt = (id: string): [number, number] => timing[id] || [0, data.total || 4];
  const active = data.beats.find((b) => {
    const [s, e] = beatAt(b.id);
    return t >= s && t < e;
  });

  let subText = "";
  let subAlpha = 0;
  for (const [a, b, txt] of subs || []) {
    if (t >= a && t < b) {
      subText = txt;
      subAlpha = Math.min(clamp01((t - a) / 0.08), clamp01((b - t) / 0.08));
      break;
    }
  }

  const ctx = (f0: number, rel: number): SkinCtx =>
    ({ t, frame, fps, rel, f0, w: width, h: height, wide, k, vw: wide ? 380 : 700 });

  // 撞镜:每拍开头画面整体快速推近再回落(精细档)
  const activeF0 = active ? beatAt(active.id)[0] * fps : 0;
  const crash = ql.trans === "slam" ? 0.13 * (1 - easeOut(clamp01((frame - activeF0) / 16))) : 0;
  const pct = clamp01(t / (data.total || 4));
  const kwMask = ql.polish && subText ? markKeywords(subText, active ? beatLines(active) : []) : [];

  return (
    <AbsoluteFill style={{ overflow: "hidden", fontFamily: SANS }}>
      {/* 风格底:每种风格自己的背景语言 */}
      {skin.backdrop(ctx(0, 0))}

      {/* 内容层:常驻慢漂移,避免任何画幅静成死场 */}
      <AbsoluteFill style={{
        transform: `translate(${Math.sin(t * 1.05) * 11}px, ${Math.cos(t * 0.85) * 9}px) scale(${(1.02 + Math.sin(t * 0.35) * 0.012) * (1 + crash)})`,
      }}>
        {active && (() => {
          const [s, e] = beatAt(active.id);
          const f0 = s * fps;
          const fIn = frame - f0;
          const rel = clamp01((t - s) / Math.max(0.001, e - s));
          const c = ctx(f0, rel);
          const i = data.beats.findIndex((b) => b.id === active.id);
          const body = enter(frame, f0, fps, 44);
          // 转场语言:快剪淡入 / 标准推入 / 精细砸落(shotcraft 的 score-slam)
          let tx = 0, ts = 1, op = 1, blur = 0;
          if (ql.trans === "cut") {
            op = clamp01(fIn / 5);
          } else if (ql.trans === "slide") {
            const p = spring({ frame: Math.max(0, fIn), fps, config: { damping: 18, mass: 0.7 } });
            tx = lerp(96, 0, p);
            op = clamp01(fIn / 4);
          } else {
            const sm = slamIn(fIn, fps);
            ts = sm.s; op = sm.o; blur = sm.blur;
          }
          const drift = Math.sin(t * 1.7) * 7;
          return (
            <>
              {/* 装饰层降为背景水印:现在主体有了专属招牌图形,
                  装饰若与主体同等强度就会互相打架(样张里就是这么糊的)。 */}
              {skin.deco && (
                <div style={{ position: "absolute", inset: 0, opacity: 0.4, pointerEvents: "none" }}>
                  {skin.deco(c, active, i)}
                </div>
              )}
              <AbsoluteFill style={{
                // 竖屏:上留标题区,下留字幕区,主体在中间 —— 不要贴顶,
                // 也不要让图形掉到很下面,那样中间会空一大块。
                padding: wide ? `70px ${110}px` : `118px ${64}px 250px ${64}px`,
                boxSizing: "border-box",
                display: "flex",
                flexDirection: wide ? "row" : "column",
                alignItems: wide ? "center" : "stretch",
                justifyContent: wide ? "center" : "flex-start",
                gap: wide ? 46 : 0,
              }}>
                <div style={{
                  flex: wide ? "1 1 58%" : "0 0 auto",
                  maxWidth: wide ? 940 : 900,
                  transform: `translate(${tx}px, ${body.v + drift}px) scale(${ts * body.s})`,
                  opacity: op * body.o,
                  filter: blur > 0.1 ? `blur(${blur}px)` : undefined,
                }}>
                  <BeatBody s={skin} c={c} b={active} />
                </div>
                {ql.density > 0 && (
                  <div style={{
                    flex: wide ? "0 0 38%" : "0 0 auto",
                    // 竖屏时主体要占满整行,否则会贴着左边像没对齐
                    alignSelf: wide ? "auto" : "stretch",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    opacity: op,
                    marginTop: wide ? 0 : 30,
                    transform: `translateY(${drift * 0.6}px) scale(${0.92 + 0.08 * op})`,
                  }}>
                    <VisualBody b={active} c={c} s={skin} density={ql.density} />
                  </div>
                )}
              </AbsoluteFill>
              {/* 闪白:砸落的那一下(精细档) */}
              {ql.trans === "slam" && fIn >= 0 && fIn < 3 && (
                <AbsoluteFill style={{ background: "#fff", opacity: 0.5 * (1 - fIn / 3), pointerEvents: "none" }} />
              )}
              {/* 冲击环 */}
              {ql.trans === "slam" && (active.kind === "hook" || active.kind === "cta") && fIn >= 0 && fIn < 26 && (
                <svg width="100%" height="100%" style={{ position: "absolute", pointerEvents: "none" }}>
                  <circle cx="50%" cy="46%" r={lerp(70, 760, easeOut(clamp01(fIn / 16)))}
                    fill="none" stroke={skin.accent} strokeWidth={lerp(10, 2, clamp01(fIn / 20))}
                    opacity={clamp01(1 - Math.max(0, fIn - 16) / 10)} />
                </svg>
              )}
            </>
          );
        })()}
      </AbsoluteFill>

      {/* 胶片颗粒:8 帧循环,整帧逐帧变化。
          这不是装饰 —— 没有它,安静的读字段会被死场检测判成「画面不动」,
          而观众也会觉得画面是张静止的 PPT。 */}
      <AbsoluteFill style={{
        backgroundImage: `url(${staticFile(`ai-bubble/grain/${Math.floor(t * 12) % 8}.png`)})`,
        backgroundSize: "cover",
        // 华尔街的织物底自带斜纹/颗粒/色光三路持续变化,再叠屏幕颗粒会过曝成光斑
        opacity: skin.id === "mg-wallstreet" ? 0.14
          : DARK_STYLES.has(skin.id) ? 0.5 : 0.38,
        mixBlendMode: DARK_STYLES.has(skin.id) ? "screen" : "multiply",
        pointerEvents: "none",
      }} />

      {/* 缓慢扫过的柔光带:给整帧一点持续的明暗流动,避免安静的读字段被判成死场 */}
      <div style={{
        position: "absolute", top: "-40%", height: "180%", width: "38%",
        left: `${((t * 0.11) % 1) * 160 - 45}%`,
        background: skin.id === "mg-wallstreet"
          ? "linear-gradient(90deg,transparent,rgba(255,243,181,.045),transparent)"
          : DARK_STYLES.has(skin.id)
            ? "linear-gradient(90deg,transparent,rgba(255,255,255,.20),transparent)"
            : "linear-gradient(90deg,transparent,rgba(0,0,0,.10),transparent)",
        mixBlendMode: DARK_STYLES.has(skin.id) ? "screen" : "multiply",
        transform: "rotate(11deg)", pointerEvents: "none",
      }} />

      {/* 页眉 / 页脚:所有风格共用同一套信息位,但颜色走风格 */}
      {data.header && (
        <div style={{
          position: "absolute", left: wide ? 110 : 70, top: wide ? 34 : 74,
          fontFamily: MONO, fontSize: 24, letterSpacing: 5, color: skin.muted, opacity: 0.85, zIndex: 3,
        }}>{data.header}</div>
      )}

      {/* 字幕:风格自己的底板(精细档会强调关键词) */}
      {subText && (
        <div style={{
          position: "absolute", left: 0, right: 0, bottom: wide ? 56 : 210,
          display: "flex", justifyContent: "center", padding: "0 60px", zIndex: 4,
        }}>
          <div style={{ ...skin.sub(ctx(0, 0)), opacity: subAlpha, textAlign: "center" }}>
            {ql.polish
              ? subText.split("").map((ch, i) => (
                  <span key={i} style={kwMask[i] ? { color: skin.accent } : undefined}>{ch}</span>
                ))
              : subText}
          </div>
        </div>
      )}

      {/* 精修层:进度刻度 + 暗角(精细档) */}
      {ql.polish && (
        <>
          <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 4, background: "rgba(128,128,128,.18)", zIndex: 5 }}>
            <div style={{ width: `${pct * 100}%`, height: "100%", background: skin.accent }} />
          </div>
          {data.beats.map((b) => {
            const bp = beatAt(b.id)[0] / (data.total || 4);
            return (
              <div key={b.id} style={{
                position: "absolute", left: `${bp * 100}%`, top: 0, width: 2, height: 12,
                background: skin.accent, opacity: 0.7, zIndex: 6,
              }} />
            );
          })}
          <AbsoluteFill style={{
            background: "radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 52%, rgba(0,0,0,.30) 100%)",
            pointerEvents: "none",
          }} />
        </>
      )}

      <div style={{
        position: "absolute", left: 60, bottom: 46, fontFamily: MONO, fontSize: 20,
        color: skin.muted, opacity: 0.55, letterSpacing: 3, zIndex: 4,
      }}>{data.footer?.label || ""}</div>
      <div style={{
        position: "absolute", right: 60, bottom: 46, fontFamily: MONO, fontSize: 20,
        color: skin.muted, opacity: 0.55, zIndex: 4,
      }}>{Math.round(clamp01(t / (data.total || 4)) * 100)}%</div>

      {audioSrc ? <Audio src={resolveAsset(audioSrc)} /> : null}
    </AbsoluteFill>
  );
};
