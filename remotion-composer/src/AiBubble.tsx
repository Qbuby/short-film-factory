import React from "react";
import {
  AbsoluteFill,
  Audio,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { resolveAsset } from "./lib/resolveAsset";

/**
 * 粗描边贴纸人科普 MG（回形针 / 林超风格）· Bold-outline Sticker Explainer
 * 题材：AI 泡沫破裂（量子位《AI泡裂纳指崩了》）
 *
 * 招牌特征（对标 mg-styles-15 / 19-paperclip）：
 *   - 贴纸化：白粗描边 + 软阴影，消除素材来源差异
 *   - 蓝灰/米白冷静底色 + 4~5 色克制配色
 *   - 大画布 + 摄像机平移缩放（长 ease），一镜串多个信息点
 *   - 精确图表：柱状图按比例、数字滚动计数
 *
 * 镜头动效复用 video-shotcraft 的配方卡：
 *   camera/crash-zoom-punch     急推 6f（1→2.4）、撞停震屏 14px·e^(-t/1.8)
 *   effects/slam-entrance-moves  砸落 scale 2.6→0.965→spring 1、冲击环 120→1500/16f、震屏 18px 指数衰减
 *   effects/impact-feedback      落点白闪 2f
 */

const W = 1080;
const H = 1920;
const DUR = 42.56;
const FPS = 30;

const C = {
  canvas: "#E9EEF2",
  paper: "#F8F3E9",
  slate: "#33475B",
  deep: "#1B2430",
  accent: "#FF5A36",
  gold: "#E8A33D",
  line: "#C8D3DD",
  white: "#FFFFFF",
};
const SANS = `"Noto Sans SC","Microsoft YaHei","PingFang SC","SimHei",sans-serif`;
const MONO = `"Consolas","Courier New",monospace`;

// 节拍表由 tools/motion_design/sync_remotion_timing.py 从 timing.json 生成,
// 和口播是同一份实测数据 —— 手抄七个秒数正是上次「人声比字幕晚一句」的来源。
import { AI_BUBBLE_BEATS, AI_BUBBLE_SPLIT } from "./aiBubbleTiming";

const BEATS = AI_BUBBLE_BEATS;
type BeatId = keyof typeof BEATS;

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
const lerp = (a: number, b: number, x: number) => a + (b - a) * x;
const easeOutCubic = (x: number) => 1 - Math.pow(1 - x, 3);
const easeInCubic = (x: number) => x * x * x;
const easeInOutCubic = (x: number) =>
  x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;

/** 拍内进度 0..1 */
const prog = (t: number, id: BeatId) => {
  const [s, e] = BEATS[id];
  return clamp01((t - s) / (e - s));
};
const active = (t: number, id: BeatId) => t >= BEATS[id][0] && t < BEATS[id][1];

/**
 * score-slam 砸落（shotcraft effects/slam-entrance-moves B 式）
 * 0–9f 悬在镜头前（scale 2.6、虚化）→ 9–15f ease-in 砸到 0.965 → spring 回 1
 * ease-in 才是「砸」，ease-out 是「放下」。
 */
function slam(frame: number, startFrame: number, fps: number, from = 2.75, hover = 2.6) {
  const f = frame - startFrame;
  if (f < 0) return { scale: hover, blur: 12, opacity: 0, hit: 0 };
  const pre = clamp01(f / 9);
  if (f < 9) {
    return { scale: lerp(from, hover, pre), blur: 12, opacity: clamp01(f / 2) * 0.9, hit: 0 };
  }
  const land = clamp01((f - 9) / 6);
  if (f < 15) {
    return {
      scale: lerp(hover, 0.965, easeInCubic(land)),
      blur: lerp(10, 0, easeInCubic(land)),
      opacity: 1,
      hit: 0,
    };
  }
  const back = spring({ frame: f - 15, fps, config: { damping: 14, mass: 0.6 } });
  return { scale: lerp(0.965, 1, back), blur: 0, opacity: 1, hit: 1 };
}

/** 撞停震屏：18px 指数衰减，偏竖向 */
function shake(frame: number, startFrame: number, amp = 18, tau = 4.5) {
  const f = frame - startFrame;
  if (f < 0 || f > 30) return { x: 0, y: 0 };
  const env = Math.exp(-f / tau) * amp;
  return { x: Math.sin(f * 2.3) * env * 0.35, y: Math.cos(f * 3.1) * env };
}

/** 冲击环：直径 120 → 1500，16f，「扩散」用 out-cubic、「消散」用线性 */
const impactRing = (frame: number, startFrame: number) => {
  const f = frame - startFrame;
  const life = 16;
  if (f < 0 || f > life + 10) return null;
  const spread = clamp01(f / life);
  const fade = clamp01(1 - Math.max(0, f - life) / 10);
  return { r: lerp(60, 750, easeOutCubic(spread)), alpha: fade * (f < life ? 1 : 0.5) };
};

/** 落点白闪 2f */
const flash = (frame: number, startFrame: number, dur = 2) => {
  const f = frame - startFrame;
  if (f < 0 || f >= dur) return 0;
  return 1 - f / dur;
};

/** 每拍的摄像机推移：paperclip 的"大画布 + 长 ease 运镜"。
    没有它，画面就是钉死在屏幕上的 PPT；有了它，网格随镜头缩放，
    才有纵深和视差。 */
const CAM: Record<BeatId, { z0: number; z1: number; x0: number; x1: number; y0: number; y1: number }> = {
  hook:      { z0: 1.0,  z1: 1.04, x0: 0,   x1: -10, y0: 0,   y1: -16 },
  openai:    { z0: 1.035, z1: 1.0, x0: -14, x1: 6,   y0: 6,   y1: -4 },
  anthropic: { z0: 1.0,  z1: 1.045, x0: 10, x1: -8,  y0: -6,  y1: 10 },
  money:     { z0: 1.0,  z1: 1.055, x0: 0,  x1: 0,   y0: 14,  y1: -20 },
  crash:     { z0: 1.045, z1: 1.0, x0: -12, x1: 8,   y0: 10,  y1: -6 },
  echo:      { z0: 1.0,  z1: 1.04, x0: 10,  x1: -10, y0: 0,   y1: -10 },
  end:       { z0: 1.02, z1: 1.0,  x0: 0,   x1: 0,   y0: -8,  y1: 6 },
};
const Camera: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = f / fps;
  const id = (Object.keys(BEATS) as BeatId[]).find((k) => active(t, k)) ?? "hook";
  const c = CAM[id];
  const p = easeInOutCubic(prog(t, id));   // 长 ease，贯穿整拍
  const z = lerp(c.z0, c.z1, p);
  const x = lerp(c.x0, c.x1, p);
  const y = lerp(c.y0, c.y1, p);
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `translate(${x}px, ${y}px) scale(${z})`, transformOrigin: "50% 46%" }}>
        {children}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/* ── 贴纸：白粗描边 + 软阴影 ── */
const Sticker: React.FC<{
  x: number;
  y: number;
  rotate?: number;
  bg?: string;
  pad?: number;
  outline?: number;
  radius?: number;
  shadow?: boolean;
  style?: React.CSSProperties;
  children: React.ReactNode;
}> = ({ x, y, rotate = 0, bg = C.paper, pad = 26, outline = 10, radius = 14, shadow = true, style, children }) => (
  <div
    style={{
      position: "absolute",
      left: x,
      top: y,
      background: bg,
      // 白描边压在米白底上等于没有。paperclip 的做法是白边 + 外面一圈
      // 极细墨线：白边才读得出来，卡片的"剪下来"质感才成立。
      border: `${outline}px solid ${C.white}`,
      outline: `2px solid rgba(51,71,91,0.55)`,
      outlineOffset: `${outline}px`,
      borderRadius: radius,
      boxShadow: shadow ? "0 10px 22px rgba(27,36,48,0.16)" : "none",
      padding: pad,
      transform: `rotate(${rotate}deg)`,
      ...style,
    }}
  >
    {children}
  </div>
);

/** 图章：粗描边 + 倾斜 + 一点点墨色不匀（radial 遮罩近似） */
const Stamp: React.FC<{ x: number; y: number; text: string; rotate?: number; scale?: number; color?: string }> = ({
  x,
  y,
  text,
  rotate = -8,
  scale = 1,
  color = C.accent,
}) => (
  <div
    style={{
      position: "absolute",
      left: x,
      top: y,
      transform: `rotate(${rotate}deg) scale(${scale})`,
      border: `7px solid ${color}`,
      borderRadius: 10,
      padding: "12px 26px",
      color,
      fontFamily: SANS,
      fontWeight: 900,
      fontSize: 62,
      letterSpacing: 6,
      whiteSpace: "nowrap",
      background: "rgba(255,255,255,0.72)",
      boxShadow: `0 10px 24px rgba(255,90,54,0.22)`,
      opacity: 0.94,
    }}
  >
    {text}
  </div>
);

/* ══════════ 1 HOOK：泡沫破了 ══════════ */
const BeatHook: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = prog(f / fps, "hook");
  const s = slam(f, 0, fps);
  const ring = impactRing(f, 15);
  const fl = flash(f, 15, 3);
  const sh = shake(f, 15, 14);
  // 第二句「硅谷最亮的那两颗星」起音时，两块铭牌砸进来。
  // 时刻由 sync_remotion_timing.py 从字幕数据算出，改稿自动跟着走。
  const f1 = AI_BUBBLE_SPLIT * fps;
  const s2 = slam(f, f1, fps);
  const sh2 = shake(f, f1, 11);
  const ring2 = impactRing(f, f1);
  return (
    <AbsoluteFill style={{ transform: `translate(${sh.x + sh2.x}px, ${sh.y + sh2.y}px)` }}>
      {/* 破掉的泡泡：一条圆弧 + 碎屑 */}
      <svg width={W} height={520} style={{ position: "absolute", top: 120, left: 0 }}>
        <g transform="translate(540,240)">
          <circle r={190} fill="none" stroke={C.line} strokeWidth={8} strokeDasharray="640 560" strokeDashoffset={40} />
          {[...Array(7)].map((_, i) => {
            const a = -0.9 + i * 0.42;
            const d = easeOutCubic(clamp01((p - 0.05) / 0.5)) * (120 + i * 26);
            return (
              <rect
                key={i}
                x={Math.cos(a) * (200 + d)}
                y={Math.sin(a) * (200 + d)}
                width={22}
                height={16}
                fill={C.accent}
                opacity={0.85 - i * 0.08}
                transform={`rotate(${i * 37})`}
              />
            );
          })}
        </g>
      </svg>

      <div style={{ position: "absolute", left: 0, right: 0, top: 470, textAlign: "center" }}>
        <div
          style={{
            fontFamily: SANS,
            fontWeight: 900,
            fontSize: 148,
            lineHeight: 1.06,
            color: C.slate,
            letterSpacing: 4,
            transform: `scale(${s.scale})`,
            filter: `blur(${s.blur}px)`,
            opacity: s.opacity,
          }}
        >
          AI 泡沫
          <br />
          <span style={{ color: C.accent }}>破了</span>
        </div>
      </div>

      {ring && (
        <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
          <circle cx={540} cy={640} r={ring.r} fill="none" stroke={C.accent} strokeWidth={10} opacity={ring.alpha * 0.65} />
        </svg>
      )}

      <Sticker x={70} y={900} rotate={-2} pad={26} style={{ width: 940, boxSizing: "border-box" }}>
        <div style={{ fontFamily: SANS, fontWeight: 800, fontSize: 36, color: C.slate, letterSpacing: 2 }}>
          华尔街开始重新定价风险
        </div>
        <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 54, color: C.accent, marginTop: 6 }}>
          钱，不往 AI 里去了
        </div>
      </Sticker>

      <div style={{ position: "absolute", left: 0, right: 0, top: 1178, textAlign: "center", fontFamily: MONO, fontSize: 34, color: C.slate, letterSpacing: 6, opacity: 0.7 }}>
        2026.10.30 · 华尔街
      </div>

      {/* 底排元素一律收在 y≈1425 以内：字幕条压在 1510–1620，
          再往下就是平台自己的 UI 区，压上去等于白做。 */}
      <div style={{ position: "absolute", left: 70, right: 70, top: 1240, display: "flex", gap: 24, transform: `scale(${s2.scale})`, filter: `blur(${s2.blur}px)`, opacity: s2.opacity }}>
        {[
          { n: "OpenAI", s: "融不到钱", c: C.slate },
          { n: "Anthropic", s: "评级被打", c: C.accent },
        ].map((it, i) => (
          <div
            key={i}
            style={{
              flex: 1,
              background: C.paper,
              border: `10px solid ${C.white}`,
              borderRadius: 16,
              boxShadow: "0 16px 34px rgba(27,36,48,0.18)",
              padding: "22px 18px",
              textAlign: "center",
              transform: `rotate(${i === 0 ? -2 : 2}deg)`,
              opacity: s.opacity,
            }}
          >
            <div style={{ fontFamily: MONO, fontSize: 40, fontWeight: 900, color: it.c, letterSpacing: 1 }}>{it.n}</div>
            <div style={{ fontFamily: SANS, fontSize: 26, fontWeight: 800, color: C.slate, marginTop: 8 }}>{it.s}</div>
          </div>
        ))}
      </div>

      {/* 第二次落点的冲击环，圆心压在铭牌中间 */}
      {ring2 && (
        <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
          <circle cx={540} cy={1330} r={ring2.r} fill="none" stroke={C.slate} strokeWidth={8} opacity={ring2.alpha * 0.42} />
        </svg>
      )}

      {fl > 0 && <AbsoluteFill style={{ background: C.white, opacity: fl * 0.75 }} />}
    </AbsoluteFill>
  );
};

/* ══════════ 2 OpenAI：一半都不到 ══════════ */
const BeatOpenAI: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = prog(f / fps, "openai");
  const f0 = BEATS.openai[0] * fps;
  const grow = easeOutCubic(clamp01((f - f0 - 6) / 16));
  const num = Math.round(lerp(0, 110, easeOutCubic(clamp01((f - f0 - 10) / 20))));
  const st = slam(f, f0 + 40, fps, 1.85, 1.7);
  const sh = shake(f, f0 + 55, 16);
  const fl = flash(f, f0 + 55, 2);
  return (
    <AbsoluteFill style={{ transform: `translate(${sh.x}px, ${sh.y}px)` }}>
      <div style={{ position: "absolute", left: 70, top: 150, fontFamily: SANS, fontWeight: 900, fontSize: 76, color: C.slate, letterSpacing: 3 }}>
        OpenAI：想融 300 亿
      </div>

      {/* 双柱：目标（空心）vs 实到（实心） */}
      <svg width={W} height={720} style={{ position: "absolute", top: 300, left: 0 }}>
        <line x1={110} y1={620} x2={W - 110} y2={620} stroke={C.slate} strokeWidth={5} />
        {/* 目标 300 亿 */}
        <rect x={170} y={620 - 520 * grow} width={210} height={520 * grow} fill="none" stroke={C.slate} strokeWidth={7} strokeDasharray="14 10" />
        <text x={275} y={620 - 520 * grow - 24} textAnchor="middle" fontFamily={SANS} fontWeight={900} fontSize={56} fill={C.slate}>300 亿</text>
        <text x={275} y={668} textAnchor="middle" fontFamily={SANS} fontWeight={800} fontSize={30} fill={C.slate} opacity={0.8}>目标</text>
        {/* 实到 110 亿 */}
        <rect x={600} y={620 - (520 * 110) / 300 * grow} width={210} height={((520 * 110) / 300) * grow} fill={C.accent} />
        <text x={705} y={620 - (520 * 110) / 300 * grow - 24} textAnchor="middle" fontFamily={SANS} fontWeight={900} fontSize={56} fill={C.accent}>{num} 亿</text>
        <text x={705} y={668} textAnchor="middle" fontFamily={SANS} fontWeight={800} fontSize={30} fill={C.accent}>实到</text>
        {/* 缺口标注 */}
        <line x1={275} y1={620 - 520 * grow} x2={600} y2={620 - 520 * grow} stroke={C.slate} strokeWidth={3} strokeDasharray="8 8" opacity={grow} />
      </svg>

      <div style={{ position: "absolute", left: 74, top: 1030, transform: `scale(${st.scale})`, filter: `blur(${st.blur}px)`, opacity: st.opacity }}>
        <Stamp x={0} y={0} text="少 190 亿" rotate={-9} scale={1.0} />
      </div>

      <Sticker x={70} y={1250} rotate={1.4} pad={24} bg={C.paper} style={{ width: 940, boxSizing: "border-box" }}>
        <div style={{ fontFamily: SANS, fontWeight: 800, fontSize: 34, color: C.slate }}>估值缩水到</div>
        <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 72, color: C.deep, marginTop: 4 }}>1.25 万亿</div>
      </Sticker>

      {fl > 0 && <AbsoluteFill style={{ background: C.white, opacity: fl * 0.6 }} />}
    </AbsoluteFill>
  );
};

/* ══════════ 3 Anthropic：高级垃圾级 ══════════ */
const BeatAnthropic: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = prog(f / fps, "anthropic");
  const f0 = BEATS.anthropic[0] * fps;
  const st = slam(f, f0 + 96, fps, 1.85, 1.7);
  const sh = shake(f, f0 + 112, 18);
  const fl = flash(f, f0 + 112, 2);
  const ring = impactRing(f, f0 + 112);
  // 评级卡：0.35 之后从「投资级」翻成「垃圾级」
  const flip = easeInOutCubic(clamp01((p - 0.3) / 0.16));
  return (
    <AbsoluteFill style={{ transform: `translate(${sh.x}px, ${sh.y}px)` }}>
      <div style={{ position: "absolute", left: 70, top: 150, fontFamily: SANS, fontWeight: 900, fontSize: 72, color: C.slate, letterSpacing: 2 }}>
        Anthropic：要上市
      </div>

      <Sticker x={70} y={260} rotate={-1.6} pad={26}>
        <div style={{ fontFamily: SANS, fontWeight: 800, fontSize: 32, color: C.slate }}>计划烧到 2045 年</div>
        <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 96, color: C.deep, letterSpacing: -2, marginTop: 2 }}>
          8000 亿
        </div>
      </Sticker>

      {/* 评级卡 */}
      <div style={{ position: "absolute", left: 70, top: 560, width: 940, height: 300, perspective: 1200 }}>
        <div
          style={{
            width: "100%",
            height: "100%",
            transformStyle: "preserve-3d",
            transform: `rotateY(${flip * 180}deg)`,
            position: "relative",
          }}
        >
          <div
            style={{
              position: "absolute",
              inset: 0,
              backfaceVisibility: "hidden",
              background: C.paper,
              border: `10px solid ${C.white}`,
              borderRadius: 16,
              boxShadow: "0 16px 34px rgba(27,36,48,0.18)",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <div style={{ fontFamily: SANS, fontWeight: 800, fontSize: 34, color: C.slate }}>黑石原本承诺</div>
            <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 96, color: C.slate, letterSpacing: 4 }}>投资级</div>
          </div>
          <div
            style={{
              position: "absolute",
              inset: 0,
              backfaceVisibility: "hidden",
              transform: "rotateY(180deg)",
              background: "#FFF1EE",
              border: `10px solid ${C.white}`,
              borderRadius: 16,
              boxShadow: "0 16px 34px rgba(255,90,54,0.22)",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <div style={{ fontFamily: SANS, fontWeight: 800, fontSize: 34, color: C.accent }}>现在改口</div>
            <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 108, color: C.accent, letterSpacing: 2 }}>
              高级垃圾级
            </div>
          </div>
        </div>
      </div>

      {ring && (
        <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
          <circle cx={540} cy={710} r={ring.r} fill="none" stroke={C.accent} strokeWidth={9} opacity={ring.alpha * 0.55} />
        </svg>
      )}

      <div style={{ position: "absolute", left: 70, top: 940, transform: `scale(${st.scale})`, filter: `blur(${st.blur}px)`, opacity: st.opacity }}>
        <Stamp x={0} y={0} text="垃圾级" rotate={7} scale={1.2} />
      </div>

      <Sticker x={70} y={1250} rotate={-0.8} pad={24} style={{ width: 940, boxSizing: "border-box" }}>
        <div style={{ fontFamily: SANS, fontWeight: 800, fontSize: 32, color: C.slate }}>
          养老基金、保险基金按规定不能碰
        </div>
        <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 44, color: C.accent, marginTop: 8 }}>
          利息 3% → 6%，8000 亿的账直接崩
        </div>
      </Sticker>

      {fl > 0 && <AbsoluteFill style={{ background: C.white, opacity: fl * 0.7 }} />}
    </AbsoluteFill>
  );
};

/* ══════════ 4 HERO：金主也没钱了 ══════════ */
const BeatMoney: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = prog(f / fps, "money");
  const f0 = BEATS.money[0] * fps;
  // 现金流曲线：从 +148 穿过 0 掉到 -424
  const draw = easeInOutCubic(clamp01(p / 0.42));
  const zx = lerp(1, 1.55, easeInCubic(clamp01((p - 0.5) / 0.16))); // 急推
  const sh = shake(f, f0 + 40, 14);
  const val = Math.round(lerp(148, -424, easeOutCubic(clamp01((p - 0.18) / 0.4))));
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ transform: `translate(${sh.x}px,${sh.y}px)` }}>
        <div style={{ position: "absolute", left: 70, top: 150, fontFamily: SANS, fontWeight: 900, fontSize: 70, color: C.slate, letterSpacing: 2 }}>
          地主家也没余粮了
        </div>

        {/* 现金流曲线 */}
        <svg width={W} height={560} style={{ position: "absolute", top: 290, left: 0 }}>
          <line x1={70} y1={300} x2={W - 70} y2={300} stroke={C.slate} strokeWidth={4} strokeDasharray="10 8" />
          <text x={80} y={286} fontFamily={MONO} fontSize={26} fill={C.slate} opacity={0.75}>0</text>
          <polyline
            points={`110,190 280,210 430,250 560,300 700,430 860,520`}
            fill="none"
            stroke={C.accent}
            strokeWidth={10}
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeDasharray={1400}
            strokeDashoffset={1400 * (1 - draw)}
          />
          <circle cx={110} cy={190} r={11} fill={C.slate} opacity={draw > 0.05 ? 1 : 0} />
          <text x={118} y={168} fontFamily={SANS} fontWeight={900} fontSize={30} fill={C.slate} opacity={draw > 0.05 ? 1 : 0}>+148 亿</text>
          <circle cx={860} cy={520} r={13} fill={C.accent} opacity={draw > 0.95 ? 1 : 0} />
          {/* 坐标系：没有轴的折线在"精确图表"风格里读作涂鸦 */}
          <text x={96} y={196} fontFamily={MONO} fontSize={22} fill={C.slate} opacity={0.65}>+148</text>
          <line x1={90} y1={300} x2={90} y2={196} stroke={C.slate} strokeWidth={2} opacity={0.4} />
          <text x={838} y={556} fontFamily={MONO} fontSize={22} fill={C.accent} opacity={0.85}>−424</text>
          <line x1={880} y1={300} x2={880} y2={520} stroke={C.accent} strokeWidth={2} strokeDasharray="6 6" opacity={0.45} />
          <text x={700} y={556} fontFamily={MONO} fontSize={20} fill={C.slate} opacity={0.55}>12 个月</text>
        </svg>

        {/* 急推的数字 */}
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: 830,
            textAlign: "center",
            transform: `scale(${zx})`,
            transformOrigin: "540px 60px",
          }}
        >
          <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 150, color: C.accent, letterSpacing: -4, lineHeight: 1 }}>
            {val} 亿
          </div>
          <div style={{ fontFamily: SANS, fontWeight: 800, fontSize: 38, color: C.slate, marginTop: 10, letterSpacing: 2 }}>
            亚马逊自由现金流（12 个月滚动）
          </div>
        </div>
      </AbsoluteFill>

      <Sticker x={70} y={1250} rotate={1.2} pad={24} style={{ width: 940, boxSizing: "border-box" }}>
        <div style={{ fontFamily: SANS, fontWeight: 800, fontSize: 30, color: C.slate }}>
          一年前还是正的 148 亿 · 今年资本支出约 2200 亿
        </div>
      </Sticker>
    </AbsoluteFill>
  );
};

/* ══════════ 5 崩盘 ══════════ */
const BeatCrash: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = prog(f / fps, "crash");
  const f0 = BEATS.crash[0] * fps;
  const crash = easeInCubic(clamp01((p - 0.25) / 0.22));
  const sh = shake(f, f0 + 22, 20);
  const fl = flash(f, f0 + 22, 3);
  const st = slam(f, f0 + 55, fps, 1.85, 1.7);
  return (
    <AbsoluteFill style={{ transform: `translate(${sh.x}px, ${sh.y}px)` }}>
      <div style={{ position: "absolute", left: 70, top: 150, fontFamily: SANS, fontWeight: 900, fontSize: 76, color: C.slate, letterSpacing: 2 }}>
        纳斯达克，崩了
      </div>

      <svg width={W} height={620} style={{ position: "absolute", top: 280, left: 0 }}>
        <polyline points="90,300 240,270 380,230 500,250 600,210" fill="none" stroke={C.slate} strokeWidth={9} strokeLinejoin="round" strokeLinecap="round" />
        <polyline
          points={`600,210 ${600 + 80 * crash},${210 + 200 * crash} ${600 + 140 * crash},${210 + 330 * crash} ${600 + 200 * crash},${210 + 400 * crash}`}
          fill="none" stroke={C.accent} strokeWidth={11} strokeLinejoin="round" strokeLinecap="round"
        />
        <line x1={600} y1={90} x2={600} y2={530} stroke={C.accent} strokeWidth={3} strokeDasharray="10 8" opacity={0.6} />
        {/* 坐标轴：横轴时间、纵轴幅度，刻度给到 −3.5% */}
        <line x1={90} y1={520} x2={W - 90} y2={520} stroke={C.slate} strokeWidth={3} opacity={0.45} />
        <line x1={90} y1={520} x2={90} y2={170} stroke={C.slate} strokeWidth={3} opacity={0.45} />
        <text x={100} y={200} fontFamily={MONO} fontSize={22} fill={C.slate} opacity={0.6}>0%</text>
        <text x={100} y={470} fontFamily={MONO} fontSize={22} fill={C.accent} opacity={0.8}>−3.5%</text>
        <text x={740} y={556} fontFamily={MONO} fontSize={20} fill={C.slate} opacity={0.55}>10 月</text>
        <text x={620} y={110} fontFamily={MONO} fontSize={30} fill={C.accent} fontWeight={900}>10/30</text>
      </svg>

      <div style={{ position: "absolute", left: 0, right: 0, top: 900, textAlign: "center", transform: `scale(${st.scale})`, filter: `blur(${st.blur}px)`, opacity: st.opacity }}>
        <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 128, color: C.accent, letterSpacing: -3, lineHeight: 1 }}>
          −3.46%
        </div>
        <div style={{ fontFamily: SANS, fontWeight: 800, fontSize: 36, color: C.slate, marginTop: 6 }}>单日 · 数月来最大跌幅</div>
      </div>

      <Sticker x={70} y={1250} rotate={-1.2} pad={24} style={{ width: 940, boxSizing: "border-box" }}>
        <div style={{ fontFamily: SANS, fontWeight: 800, fontSize: 32, color: C.slate }}>
          10 月整月 −5.3%，2025 年 3 月以来最差
        </div>
        <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 40, color: C.accent, marginTop: 6 }}>
          英伟达、AMD，集体跳水
        </div>
      </Sticker>

      {fl > 0 && <AbsoluteFill style={{ background: C.white, opacity: fl * 0.55 }} />}
    </AbsoluteFill>
  );
};

/* ══════════ 6 26 年前 ══════════ */
const BeatEcho: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = prog(f / fps, "echo");
  const a = easeOutCubic(clamp01(p / 0.3));
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 70, top: 150, fontFamily: SANS, fontWeight: 900, fontSize: 72, color: C.slate, letterSpacing: 2, opacity: a }}>
        历史，就是个循环
      </div>

      <div style={{ position: "absolute", left: 70, right: 70, top: 330, display: "flex", gap: 26, opacity: a }}>
        {[
          { k: "2000", v: "互联网泡沫", s: "纳斯达克两年跌 78%" },
          { k: "2026", v: "AI 泡沫", s: "同一天，同一个姿势" },
        ].map((it, i) => (
          <div
            key={i}
            style={{
              flex: 1,
              background: i === 1 ? "#FFF1EE" : C.paper,
              border: `10px solid ${C.white}`,
              borderRadius: 18,
              boxShadow: "0 16px 34px rgba(27,36,48,0.18)",
              padding: "28px 22px",
              textAlign: "center",
              transform: `rotate(${i === 0 ? -2.4 : 2.4}deg)`,
            }}
          >
            <div style={{ fontFamily: MONO, fontSize: 40, fontWeight: 900, color: i === 1 ? C.accent : C.slate }}>{it.k}</div>
            <div style={{ fontFamily: SANS, fontSize: 44, fontWeight: 900, color: C.deep, marginTop: 8 }}>{it.v}</div>
            <div style={{ fontFamily: SANS, fontSize: 24, fontWeight: 700, color: C.slate, marginTop: 12, lineHeight: 1.4 }}>{it.s}</div>
          </div>
        ))}
      </div>

      <div style={{ position: "absolute", left: 0, right: 0, top: 760, textAlign: "center" }}>
        <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 190, color: C.accent, letterSpacing: -6, lineHeight: 1, opacity: a }}>
          26
        </div>
        <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 52, color: C.slate, letterSpacing: 8 }}>年前</div>
      </div>

      <Sticker x={70} y={1250} rotate={-0.8} pad={24} style={{ width: 940, boxSizing: "border-box" }}>
        <div style={{ fontFamily: SANS, fontWeight: 800, fontSize: 34, color: C.slate }}>
          一样的故事，一样的钱荒
        </div>
      </Sticker>
    </AbsoluteFill>
  );
};

/* ══════════ 7 收尾 ══════════ */
const BeatEnd: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = prog(f / fps, "end");
  const s1 = easeOutCubic(clamp01(p / 0.22));
  const s2 = easeOutCubic(clamp01((p - 0.26) / 0.24));
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 80, right: 80, top: 280 }}>
        <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 96, lineHeight: 1.22, color: C.slate, letterSpacing: 2, opacity: s1 }}>
          打着 AI 的名头
          <br />
          就能像大爷一样
          <br />
          要钱的时代
        </div>
        <div
          style={{
            fontFamily: SANS,
            fontWeight: 900,
            fontSize: 132,
            color: C.accent,
            letterSpacing: 8,
            marginTop: 18,
            opacity: s2,
            transform: `translateY(${(1 - s2) * 30}px)`,
          }}
        >
          结束了
        </div>
      </div>

      <Sticker x={80} y={1150} rotate={-1.6} pad={22}>
        <div style={{ fontFamily: MONO, fontSize: 26, color: C.slate, letterSpacing: 2 }}>
          来源 · 量子位《AI泡裂纳指崩了》
        </div>
        <div style={{ fontFamily: MONO, fontSize: 22, color: C.slate, opacity: 0.75, marginTop: 6 }}>
          OpenAI 300 → 110 亿 · Anthropic「高级垃圾级」· 纳指 −3.46%
        </div>
      </Sticker>

      <div style={{ position: "absolute", left: 0, right: 0, top: 940, textAlign: "center", fontFamily: SANS, fontWeight: 900, fontSize: 54, color: C.accent, opacity: easeOutCubic(clamp01((p - 0.6) / 0.25)), letterSpacing: 6 }}>
        钱，是信心借来的
      </div>
    </AbsoluteFill>
  );
};

/* ══════════ 主组件 ══════════ */
export type AiBubbleProps = {
  subs: [number, number, string][];
  audioSrc?: string;
};

export const AiBubble: React.FC<AiBubbleProps> = ({ subs, audioSrc }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  let subText = "";
  let subAlpha = 0;
  for (const [a, b, txt] of subs) {
    if (t >= a && t < b) {
      subText = txt;
      subAlpha = Math.min(clamp01((t - a) / 0.1), clamp01((b - t) / 0.1));
      break;
    }
  }

  return (
    <AbsoluteFill style={{ background: C.canvas, overflow: "hidden" }}>
      {/* 网格与内容一起进摄像机层 —— 镜头推移时网格跟着缩放，
          才有纵深；钉在屏幕上就只是 PPT 背景。 */}
      <Camera>
        <AbsoluteFill
          style={{
            backgroundImage: `linear-gradient(${C.line} 1px, transparent 1px), linear-gradient(90deg, ${C.line} 1px, transparent 1px)`,
            backgroundSize: "72px 72px",
            opacity: 0.5,
          }}
        />
        <AbsoluteFill style={{ background: "radial-gradient(circle at 50% 38%, rgba(255,255,255,0.85), rgba(233,238,242,0) 62%)" }} />

        {active(t, "hook") && <BeatHook />}
        {active(t, "openai") && <BeatOpenAI />}
        {active(t, "anthropic") && <BeatAnthropic />}
        {active(t, "money") && <BeatMoney />}
        {active(t, "crash") && <BeatCrash />}
        {active(t, "echo") && <BeatEcho />}
        {active(t, "end") && <BeatEnd />}
      </Camera>

      {/* 纸纹：8 张低频噪声轮流铺，按 12fps 定格切换。
          贴纸风落定后画面本来就不动，这层同时解决"纸感"和"死场"。 */}
      <AbsoluteFill
        style={{
          backgroundImage: `url(${staticFile(`ai-bubble/grain/${Math.floor(t * 12) % 8}.png`)})`,
          backgroundSize: "1080px 1920px",
          opacity: 0.42,
        }}
      />

      {/* 字幕：贴纸式小条，不用播放器样式的黑圆角 */}
      {subText ? (
        <div
          style={{
            position: "absolute",
            left: 60,
            right: 60,
            bottom: 300,
            display: "flex",
            justifyContent: "center",
          }}
        >
          <div
            style={{
              background: C.white,
              border: `6px solid ${C.slate}`,
              borderRadius: 10,
              padding: "12px 24px",
              fontFamily: SANS,
              fontWeight: 800,
              fontSize: 42,
              color: C.deep,
              opacity: subAlpha,
              transform: `rotate(-0.6deg)`,
              textAlign: "center",
              lineHeight: 1.35,
            }}
          >
            {subText}
          </div>
        </div>
      ) : null}

      {/* 页脚：一条细分隔线 + 刊头，杂志版式的收口，也填住底部 */}
      <div style={{ position: "absolute", left: 60, right: 60, bottom: 150, height: 2, background: C.slate, opacity: 0.35 }} />
      <div style={{ position: "absolute", left: 60, bottom: 106, fontFamily: MONO, fontSize: 22, color: C.slate, letterSpacing: 4, opacity: 0.55 }}>
        AI BUBBLE · 2026.10
      </div>
      <div style={{ position: "absolute", right: 60, bottom: 106, fontFamily: MONO, fontSize: 22, color: C.slate, letterSpacing: 4, opacity: 0.55 }}>
        {String(Math.floor(t / DUR * 100)).padStart(3, " ")}%
      </div>

      {audioSrc ? <Audio src={resolveAsset(audioSrc)} /> : null}
    </AbsoluteFill>
  );
};
