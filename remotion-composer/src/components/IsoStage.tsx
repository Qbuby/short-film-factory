import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { HookIsometric, type HookIsometricProps } from "./HookIsometric";

export interface IsoStageProps extends HookIsometricProps {
  /** 出现在前多少秒之后淡出(秒) */
  untilSeconds?: number;
  /** 背景色 */
  background?: string;
}

/**
 * 等距 3D 场景作为一个"段落"盖在内容之上。
 *
 * 短视频的开头需要的是热闹,不是信息:先让观众看一段会自己长出来的微缩城市,
 * 再切进正文。淡出之后内容接管,进度条式的钩子可以退回到底部战场层。
 */
export const IsoStage: React.FC<IsoStageProps> = ({ untilSeconds = 10, background = "transparent", ...rest }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const fadeStart = Math.max(0, untilSeconds - 0.8);
  const opacity = t <= fadeStart ? 1 : Math.max(0, 1 - (t - fadeStart) / 0.8);

  return (
    <AbsoluteFill style={{ opacity, background }}>
      <HookIsometric {...rest} />
    </AbsoluteFill>
  );
};
