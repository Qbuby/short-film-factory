import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

/**
 * 闯关式钩子(Hook Journey)。
 *
 * 规则(见 .agents/skills/short-video-attention-hook/SKILL.md):
 *  - 机器人位置 = 视频进度:片头在最左,片尾刚好到最右。
 *  - 一路上按 encounters 指定的时间点,敌人从右侧冲过来,机器人用不同能力解决它。
 *  - 每解决一个,观众得到一个"关卡通过"的小奖励 —— 这是把注意力续到下一段的钩子。
 *
 * 设计取舍:全部矢量 + React 变换,不依赖外部素材。理由是 AI 生成的精灵图抠不干净,
 * 而"具身感"来自关节、重心和预备动作,不来自贴图精度。
 */

export type JourneyAbility = "jump" | "shield" | "net" | "spin" | "magnet";
export type JourneyEnemy = "drone" | "saw" | "missile" | "spike";

export interface JourneyEncounter {
  /** 触发时刻,占全片比例 0–1(0.25 = 视频走到四分之一时) */
  at: number;
  ability: JourneyAbility;
  enemy?: JourneyEnemy;
}

export interface HookJourneyProps {
  /** 机器人起点(画面宽度比例) */
  startX?: number;
  /** 机器人终点(画面宽度比例) */
  endX?: number;
  /** 地面线高度(画面高度比例) */
  groundY?: number;
  /** 机器人宽度(画面宽度比例) */
  size?: number;
  /** 主色 */
  accent?: string;
  encounters?: JourneyEncounter[];
  /** 是否画一条进度轨(机器人脚下的细线) */
  showTrack?: boolean;
}

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

const DEFAULT_ENCOUNTERS: JourneyEncounter[] = [
  { at: 0.14, ability: "jump", enemy: "spike" },
  { at: 0.3, ability: "shield", enemy: "missile" },
  { at: 0.46, ability: "net", enemy: "drone" },
  { at: 0.62, ability: "spin", enemy: "saw" },
  { at: 0.78, ability: "magnet", enemy: "missile" },
  { at: 0.92, ability: "jump", enemy: "spike" },
];

/** 敌人外形(纯矢量,小尺寸下也认得出) */
const EnemyShape: React.FC<{ kind: JourneyEnemy; size: number; spin: number }> = ({
  kind,
  size,
  spin,
}) => {
  const s = size;
  if (kind === "drone") {
    return (
      <svg width={s} height={s} viewBox="0 0 100 100" style={{ transform: `rotate(${spin}deg)` }}>
        <rect x="30" y="42" width="40" height="22" rx="8" fill="#334155" />
        <rect x="10" y="26" width="34" height="6" rx="3" fill="#475569" />
        <rect x="56" y="26" width="34" height="6" rx="3" fill="#475569" />
        <circle cx="20" cy="26" r="9" fill="none" stroke="#94A3B8" strokeWidth="3" />
        <circle cx="80" cy="26" r="9" fill="none" stroke="#94A3B8" strokeWidth="3" />
        <circle cx="50" cy="53" r="6" fill="#EF4444" />
      </svg>
    );
  }
  if (kind === "saw") {
    const teeth = Array.from({ length: 10 }, (_, i) => {
      const a = (i / 10) * Math.PI * 2;
      return (
        <path
          key={i}
          d={`M ${50 + Math.cos(a) * 30} ${50 + Math.sin(a) * 30} L ${50 + Math.cos(a + 0.12) * 44} ${50 + Math.sin(a + 0.12) * 44} L ${50 + Math.cos(a + 0.24) * 30} ${50 + Math.sin(a + 0.24) * 30} Z`}
          fill="#CBD5E1"
        />
      );
    });
    return (
      <svg width={s} height={s} viewBox="0 0 100 100" style={{ transform: `rotate(${spin}deg)` }}>
        {teeth}
        <circle cx="50" cy="50" r="30" fill="#94A3B8" />
        <circle cx="50" cy="50" r="10" fill="#475569" />
      </svg>
    );
  }
  if (kind === "missile") {
    return (
      <svg width={s} height={s} viewBox="0 0 100 100">
        <g transform="rotate(-12 50 50)">
          <rect x="24" y="42" width="46" height="16" rx="8" fill="#E2E8F0" />
          <path d="M70 42 L86 50 L70 58 Z" fill="#EF4444" />
          <path d="M28 42 L16 34 L28 50 Z" fill="#94A3B8" />
          <path d="M28 58 L16 66 L28 50 Z" fill="#94A3B8" />
          <circle cx="46" cy="50" r="5" fill="#0F172A" opacity="0.6" />
        </g>
      </svg>
    );
  }
  const spikes = Array.from({ length: 8 }, (_, i) => {
    const a = (i / 8) * Math.PI * 2;
    return (
      <path
        key={i}
        d={`M ${50 + Math.cos(a) * 16} ${50 + Math.sin(a) * 16} L ${50 + Math.cos(a + 0.2) * 44} ${50 + Math.sin(a + 0.2) * 44} L ${50 + Math.cos(a + 0.4) * 16} ${50 + Math.sin(a + 0.4) * 16} Z`}
        fill="#7C3AED"
      />
    );
  });
  return (
    <svg width={s} height={s} viewBox="0 0 100 100" style={{ transform: `rotate(${spin}deg)` }}>
      {spikes}
      <circle cx="50" cy="50" r="18" fill="#A78BFA" />
      <circle cx="44" cy="47" r="3.4" fill="#1E1B4B" />
      <circle cx="56" cy="47" r="3.4" fill="#1E1B4B" />
    </svg>
  );
};

/**
 * 机器人本体。所有关节都由外部传入的角度/位移驱动,
 * 这样才能做出"预备—发力—回收"的重心感,而不是整体平移。
 */
const Robot: React.FC<{
  w: number;
  accent: string;
  legSwing: number;
  armSwing: number;
  bodyLean: number;
  squash: number;
  eyeLook: number;
  spin: number;
  shieldR: number;
  netOut: number;
  magnetOn: number;
  drill: number;
}> = ({ w, accent, legSwing, armSwing, bodyLean, squash, eyeLook, spin, shieldR, netOut, magnetOn, drill }) => {
  const h = w * 1.15;
  return (
    <svg width={w} height={h} viewBox="0 0 100 115" style={{ overflow: "visible" }}>
      <defs>
        <linearGradient id="hj-body" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#F8FAFC" />
          <stop offset="100%" stopColor="#CBD5E1" />
        </linearGradient>
        <radialGradient id="hj-glow">
          <stop offset="0%" stopColor={accent} stopOpacity="0.9" />
          <stop offset="100%" stopColor={accent} stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* 护盾 */}
      {shieldR > 0.01 && (
        <circle cx="50" cy="62" r={30 + shieldR * 26} fill={accent} opacity={0.16} />
      )}
      {shieldR > 0.01 && (
        <circle
          cx="50"
          cy="62"
          r={30 + shieldR * 26}
          fill="none"
          stroke={accent}
          strokeWidth={2.5}
          opacity={0.55 + shieldR * 0.4}
        />
      )}

      <g transform={`translate(50 62) rotate(${spin}deg) translate(-50 -62)`}>
        <g transform={`translate(50 62) scale(${1 + squash * 0.06} ${1 - squash * 0.06}) translate(-50 -62)`}>
          {/* 腿 */}
          <g transform={`rotate(${legSwing} 40 92)`}>
            <rect x="34" y="88" width="8" height="18" rx="4" fill="#94A3B8" />
            <rect x="28" y="102" width="18" height="7" rx="3.5" fill="#64748B" />
          </g>
          <g transform={`rotate(${-legSwing} 60 92)`}>
            <rect x="58" y="88" width="8" height="18" rx="4" fill="#94A3B8" />
            <rect x="54" y="102" width="18" height="7" rx="3.5" fill="#64748B" />
          </g>

          {/* 躯干 */}
          <rect x="32" y="52" width="36" height="42" rx="14" fill="url(#hj-body)" stroke="#94A3B8" strokeWidth="1.6" />
          <rect x="42" y="66" width="16" height="10" rx="3" fill={accent} opacity="0.85" />

          {/* 手臂:右臂负责"出招" */}
          <g transform={`rotate(${armSwing} 34 62)`}>
            <rect x="24" y="58" width="7" height="22" rx="3.5" fill="#94A3B8" />
            <circle cx="27.5" cy="82" r="5" fill="#64748B" />
          </g>
          <g transform={`rotate(${-armSwing * 1.4 - drill * 26} 66 62)`}>
            <rect x="69" y="56" width="7" height="24" rx="3.5" fill="#94A3B8" />
            <circle cx="72.5" cy="82" r="5.5" fill={accent} />
            {drill > 0.05 && (
              <path d={`M72 84 L78 96 L66 96 Z`} fill="#E2E8F0" transform={`rotate(${drill * 720} 72 90)`} />
            )}
          </g>

          {/* 头 */}
          <g transform={`translate(0 ${-bodyLean * 2})`}>
            <rect x="34" y="20" width="32" height="28" rx="12" fill="url(#hj-body)" stroke="#94A3B8" strokeWidth="1.6" />
            {/* 单眼:看向敌人 */}
            <ellipse cx={50 + eyeLook * 6} cy="33" rx="9" ry="7" fill="#0F172A" />
            <circle cx={50 + eyeLook * 6 + 2.5} cy="31" r="2.4" fill="#FFFFFF" opacity="0.9" />
            {/* 天线 */}
            <g transform={`rotate(${legSwing * 0.35} 50 20)`}>
              <rect x="49" y="8" width="2" height="13" rx="1" fill="#94A3B8" />
              <circle cx="50" cy="7" r="3.4" fill={accent} />
            </g>
          </g>
        </g>
      </g>

      {/* 磁力场 */}
      {magnetOn > 0.02 && (
        <g opacity={magnetOn}>
          <circle cx="50" cy="62" r={26 + magnetOn * 20} fill="none" stroke={accent} strokeWidth={2} strokeDasharray="5 6" />
        </g>
      )}

      {/* 发射的网 */}
      {netOut > 0.02 && (
        <g opacity={Math.min(1, netOut * 1.6)}>
          <path
            d={`M72 78 L${72 + netOut * 46} ${78 - netOut * 12} L${72 + netOut * 40} ${78 + netOut * 26} Z`}
            fill="none"
            stroke="#E2E8F0"
            strokeWidth="1.6"
            strokeDasharray="4 3"
          />
        </g>
      )}
    </svg>
  );
};

export const HookJourney: React.FC<HookJourneyProps> = ({
  startX = 0.08,
  endX = 0.84,
  groundY = 0.72,
  size = 0.11,
  accent = "#38BDF8",
  encounters = DEFAULT_ENCOUNTERS,
  showTrack = true,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();

  const t = frame / fps;
  const durSec = durationInFrames / fps;
  const progress = clamp01(frame / Math.max(1, durationInFrames - 1));

  const robotW = Math.round(width * size);
  const groundPx = height * groundY;
  const x = lerp(width * startX, width * endX, progress);

  // 走路:相位跟"走了多远"绑定,停下时腿也停
  const stride = robotW * 0.55;
  const walkPhase = (x / stride) * Math.PI;
  const legSwing = Math.sin(walkPhase) * 16;
  const armSwing = Math.sin(walkPhase) * 12;
  const bob = Math.abs(Math.sin(walkPhase)) * robotW * 0.035;

  // 找到当前生效的遭遇战(at 前后各 1.15s 的窗口)
  const ENC_IN = 1.15;
  const ENC_OUT = 1.25;
  const enc = encounters.find((e) => {
    const atSec = e.at * durSec;
    return t >= atSec - ENC_IN && t <= atSec + ENC_OUT;
  });
  const encLocal = enc ? t - enc.at * durSec : -99;

  let jumpY = 0;
  let squash = 0;
  let spin = 0;
  let shieldR = 0;
  let netOut = 0;
  let magnetOn = 0;
  let drill = 0;
  let lean = 0;

  if (enc) {
    const kind = enc.ability;
    if (kind === "jump") {
      // 预备(-0.25s 下蹲)→ 起跳(0)→ 滞空 → 落地挤压
      const crouch = interpolate(encLocal, [-0.5, -0.22], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
      const air = interpolate(encLocal, [-0.22, 0.02, 0.5], [0, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
      jumpY = air * robotW * 1.5;
      squash = crouch * (1 - air) + Math.max(0, 1 - Math.abs(encLocal - 0.55) * 6) * 0.9;
      lean = -air * 6;
    } else if (kind === "shield") {
      shieldR = interpolate(encLocal, [-0.45, -0.05, 0.45, 0.9], [0, 1, 1, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
      squash = Math.max(0, 1 - Math.abs(encLocal) * 5) * 0.5;
    } else if (kind === "net") {
      netOut = interpolate(encLocal, [-0.1, 0.35, 1.0], [0, 1, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
      lean = interpolate(encLocal, [-0.2, 0.1, 0.5], [0, 5, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    } else if (kind === "spin") {
      spin = interpolate(encLocal, [-0.15, 0.55], [0, 720], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
      jumpY = Math.sin(clamp01((encLocal + 0.15) / 0.7) * Math.PI) * robotW * 0.35;
    } else if (kind === "magnet") {
      magnetOn = interpolate(encLocal, [-0.6, -0.2, 0.35, 0.7], [0, 1, 1, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
      lean = magnetOn * 4;
    }
  }

  const bobY = bob - jumpY;

  // 敌人:从右侧冲来 → 被解决 → 飞出
  const enemyEl = enc ? (
    <EnemyLayer
      enc={enc}
      encLocal={encLocal}
      width={width}
      groundPx={groundPx}
      robotX={x}
      robotW={robotW}
    />
  ) : null;

  // 已通关的关卡:在身后留一个小标记
  const passed = encounters.filter((e) => t > e.at * durSec + ENC_OUT);

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {/* 进度轨:脚下一条细线,填色 = 已走过的比例 */}
      {showTrack && (
        <>
          <div
            style={{
              position: "absolute",
              left: width * startX,
              top: groundPx + robotW * 0.2,
              width: (width * endX - width * startX) + robotW * 0.3,
              height: 3,
              borderRadius: 2,
              background: "rgba(148,163,184,0.22)",
            }}
          />
          <div
            style={{
              position: "absolute",
              left: width * startX,
              top: groundPx + robotW * 0.2,
              width: ((width * endX - width * startX) + robotW * 0.3) * progress,
              height: 3,
              borderRadius: 2,
              background: accent,
              opacity: 0.8,
            }}
          />
        </>
      )}

      {/* 通关标记 */}
      {passed.map((e, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            left: lerp(width * startX, width * endX, e.at) - 5,
            top: groundPx + robotW * 0.34,
            width: 10,
            height: 10,
            borderRadius: 5,
            background: accent,
            opacity: 0.55,
          }}
        />
      ))}

      {enemyEl}

      {/* 影子 */}
      <div
        style={{
          position: "absolute",
          left: x - robotW * 0.3,
          top: groundPx + robotW * 0.02,
          width: robotW * 0.6,
          height: robotW * 0.12,
          borderRadius: "50%",
          background: "rgba(0,0,0,0.35)",
          filter: "blur(3px)",
          transform: `scale(${1 - jumpY / (robotW * 3)})`,
          opacity: 0.8,
        }}
      />

      {/* 机器人 */}
      <div
        style={{
          position: "absolute",
          left: x - robotW / 2,
          top: groundPx - robotW * 1.15 + robotW * 0.18 + bobY,
          transform: `rotate(${lean}deg)`,
        }}
      >
        <Robot
          w={robotW}
          accent={accent}
          legSwing={legSwing}
          armSwing={armSwing}
          bodyLean={lean}
          squash={squash}
          eyeLook={enc && encLocal > -0.9 ? 1 : 0.2}
          spin={spin}
          shieldR={shieldR}
          netOut={netOut}
          magnetOn={magnetOn}
          drill={drill}
        />
      </div>
    </AbsoluteFill>
  );
};

/** 敌人:接近 → 被能力解决 → 飞出/碎裂 */
const EnemyLayer: React.FC<{
  enc: JourneyEncounter;
  encLocal: number;
  width: number;
  groundPx: number;
  robotX: number;
  robotW: number;
}> = ({ enc, encLocal, width, groundPx, robotX, robotW }) => {
  const size = robotW * 0.72;
  const kind = enc.enemy ?? "drone";

  // 进场:从右边缘冲向机器人;解决时刻 = encLocal 0
  const approach = interpolate(encLocal, [-1.15, 0], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const startX = width * 1.06;
  const meetX = robotX + robotW * 0.75;
  let ex = lerp(startX, meetX, approach);

  // 被解决后的位移
  const after = encLocal;
  let ey = 0;
  let rotate = 0;
  let scale = 1;
  let opacity = 1;

  if (after > 0) {
    const k = clamp01(after / 0.9);
    if (enc.ability === "jump") {
      // 从脚下滑过去
      ex = lerp(meetX, robotX - robotW * 1.2, k);
      rotate = k * -220;
    } else if (enc.ability === "shield") {
      ex = lerp(meetX, startX, k);
      ey = -k * size * 1.6;
      rotate = k * 320;
      scale = 1 - k * 0.35;
    } else if (enc.ability === "net") {
      scale = 1 - k * 0.55;
      ey = k * size * 1.2;
      rotate = k * 180;
      opacity = 1 - k * 0.75;
    } else if (enc.ability === "spin") {
      ex = lerp(meetX, startX * 0.9, k);
      ey = -k * size * 2.2;
      rotate = k * 540;
      scale = 1 - k * 0.5;
      opacity = 1 - k * 0.6;
    } else {
      // magnet:被吸过来再甩飞
      ex = lerp(meetX, robotX + robotW * 0.2, Math.min(1, k * 2));
      ey = -Math.max(0, k - 0.4) * size * 3.2;
      rotate = k * 400;
    }
  }

  const ey0 = kind === "drone" ? -size * 1.5 : kind === "missile" ? -size * 1.05 : 0;
  const bobY = kind === "drone" ? Math.sin(encLocal * 7) * size * 0.12 : 0;

  return (
    <div
      style={{
        position: "absolute",
        left: ex - size / 2,
        top: groundPx - size + ey0 + ey + bobY,
        width: size,
        height: size,
        transform: `rotate(${rotate}deg) scale(${scale})`,
        opacity,
      }}
    >
      <EnemyShape kind={kind} size={size} spin={encLocal * 90} />
    </div>
  );
};
