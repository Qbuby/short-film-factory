/** 5-second authored style demonstration for mg-wallstreet.
 *
 * Follows the wallstreet-explainer style language (MIT): only one dark
 * twill-fabric stage, cream-gold giant number, white press-card with a
 * highlighter sweep, bars on ONE shared axis. Camera drifts, elements appear
 * plainly. No fake news screenshots, no real brands, no external assets.
 */
import React from 'react';
import { AbsoluteFill, useCurrentFrame } from 'remotion';

const SANS = '"Microsoft YaHei","Noto Sans SC",sans-serif';
const MONO = 'Consolas,"Courier New",monospace';
const TAU = Math.PI * 2;
const cyc = (t, phase = 0) => Math.sin((TAU * t) / 5 + phase);
const reveal = (t, delay = 0) => {
  const p = Math.max(0, Math.min(1, (t - delay) / 0.65));
  return 1 - Math.pow(1 - p, 3);
};

const NAVY = '#101C2E';
const CREAM = '#F1EAD2';
const GOLD = '#EFDC7A';
const PAPER = '#F4F1EA';

export const WallstreetShowcase = ({ styleId }: { styleId: string }) => {
  void styleId;
  const t = useCurrentFrame() / 30;
  const slow = Math.sin(t * 0.55) * 10;      // 镜头慢推/横摇,不是元素弹跳
  const roll = reveal(t, 0.35);
  const bar = reveal(t, 0.9);
  const sweep = (t * 150) % 1180 - 220;     // 荧光笔循环刷过

  return (
    <AbsoluteFill style={{ background: NAVY, overflow: 'hidden', fontFamily: SANS }}>
      <svg width="1080" height="1920" viewBox="0 0 1080 1920" style={{ display: 'block' }}>
        <defs>
          <linearGradient id="ws-bg" x1="0" y1="0" x2="0.6" y2="1">
            <stop offset="0%" stopColor="#16243B" />
            <stop offset="52%" stopColor="#101C2E" />
            <stop offset="100%" stopColor="#0B1422" />
          </linearGradient>
          <linearGradient id="ws-gold" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#FFFEF2" />
            <stop offset="50%" stopColor="#FFF3B5" />
            <stop offset="100%" stopColor="#EFDC7A" />
          </linearGradient>
          <linearGradient id="ws-highlight" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="rgba(255,216,74,0)" />
            <stop offset="48%" stopColor="rgba(255,216,74,.9)" />
            <stop offset="100%" stopColor="rgba(255,216,74,0)" />
          </linearGradient>
          <pattern id="ws-twill" width="9" height="9" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="9" stroke="#F1EAD2" strokeOpacity=".055" strokeWidth="1.4" />
          </pattern>
          <pattern id="ws-twill2" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">
            <line x1="0" y1="0" x2="0" y2="7" stroke="#050B14" strokeOpacity=".16" strokeWidth="1.4" />
          </pattern>
          <radialGradient id="ws-glow" cx="50%" cy="42%" r="60%">
            <stop offset="0%" stopColor="rgba(59,122,28,.22)" />
            <stop offset="55%" stopColor="rgba(28,107,98,.08)" />
            <stop offset="100%" stopColor="rgba(0,0,0,0)" />
          </radialGradient>
          <radialGradient id="ws-vignette" cx="50%" cy="46%" r="72%">
            <stop offset="55%" stopColor="rgba(0,0,0,0)" />
            <stop offset="100%" stopColor="rgba(4,9,18,.5)" />
          </radialGradient>
        </defs>

        {/* 唯一底色:细斜纹深蓝织物 + 一团克制的品牌色光 */}
        <rect width="1080" height="1920" fill="url(#ws-bg)" />
        <rect width="1080" height="1920" fill="url(#ws-twill)" />
        <rect width="1080" height="1920" fill="url(#ws-twill2)" />
        <rect width="1080" height="1920" fill="url(#ws-glow)" />
        <rect width="1080" height="1920" fill="url(#ws-vignette)" />

        {/* 眉题:一帧最多一组,奶油白 + 大字距 */}
        <g transform={`translate(${slow * 0.35} 0)`}>
          <text x="88" y="150" fill={GOLD} fontFamily={SANS} fontSize="40" fontWeight="800" letterSpacing="12">
            一 笔 账
          </text>
          <text x="90" y="196" fill="#9AA8BD" fontFamily={MONO} fontSize="21" letterSpacing="7" opacity=".7">
            FOLLOW THE MONEY · STYLE DEMO
          </text>
          {/* 样片是风格演示,不是真实财报:明确标出,别让人把示意数字当事实 */}
          <text x="992" y="196" textAnchor="end" fill="#9AA8BD" fontFamily={SANS}
            fontSize="20" letterSpacing="3" opacity=".75">
            数字为示意 · 非真实数据
          </text>
          <path d="M88 226H992" stroke={GOLD} strokeOpacity=".5" strokeWidth="2" />
        </g>

        {/* 奶油金巨数:渐变小外发光,数字滚动到满位 */}
        <g transform={`translate(${slow * 0.6} ${cyc(t) * 6})`}>
          <text x="540" y="560" textAnchor="middle" fill="url(#ws-gold)" fontFamily={MONO}
            fontWeight="900" fontSize="270" letterSpacing="-8" opacity={0.35 + 0.65 * roll}>
            ${Math.round(725 * roll).toString().padStart(3, '0')}B
          </text>
          <text x="540" y="632" textAnchor="middle" fill="#F2E27E" fontFamily={SANS}
            fontWeight="800" fontSize="40" letterSpacing="14">
            一 年 的 算 力 开 支
          </text>
        </g>

        {/* 白边画框里的白底原文卡:证据感 */}
        <g transform={`translate(88 ${790 + cyc(t, 1) * 8}) rotate(-1.2 452 200)`}>
          <rect x="-8" y="-8" width="920" height="416" rx="14" fill="none" stroke={PAPER} strokeWidth="10" />
          <rect width="904" height="400" rx="6" fill={PAPER} />
          <rect x="0" y="0" width="904" height="54" fill="#DFD9CB" />
          <text x="26" y="37" fill="#3C4149" fontFamily={MONO} fontSize="22" letterSpacing="3">
            ILLUSTRATIVE LAYOUT / STYLE DEMO
          </text>
          {[
            '资本开支同比 +218%，主要投向数据中心',
            '推理成本下降 41%，但训练需求翻倍',
            '现金流转正，仍低于市场一致预期',
          ].map((line, i) => (
            <g key={i}>
              <text x="34" y={118 + i * 84} fill="#2A3038" fontFamily={SANS} fontSize="34" fontWeight="600">
                {line}
              </text>
              <path d={`M34 ${132 + i * 84}H${440 + i * 120}`} stroke="#B9B2A2" strokeWidth="1.5" />
            </g>
          ))}
          {/* 荧光黄:正片叠底的一道光横刷过,一直循环 */}
          <rect x={sweep} y="196" width="300" height="46" rx="4" fill="url(#ws-highlight)" opacity=".85" />
        </g>

        {/* 同一坐标系的柱子:连续累积,不是每镜重画 */}
        <g transform={`translate(88 ${1280 + cyc(t, 2) * 6})`}>
          <text x="0" y="-24" fill={CREAM} fontFamily={SANS} fontSize="32" fontWeight="700" letterSpacing="4">
            钱 流 去 了 哪 里
          </text>
          <path d="M0 330H904" stroke={CREAM} strokeOpacity=".35" strokeWidth="2" />
          {[0.38, 0.62, 0.5, 0.88, 0.72].map((v, i) => {
            const h = 300 * v * (0.88 + 0.12 * Math.sin(t * 1.4 + i * 0.8)) * bar;
            const x = 40 + i * 176;
            return (
              <g key={i}>
                <rect x={x} y={330 - h} width="104" height={h} rx="4"
                  fill={i === 3 ? GOLD : 'rgba(241,234,210,.42)'} />
                <text x={x + 52} y={362} textAnchor="middle" fill="#9AA8BD"
                  fontFamily={MONO} fontSize="21" letterSpacing="2">
                  {['Q1', 'Q2', 'Q3', 'Q4', 'FY'][i]}
                </text>
              </g>
            );
          })}
        </g>

        {/* 稳定字幕层:白色、底部一行,不逐字打出 */}
        <text x="540" y="1770" textAnchor="middle" fill="#FFFFFF" fontFamily={SANS}
          fontSize="46" fontWeight="600" opacity={0.92}>
          把数字摆在一起，答案自己会出来。
        </text>
        <path d="M88 1810H992" stroke={GOLD} strokeOpacity=".35" strokeWidth="2" />
        <text x="88" y="1856" fill="#9AA8BD" fontFamily={MONO} fontSize="20" letterSpacing="4">
          WALL STREET EXPLAINER / 16
        </text>
        <text x="992" y="1856" textAnchor="end" fill="#9AA8BD" fontFamily={MONO} fontSize="20" letterSpacing="4">
          {(t).toFixed(2)}s
        </text>
      </svg>
    </AbsoluteFill>
  );
};
