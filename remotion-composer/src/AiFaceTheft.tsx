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
import { AI_FACE_BEATS, AI_FACE_SPLIT } from "./aiFaceTiming";

const W = 1080;
const H = 1920;
const BEATS = AI_FACE_BEATS;
type BeatId = keyof typeof BEATS;

const C = {
  canvas: "#E8EDF0",
  paper: "#FAF4E8",
  white: "#FFFFFF",
  ink: "#172838",
  slate: "#3C5264",
  muted: "#AFC0CB",
  red: "#F04438",
  redDark: "#B42318",
  green: "#14866D",
  yellow: "#F6C453",
  skin: "#FFD2AE",
  skinShade: "#E8A77D",
};
const SANS = `"Noto Sans SC","Microsoft YaHei","PingFang SC","SimHei",sans-serif`;
const MONO = `"Consolas","Courier New",monospace`;

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
const lerp = (a: number, b: number, x: number) => a + (b - a) * x;
const easeOutCubic = (x: number) => 1 - Math.pow(1 - x, 3);
const easeInCubic = (x: number) => x * x * x;
const easeInOutCubic = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
const prog = (t: number, id: BeatId) => clamp01((t - BEATS[id][0]) / (BEATS[id][1] - BEATS[id][0]));
const active = (t: number, id: BeatId) => t >= BEATS[id][0] && t < BEATS[id][1];

// shotcraft effects/slam-entrance-moves B 式：悬停 → ease-in 砸落 → spring 回弹。
function slam(frame: number, startFrame: number, fps: number, from = 2.25, hover = 2.05) {
  const f = frame - startFrame;
  if (f < 0) return { scale: hover, blur: 12, opacity: 0 };
  if (f < 9) return { scale: lerp(from, hover, clamp01(f / 9)), blur: 12, opacity: clamp01(f / 2) * 0.9 };
  if (f < 15) {
    const land = easeInCubic(clamp01((f - 9) / 6));
    return { scale: lerp(hover, 0.965, land), blur: lerp(10, 0, land), opacity: 1 };
  }
  const back = spring({ frame: f - 15, fps, config: { damping: 14, mass: 0.6 } });
  return { scale: lerp(0.965, 1, back), blur: 0, opacity: 1 };
}

// shotcraft effects/impact-feedback：指数衰减震屏 + 落点白闪。
function shake(frame: number, startFrame: number, amp = 16, tau = 4.5) {
  const f = frame - startFrame;
  if (f < 0 || f > 30) return { x: 0, y: 0 };
  const env = Math.exp(-f / tau) * amp;
  return { x: Math.sin(f * 2.3) * env * 0.35, y: Math.cos(f * 3.1) * env };
}
const impactRing = (frame: number, startFrame: number) => {
  const f = frame - startFrame;
  if (f < 0 || f > 26) return null;
  return { r: lerp(60, 750, easeOutCubic(clamp01(f / 16))), alpha: clamp01(1 - Math.max(0, f - 16) / 10) };
};
const flash = (frame: number, startFrame: number, dur = 2) => {
  const f = frame - startFrame;
  return f < 0 || f >= dur ? 0 : 1 - f / dur;
};

const CAM: Record<BeatId, { z0: number; z1: number; x0: number; x1: number }> = {
  hook: { z0: 1.0, z1: 1.035, x0: 0, x1: -8 },
  case: { z0: 1.04, z1: 1.0, x0: -8, x1: 5 },
  blink: { z0: 1.0, z1: 1.045, x0: 6, x1: -6 },
  camera: { z0: 1.035, z1: 1.0, x0: -8, x1: 7 },
  risk: { z0: 1.0, z1: 1.035, x0: 0, x1: 0 },
  defense: { z0: 1.025, z1: 1.0, x0: 0, x1: -4 },
  end: { z0: 1.0, z1: 1.03, x0: 0, x1: 0 },
};
const Camera: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = f / fps;
  const id = (Object.keys(BEATS) as BeatId[]).find((k) => active(t, k)) ?? "hook";
  const c = CAM[id];
  const p = prog(t, id);
  const local = t - BEATS[id][0];
  // shotcraft camera/crash-zoom-punch：每拍切入先急推，再撞停，接长 ease 运镜。
  const punch = local < 0.34 ? lerp(1.055, 1, easeOutCubic(local / 0.34)) : 1;
  const z = lerp(c.z0, c.z1, easeInOutCubic(p)) * punch;
  return (
    <AbsoluteFill style={{ transform: `translate(${lerp(c.x0, c.x1, p)}px, 0px) scale(${z})` }}>
      {children}
    </AbsoluteFill>
  );
};

const Sticker: React.FC<{
  x: number; y: number; children: React.ReactNode; rotate?: number;
  pad?: number; bg?: string; style?: React.CSSProperties;
}> = ({ x, y, children, rotate = 0, pad = 22, bg = C.paper, style }) => (
  <div
    style={{
      position: "absolute", left: x, top: y, padding: pad, background: bg,
      border: `11px solid ${C.white}`, outline: `2px solid rgba(23,40,56,0.5)`,
      outlineOffset: 11, borderRadius: 12, transform: `rotate(${rotate}deg)`,
      boxShadow: "0 16px 32px rgba(23,40,56,0.16)", ...style,
    }}
  >
    {children}
  </div>
);

const Stamp: React.FC<{ x: number; y: number; text: string; rotate?: number; color?: string; size?: number }> = ({
  x, y, text, rotate = -7, color = C.red, size = 58,
}) => (
  <div
    style={{
      position: "absolute", left: x, top: y, transform: `rotate(${rotate}deg)`,
      border: `7px solid ${color}`, borderRadius: 10, padding: "10px 24px", color,
      fontFamily: SANS, fontWeight: 900, fontSize: size, letterSpacing: 5,
      whiteSpace: "nowrap", background: "rgba(255,255,255,0.78)",
    }}
  >
    {text}
  </div>
);

const BeatTitle: React.FC<{ children: React.ReactNode; top?: number; size?: number; color?: string }> = ({
  children, top = 150, size = 72, color = C.ink,
}) => (
  <div style={{ position: "absolute", left: 70, right: 60, top, fontFamily: SANS, fontWeight: 900, fontSize: size, lineHeight: 1.12, color, letterSpacing: 2 }}>
    {children}
  </div>
);

const Note: React.FC<{ children: React.ReactNode; y?: number; color?: string }> = ({ children, y = 1290, color = C.ink }) => (
  <Sticker x={70} y={y} rotate={-0.8} pad={22} style={{ width: 940, boxSizing: "border-box" }}>
    <div style={{ fontFamily: SANS, fontWeight: 800, fontSize: 36, lineHeight: 1.3, color }}>{children}</div>
  </Sticker>
);

/** 程序化人脸贴纸：眼睛和头部真的在动，第一帧就不是静图。 */
const FaceCard: React.FC<{
  x: number; y: number; scale?: number; rotate?: number; t: number;
  nod?: boolean; dim?: boolean; label?: string;
}> = ({ x, y, scale = 1, rotate = 0, t, nod = true, dim = false, label }) => {
  const blink = t % 2.35 < 0.16;
  const nodAngle = nod ? Math.sin(t * 3.1) * 4.5 : 0;
  const eyeOpen = blink ? 2 : 24;
  return (
    <Sticker x={x} y={y} rotate={rotate + nodAngle * 0.18} pad={18} style={{ opacity: dim ? 0.35 : 1 }}>
      <div style={{ transform: `scale(${scale})`, transformOrigin: "top left", width: 280, height: 340 }}>
        <svg width={280} height={340} viewBox="0 0 280 340">
          <rect x={4} y={4} width={272} height={332} rx={20} fill="#DCE7EC" />
          <circle cx={140} cy={156} r={112} fill="#C2D6DF" stroke={C.white} strokeWidth={8} strokeDasharray="12 9" />
          <g transform={`rotate(${nodAngle} 140 170)`}>
            <rect x={99} y={239} width={82} height={72} rx={24} fill={C.skinShade} />
            <path d="M55 333 Q65 266 140 266 Q215 266 225 333 Z" fill={C.ink} />
            <ellipse cx={140} cy={164} rx={83} ry={103} fill={C.skin} stroke={C.ink} strokeWidth={6} />
            <path d="M58 151 Q50 51 140 49 Q230 51 222 151 Q194 110 160 111 Q106 119 58 151" fill={C.ink} />
            <ellipse cx={60} cy={174} rx={13} ry={23} fill={C.skin} stroke={C.ink} strokeWidth={5} />
            <ellipse cx={220} cy={174} rx={13} ry={23} fill={C.skin} stroke={C.ink} strokeWidth={5} />
            <path d="M86 140 Q107 128 124 140" fill="none" stroke={C.ink} strokeWidth={7} strokeLinecap="round" />
            <path d="M156 140 Q177 128 194 140" fill="none" stroke={C.ink} strokeWidth={7} strokeLinecap="round" />
            <rect x={92} y={150} width={30} height={eyeOpen} rx={15} fill={C.white} stroke={C.ink} strokeWidth={5} />
            <rect x={158} y={150} width={30} height={eyeOpen} rx={15} fill={C.white} stroke={C.ink} strokeWidth={5} />
            {!blink && <><circle cx={107} cy={162} r={7} fill={C.ink} /><circle cx={173} cy={162} r={7} fill={C.ink} /></>}
            <path d="M139 166 L130 203 L148 203" fill="none" stroke={C.ink} strokeWidth={5} strokeLinecap="round" />
            <path d="M111 224 Q140 241 169 224" fill="none" stroke={C.ink} strokeWidth={7} strokeLinecap="round" />
          </g>
        </svg>
        {label && <div style={{ position: "absolute", left: 18, bottom: 16, fontFamily: MONO, fontWeight: 900, fontSize: 25, color: C.ink }}>{label}</div>}
      </div>
    </Sticker>
  );
};

const Phone: React.FC<{ x: number; y: number; w?: number; h?: number; children: React.ReactNode; rotate?: number }> = ({
  x, y, w = 320, h = 560, children, rotate = 0,
}) => (
  <div style={{ position: "absolute", left: x, top: y, width: w, height: h, border: `12px solid ${C.ink}`, borderRadius: 42, background: C.white, boxShadow: "0 22px 38px rgba(23,40,56,0.2)", transform: `rotate(${rotate}deg)`, overflow: "hidden" }}>
    <div style={{ position: "absolute", left: "35%", right: "35%", top: 12, height: 16, borderRadius: 10, background: C.ink }} />
    <div style={{ position: "absolute", inset: "42px 12px 18px" }}>{children}</div>
  </div>
);

const Arrow: React.FC<{ x: number; y: number; color?: string; size?: number }> = ({ x, y, color = C.red, size = 66 }) => (
  <div style={{ position: "absolute", left: x, top: y, color, fontFamily: SANS, fontWeight: 900, fontSize: size }}>→</div>
);

/* 1 你的脸，正在替你下单 */
const BeatHook: React.FC = () => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig(); const t = f / fps;
  const s = slam(f, 0, fps); const s2 = slam(f, AI_FACE_SPLIT * fps, fps, 1.85, 1.7);
  const sh = shake(f, 15, 14); const sh2 = shake(f, AI_FACE_SPLIT * fps, 10);
  return (
    <AbsoluteFill style={{ transform: `translate(${sh.x + sh2.x}px, ${sh.y + sh2.y}px)` }}>
      <div style={{ position: "absolute", left: 70, top: 90, fontFamily: MONO, fontSize: 30, letterSpacing: 5, color: C.slate }}>AI 时代 · 人脸识别新风险</div>
      <FaceCard x={70} y={250} t={t} label="正在点头 / 眨眼" />
      <Phone x={610} y={300} rotate={3}>
        <div style={{ height: "100%", background: "#EDF3F5", padding: 28, boxSizing: "border-box" }}>
          <div style={{ fontFamily: MONO, fontWeight: 900, fontSize: 28, color: C.slate }}>FACE PAY</div>
          <div style={{ marginTop: 58, width: 160, height: 170, marginLeft: 38, background: C.yellow, border: `7px solid ${C.ink}`, borderRadius: 16, position: "relative", transform: `translateY(${Math.sin(t * 4) * 5}px)` }}>
            <div style={{ position: "absolute", left: 42, top: -38, width: 64, height: 55, border: `7px solid ${C.ink}`, borderBottom: 0, borderRadius: "40px 40px 0 0" }} />
            <div style={{ position: "absolute", left: 26, top: 55, fontFamily: SANS, fontWeight: 900, fontSize: 58, color: C.ink }}>单</div>
          </div>
          <div style={{ marginTop: 50, background: C.red, color: C.white, borderRadius: 12, textAlign: "center", padding: "18px 0", fontFamily: SANS, fontWeight: 900, fontSize: 36 }}>验证通过</div>
        </div>
      </Phone>
      <div style={{ position: "absolute", left: 70, top: 850, transform: `scale(${s.scale})`, filter: `blur(${s.blur}px)`, opacity: s.opacity, fontFamily: SANS, fontWeight: 900, fontSize: 108, lineHeight: 1.05, color: C.ink }}>
        你的脸<br /><span style={{ color: C.red, fontSize: 90 }}>正在替你下单</span>
      </div>
      <div style={{ transform: `scale(${s2.scale})`, filter: `blur(${s2.blur}px)`, opacity: s2.opacity }}>
        <Stamp x={90} y={1190} text="可你根本不在场" size={54} />
      </div>
      <Note y={1320}>你在家躺着，「你」却在别处完成了验证。</Note>
    </AbsoluteFill>
  );
};

/* 2 案件：照片 → 动态视频 → 摄像头 */
const BeatCase: React.FC = () => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig(); const t = f / fps;
  const f0 = BEATS.case[0] * fps; const st = slam(f, f0 + 45, fps, 1.85, 1.7);
  const sh = shake(f, f0 + 60, 16); const ring = impactRing(f, f0 + 60);
  const n = Math.round(lerp(0, 30, easeOutCubic(clamp01((f - f0 - 8) / 45))));
  return (
    <AbsoluteFill style={{ transform: `translate(${sh.x}px, ${sh.y}px)` }}>
      <BeatTitle size={66}>一张照片，怎么刷开账号？</BeatTitle>
      {[
        { x: 60, label: "网上照片", icon: "照", bg: "#DCE7EC" },
        { x: 400, label: "动态视频", icon: "▶", bg: "#FFE0D8" },
        { x: 740, label: "摄像头画面", icon: "换", bg: "#FFF0C8" },
      ].map((it, i) => (
        <Sticker key={it.label} x={it.x} y={320 + (i % 2) * 20} rotate={i === 1 ? 2 : -2} pad={18}>
          <div style={{ width: 230, height: 250, background: it.bg, borderRadius: 12, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", transform: `translateY(${Math.sin(t * 3 + i) * 5}px)` }}>
            <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 96, color: i === 1 ? C.red : C.ink }}>{it.icon}</div>
            <div style={{ marginTop: 20, fontFamily: SANS, fontWeight: 900, fontSize: 30, color: C.ink }}>{it.label}</div>
          </div>
        </Sticker>
      ))}
      <Arrow x={330} y={400} /><Arrow x={670} y={400} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 760, textAlign: "center", fontFamily: SANS, fontWeight: 900, color: C.red, fontSize: 170, lineHeight: 1 }}>
        近 {n} 个
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 960, textAlign: "center", fontFamily: SANS, fontWeight: 900, color: C.ink, fontSize: 58 }}>账号被刷开</div>
      <div style={{ transform: `scale(${st.scale})`, filter: `blur(${st.blur}px)`, opacity: st.opacity }}><Stamp x={90} y={1110} text="不是段子" size={54} /></div>
      {ring && <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}><circle cx={540} cy={850} r={ring.r} fill="none" stroke={C.red} strokeWidth={9} opacity={ring.alpha * 0.45} /></svg>}
      <Note y={1300}>原片案件：收货地址、购物车信息被翻走。</Note>
    </AbsoluteFill>
  );
};

/* 3 活体检测反转 */
const BeatBlink: React.FC = () => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig(); const t = f / fps;
  const f0 = BEATS.blink[0] * fps; const st = slam(f, f0 + 52, fps, 1.85, 1.7);
  const sh = shake(f, f0 + 67, 16); const fl = flash(f, f0 + 67, 2);
  return (
    <AbsoluteFill style={{ transform: `translate(${sh.x}px, ${sh.y}px)` }}>
      <BeatTitle size={78}>平台：请眨眼</BeatTitle>
      <FaceCard x={350} y={270} scale={1.25} t={t} label="动作符合" />
      {["点头", "摇头", "眨眼"].map((x, i) => (
        <div key={x} style={{ position: "absolute", left: i === 1 ? 770 : 70, top: 330 + i * 180, padding: "14px 24px", background: C.white, border: `5px solid ${C.ink}`, borderRadius: 30, fontFamily: SANS, fontWeight: 900, fontSize: 34, color: C.ink, opacity: clamp01((t - BEATS.blink[0] - i * 0.45) / 0.25) }}>请{x}</div>
      ))}
      <div style={{ transform: `scale(${st.scale})`, filter: `blur(${st.blur}px)`, opacity: st.opacity }}><Stamp x={110} y={870} text="会眨眼 ≠ 本人" size={70} /></div>
      <div style={{ position: "absolute", left: 70, right: 60, top: 1080, fontFamily: SANS, fontWeight: 900, fontSize: 60, lineHeight: 1.25, color: C.ink }}>平台想验活人<br /><span style={{ color: C.red }}>骗子递上一段视频</span></div>
      <Note y={1320}>动作答对了，也不代表镜头前是你。</Note>
      {fl > 0 && <AbsoluteFill style={{ background: C.white, opacity: fl * 0.55 }} />}
    </AbsoluteFill>
  );
};

/* 4 摄像头被掉包 */
const BeatCamera: React.FC = () => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig(); const t = f / fps;
  const p = prog(t, "camera"); const f0 = BEATS.camera[0] * fps;
  const st = slam(f, f0 + 65, fps, 1.85, 1.7); const sh = shake(f, f0 + 80, 17);
  const swap = easeInOutCubic(clamp01((p - 0.22) / 0.25));
  return (
    <AbsoluteFill style={{ transform: `translate(${sh.x}px, ${sh.y}px)` }}>
      <BeatTitle size={64}>它看到的，根本不是现场</BeatTitle>
      <div style={{ position: "absolute", left: 70, top: 290, fontFamily: MONO, fontWeight: 900, fontSize: 30, color: C.slate }}>你以为：LIVE CAMERA</div>
      <FaceCard x={70} y={350} scale={0.9} t={t} dim={swap > 0.7} />
      <div style={{ position: "absolute", left: 650, top: 290, fontFamily: MONO, fontWeight: 900, fontSize: 30, color: C.red }}>实际：PLAYBACK</div>
      <Sticker x={650} y={350} rotate={2} pad={18} style={{ transform: `translate(${-swap * 40}px, ${-swap * 20}px) rotate(2deg)` }}>
        <div style={{ width: 252, height: 306, background: C.ink, display: "flex", alignItems: "center", justifyContent: "center", position: "relative" }}>
          <div style={{ width: 110, height: 110, borderRadius: 60, background: C.red, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 66, color: C.white, paddingLeft: 10 }}>▶</div>
          <div style={{ position: "absolute", left: 16, bottom: 14, fontFamily: MONO, fontSize: 25, color: C.white }}>预录视频</div>
          <div style={{ position: "absolute", left: 16, top: 14, width: 18, height: 18, borderRadius: 9, background: C.red }} />
        </div>
      </Sticker>
      <Arrow x={480} y={470} size={90} />
      <div style={{ transform: `scale(${st.scale})`, filter: `blur(${st.blur}px)`, opacity: st.opacity }}><Stamp x={280} y={760} text="掉包" size={62} /></div>
      <div style={{ position: "absolute", left: 70, top: 970, fontFamily: SANS, fontWeight: 900, fontSize: 64, color: C.ink }}>人脸识别</div>
      <Arrow x={90} y={1060} size={70} />
      <div style={{ position: "absolute", left: 210, top: 1050, fontFamily: SANS, fontWeight: 900, fontSize: 92, color: C.red }}>录像审核</div>
      <Note y={1320}>不是识别错了，是摄像头输入被换了。</Note>
    </AbsoluteFill>
  );
};

/* 5 密码能改，脸呢 */
const BeatRisk: React.FC = () => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig(); const t = f / fps;
  const f0 = BEATS.risk[0] * fps; const st = slam(f, f0 + 25, fps, 1.9, 1.75);
  const sh = shake(f, f0 + 40, 14);
  return (
    <AbsoluteFill style={{ transform: `translate(${sh.x}px, ${sh.y}px)` }}>
      <Sticker x={70} y={230} rotate={-2} pad={26}>
        <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 46, color: C.ink }}>密码泄露</div>
        <div style={{ marginTop: 24, width: 360, padding: "22px 0", border: `5px dashed ${C.slate}`, borderRadius: 12, textAlign: "center", fontFamily: MONO, fontSize: 42, color: C.slate }}>••••••••</div>
        <div style={{ marginTop: 24, background: C.green, color: C.white, borderRadius: 12, padding: "18px 0", textAlign: "center", fontFamily: SANS, fontWeight: 900, fontSize: 36 }}>重新设置</div>
      </Sticker>
      <Stamp x={510} y={350} text="能改" color={C.green} size={62} />
      <FaceCard x={650} y={230} scale={0.95} t={t} nod={false} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 800, textAlign: "center", fontFamily: SANS, fontWeight: 900, fontSize: 66, color: C.ink }}>那你的脸泄露了</div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 930, textAlign: "center", transform: `scale(${st.scale})`, filter: `blur(${st.blur}px)`, opacity: st.opacity, fontFamily: SANS, fontWeight: 900, fontSize: 174, color: C.red }}>换一张？</div>
      <Note y={1300}>生物特征，没法像密码一样重置。</Note>
    </AbsoluteFill>
  );
};

const DefenseCard: React.FC<{ n: string; title: string; sub: string; y: number; icon: string; tone: string }> = ({ n, title, sub, y, icon, tone }) => (
  <Sticker x={70} y={y} rotate={Number(n) % 2 ? -0.8 : 0.8} pad={20} style={{ width: 940, boxSizing: "border-box" }}>
    <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
      <div style={{ width: 120, height: 120, borderRadius: 16, background: tone, color: C.white, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: SANS, fontWeight: 900, fontSize: 58 }}>{icon}</div>
      <div>
        <div style={{ fontFamily: MONO, fontWeight: 900, fontSize: 28, color: C.slate }}>{n}</div>
        <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 50, color: C.ink }}>{title}</div>
        <div style={{ marginTop: 6, fontFamily: SANS, fontWeight: 700, fontSize: 29, color: C.slate }}>{sub}</div>
      </div>
    </div>
  </Sticker>
);

/* 6 三个动作 */
const BeatDefense: React.FC = () => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig();
  const t = f / fps;
  const f0 = BEATS.defense[0] * fps;
  const cards = [
    { n: "01", title: "开二次验证", sub: "支付、转账、购物账号，都加上一道锁", y: 320, icon: "锁", tone: C.green },
    { n: "02", title: "非必要不刷脸", sub: "有密码或其他方式，就别只交一张脸", y: 590, icon: "拒", tone: C.slate },
    { n: "03", title: "异常就处理", sub: "改密、冻结、查资料，必要时报警", y: 860, icon: "警", tone: C.red },
  ];
  return (
    <AbsoluteFill>
      <BeatTitle size={72}>现在，做这三件事</BeatTitle>
      {cards.map((c, i) => {
        const s = slam(f, f0 + 10 + i * 42, fps, 1.6, 1.45);
        return <div key={c.n} style={{ transform: `translateY(${Math.sin(t * 2.6 + i * 0.8) * 5}px) scale(${s.scale})`, filter: `blur(${s.blur}px)`, opacity: s.opacity }}><DefenseCard {...c} /></div>;
      })}
      <Note y={1240}>重要账号，别只靠一张脸。</Note>
    </AbsoluteFill>
  );
};

/* 7 转发 */
const BeatEnd: React.FC = () => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig(); const t = f / fps;
  const f0 = BEATS.end[0] * fps; const st = slam(f, f0 + 60, fps, 1.85, 1.7);
  const sh = shake(f, f0 + 75, 12);
  return (
    <AbsoluteFill style={{ transform: `translate(${sh.x}px, ${sh.y}px)` }}>
      <div style={{ position: "absolute", left: 70, right: 60, top: 180, fontFamily: SANS, fontWeight: 900, fontSize: 104, lineHeight: 1.1, color: C.ink }}>别让你的脸</div>
      <div style={{ position: "absolute", left: 70, right: 60, top: 320, fontFamily: SANS, fontWeight: 900, fontSize: 94, lineHeight: 1.15, color: C.red }}>单独替你做主</div>
      <Phone x={380} y={550} w={320} h={500}>
        <div style={{ height: "100%", background: "#E8F2EF", display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 50, boxSizing: "border-box" }}>
          <div style={{ width: 120, height: 140, border: `10px solid ${C.green}`, borderRadius: "60px 60px 20px 20px", position: "relative" }}>
            <div style={{ position: "absolute", left: 24, top: 55, width: 52, height: 58, background: C.green, borderRadius: 8 }} />
          </div>
          <div style={{ marginTop: 36, fontFamily: SANS, fontWeight: 900, fontSize: 38, color: C.ink }}>人脸 + 二次验证</div>
          <div style={{ marginTop: 30, padding: "14px 20px", background: C.green, color: C.white, borderRadius: 10, fontFamily: SANS, fontWeight: 900, fontSize: 32 }}>双保险</div>
        </div>
      </Phone>
      <div style={{ transform: `scale(${st.scale})`, filter: `blur(${st.blur}px)`, opacity: st.opacity }}><Stamp x={120} y={1160} text="转给只刷脸的人" size={62} /></div>
      <Note y={1320}>二次验证，不是麻烦，是底线。</Note>
    </AbsoluteFill>
  );
};

export type AiFaceTheftProps = { subs: [number, number, string][]; audioSrc?: string };
export const AiFaceTheft: React.FC<AiFaceTheftProps> = ({ subs, audioSrc }) => {
  const frame = useCurrentFrame(); const { fps } = useVideoConfig(); const t = frame / fps;
  let subText = ""; let subAlpha = 0;
  for (const [a, b, txt] of subs) {
    if (t >= a && t < b) { subText = txt; subAlpha = Math.min(clamp01((t - a) / 0.08), clamp01((b - t) / 0.08)); break; }
  }
  const beatStart = (Object.values(BEATS) as readonly (readonly [number, number])[]).find(([s, e]) => t >= s && t < s + 0.27 && s > 0)?.[0];
  return (
    <AbsoluteFill style={{ background: C.canvas, overflow: "hidden" }}>
      <Camera>
        <AbsoluteFill style={{ backgroundImage: `linear-gradient(${C.muted} 1px, transparent 1px),linear-gradient(90deg,${C.muted} 1px,transparent 1px)`, backgroundSize: "72px 72px", opacity: 0.42 }} />
        <AbsoluteFill style={{ background: "radial-gradient(circle at 50% 35%,rgba(255,255,255,0.86),rgba(232,237,240,0) 64%)" }} />
        {active(t, "hook") && <BeatHook />}
        {active(t, "case") && <BeatCase />}
        {active(t, "blink") && <BeatBlink />}
        {active(t, "camera") && <BeatCamera />}
        {active(t, "risk") && <BeatRisk />}
        {active(t, "defense") && <BeatDefense />}
        {active(t, "end") && <BeatEnd />}
      </Camera>
      <AbsoluteFill style={{ backgroundImage: `url(${staticFile(`ai-bubble/grain/${Math.floor(t * 12) % 8}.png`)})`, backgroundSize: "cover", opacity: 0.4, mixBlendMode: "multiply" }} />
      {beatStart !== undefined && (
        <div style={{ position: "absolute", top: -200, bottom: -200, left: 0, width: 180, background: C.red, opacity: 0.18, transform: `translateX(${lerp(-260, W + 200, easeInOutCubic(clamp01((t - beatStart) / 0.27)))}px) rotate(10deg)` }} />
      )}
      {subText && (
        <div style={{ position: "absolute", left: 60, right: 60, bottom: 300, display: "flex", justifyContent: "center" }}>
          <div style={{ background: C.white, border: `6px solid ${C.ink}`, borderRadius: 10, padding: "12px 24px", fontFamily: SANS, fontWeight: 800, fontSize: 42, lineHeight: 1.25, color: C.ink, opacity: subAlpha, transform: "rotate(-0.6deg)", boxShadow: "0 10px 24px rgba(23,40,56,0.16)", textAlign: "center" }}>{subText}</div>
        </div>
      )}
      <div style={{ position: "absolute", left: 60, right: 60, bottom: 150, height: 2, background: C.ink, opacity: 0.3 }} />
      <div style={{ position: "absolute", left: 60, bottom: 106, fontFamily: MONO, fontSize: 22, color: C.slate, letterSpacing: 4, opacity: 0.55 }}>FACE THEFT · 2026.11</div>
      <div style={{ position: "absolute", right: 60, bottom: 106, fontFamily: MONO, fontSize: 22, color: C.slate, opacity: 0.55 }}>{Math.round((t / BEATS.end[1]) * 100)}%</div>
      {audioSrc ? <Audio src={resolveAsset(audioSrc)} /> : null}
    </AbsoluteFill>
  );
};