import { AbsoluteFill, Img, useCurrentFrame, useVideoConfig } from "remotion";
import { resolveAsset } from "../lib/resolveAsset";

/**
 * 常驻"钩子物"(hook object)。
 *
 * 短视频观众是来看热闹的,不是来听道理的。前 3 秒里如果只有静止文字,
 * 手指就划走了。这个组件把一只不该出现在画面里的会动的小东西,固定放在
 * 竖屏中下部的空白带里,持续跳/摇/绕,替内容"拦人"。
 *
 * 规格见 .agents/skills/short-video-attention-hook/SKILL.md:
 * 面积 ≥ 短边 18%,位置 y 55–75%,不压底部字幕带,每 3–5 秒一个动作循环,
 * 每次 cut 切换做一次"跳+旋"作为视觉重音。
 */
export type HookMotion = "bounce" | "swing" | "orbit";

export interface HookSpriteProps {
  /** 自定义精灵图(需要透明底 PNG)。留空则用内置矢量小黄鸭。 */
  src?: string;
  /** 相对画面短边的比例,默认 0.22(≥0.18 才够抢眼) */
  size?: number;
  /** 画面宽度比例 0–1,默认 0.72 */
  x?: number;
  /** 画面高度比例 0–1,默认 0.66(中下部) */
  y?: number;
  motion?: HookMotion;
  /** 动作循环周期(秒),默认 4.5 */
  beatEverySeconds?: number;
  /** 场景切换时间点(秒),在这些时刻做一次额外弹跳 */
  beats?: number[];
}

/**
 * 内置矢量小黄鸭。
 *
 * 为什么内置:AI 生成的"洋红底小物"抠图极不可靠(渐变底 + 软阴影,
 * chroma key 要么全抠掉要么留下粉方块)。矢量图没有这个问题,任意尺寸都清晰,
 * 而且"廉价贴纸感"正好是短视频钩子需要的调性。
 */
const BuiltinDuck: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 100 100" fill="none">
    {/* 身体 */}
    <ellipse cx="46" cy="66" rx="30" ry="21" fill="#FFD23F" />
    {/* 尾巴 */}
    <path d="M18 60c-6-4-10-12-8-16 5 3 9 7 11 12z" fill="#FFC107" />
    {/* 头 */}
    <circle cx="64" cy="38" r="19" fill="#FFD23F" />
    {/* 翅膀 */}
    <path d="M34 63c8-6 18-6 24 1-7 6-18 6-24-1z" fill="#FFC107" opacity="0.9" />
    {/* 喙 */}
    <path d="M81 40c6 1 10 4 10 7 0 3-5 5-11 4z" fill="#FF8A00" />
    {/* 眼睛 */}
    <circle cx="70" cy="33" r="3.2" fill="#1F2937" />
    <circle cx="71" cy="32" r="1" fill="#FFFFFF" />
    {/* 腮红 */}
    <circle cx="60" cy="45" r="3.6" fill="#FF8FA3" opacity="0.6" />
  </svg>
);

export const HookSprite: React.FC<HookSpriteProps> = ({
  src,
  size = 0.22,
  x = 0.72,
  y = 0.66,
  motion = "bounce",
  beatEverySeconds = 4.5,
  beats = [],
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();

  const px = Math.round(Math.min(width, height) * size);
  const centerX = width * x;
  const centerY = height * y;
  const t = frame / fps;

  let translateX = 0;
  let translateY = 0;
  let rotate = 0;
  let scale = 1;

  const cycle = Math.max(0.8, beatEverySeconds);
  const phase = (t % cycle) / cycle;

  if (motion === "bounce") {
    // 一次干净的起跳 + 落地挤压
    const lift = Math.sin(Math.PI * Math.min(1, phase / 0.62));
    translateY = -lift * px * 0.55;
    scale = 1 + 0.07 * lift;
    rotate = Math.sin(t * 5.2) * 7;
  } else if (motion === "swing") {
    rotate = Math.sin(t * 2.6) * 17;
    translateY = -Math.abs(Math.sin(t * 2.6)) * px * 0.06;
  } else {
    translateX = Math.cos(t * 1.9) * px * 0.38;
    translateY = Math.sin(t * 1.9) * px * 0.2;
    rotate = t * 55;
  }

  // 场景切换的视觉重音:切点后 0.45 秒内多弹一下
  let beatBoost = 0;
  for (const beat of beats) {
    const delta = t - beat;
    if (delta >= 0 && delta <= 0.45) {
      const p = 1 - delta / 0.45;
      beatBoost = Math.max(beatBoost, p);
    }
  }
  if (beatBoost > 0) {
    translateY -= beatBoost * px * 0.3;
    scale *= 1 + beatBoost * 0.12;
    rotate += beatBoost * 12;
  }

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          left: centerX - px / 2 + translateX,
          top: centerY - px / 2 + translateY,
          width: px,
          height: px,
          transform: `rotate(${rotate}deg) scale(${scale})`,
          filter: "drop-shadow(0 14px 28px rgba(0,0,0,0.45))",
        }}
      >
        {src ? (
          <Img
            src={resolveAsset(src)}
            style={{ width: px, height: px, objectFit: "contain" }}
          />
        ) : (
          <BuiltinDuck size={px} />
        )}
      </div>
    </AbsoluteFill>
  );
};
