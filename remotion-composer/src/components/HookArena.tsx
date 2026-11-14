import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";

/**
 * 2.5D 俯视闯关战场(HookArena)。
 *
 * 和侧向轨道(HookJourney)的区别:
 *  - 地面是有纵深的平面(近大远小),机器人站在平面上,不是一个贴边的小人;
 *  - 敌人从**四个方向**涌进来(左/右/后方/正面),不只是从右边;
 *  - 敌人在两次出招之间也**源源不断**地刷,不是只在遭遇点出现;
 *  - 出招分两类:自身能力(拳/旋风/砸地/网/盾/磁)与**就地取材**(踢箱子/抡铁管/甩井盖)。
 *
 * 确定性:所有"随机"都用下标哈希,不用 Math.random —— Remotion 逐帧独立渲染,
 * 用真随机会导致每帧敌人位置抖动。
 */

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const easeOut = (t: number) => 1 - Math.pow(1 - t, 3);
const easeIn = (t: number) => t * t;

/** 下标哈希:同一个 i 永远得到同一个 0–1 值 */
const rand = (i: number, salt = 0) => {
  const v = Math.sin((i + 1) * 12.9898 + salt * 78.233) * 43758.5453;
  return v - Math.floor(v);
};

export type ArenaAbility =
  | "punch"
  | "spin"
  | "stomp"
  | "net"
  | "shield"
  | "magnet"
  | "kick_crate"
  | "swing_pipe"
  | "throw_cover";

export type ArenaEnemyKind = "spike" | "saw" | "drone" | "missile" | "crawler" | "bomber";

export interface ArenaWave {
  /** 占全片比例 0–1 */
  at: number;
  ability: ArenaAbility;
  /** 这一波的敌人数量 */
  count?: number;
  /** 优先从哪个方向来 */
  from?: "left" | "right" | "back" | "front" | "any";
}

export interface HookArenaProps {
  startX?: number;
  endX?: number;
  /** 地平线高度(画面比例) */
  horizonY?: number;
  /** 地面底边(画面比例) */
  bottomY?: number;
  /** 机器人宽度(画面宽度比例) */
  size?: number;
  accent?: string;
  waves?: ArenaWave[];
  /** 两次出招之间持续刷怪,间隔秒数 */
  trickleSeconds?: number;
  showGrid?: boolean;
}

const DEFAULT_WAVES: ArenaWave[] = [
  { at: 0.08, ability: "punch", count: 4, from: "right" },
  { at: 0.17, ability: "kick_crate", count: 5, from: "left" },
  { at: 0.26, ability: "spin", count: 6, from: "any" },
  { at: 0.35, ability: "shield", count: 4, from: "back" },
  { at: 0.44, ability: "swing_pipe", count: 5, from: "right" },
  { at: 0.53, ability: "stomp", count: 6, from: "front" },
  { at: 0.62, ability: "net", count: 5, from: "any" },
  { at: 0.71, ability: "throw_cover", count: 6, from: "left" },
  { at: 0.80, ability: "magnet", count: 6, from: "any" },
  { at: 0.89, ability: "spin", count: 7, from: "any" },
  { at: 0.96, ability: "stomp", count: 6, from: "any" },
];

const ENEMY_KINDS: ArenaEnemyKind[] = ["spike", "saw", "drone", "missile", "crawler", "bomber"];

/* ────────────────────────── 敌人外形 ────────────────────────── */

const EnemyShape: React.FC<{ kind: ArenaEnemyKind; s: number; spin: number }> = ({ kind, s, spin }) => {
  if (kind === "drone") {
    return (
      <svg width={s} height={s} viewBox="0 0 100 100" style={{ transform: `rotate(${spin * 0.2}deg)` }}>
        <rect x="30" y="44" width="40" height="20" rx="8" fill="#334155" stroke="#64748B" strokeWidth="2" />
        <rect x="8" y="28" width="36" height="5" rx="2.5" fill="#475569" />
        <rect x="56" y="28" width="36" height="5" rx="2.5" fill="#475569" />
        <ellipse cx="20" cy="26" rx="14" ry="3.5" fill="none" stroke="#94A3B8" strokeWidth="2" opacity="0.8" />
        <ellipse cx="80" cy="26" rx="14" ry="3.5" fill="none" stroke="#94A3B8" strokeWidth="2" opacity="0.8" />
        <circle cx="50" cy="54" r="5.5" fill="#EF4444" />
      </svg>
    );
  }
  if (kind === "saw") {
    const teeth = Array.from({ length: 9 }, (_, i) => {
      const a = (i / 9) * Math.PI * 2;
      return (
        <path
          key={i}
          d={`M ${50 + Math.cos(a) * 28} ${50 + Math.sin(a) * 28} L ${50 + Math.cos(a + 0.14) * 45} ${50 + Math.sin(a + 0.14) * 45} L ${50 + Math.cos(a + 0.28) * 28} ${50 + Math.sin(a + 0.28) * 28} Z`}
          fill="#CBD5E1"
        />
      );
    });
    return (
      <svg width={s} height={s} viewBox="0 0 100 100" style={{ transform: `rotate(${spin}deg)` }}>
        {teeth}
        <circle cx="50" cy="50" r="28" fill="#94A3B8" />
        <circle cx="50" cy="50" r="9" fill="#475569" />
      </svg>
    );
  }
  if (kind === "missile") {
    return (
      <svg width={s} height={s} viewBox="0 0 100 100">
        <g transform="rotate(-10 50 50)">
          <rect x="22" y="43" width="48" height="14" rx="7" fill="#E2E8F0" />
          <path d="M70 43 L88 50 L70 57 Z" fill="#EF4444" />
          <path d="M26 43 L14 35 L26 50 Z" fill="#94A3B8" />
          <path d="M26 57 L14 65 L26 50 Z" fill="#94A3B8" />
        </g>
      </svg>
    );
  }
  if (kind === "crawler") {
    return (
      <svg width={s} height={s} viewBox="0 0 100 100">
        <ellipse cx="50" cy="62" rx="30" ry="18" fill="#22D3EE" opacity="0.9" />
        <ellipse cx="50" cy="50" rx="18" ry="14" fill="#67E8F9" />
        <circle cx="44" cy="48" r="3.2" fill="#0F172A" />
        <circle cx="56" cy="48" r="3.2" fill="#0F172A" />
        <path d="M28 66 L14 76 M40 70 L30 82 M60 70 L70 82 M72 66 L86 76" stroke="#0E7490" strokeWidth="4" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === "bomber") {
    return (
      <svg width={s} height={s} viewBox="0 0 100 100">
        <circle cx="50" cy="52" r="30" fill="#1F2937" stroke="#F59E0B" strokeWidth="3" />
        <path d="M50 22 L50 12" stroke="#F59E0B" strokeWidth="4" strokeLinecap="round" />
        <circle cx="50" cy="10" r="5" fill="#FBBF24" />
        <circle cx="40" cy="48" r="4" fill="#F59E0B" />
        <circle cx="60" cy="48" r="4" fill="#F59E0B" />
        <path d="M38 62 Q50 70 62 62" stroke="#F59E0B" strokeWidth="3" fill="none" />
      </svg>
    );
  }
  const spikes = Array.from({ length: 8 }, (_, i) => {
    const a = (i / 8) * Math.PI * 2;
    return (
      <path
        key={i}
        d={`M ${50 + Math.cos(a) * 15} ${50 + Math.sin(a) * 15} L ${50 + Math.cos(a + 0.2) * 44} ${50 + Math.sin(a + 0.2) * 44} L ${50 + Math.cos(a + 0.4) * 15} ${50 + Math.sin(a + 0.4) * 15} Z`}
        fill="#7C3AED"
      />
    );
  });
  return (
    <svg width={s} height={s} viewBox="0 0 100 100" style={{ transform: `rotate(${spin * 1.6}deg)` }}>
      {spikes}
      <circle cx="50" cy="50" r="17" fill="#A78BFA" />
      <circle cx="44" cy="47" r="3" fill="#1E1B4B" />
      <circle cx="56" cy="47" r="3" fill="#1E1B4B" />
    </svg>
  );
};

/* ────────────────────────── 可交互道具 ────────────────────────── */

const PropShape: React.FC<{ kind: "crate" | "pipe" | "cover"; s: number; rot: number }> = ({ kind, s, rot }) => {
  if (kind === "crate") {
    return (
      <svg width={s} height={s} viewBox="0 0 100 100" style={{ transform: `rotate(${rot}deg)` }}>
        <rect x="16" y="24" width="68" height="58" rx="4" fill="#B45309" stroke="#78350F" strokeWidth="4" />
        <path d="M16 44 L84 44 M16 62 L84 62" stroke="#92400E" strokeWidth="5" />
        <path d="M34 24 L34 82 M66 24 L66 82" stroke="#92400E" strokeWidth="5" />
      </svg>
    );
  }
  if (kind === "pipe") {
    return (
      <svg width={s} height={s} viewBox="0 0 100 100" style={{ transform: `rotate(${rot}deg)` }}>
        <rect x="10" y="42" width="80" height="16" rx="8" fill="#94A3B8" stroke="#475569" strokeWidth="3" />
        <rect x="14" y="45" width="18" height="10" rx="5" fill="#CBD5E1" opacity="0.7" />
        <rect x="68" y="45" width="18" height="10" rx="5" fill="#CBD5E1" opacity="0.7" />
      </svg>
    );
  }
  return (
    <svg width={s} height={s} viewBox="0 0 100 100" style={{ transform: `rotate(${rot}deg)` }}>
      <ellipse cx="50" cy="50" rx="40" ry="40" fill="#64748B" stroke="#334155" strokeWidth="4" />
      <ellipse cx="50" cy="50" rx="26" ry="26" fill="none" stroke="#475569" strokeWidth="3" strokeDasharray="6 5" />
    </svg>
  );
};

/* ────────────────────────── 机器人 ────────────────────────── */

const Robot: React.FC<{
  w: number;
  accent: string;
  legSwing: number;
  armSwing: number;
  lean: number;
  squash: number;
  eye: number;
  spin: number;
  shield: number;
  glow: number;
}> = ({ w, accent, legSwing, armSwing, lean, squash, eye, spin, shield, glow }) => {
  const h = w * 1.2;
  return (
    <svg width={w} height={h} viewBox="0 0 100 120" style={{ overflow: "visible" }}>
      <defs>
        <linearGradient id="ar-body" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#FFFFFF" />
          <stop offset="100%" stopColor="#CBD5E1" />
        </linearGradient>
        <radialGradient id="ar-glow">
          <stop offset="0%" stopColor={accent} stopOpacity="0.85" />
          <stop offset="100%" stopColor={accent} stopOpacity="0" />
        </radialGradient>
      </defs>

      {glow > 0.02 && <ellipse cx="50" cy="112" rx={26 + glow * 16} ry={7 + glow * 4} fill="url(#ar-glow)" />}
      {shield > 0.02 && <circle cx="50" cy="66" r={34 + shield * 22} fill={accent} opacity={0.14} />}
      {shield > 0.02 && (
        <circle cx="50" cy="66" r={34 + shield * 22} fill="none" stroke={accent} strokeWidth="2.5" opacity={0.5 + shield * 0.4} />
      )}

      <g transform={`translate(50 66) rotate(${spin}deg) translate(-50 -66)`}>
        <g transform={`translate(50 66) scale(${1 + squash * 0.07} ${1 - squash * 0.07}) translate(-50 -66)`}>
          <g transform={`rotate(${legSwing} 40 96)`}>
            <rect x="33" y="92" width="9" height="18" rx="4.5" fill="#94A3B8" />
            <rect x="27" y="106" width="19" height="8" rx="4" fill="#64748B" />
          </g>
          <g transform={`rotate(${-legSwing} 60 96)`}>
            <rect x="58" y="92" width="9" height="18" rx="4.5" fill="#94A3B8" />
            <rect x="54" y="106" width="19" height="8" rx="4" fill="#64748B" />
          </g>

          <rect x="31" y="54" width="38" height="44" rx="15" fill="url(#ar-body)" stroke="#94A3B8" strokeWidth="1.8" />
          <rect x="41" y="70" width="18" height="11" rx="3.5" fill={accent} opacity="0.9" />

          <g transform={`rotate(${armSwing} 33 64)`}>
            <rect x="23" y="60" width="8" height="24" rx="4" fill="#94A3B8" />
            <circle cx="27" cy="86" r="5.5" fill="#64748B" />
          </g>
          <g transform={`rotate(${-armSwing * 1.5} 67 64)`}>
            <rect x="69" y="58" width="8" height="26" rx="4" fill="#94A3B8" />
            <circle cx="73" cy="86" r="6" fill={accent} />
          </g>

          <g transform={`translate(0 ${-lean * 1.6})`}>
            <rect x="33" y="18" width="34" height="30" rx="13" fill="url(#ar-body)" stroke="#94A3B8" strokeWidth="1.8" />
            <ellipse cx={50 + eye * 6} cy="32" rx="9.5" ry="7.5" fill="#0F172A" />
            <circle cx={50 + eye * 6 + 2.6} cy="30" r="2.5" fill="#FFFFFF" opacity="0.9" />
            <g transform={`rotate(${legSwing * 0.3} 50 18)`}>
              <rect x="49" y="6" width="2.2" height="13" rx="1.1" fill="#94A3B8" />
              <circle cx="50" cy="5" r="3.6" fill={accent} />
            </g>
          </g>
        </g>
      </g>
    </svg>
  );
};

/* ────────────────────────── 主组件 ────────────────────────── */

interface EnemyState {
  id: number;
  kind: ArenaEnemyKind;
  spawnAt: number; // 秒
  from: "left" | "right" | "back" | "front";
  wx0: number;
  d0: number;
  speed: number;
  killedAt: number | null;
  killDir: number;
}

export const HookArena: React.FC<HookArenaProps> = ({
  startX = 0.18,
  endX = 0.82,
  horizonY = 0.55,
  bottomY = 0.9,
  size = 0.13,
  accent = "#38BDF8",
  waves = DEFAULT_WAVES,
  trickleSeconds = 1.15,
  showGrid = true,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();

  const t = frame / fps;
  const durSec = durationInFrames / fps;
  const progress = clamp01(frame / Math.max(1, durationInFrames - 1));

  const robotW = Math.round(width * size);
  const halfW = width * 0.62;
  const centerX = width / 2;
  const horizonPx = height * horizonY;
  const bottomPx = height * bottomY;

  // 2.5D 投影:深度 d(0 远 / 1 近)→ 屏幕 y 与缩放
  const depthY = (d: number) => lerp(horizonPx, bottomPx, Math.pow(clamp01(d), 1.5));
  const depthScale = (d: number) => lerp(0.42, 1.2, clamp01(d));
  const project = (wx: number, d: number) => ({
    x: centerX + wx * halfW * depthScale(d),
    y: depthY(d),
    s: depthScale(d),
  });

  // 机器人:世界坐标随进度从左到右,深度固定在中景
  const robotWX = lerp(-0.82, 0.82, progress);
  const robotD = 0.6;
  const robotPos = project(robotWX, robotD);
  const stride = robotW * 0.5;
  const walkPhase = ((robotPos.x - centerX) / stride) * Math.PI;
  const legSwing = Math.sin(walkPhase) * 15;
  const armSwing = Math.sin(walkPhase) * 11;
  const bob = Math.abs(Math.sin(walkPhase)) * robotW * 0.03;

  /* ── 生成敌人时间表(确定性) ── */
  const enemies: EnemyState[] = [];
  let eid = 0;
  // 1) 波次敌人
  waves.forEach((w, wi) => {
    const atSec = w.at * durSec;
    const count = w.count ?? 4;
    for (let k = 0; k < count; k++) {
      const from: EnemyState["from"] =
        w.from && w.from !== "any"
          ? w.from
          : (["left", "right", "back", "front"] as const)[Math.floor(rand(wi * 13 + k, 1) * 4)];
      const jitter = rand(wi * 13 + k, 2) * 0.5;
      enemies.push({
        id: eid++,
        kind: ENEMY_KINDS[Math.floor(rand(wi * 13 + k, 3) * ENEMY_KINDS.length)],
        spawnAt: atSec - 1.5 - jitter,
        from,
        wx0: from === "left" ? -1.15 : from === "right" ? 1.15 : (rand(wi * 13 + k, 4) - 0.5) * 1.1,
        d0: from === "back" ? 0.08 : from === "front" ? 0.98 : 0.3 + rand(wi * 13 + k, 5) * 0.45,
        speed: 1.05 + rand(wi * 13 + k, 6) * 0.5,
        killedAt: null,
        killDir: rand(wi * 13 + k, 7) > 0.5 ? 1 : -1,
      });
    }
  });
  // 2) 持续刷怪(两次波次之间也不断有人冲上来)
  const trickleCount = Math.floor(durSec / trickleSeconds) * 2;
  for (let i = 0; i < trickleCount; i++) {
    const spawnAt = Math.floor(i / 2) * trickleSeconds + 0.4 + (i % 2) * 0.28;
    const from = (["left", "right", "back", "front"] as const)[Math.floor(rand(i, 11) * 4)];
    enemies.push({
      id: eid++,
      kind: ENEMY_KINDS[Math.floor(rand(i, 12) * ENEMY_KINDS.length)],
      spawnAt,
      from,
      wx0: from === "left" ? -1.1 : from === "right" ? 1.1 : (rand(i, 13) - 0.5) * 1.0,
      d0: from === "back" ? 0.1 : from === "front" ? 0.96 : 0.25 + rand(i, 14) * 0.5,
      speed: 1.0 + rand(i, 15) * 0.6,
      killedAt: null,
      killDir: rand(i, 16) > 0.5 ? 1 : -1,
    });
  }

  /* ── 当前出招 ── */
  const WINDOW_IN = 0.55;
  const WINDOW_OUT = 1.0;
  const wave = waves.find((w) => {
    const atSec = w.at * durSec;
    return t >= atSec - WINDOW_IN && t <= atSec + WINDOW_OUT;
  });
  const waveLocal = wave ? t - wave.at * durSec : -99;
  const waveRadius = 0.82; // 世界坐标下的清场半径

  // 判定每个敌人是否被这招打掉
  if (wave) {
    for (const e of enemies) {
      if (e.killedAt !== null) continue;
      const age = t - e.spawnAt;
      if (age < 0) continue;
      const k = clamp01(age / 1.6);
      const wx = lerp(e.wx0, robotWX, easeIn(k));
      const d = lerp(e.d0, robotD, easeIn(k));
      const dist = Math.hypot(wx - robotWX, d - robotD);
      if (waveLocal >= -0.05 && dist < waveRadius) e.killedAt = t;
    }
  }

  /* ── 出招状态 ── */
  let spin = 0;
  let squash = 0;
  let lean = 0;
  let shield = 0;
  let glow = 0;
  let hop = 0;
  let propKind: "crate" | "pipe" | "cover" | null = null;
  let propRot = 0;
  let propPhase = 0;

  if (wave) {
    const a = wave.ability;
    if (a === "spin") {
      spin = lerp(clamp01((waveLocal + 0.15) / 0.6), 0, 1) * 720;
      glow = 0.6;
    } else if (a === "stomp") {
      hop = Math.sin(clamp01((waveLocal + 0.35) / 0.75) * Math.PI) * robotW * 0.75;
      squash = Math.max(0, 1 - Math.abs(waveLocal - 0.4) * 6);
      glow = 0.9;
    } else if (a === "shield") {
      shield = lerp(clamp01((waveLocal + 0.35) / 0.5), 0, 1);
      if (waveLocal > 0.4) shield = 1 - clamp01((waveLocal - 0.4) / 0.6);
    } else if (a === "punch") {
      lean = Math.sin(clamp01((waveLocal + 0.2) / 0.6) * Math.PI) * 8;
      squash = 0.25;
    } else if (a === "net" || a === "magnet") {
      lean = 3;
      glow = 0.5;
    } else if (a === "kick_crate") {
      propKind = "crate";
      propPhase = clamp01((waveLocal + 0.45) / 1.0);
      propRot = propPhase * 240;
    } else if (a === "swing_pipe") {
      propKind = "pipe";
      propPhase = clamp01((waveLocal + 0.45) / 1.0);
      propRot = lerp(-120, 70, easeOut(propPhase));
    } else if (a === "throw_cover") {
      propKind = "cover";
      propPhase = clamp01((waveLocal + 0.45) / 1.0);
      propRot = propPhase * 540;
    }
  }

  // 贴身敌人:自动出拳,让"一招一式"是持续的,而不是只在波次里
  const nearest = enemies
    .map((e) => {
      const age = t - e.spawnAt;
      if (age < 0 || e.killedAt !== null) return 99;
      const k = clamp01(age / 1.6);
      const wx = lerp(e.wx0, robotWX, easeIn(k));
      const d = lerp(e.d0, robotD, easeIn(k));
      return Math.hypot(wx - robotWX, d - robotD);
    })
    .reduce((m, v) => Math.min(m, v), 99);
  if (!wave && nearest < 0.3) {
    lean = Math.sin(t * 9) * 7;
    squash = 0.12;
  }

  const robotS = depthScale(robotD);

  /* ── 渲染敌人(按深度排序:远的先画) ── */
  const visible = enemies
    .map((e) => {
      const age = t - e.spawnAt;
      if (age < 0) return null;
      const k = clamp01(age / 1.6);
      let wx = lerp(e.wx0, robotWX, easeIn(k));
      let d = lerp(e.d0, robotD, easeIn(k));
      let rot = age * 40 * e.killDir;
      let scale = 1;
      let alpha = 1;

      if (e.killedAt !== null) {
        const after = t - e.killedAt;
        if (after > 1.1) return null;
        const kk = clamp01(after / 1.1);
        wx += e.killDir * kk * 1.1;
        d = clamp01(d + kk * 0.25);
        rot = e.killDir * kk * 620;
        scale = 1 - kk * 0.55;
        alpha = 1 - kk;
      }
      const p = project(wx, d);
      return { e, p, rot, scale, alpha, depth: d };
    })
    .filter(Boolean) as { e: EnemyState; p: { x: number; y: number; s: number }; rot: number; scale: number; alpha: number; depth: number }[];

  visible.sort((a, b) => a.depth - b.depth);

  const enemySize = (depth: number) => robotW * 0.62 * depthScale(depth);

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {/* 地面:透视网格 */}
      {showGrid && (
        <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
          <defs>
            <linearGradient id="ar-floor" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={accent} stopOpacity="0.14" />
              <stop offset="100%" stopColor={accent} stopOpacity="0.02" />
            </linearGradient>
          </defs>
          <rect x="0" y={horizonPx} width={width} height={bottomPx - horizonPx} fill="rgba(2,6,23,0.55)" />
          <rect x="0" y={horizonPx} width={width} height={bottomPx - horizonPx} fill="url(#ar-floor)" />
          {/* 纵向线:向消失点收敛 */}
          {Array.from({ length: 13 }, (_, i) => {
            const wx = (i / 12 - 0.5) * 2;
            const a = project(wx, 0.02);
            const b = project(wx, 1);
            return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={accent} strokeOpacity={0.2} strokeWidth={1} />;
          })}
          {/* 横向线:等深线 */}
          {Array.from({ length: 7 }, (_, i) => {
            const d = 0.1 + (i / 6) * 0.9;
            const y = depthY(d);
            return <line key={i} x1={0} y1={y} x2={width} y2={y} stroke={accent} strokeOpacity={0.16} strokeWidth={1} />;
          })}
          {/* 地平线 */}
          <line x1={0} y1={horizonPx} x2={width} y2={horizonPx} stroke={accent} strokeOpacity={0.3} strokeWidth={2} />
        </svg>
      )}

      {/* 敌人 */}
      {visible.map(({ e, p, rot, scale, alpha, depth }) => {
        const s = enemySize(depth) * scale;
        return (
          <div
            key={e.id}
            style={{
              position: "absolute",
              left: p.x - s / 2,
              top: p.y - s * 0.92,
              width: s,
              height: s,
              opacity: alpha,
              transform: `rotate(${rot}deg)`,
            }}
          >
            <EnemyShape kind={e.kind} s={s} spin={t * 160} />
          </div>
        );
      })}

      {/* 道具 */}
      {propKind && (
        <div
          style={{
            position: "absolute",
            left: robotPos.x + robotW * (propPhase < 0.5 ? 0.5 : lerp(0.6, 2.6, (propPhase - 0.5) * 2)),
            top: robotPos.y - robotW * (propPhase < 0.5 ? 0.55 : lerp(0.9, 0.35, (propPhase - 0.5) * 2)),
            width: robotW * 0.55,
            height: robotW * 0.55,
          }}
        >
          <PropShape kind={propKind} s={robotW * 0.55} rot={propRot} />
        </div>
      )}

      {/* 机器人影子 */}
      <div
        style={{
          position: "absolute",
          left: robotPos.x - robotW * 0.42 * robotS,
          top: robotPos.y - robotW * 0.06,
          width: robotW * 0.84 * robotS,
          height: robotW * 0.16 * robotS,
          borderRadius: "50%",
          background: "rgba(0,0,0,0.4)",
          filter: "blur(4px)",
        }}
      />

      {/* 机器人 */}
      <div
        style={{
          position: "absolute",
          left: robotPos.x - (robotW * robotS) / 2,
          top: robotPos.y - robotW * 1.15 * robotS + bob - hop,
          transform: `rotate(${lean}deg)`,
        }}
      >
        <Robot
          w={robotW * robotS}
          accent={accent}
          legSwing={legSwing}
          armSwing={armSwing}
          lean={lean}
          squash={squash}
          eye={wave && waveLocal > -0.9 ? 1 : 0.25}
          spin={spin}
          shield={shield}
          glow={glow}
        />
      </div>
    </AbsoluteFill>
  );
};
