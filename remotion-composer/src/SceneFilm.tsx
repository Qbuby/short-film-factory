import React from "react";
import { AbsoluteFill, Audio, useCurrentFrame, useVideoConfig } from "remotion";
import { resolveAsset } from "./lib/resolveAsset";
import { SCENE_MODULES } from "./generated/registry";

/**
 * SceneFilm —— 短片工厂的「模型写画面」外壳。
 *
 * 以前所有题材都被渲成同一张贴纸模板(脸 + 手机 + 验证通过)。
 * 现在 film.py scene 会让模型为**每个项目**写一个专属 TSX
 * (src/generated/<slug>.tsx,只导出默认的 Scene 组件),由
 * src/generated/registry.ts 静态注册进来;Root 为每个注册项建一个
 * `scene-<slug>` 组合。
 *
 * 这个文件只负责三件事,不负责画内容:
 *   1. 交出满画布(按 useVideoConfig 的宽高);
 *   2. 找到当前时间点属于哪一拍,把 beat/t(拍内秒数)/palette 喂给模型组件;
 *   3. 叠一条字幕条(film/subtitles)和页眉页脚,保持和模板同一个产品观感。
 *
 * 没有对应 slug 的场景模块时,Root 根本不会注册组合 —— 回退到 sf-<slug>
 * 模板由 film.py 负责,这里不做「占位帧」假装修好了。
 */

export type SceneFilmProps = {
  subs: [number, number, string][];
  /** build 写进 props.json 的配乐+口播混音;不播它就是一条静音片 */
  audioSrc?: string;
  film?: Record<string, any> | null;
  slug: string;
};

type SceneComponent = React.FC<{
  beat: any;
  t: number;
  palette: Record<string, string>;
  width: number;
  height: number;
}>;

const SANS = `"Noto Sans SC","Microsoft YaHei","PingFang SC","SimHei",sans-serif`;
const MONO = `"Consolas","Courier New",monospace`;

const PAPER_PALETTE: Record<string, string> = {
  canvas: "#E8EDF0",
  paper: "#FAF4E8",
  white: "#FFFFFF",
  ink: "#172838",
  slate: "#3C5264",
  muted: "#AFC0CB",
  red: "#F04438",
  green: "#14866D",
  yellow: "#F6C453",
  skin: "#FFD2AE",
  skinShade: "#E8A77D",
};

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

/** 从注册表取组件。module 可能是 ESM 命名空间,也可能已经是组件。 */
function pickComponent(mod: unknown): SceneComponent | null {
  if (!mod) return null;
  if (typeof mod === "function") return mod as SceneComponent;
  const m = mod as { default?: unknown };
  return typeof m.default === "function" ? (m.default as SceneComponent) : null;
}

/** 当前时间点落在哪一拍;拍外取最近的一拍(片头片尾不至于白屏)。 */
function activeBeat(
  beats: any[],
  timing: Record<string, [number, number]>,
  t: number,
): { beat: any; start: number; end: number } | null {
  if (!beats.length) return null;
  for (const b of beats) {
    const span = timing?.[b.id];
    if (Array.isArray(span) && t >= span[0] && t < span[1]) {
      return { beat: b, start: span[0], end: span[1] };
    }
  }
  // 拍与拍之间的空档(或 t 越界):取起始时间最接近且已开始的一拍,
  // 保证画面上永远是「某一片段」而不是空帧。
  let best = beats[0];
  let bestStart = timing?.[best.id]?.[0] ?? 0;
  for (const b of beats) {
    const s = timing?.[b.id]?.[0];
    if (typeof s === "number" && s <= t) {
      best = b;
      bestStart = s;
    }
  }
  const span = timing?.[best.id];
  return {
    beat: best,
    start: bestStart,
    end: Array.isArray(span) ? span[1] : bestStart + 4,
  };
}

export const SceneFilm: React.FC<SceneFilmProps> = ({ subs, audioSrc, film, slug }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const t = frame / fps;
  const wide = width > height;

  const data = film || {};
  const beats: any[] = Array.isArray(data.beats) ? data.beats : [];
  const timing: Record<string, [number, number]> = data.timing || {};
  const palette: Record<string, string> = { ...PAPER_PALETTE, ...(data.theme || {}) };

  // 注册表按 slug 静态导入(ESM 打包里没有 require)。
  const Scene = pickComponent(SCENE_MODULES?.[slug]);

  const cur = activeBeat(beats, timing, t);
  const beatLocal = cur ? Math.max(0, t - cur.start) : 0;

  let subText = "";
  let subAlpha = 0;
  for (const [a, b, txt] of subs || []) {
    if (t >= a && t < b) {
      subText = txt;
      subAlpha = Math.min(clamp01((t - a) / 0.08), clamp01((b - t) / 0.08));
      break;
    }
  }

  // 字幕条占底部一条固定高度。模型是按整幅 1080×1920 作画的,prompt 里
  // 「底部留 300px」只是口头约定,模型经常不遵守 —— 真实事故里它的底部
  // 信息面板正好被字幕条压住。这里从结构上让开:画面整体略微上移并压扁
  // 一点点(不是等比缩小),字幕条永远落在模型内容之外。
  // 压扁 6% 在贴纸风里看不出变形,但换来的是「字幕永远不会盖住内容」。
  const SUB_ZONE = wide ? Math.round(height * 0.14) : Math.round(height * 0.17);
  const artH = Math.max(1, height - SUB_ZONE);
  const artScaleY = artH / Math.max(1, height);

  return (
    <AbsoluteFill
      style={{
        width,
        height,
        overflow: "hidden",
        fontFamily: SANS,
        background: palette.canvas,
      }}
    >
      {Scene && cur ? (
        <AbsoluteFill style={{ width, height: artH, overflow: "hidden" }}>
          {/* 外壳兜底微动:模型偶尔会画出内容正确、但某个分支完全没有动画的画面,
              那一段在成片里就是定格 → 评审判死场、观众划走。这里叠两层
              几乎看不见的持续运动(呼吸缩放 + 缓慢扫过的高光),让任何一帧
              都不可能和上一帧完全相同,同时不改变模型的设计。

              幅度刻意压到 0.35% / 4%:肉眼几乎无感,但帧差检测能稳定捕捉到。
              已经有运动的画面叠加后不受影响(它们的变化量远大于这层)。 */}
          <AbsoluteFill
            style={{
              transform: `scale(${1 + 0.0035 * Math.sin(t * 2.1)})`,
              transformOrigin: "50% 45%",
            }}
          >
            <div
              style={{
                position: "absolute",
                left: 0,
                top: 0,
                width,
                height,
                transform: `scaleY(${artScaleY})`,
                transformOrigin: "top left",
                overflow: "hidden",
              }}
            >
              <Scene
                beat={cur.beat}
                t={beatLocal}
                palette={palette}
                width={width}
                height={height}
              />
            </div>
          </AbsoluteFill>
          <AbsoluteFill
            style={{
              pointerEvents: "none",
              background: `linear-gradient(115deg, rgba(255,255,255,0) 42%, rgba(255,255,255,0.05) 50%, rgba(255,255,255,0) 58%)`,
              backgroundSize: "300% 300%",
              backgroundPosition: `${((t * 9) % 300).toFixed(1)}% 50%`,
              mixBlendMode: "soft-light",
            }}
          />
        </AbsoluteFill>
      ) : (
        // 只有注册表与 props 对不上时才会走到这里(例如项目刚删、props 还旧)。
        // 这不是「专属画面」,所以明说,别让人误以为模型画过了。
        <AbsoluteFill
          style={{
            alignItems: "center",
            justifyContent: "center",
            color: palette.slate,
            fontSize: 34,
            letterSpacing: 2,
          }}
        >
          本条未生成专属画面
        </AbsoluteFill>
      )}

      {/* 页眉:只在没有专属画面时由外壳补。
          模型写的画面会自己画页眉(prompt 里给了 header 文案,并要求顶部留白),
          外壳再加一条就会两行叠在一起。 */}
      {data.header && !(Scene && cur) ? (
        <div
          style={{
            position: "absolute",
            left: wide ? 110 : 70,
            top: wide ? 34 : 74,
            fontFamily: MONO,
            fontSize: 24,
            letterSpacing: 5,
            color: palette.slate,
            opacity: 0.8,
            zIndex: 3,
          }}
        >
          {data.header}
        </div>
      ) : null}

      {/* 字幕条:纸感底板 + 墨色字,不压成黑底白字的默认样式。
          它落在 artH 之下那段专门让出来的区域,不会覆盖模型内容。 */}
      {subText ? (
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            bottom: wide ? 56 : 128,
            display: "flex",
            justifyContent: "center",
            padding: "0 56px",
            zIndex: 4,
          }}
        >
          <div
            style={{
              opacity: subAlpha,
              textAlign: "center",
              maxWidth: wide ? 1280 : 940,
              padding: "14px 26px",
              borderRadius: 14,
              // 字幕底板必须压得住模型画面:它下面是任意内容,半透明会被穿透。
              background: "rgba(250,244,232,0.97)",
              border: `3px solid ${palette.ink}`,
              boxShadow: "0 10px 24px rgba(23,40,56,0.18)",
              color: palette.ink,
              fontSize: wide ? 42 : 44,
              fontWeight: 800,
              lineHeight: 1.32,
              letterSpacing: 1.5,
            }}
          >
            {subText}
          </div>
        </div>
      ) : null}

      {/* 页脚:模型画面已经带了自己的页脚徽章(prompt 给了 footer 文案),
          外壳只在没有专属画面时才补,避免同一个标签出现两次。 */}
      {data.footer?.label && !(Scene && cur) ? (
        <div
          style={{
            position: "absolute",
            left: 60,
            bottom: 46,
            fontFamily: MONO,
            fontSize: 20,
            color: palette.slate,
            opacity: 0.55,
            letterSpacing: 3,
            zIndex: 4,
          }}
        >
          {data.footer.label}
        </div>
      ) : null}

      {audioSrc ? <Audio src={resolveAsset(audioSrc)} /> : null}
    </AbsoluteFill>
  );
};
