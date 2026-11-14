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
 * StickerFilm —— 短片工厂的通用贴纸科普模板(mg-paperclip)。
 *
 * 普通人不写 TSX:在 projects/code-first/<项目>/film.json 里描述每一拍,
 * film.py build 会把实测节拍拍进 props,这里只负责照着画。
 *
 * beat.kind 一共六种(对应两条成片里验证过的画面模式):
 *   hook      开场:会动的脸 + 手机 + 两行大字 + 图章
 *   flow      三步流程 + 滚动大数字 + 图章
 *   compare   左右对照(实时 vs 预录) + 反转图章
 *   verdict   两张卡对照(能改 vs 不能改) + 巨大反问
 *   checklist 三件事清单,逐张飞入
 *   cta       收尾:两行金句 + 手机 + 转发图章
 */

const W = 1080;
const H = 1920;

/* 9:16 的版式预算(1080×1920):
   页眉 y<100;内容层整体下移 160(见 StickerFilm 里的 translate);
   字幕带 bottom:300 → 约 1490~1620;页脚分隔线 1770、页脚文字 1790。

   拍内小注(Note)必须停在这条线以上。之前它放在 1240~1320,两行时高度约 138,
   加上内容层的 +160 偏移正好落到 1480~1618,盖在字幕条上 —— 成片里两行字
   叠成一团,字幕完全读不了。这里把它的位置和行数一起钉死。 */
const NOTE_Y = 1130;
const SUB_TOP = 1470;

/* 一个中文/英文混排的字,大概多宽。用来在**不知道渲染器怎么折行**的情况下
   预先把字号压到框里 —— 之前 chip 框 250px 宽却用 64px 字号画 5 个字,
   "3万元芯片"直接糊在旁边的圆圈上。 */
const textWidth = (s: string, size: number) => {
  let w = 0;
  for (const ch of s) w += /[\u2E80-\u9FFF\uF900-\uFAFF\uFF00-\uFFEF]/.test(ch) ? size : size * 0.56;
  return w;
};

/* 把一段文字压进给定宽度:先缩字号,还超就截断加省略号。
   返回 [字号, 截断后的文字]。 */
const fitText = (text: string, maxWidth: number, maxSize: number, minSize = 18): [number, string] => {
  let size = maxSize;
  let out = text;
  while (size > minSize && textWidth(out, size) > maxWidth) {
    size -= 2;
    out = text;
  }
  while (out.length > 1 && textWidth(out, size) > maxWidth) out = out.slice(0, -1);
  return [size, out === text ? out : out + "…"];
};

type Beat = {
  id: string;
  kind: "hook" | "flow" | "compare" | "verdict" | "checklist" | "cta" | "quote";
  title?: string | string[];
  note?: string;
  stamp?: string;
  n?: string;
  face?: boolean;
  visual?: "face" | "robot" | "clock" | "chip" | "none";
  phone?: string;
  spec?: [string, string][];
  steps?: { label: string; icon?: string }[];
  big?: string;
  bigSub?: string;
  left?: { label?: string };
  right?: { label?: string };
  lines?: string[];
  statement?: string;
  items?: { n?: string; title: string; sub?: string; icon?: string; tone?: string }[];
};

type Film = {
  theme?: Record<string, string>;
  header?: string;
  footer?: { label?: string };
  beats: Beat[];
  timing: Record<string, [number, number]>;
  split: number;
  total: number;
};

const DEMO_FILM: Film = {
  header: "短片工厂 · 示例",
  footer: { label: "示例 · 用 --props 传入真实数据" },
  beats: [
    { id: "hook", kind: "hook", title: ["把最狠的一句话", "放在这里"], stamp: "占位示例", note: "改 film.json 后重跑 film build。" },
  ],
  timing: { hook: [0, 5] },
  split: 2,
  total: 5,
};

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
const lerp = (a: number, b: number, x: number) => a + (b - a) * x;
const easeOutCubic = (x: number) => 1 - Math.pow(1 - x, 3);
const easeInCubic = (x: number) => x * x * x;
const easeInOutCubic = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);

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

const SANS = `"Noto Sans SC","Microsoft YaHei","PingFang SC","SimHei",sans-serif`;
const MONO = `"Consolas","Courier New",monospace`;
const TONE: Record<string, string> = { green: "#14866D", red: "#F04438", slate: "#3C5264", yellow: "#D97706" };

const Sticker: React.FC<{
  x: number; y: number; children: React.ReactNode; rotate?: number; pad?: number;
  bg?: string; c: Record<string, string>; style?: React.CSSProperties;
}> = ({ x, y, children, rotate = 0, pad = 22, bg, c, style }) => (
  <div style={{
    position: "absolute", left: x, top: y, padding: pad, background: bg || c.paper,
    border: `11px solid ${c.white}`, outline: `2px solid rgba(23,40,56,0.5)`, outlineOffset: 11,
    borderRadius: 12, transform: `rotate(${rotate}deg)`,
    boxShadow: "0 16px 32px rgba(23,40,56,0.16)", ...style,
  }}>{children}</div>
);

const Stamp: React.FC<{ x: number; y: number; text: string; rotate?: number; color?: string; size?: number }> = ({
  x, y, text, rotate = -7, color = "#F04438", size = 54,
}) => {
  // 图章文字必须留在画面里。以前 nowrap + 固定字号,一句长图章直接跑出右边界。
  const [s2, t2] = fitText(text, 880, size, 24);
  return (
    <div style={{
      position: "absolute", left: x, top: y, transform: `rotate(${rotate}deg)`,
      border: `7px solid ${color}`, borderRadius: 10, padding: "10px 24px", color,
      fontFamily: SANS, fontWeight: 900, fontSize: s2, letterSpacing: 5,
      whiteSpace: "normal", maxWidth: 900, overflowWrap: "anywhere", background: "rgba(255,255,255,0.78)",
    }}>{t2}</div>
  );
};

const BeatTitle: React.FC<{ text: string | string[] | undefined; c: Record<string, string>; size?: number; top?: number }> = ({
  text, c, size = 66, top = 150,
}) => {
  if (!text) return null;
  const lines = Array.isArray(text) ? text : [text];
  return (
    <div style={{ position: "absolute", left: 70, right: 60, top, fontFamily: SANS, fontWeight: 900, fontSize: size, lineHeight: 1.14, color: c.ink, letterSpacing: 2 }}>
      {lines.map((l, i) => <div key={i}>{l}</div>)}
    </div>
  );
};

const Note: React.FC<{ text?: string; y?: number; c: Record<string, string> }> = ({ text, y = NOTE_Y, c }) =>
  text ? (
    <Sticker x={70} y={y} rotate={-0.8} pad={22} c={c} style={{ width: 940, boxSizing: "border-box" }}>
      <div style={{
        fontFamily: SANS, fontWeight: 800, fontSize: 36, lineHeight: 1.3, color: c.ink,
        // 最多两行:多一行就会顶到字幕条上
        display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden",
      }}>{text}</div>
    </Sticker>
  ) : null;

/** 程序化人脸贴纸:眼和头真的在动(第一帧就不是静图)。 */
const FaceCard: React.FC<{ x: number; y: number; scale?: number; rotate?: number; t: number; nod?: boolean; dim?: boolean; label?: string; c: Record<string, string> }> = ({
  x, y, scale = 1, rotate = 0, t, nod = true, dim = false, label, c,
}) => {
  const blink = t % 2.35 < 0.16;
  const nodAngle = nod ? Math.sin(t * 3.1) * 4.5 : 0;
  const eyeOpen = blink ? 2 : 24;
  return (
    <Sticker x={x} y={y} rotate={rotate} pad={18} c={c} style={{ opacity: dim ? 0.35 : 1 }}>
      <div style={{ transform: `scale(${scale})`, transformOrigin: "top left", width: 280, height: 340 }}>
        <svg width={280} height={340} viewBox="0 0 280 340">
          <rect x={4} y={4} width={272} height={332} rx={20} fill="#DCE7EC" />
          <circle cx={140} cy={156} r={112} fill="#C2D6DF" stroke={c.white} strokeWidth={8} strokeDasharray="12 9" />
          <g transform={`rotate(${nodAngle} 140 170)`}>
            <rect x={99} y={239} width={82} height={72} rx={24} fill={c.skinShade} />
            <path d="M55 333 Q65 266 140 266 Q215 266 225 333 Z" fill={c.ink} />
            <ellipse cx={140} cy={164} rx={83} ry={103} fill={c.skin} stroke={c.ink} strokeWidth={6} />
            <path d="M58 151 Q50 51 140 49 Q230 51 222 151 Q194 110 160 111 Q106 119 58 151" fill={c.ink} />
            <ellipse cx={60} cy={174} rx={13} ry={23} fill={c.skin} stroke={c.ink} strokeWidth={5} />
            <ellipse cx={220} cy={174} rx={13} ry={23} fill={c.skin} stroke={c.ink} strokeWidth={5} />
            <path d="M86 140 Q107 128 124 140" fill="none" stroke={c.ink} strokeWidth={7} strokeLinecap="round" />
            <path d="M156 140 Q177 128 194 140" fill="none" stroke={c.ink} strokeWidth={7} strokeLinecap="round" />
            <rect x={92} y={150} width={30} height={eyeOpen} rx={15} fill={c.white} stroke={c.ink} strokeWidth={5} />
            <rect x={158} y={150} width={30} height={eyeOpen} rx={15} fill={c.white} stroke={c.ink} strokeWidth={5} />
            {!blink && <><circle cx={107} cy={162} r={7} fill={c.ink} /><circle cx={173} cy={162} r={7} fill={c.ink} /></>}
            <path d="M139 166 L130 203 L148 203" fill="none" stroke={c.ink} strokeWidth={5} strokeLinecap="round" />
            <path d="M111 224 Q140 241 169 224" fill="none" stroke={c.ink} strokeWidth={7} strokeLinecap="round" />
          </g>
        </svg>
        {label && <div style={{ position: "absolute", left: 18, bottom: 16, fontFamily: MONO, fontWeight: 900, fontSize: 25, color: c.ink }}>{label}</div>}
      </div>
    </Sticker>
  );
};

/** 机器人头贴纸:讲机器人/AI 产品时的 hook 主视觉。 */
const RobotCard: React.FC<{ x: number; y: number; t: number; label?: string; c: Record<string, string> }> = ({
  x, y, t, label, c,
}) => {
  const eyeGlow = 0.6 + 0.4 * Math.sin(t * 2.2);
  const tilt = Math.sin(t * 1.1) * 3;
  return (
    <Sticker x={x} y={y} rotate={tilt * 0.4} pad={18} c={c}>
      <div style={{ width: 280, height: 340 }}>
        <svg width={280} height={340} viewBox="0 0 280 340">
          <rect x={4} y={4} width={272} height={332} rx={20} fill="#DDE8EC" />
          <line x1={140} y1={30} x2={140} y2={78} stroke={c.ink} strokeWidth={8} />
          <circle cx={140} cy={26} r={12} fill={c.red} stroke={c.ink} strokeWidth={5} />
          <rect x={62} y={78} width={156} height={136} rx={30} fill="#E9EFF2" stroke={c.ink} strokeWidth={7} />
          <rect x={84} y={118} width={46} height={26} rx={13} fill={c.ink} />
          <rect x={150} y={118} width={46} height={26} rx={13} fill={c.ink} />
          <circle cx={107} cy={131} r={9 + eyeGlow * 3} fill={c.yellow} />
          <circle cx={173} cy={131} r={9 + eyeGlow * 3} fill={c.yellow} />
          <rect x={104} y={170} width={72} height={16} rx={8} fill={c.ink} />
          <rect x={92} y={228} width={96} height={64} rx={14} fill="#CBD8DE" stroke={c.ink} strokeWidth={6} />
          <text x={140} y={272} textAnchor="middle" fontFamily={SANS} fontWeight={900} fontSize={40} fill={c.ink}>Max</text>
        </svg>
        {label && <div style={{ position: "absolute", left: 18, bottom: 16, fontFamily: MONO, fontWeight: 900, fontSize: 25, color: c.ink }}>{label}</div>}
      </div>
    </Sticker>
  );
};

const Phone: React.FC<{ x: number; y: number; w?: number; h?: number; rotate?: number; children: React.ReactNode; c: Record<string, string> }> = ({
  x, y, w = 320, h = 560, rotate = 0, children, c,
}) => (
  <div style={{ position: "absolute", left: x, top: y, width: w, height: h, border: `12px solid ${c.ink}`, borderRadius: 42, background: c.white, boxShadow: "0 22px 38px rgba(23,40,56,0.2)", transform: `rotate(${rotate}deg)`, overflow: "hidden" }}>
    <div style={{ position: "absolute", left: "35%", right: "35%", top: 12, height: 16, borderRadius: 10, background: c.ink }} />
    <div style={{ position: "absolute", inset: "42px 12px 18px" }}>{children}</div>
  </div>
);

const PhoneShop: React.FC<{ c: Record<string, string>; t: number }> = ({ c, t }) => (
  <div style={{ height: "100%", background: "#EDF3F5", padding: 28, boxSizing: "border-box" }}>
    <div style={{ fontFamily: MONO, fontWeight: 900, fontSize: 28, color: c.slate }}>FACE PAY</div>
    <div style={{ marginTop: 58, width: 160, height: 170, marginLeft: 38, background: c.yellow, border: `7px solid ${c.ink}`, borderRadius: 16, position: "relative", transform: `translateY(${Math.sin(t * 4) * 5}px)` }}>
      <div style={{ position: "absolute", left: 42, top: -38, width: 64, height: 55, border: `7px solid ${c.ink}`, borderBottom: 0, borderRadius: "40px 40px 0 0" }} />
      <div style={{ position: "absolute", left: 26, top: 55, fontFamily: SANS, fontWeight: 900, fontSize: 58, color: c.ink }}>单</div>
    </div>
    <div style={{ marginTop: 50, background: c.red, color: c.white, borderRadius: 12, textAlign: "center", padding: "18px 0", fontFamily: SANS, fontWeight: 900, fontSize: 36 }}>验证通过</div>
  </div>
);

const PhoneSpec: React.FC<{ c: Record<string, string>; rows?: [string, string][] }> = ({ c, rows }) => {
  const data = rows && rows.length ? rows.slice(0, 4) : [["代号", "—"], ["状态", "原型"]];
  return (
  <div style={{ height: "100%", background: "#EDF3F5", padding: 26, boxSizing: "border-box", display: "flex", flexDirection: "column", justifyContent: "center", gap: 22 }}>
    {(data as [string, string][]).map(([k, v]) => (
      <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", borderBottom: `3px solid ${c.muted}`, paddingBottom: 8 }}>
        <span style={{ fontFamily: SANS, fontWeight: 700, fontSize: 28, color: c.slate }}>{k}</span>
        <span style={{ fontFamily: SANS, fontWeight: 900, fontSize: 38, color: c.ink }}>{v}</span>
      </div>
    ))}
  </div>
  );
};

const PhoneLock: React.FC<{ c: Record<string, string> }> = ({ c }) => (
  <div style={{ height: "100%", background: "#E8F2EF", display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 50, boxSizing: "border-box" }}>
    <div style={{ width: 120, height: 140, border: `10px solid ${c.green}`, borderRadius: "60px 60px 20px 20px", position: "relative" }}>
      <div style={{ position: "absolute", left: 24, top: 55, width: 52, height: 58, background: c.green, borderRadius: 8 }} />
    </div>
    <div style={{ marginTop: 36, fontFamily: SANS, fontWeight: 900, fontSize: 38, color: c.ink }}>人脸 + 二次验证</div>
    <div style={{ marginTop: 30, padding: "14px 20px", background: c.green, color: c.white, borderRadius: 10, fontFamily: SANS, fontWeight: 900, fontSize: 32 }}>双保险</div>
  </div>
);

const PhoneShare: React.FC<{ c: Record<string, string> }> = ({ c }) => (
  <div style={{ height: "100%", background: "#EDF3F5", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 30, boxSizing: "border-box" }}>
    <div style={{ width: 190, height: 130, background: c.white, border: `7px solid ${c.ink}`, borderRadius: "26px 26px 26px 6px", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: SANS, fontWeight: 900, fontSize: 40, color: c.ink }}>这条短片</div>
    <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 46, color: c.red }}>转发 ↓</div>
    <div style={{ width: 190, height: 130, background: c.white, border: `7px solid ${c.ink}`, borderRadius: "6px 26px 26px 26px", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: SANS, fontWeight: 900, fontSize: 40, color: c.ink }}>家人 / 同事</div>
  </div>
);

const Arrow: React.FC<{ x: number; y: number; color: string; size?: number }> = ({ x, y, color, size = 66 }) => (
  <div style={{ position: "absolute", left: x, top: y, color, fontFamily: SANS, fontWeight: 900, fontSize: size }}>→</div>
);

type Item = NonNullable<Beat["items"]>[number];
const DEF_Y = [320, 590, 860];
const DefenseCard: React.FC<{ item: Item; y: number; c: Record<string, string> }> = ({ item, y, c }) => (
  <Sticker x={70} y={y} rotate={0.8} pad={20} c={c} style={{ width: 940, boxSizing: "border-box" }}>
    <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
      <div style={{ width: 120, height: 120, borderRadius: 16, background: TONE[item.tone || "slate"] || item.tone, color: c.white, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: SANS, fontWeight: 900, fontSize: 58 }}>{item.icon || "✓"}</div>
      <div>
        {item.n && <div style={{ fontFamily: MONO, fontWeight: 900, fontSize: 28, color: c.slate }}>{item.n}</div>}
        <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 50, color: c.ink }}>{item.title}</div>
        {item.sub && <div style={{ marginTop: 6, fontFamily: SANS, fontWeight: 700, fontSize: 29, color: c.slate }}>{item.sub}</div>}
      </div>
    </div>
  </Sticker>
);

/**
 * 内容驱动的画面主体:这一拍讲什么,就画什么。
 *
 * 之前这里写死了「人脸贴纸 + 手机 + 验证通过」,于是不管素材是什么,
 * 出来的片子都长得像同一条换脸盗号片。现在只从这一拍自己的字段
 * (大数字、规格表、关键词、步骤)取内容,取不到就老实地把字排好。
 */
const ContentHero: React.FC<{ b: Beat; t: number; c: Record<string, string> }> = ({ b, t, c }) => {
  const big = b.big || "";
  const rows = b.spec || [];
  const lines = (Array.isArray(b.title) ? b.title : [b.title || ""]).filter(Boolean);
  const keyword = lines[0] || "";
  const num = big.match(/[\d.]+/);
  const pulse = 1 + Math.sin(t * 2.1) * 0.012;
  // 关键词要塞进 250px 宽的方框(留 20px 内边距)
  const [chipSize, chipText] = fitText(keyword.slice(0, 6), 206, 64, 26);

  if (num) {
    // 有数字就把它做成主角:环形刻度 + 超大字
    const value = num[0];
    const R = 150;
    const C = 2 * Math.PI * R;
    return (
      <div style={{ position: "absolute", left: 70, top: 250 }}>
        <svg width="640" height="380" viewBox="0 0 640 380">
          <circle cx="200" cy="190" r={R} fill="none" stroke={c.muted} strokeWidth="10" opacity="0.5" />
          <circle cx="200" cy="190" r={R} fill="none" stroke={c.red} strokeWidth="14"
            strokeDasharray={`${C * 0.78} ${C}`} strokeLinecap="round"
            transform={`rotate(-90 200 190)`} />
          <text x="200" y="205" textAnchor="middle" fontFamily={SANS} fontWeight="900" fontSize="104" fill={c.ink}>{value}</text>
          {b.bigSub && <text x="200" y="268" textAnchor="middle" fontFamily={SANS} fontWeight="800" fontSize="34" fill={c.slate}>{b.bigSub}</text>}
          <g transform={`translate(360 60) scale(${pulse})`}>
            <rect x="0" y="0" width="250" height="250" rx="24" fill={c.paper} stroke={c.ink} strokeWidth="6" />
            {/* 关键词要装得进这个方框。之前固定 64px 画 5 个字,字比框宽,
                "3万元芯片"直接糊在左边的圆圈上。 */}
            <text x="125" y="112" textAnchor="middle" fontFamily={SANS} fontWeight="900" fontSize={chipSize} fill={c.red}>{chipText}</text>
            <text x="125" y="176" textAnchor="middle" fontFamily={MONO} fontWeight="700" fontSize="30" fill={c.slate}>{String(lines[0]?.length || 0).padStart(2, "0")} 字</text>
          </g>
        </svg>
      </div>
    );
  }

  if (rows.length) {
    // 有规格就排成规格表:键值两列,来自素材里的真实参数
    return (
      <Sticker x={70} y={250} rotate={-1.5} pad={26} c={c}>
        <div style={{ width: 560, display: "flex", flexDirection: "column", gap: 18 }}>
          {rows.slice(0, 4).map((r, i) => (
            <div key={i} style={{ display: "flex", alignItems: "baseline", gap: 18, borderBottom: `4px solid ${c.muted}33`, paddingBottom: 14 }}>
              <span style={{ fontFamily: MONO, fontWeight: 800, fontSize: 30, color: c.slate, minWidth: 150 }}>{r[0]}</span>
              <span style={{ fontFamily: SANS, fontWeight: 900, fontSize: 52, color: i === 0 ? c.red : c.ink }}>{r[1]}</span>
            </div>
          ))}
        </div>
      </Sticker>
    );
  }

  // 没有数字也没有规格:把关键词做成一张会呼吸的大标签,而不是画一个假的人物
  return (
    <div style={{ position: "absolute", left: 70, top: 260, transform: `scale(${pulse})`, transformOrigin: "left top" }}>
      <Sticker x={0} y={0} rotate={-2} pad={30} c={c}>
        <div style={{ width: 560 }}>
          <div style={{ fontFamily: MONO, fontWeight: 800, fontSize: 26, letterSpacing: 4, color: c.slate }}>{b.n || "KEY POINT"}</div>
          <div style={{ marginTop: 18, fontFamily: SANS, fontWeight: 900, fontSize: 74, lineHeight: 1.16, color: c.ink }}>
            {keyword.slice(0, 14)}
          </div>
          {b.bigSub && <div style={{ marginTop: 14, fontFamily: SANS, fontWeight: 800, fontSize: 34, color: c.red }}>{b.bigSub}</div>}
        </div>
      </Sticker>
    </div>
  );
};

const BeatView: React.FC<{ b: Beat; c: Record<string, string>; f0: number; dur: number; split: number }> = ({ b, c, f0, dur, split }) => {
  const f = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const t = f / fps;
  const p = clamp01((t - f0 / fps) / Math.max(0.001, dur));
  const wrap = { transform: "translate(0px, 0px)" };
  const sh = shake(f, f0, 14);
  const s0 = slam(f, f0, fps);
  void durationInFrames;

  if (b.kind === "hook") {
    const s2 = slam(f, f0 + split * fps, fps, 1.85, 1.7);
    const ring = impactRing(f, f0 + split * fps);
    return (
      <AbsoluteFill style={{ ...wrap, transform: `translate(${sh.x}px, ${sh.y}px)` }}>
        {/* 画面来自这一拍的内容本身:大数字、规格、关键词,而不是固定的人物贴纸。
            固定贴纸会让任何素材都长成同一条片子。 */}
        <ContentHero b={b} t={t} c={c} />
        <div style={{ position: "absolute", left: 70, right: 60, top: 780, transform: `scale(${s0.scale})`, filter: `blur(${s0.blur}px)`, opacity: s0.opacity, fontFamily: SANS, fontWeight: 900, fontSize: 108, lineHeight: 1.05, color: c.ink, overflowWrap: "anywhere" }}>
          {(Array.isArray(b.title) ? b.title : [b.title || ""]).map((l, i) => (
            <div key={i} style={i === 0 ? undefined : { color: c.red, fontSize: 90 }}>{l}</div>
          ))}
        </div>
        {b.stamp && <div style={{ transform: `scale(${s2.scale})`, filter: `blur(${s2.blur}px)`, opacity: s2.opacity }}><Stamp x={90} y={1020} text={b.stamp} color={c.red} /></div>}
        {ring && <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}><circle cx={540} cy={640} r={ring.r} fill="none" stroke={c.red} strokeWidth={9} opacity={ring.alpha * 0.45} /></svg>}
        <Note text={b.note} c={c} />
      </AbsoluteFill>
    );
  }

  if (b.kind === "flow") {
    const steps = b.steps || [];
    const xs = [60, 400, 740];
    const bgs = ["#DCE7EC", "#FFE0D8", "#FFF0C8"];
    const n = b.big && /\d/.test(b.big) ? Math.round(lerp(0, parseInt((b.big.match(/\d+/) || ["0"])[0], 10), easeOutCubic(clamp01((f - f0 - 8) / 45)))) : null;
    const bigText = n === null ? (b.big || "") : (b.big || "").replace(/\d+/, String(n));
    const st = slam(f, f0 + 2.0 * fps, fps, 1.85, 1.7);
    return (
      <AbsoluteFill style={{ ...wrap, transform: `translate(${sh.x}px, ${sh.y}px)` }}>
        <BeatTitle text={b.title} c={c} />
        {steps.slice(0, 3).map((s, i) => (
          <Sticker key={i} x={xs[i]} y={320 + (i % 2) * 20} rotate={i === 1 ? 2 : -2} pad={18} c={c}>
            <div style={{ width: 230, height: 250, background: bgs[i], borderRadius: 12, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", transform: `translateY(${Math.sin(t * 3 + i) * 5}px)` }}>
              <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 96, color: i === 1 ? c.red : c.ink }}>{s.icon || String(i + 1)}</div>
              <div style={{ marginTop: 20, fontFamily: SANS, fontWeight: 900, fontSize: 30, color: c.ink }}>{s.label}</div>
            </div>
          </Sticker>
        ))}
        {steps.length > 1 && <><Arrow x={330} y={400} color={c.red} /><Arrow x={670} y={400} color={c.red} /></>}
        <div style={{ position: "absolute", left: 0, right: 0, top: 760, textAlign: "center", fontFamily: SANS, fontWeight: 900, color: c.red, fontSize: 170, lineHeight: 1 }}>{bigText}</div>
        {b.bigSub && <div style={{ position: "absolute", left: 0, right: 0, top: 960, textAlign: "center", fontFamily: SANS, fontWeight: 900, color: c.ink, fontSize: 58 }}>{b.bigSub}</div>}
        {b.stamp && <div style={{ transform: `scale(${st.scale})`, filter: `blur(${st.blur}px)`, opacity: st.opacity }}><Stamp x={90} y={1030} text={b.stamp} color={c.red} /></div>}
        <Note text={b.note} c={c} />
      </AbsoluteFill>
    );
  }

  if (b.kind === "compare") {
    const st = slam(f, f0 + 2.233 * fps, fps, 1.85, 1.7);
    const swap = easeInOutCubic(clamp01((p - 0.22) / 0.25));
    // 对照的两边就是这一拍给的两个说法,不需要一张固定的人物贴纸
    return (
      <AbsoluteFill style={{ ...wrap, transform: `translate(${sh.x}px, ${sh.y}px)` }}>
        <BeatTitle text={b.title} c={c} size={64} />
        <Sticker x={70} y={330} rotate={-2} pad={24} c={c}>
          <div style={{ width: 330, minHeight: 250, display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center" }}>
            <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 46, lineHeight: 1.25, color: c.ink }}>
              {b.left?.label || "说法一"}
            </div>
          </div>
        </Sticker>
        <div style={{ position: "absolute", left: 650, right: 60, top: 285, fontFamily: MONO, fontWeight: 900, fontSize: 26, lineHeight: 1.25, color: c.red, overflowWrap: "anywhere" }}>{b.right?.label || "说法二"}</div>
        <Sticker x={650} y={350} rotate={2} pad={18} c={c} style={{ transform: `translate(${-swap * 40}px, ${-swap * 20}px) rotate(2deg)` }}>
          <div style={{ width: 252, height: 306, background: c.ink, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 44, lineHeight: 1.2, color: c.white, textAlign: "center", padding: "0 24px" }}>
              {b.right?.label || "说法二"}
            </div>
          </div>
        </Sticker>
        <Arrow x={480} y={470} color={c.red} size={90} />
        {b.stamp && <div style={{ transform: `scale(${st.scale})`, filter: `blur(${st.blur}px)`, opacity: st.opacity }}><Stamp x={280} y={760} text={b.stamp} color={c.red} size={62} /></div>}
        {/* 两行大字:之前没有宽度约束,一句话直接冲出画面右边。
            现在放进一个封顶的盒子(870~1120),超出的部分裁掉,绝不压到下面的 note。 */}
        <div style={{ position: "absolute", left: 70, right: 60, top: 870, height: 250, display: "flex", flexDirection: "column", gap: 8, overflow: "hidden" }}>
          {(b.lines || []).slice(0, 2).map((l, i) => (
            <div key={i} style={{ fontFamily: SANS, fontWeight: 900, fontSize: i ? 72 : 54, lineHeight: 1.18, color: i ? c.red : c.ink, overflowWrap: "anywhere" }}>{l}</div>
          ))}
        </div>
        <Note text={b.note} c={c} />
      </AbsoluteFill>
    );
  }

  if (b.kind === "verdict") {
    const st = slam(f, f0 + 1.333 * fps, fps, 1.9, 1.75);
    return (
      <AbsoluteFill style={{ ...wrap, transform: `translate(${sh.x}px, ${sh.y}px)` }}>
        <Sticker x={70} y={230} rotate={-2} pad={26} c={c}>
          <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: 46, color: c.ink }}>{b.left?.label || "一种说法"}</div>
          <div style={{ marginTop: 24, width: 360, padding: "22px 0", border: `5px dashed ${c.slate}`, borderRadius: 12, textAlign: "center", fontFamily: MONO, fontSize: 42, color: c.slate }}>
            {b.bigSub || b.right?.label || "另一种说法"}
          </div>
          <div style={{ marginTop: 24, background: c.green, color: c.white, borderRadius: 12, padding: "18px 0", textAlign: "center", fontFamily: SANS, fontWeight: 900, fontSize: 36 }}>
            {b.lines?.[0] || b.stamp || "结论"}
          </div>
        </Sticker>
        {b.stamp && <Stamp x={510} y={350} text={b.stamp} color={c.green} size={62} />}
        {b.statement && <div style={{ position: "absolute", left: 70, right: 60, top: 770, textAlign: "center", fontFamily: SANS, fontWeight: 900, fontSize: 66, color: c.ink, overflowWrap: "anywhere" }}>{b.statement}</div>}
        {b.big && <div style={{ position: "absolute", left: 70, right: 60, top: 880, textAlign: "center", transform: `scale(${st.scale})`, filter: `blur(${st.blur}px)`, opacity: st.opacity, fontFamily: SANS, fontWeight: 900, fontSize: 150, color: c.red, overflowWrap: "anywhere" }}>{b.big}</div>}
        <Note text={b.note} c={c} />
      </AbsoluteFill>
    );
  }

  if (b.kind === "checklist") {
    const items = b.items || [];
    return (
      <AbsoluteFill style={wrap}>
        <BeatTitle text={b.title} c={c} size={72} />
        {items.slice(0, 3).map((it, i) => {
          const s = slam(f, f0 + (0.833 + i * 1.4) * fps, fps, 1.6, 1.45);
          return <div key={i} style={{ transform: `translateY(${Math.sin(t * 2.6 + i * 0.8) * 5}px) scale(${s.scale})`, filter: `blur(${s.blur}px)`, opacity: s.opacity }}><DefenseCard item={it} y={DEF_Y[i]} c={c} /></div>;
        })}
        <Note text={b.note} c={c} />
      </AbsoluteFill>
    );
  }

  // quote:纯文字排版。没有模型理解内容时,不假装画懂了 —— 只把这一句好好排出来。
  if (b.kind === "quote") {
    const lines = Array.isArray(b.title) ? b.title : [b.title || ""];
    const s = slam(f, f0 + 2, fps, 1.35, 1.25);
    // 按标点自然断行,不做字数硬切
    const body: string[] = b.lines && b.lines.length ? b.lines : lines;
    return (
      <AbsoluteFill style={wrap}>
        <Sticker x={70} y={250} rotate={-1} pad={0} c={c} style={{ width: 940, boxSizing: "border-box" }}>
          <div style={{ padding: "54px 46px 46px" }}>
            <div style={{ fontFamily: MONO, fontSize: 24, letterSpacing: 6, color: c.slate, marginBottom: 26 }}>
              {b.n || ""}
            </div>
            <div style={{ transform: `scale(${s.scale})`, filter: `blur(${s.blur}px)`, opacity: s.opacity, transformOrigin: "left top" }}>
              {body.map((l, i) => (
                <div key={i} style={{
                  fontFamily: SANS, fontWeight: 900, fontSize: body.length > 2 ? 58 : 68,
                  lineHeight: 1.42, color: c.ink, letterSpacing: 1, marginBottom: 16,
                }}>{l}</div>
              ))}
            </div>
          </div>
        </Sticker>
        {b.stamp && (
          <div style={{ position: "absolute", left: 80, right: 80, top: 1040, textAlign: "center" }}>
            <span style={{ fontFamily: MONO, fontSize: 26, letterSpacing: 8, color: c.slate, opacity: 0.8 }}>{b.stamp}</span>
          </div>
        )}
        <Note text={b.note} c={c} />
      </AbsoluteFill>
    );
  }

  // cta / 兜底:收尾也要讲这一拍自己的内容,不是固定一部手机
  const st = slam(f, f0 + 2.5 * fps, fps, 1.85, 1.7);
  const lines = Array.isArray(b.title) ? b.title : [b.title || ""];
  return (
    <AbsoluteFill style={{ ...wrap, transform: `translate(${sh.x}px, ${sh.y}px)` }}>
      {lines.map((l, i) => (
        <div key={i} style={{ position: "absolute", left: 70, right: 60, top: 180 + i * 140, fontFamily: SANS, fontWeight: 900, fontSize: 100, lineHeight: 1.1, color: i ? c.red : c.ink }}>{l}</div>
      ))}
      <Sticker x={150} y={560} rotate={-3} pad={26} c={c}>
        <div style={{ width: 780, minHeight: 220, display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <div style={{ fontFamily: MONO, fontWeight: 800, fontSize: 28, letterSpacing: 4, color: c.slate }}>{b.n || "TAKEAWAY"}</div>
          <div style={{ marginTop: 16, fontFamily: SANS, fontWeight: 900, fontSize: 62, lineHeight: 1.2, color: c.ink }}>
            {b.bigSub || b.stamp || (b.lines || [])[0] || "这一条的重点"}
          </div>
        </div>
      </Sticker>
      {b.stamp && <div style={{ transform: `scale(${st.scale})`, filter: `blur(${st.blur}px)`, opacity: st.opacity }}><Stamp x={120} y={1030} text={b.stamp} color={c.red} size={62} /></div>}
      <Note text={b.note} c={c} />
    </AbsoluteFill>
  );
};

export type StickerFilmProps = {
  subs: [number, number, string][];
  audioSrc?: string;
  film?: Film | null;
  // 由 Root 传入;贴纸模板不用它,但同一个 Composition 槽位要兼容 StyleFilm
  styleId?: string;
};


/**
 * 宽屏(16:9)与方形(1:1)不能靠缩放竖版 —— 两侧会空出大片,直接判死场。
 * 这里给这两种画幅单独排版:左边文字,右边视觉。
 */
const WideBeat: React.FC<{
  b: Beat; c: Record<string, string>; f0: number; wide: boolean;
}> = ({ b, c, f0, wide }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = f / fps;
  const st = slam(f, f0, fps, 1.5, 1.35);
  const sh = shake(f, f0, 12);
  const title = Array.isArray(b.title) ? b.title : [b.title || ""];
  const pad = wide ? 80 : 44;
  const gap = wide ? 56 : 26;
  const leftW = wide ? 1920 * 0.52 - pad - gap / 2 : 1080 - pad * 2;

  const visual = (() => {
    if (b.kind === "flow" && b.steps?.length) {
      return (
        <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
          {b.steps.slice(0, 3).map((stp, i) => (
            <div key={i} style={{
              width: (wide ? 210 : 128), height: (wide ? 210 : 128), borderRadius: 18,
              background: ["#DCE7EC", "#FFE0D8", "#FFF0C8"][i % 3],
              border: `4px solid ${c.ink}`, display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center", padding: 10, textAlign: "center",
              // 卡片持续轻微浮动,画面不会静成 PPT
              transform: `translateY(${Math.sin(t * 2.4 + i * 0.9) * (wide ? 9 : 6)}px) scale(${1 + Math.sin(t * 1.7 + i) * 0.015})`,
            }}>
              <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: (wide ? 62 : 38), color: i === 1 ? c.red : c.ink }}>
                {stp.icon || String(i + 1)}
              </div>
              <div style={{ marginTop: 8, fontFamily: SANS, fontWeight: 900, fontSize: (wide ? 26 : 17), color: c.ink }}>
                {stp.label}
              </div>
            </div>
          ))}
        </div>
      );
    }
    if (b.kind === "checklist" && b.items?.length) {
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {b.items.slice(0, 3).map((it, i) => (
            <div key={i} style={{ display: "flex", gap: 16, alignItems: "center",
              transform: `translateX(${Math.sin(t * 2.1 + i * 0.8) * (wide ? 10 : 6)}px)`,
              padding: (wide ? 14 : 8), borderRadius: 12,
              background: "rgba(255,255,255,.6)", border: `3px solid ${c.ink}` }}>
              <div style={{ width: (wide ? 74 : 50), height: (wide ? 74 : 50), borderRadius: 12,
                background: [c.green, c.slate, c.red][i % 3], color: c.white,
                display: "flex", alignItems: "center", justifyContent: "center",
                fontFamily: SANS, fontWeight: 900, fontSize: (wide ? 36 : 24) }}>
                {it.icon || String(i + 1)}
              </div>
              <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: (wide ? 40 : 26), color: c.ink }}>
                {it.title}
              </div>
            </div>
          ))}
        </div>
      );
    }
    if (b.kind === "compare") {
      return (
        <div style={{ display: "flex", gap: 18, alignItems: "center" }}>
          {[{ l: b.left?.label || "之前", t: c.slate }, { l: b.right?.label || "之后", t: c.red }].map((x, i) => (
            <div key={i} style={{ flex: 1, padding: (wide ? 30 : 20), background: c.white,
              border: `4px solid ${c.ink}`, borderRadius: 16, textAlign: "center",
              transform: `translateY(${Math.sin(t * 2.0 + i * 1.2) * (wide ? 10 : 7)}px)`,
              boxShadow: "0 10px 22px rgba(23,40,56,.14)" }}>
              <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: (wide ? 46 : 28), color: x.t }}>
                {x.l}
              </div>
            </div>
          ))}
        </div>
      );
    }
    if (b.kind === "quote" || !b.face) {
      // 不能返回空:横屏下空着的视觉区会让整拍静成死场。
      // 用一句话大字卡填住,既好看又不会空。
      const q = (b.lines && b.lines[0]) || title[0] || "";
      return (
        <div style={{
          flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
          background: c.paper, border: `5px solid ${c.ink}`, borderRadius: 18,
          padding: wide ? 40 : 26, minHeight: wide ? 260 : 200, textAlign: "center",
          boxShadow: "0 14px 30px rgba(23,40,56,.16)",
        }}>
          <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: wide ? 46 : 30,
            lineHeight: 1.35, color: c.ink }}>{q}</div>
        </div>
      );
    }
    // 默认:这一拍自己的关键词 + 规格,而不是一张固定的人脸
    return (
      <div style={{ display: "flex", gap: 20, alignItems: "center" }}>
        {b.spec?.length ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {b.spec.slice(0, 3).map((r, i) => (
              <div key={i} style={{ display: "flex", gap: 14, alignItems: "baseline" }}>
                <span style={{ fontFamily: MONO, fontWeight: 800, fontSize: 26, color: c.slate }}>{r[0]}</span>
                <span style={{ fontFamily: SANS, fontWeight: 900, fontSize: 46, color: i === 0 ? c.red : c.ink }}>{r[1]}</span>
              </div>
            ))}
          </div>
        ) : (
          <div style={{
            width: (wide ? 300 : 220), height: (wide ? 300 : 220), borderRadius: 28,
            background: c.paper, border: `6px solid ${c.ink}`,
            display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center",
            padding: 20, fontFamily: SANS, fontWeight: 900, fontSize: (wide ? 54 : 38), lineHeight: 1.2, color: c.ink,
          }}>
            {(Array.isArray(b.title) ? b.title[0] : b.title || "").slice(0, 12)}
          </div>
        )}
      </div>
    );
  })();

  const textCol = (
    <div style={{ width: wide ? leftW : "100%" }}>
      <div style={{ transform: `scale(${st.scale})`, filter: `blur(${st.blur}px)`, opacity: st.opacity, transformOrigin: "left top" }}>
        {title.map((l, i) => (
          <div key={i} style={{
            fontFamily: SANS, fontWeight: 900, fontSize: wide ? 92 : 58,
            lineHeight: 1.16, color: i ? c.red : c.ink, letterSpacing: 1, marginBottom: 10,
          }}>{l}</div>
        ))}
      </div>
      {b.big && (
        <div style={{ fontFamily: SANS, fontWeight: 900, fontSize: wide ? 120 : 62, color: c.red, marginTop: 14 }}>
          {b.big}
        </div>
      )}
      {b.bigSub && (
        <div style={{ fontFamily: SANS, fontWeight: 700, fontSize: wide ? 38 : 26, color: c.slate, marginTop: 6 }}>
          {b.bigSub}
        </div>
      )}
      {(b.lines || []).length > 0 && (
        <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 8 }}>
          {b.lines!.map((l, i) => (
            <div key={i} style={{ fontFamily: SANS, fontWeight: 900, fontSize: wide ? 44 : 28, color: i ? c.red : c.ink }}>
              {l}
            </div>
          ))}
        </div>
      )}
      {b.stamp && (
        <div style={{ marginTop: 20, display: "inline-block", border: `4px solid ${c.red}`, color: c.red,
          padding: "8px 16px", borderRadius: 8, fontFamily: SANS, fontWeight: 900,
          fontSize: wide ? 38 : 26, transform: "rotate(-5deg)", background: "rgba(255,255,255,.8)" }}>
          {b.stamp}
        </div>
      )}
    </div>
  );

  return (
    <AbsoluteFill style={{ padding: pad, boxSizing: "border-box", transform: `translate(${sh.x}px, ${sh.y}px)` }}>
      <div style={{
        display: "flex", gap, alignItems: wide ? "center" : "stretch", height: "100%",
        flexDirection: wide ? "row" : "column", justifyContent: wide ? "flex-start" : "center",
      }}>
        {textCol}
        {visual && <div style={{ flex: 1, display: "flex", justifyContent: wide ? "center" : "center",
          alignItems: "center" }}>{visual}</div>}
      </div>
    </AbsoluteFill>
  );
};

export const StickerFilm: React.FC<StickerFilmProps> = ({ subs, audioSrc, film }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const data: Film = film && film.beats?.length ? film : DEMO_FILM;
  const { width: cw, height: ch } = useVideoConfig();
  const c = { canvas: "#E8EDF0", paper: "#FAF4E8", white: "#FFFFFF", ink: "#172838", slate: "#3C5264", muted: "#AFC0CB", red: "#F04438", green: "#14866D", yellow: "#F6C453", skin: "#FFD2AE", skinShade: "#E8A77D", ...(data.theme || {}) };
  const timing = data.timing || {};
  const beatAt = (id: string): [number, number] => timing[id] || [0, data.total || 5];
  const order = data.beats.map((b) => b.id);
  const t0 = t;
  let subText = "";
  let subAlpha = 0;
  for (const [a, b, txt] of subs || []) {
    if (t0 >= a && t0 < b) { subText = txt; subAlpha = Math.min(clamp01((t0 - a) / 0.08), clamp01((b - t0) / 0.08)); break; }
  }
  const sweep = order.map((id) => beatAt(id)[0]).find((s, i) => i > 0 && t0 >= s && t0 < s + 0.27);
  return (
    <AbsoluteFill style={{ background: c.canvas, overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: "scale(1.02)" }}>
        <AbsoluteFill style={{ backgroundImage: `linear-gradient(${c.muted} 1px, transparent 1px),linear-gradient(90deg,${c.muted} 1px,transparent 1px)`, backgroundSize: "72px 72px", opacity: 0.42 }} />
        <AbsoluteFill style={{ background: "radial-gradient(circle at 50% 35%,rgba(255,255,255,0.86),rgba(232,237,240,0) 64%)" }} />
        {/* 手持纸面浮动:整个内容层做慢漂移 + 极缓推近。贴纸落定后画面也不会静成 PPT(死场)。 */}
        {/* 内容层整体让出页眉 150px:之前主标题从 y=150 起,
            和 y=90 的页眉叠成两行乱码。下移后标题、图形、字幕各有位置。 */}
        <AbsoluteFill style={{ transform: `translate(${Math.sin(t * 1.7) * 5}px, ${160 + Math.cos(t * 1.3) * 5}px) scale(${1.02 + Math.sin(t * 0.45) * 0.012})` }}>
          {data.beats.map((b) => {
            const [s, e] = beatAt(b.id);
            if (!(t0 >= s && t0 < e)) return null;
            // 9:16 用竖版原布局;16:9 / 1:1 走专门的宽版排版,
            // 否则两侧空一大片,会被判死场。
            if (cw === 1080 && ch === 1920) {
              return <BeatView key={b.id} b={b} c={c} f0={s * fps} dur={e - s} split={data.split} />;
            }
            return <WideBeat key={b.id} b={b} c={c} f0={s * fps} wide={cw > ch} />;
          })}
        </AbsoluteFill>
      </AbsoluteFill>
      <AbsoluteFill style={{ backgroundImage: `url(${staticFile(`ai-bubble/grain/${Math.floor(t * 12) % 8}.png`)})`, backgroundSize: "cover", opacity: 0.4, mixBlendMode: "multiply" }} />
      {sweep !== undefined && (
        <div style={{ position: "absolute", top: -200, bottom: -200, left: 0, width: 180, background: c.red, opacity: 0.18, transform: `translateX(${lerp(-260, W + 200, easeInOutCubic(clamp01((t0 - sweep) / 0.27)))}px) rotate(10deg)` }} />
      )}
      {data.header && <div style={{ position: "absolute", left: 70, top: 58, right: 70, fontFamily: MONO, fontSize: 26, letterSpacing: 4, color: c.slate, zIndex: 3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{data.header}</div>}
      {/* 纯排版模式下正片就是文字,底下再叠一条字幕只会重复同一句 */}
      {subText && !(data as Film & { layout?: string }).layout && (
        <div style={{ position: "absolute", left: 60, right: 60, bottom: 300, display: "flex", justifyContent: "center", zIndex: 4 }}>
          <div style={{ background: c.white, border: `6px solid ${c.ink}`, borderRadius: 10, padding: "12px 24px", fontFamily: SANS, fontWeight: 800, fontSize: 42, lineHeight: 1.25, color: c.ink, opacity: subAlpha, transform: "rotate(-0.6deg)", boxShadow: "0 10px 24px rgba(23,40,56,0.16)", textAlign: "center" }}>{subText}</div>
        </div>
      )}
      <div style={{ position: "absolute", left: 60, right: 60, bottom: 150, height: 2, background: c.ink, opacity: 0.3, zIndex: 4 }} />
      <div style={{ position: "absolute", left: 60, bottom: 106, fontFamily: MONO, fontSize: 22, color: c.slate, letterSpacing: 4, opacity: 0.55, zIndex: 4 }}>{data.footer?.label || ""}</div>
      <div style={{ position: "absolute", right: 60, bottom: 106, fontFamily: MONO, fontSize: 22, color: c.slate, opacity: 0.55, zIndex: 4 }}>{Math.round((t0 / (data.total || 5)) * 100)}%</div>
      {audioSrc ? <Audio src={resolveAsset(audioSrc)} /> : null}
    </AbsoluteFill>
  );
};