import { ThreeCanvas } from "@remotion/three";
import { useCurrentFrame, useVideoConfig } from "remotion";
import * as THREE from "three";
import React from "react";

/**
 * 等距 3D 微缩战场(HookIsometric)。
 *
 * 参考的是"悬浮方块平台 + 正交等距相机"的那种微缩景观:
 * 一块带边框的方格地台浮在背景里,镜头 45° 偏航、约 35° 俯角,
 * 角色在台面上推进,场景随着进度自己长出来(塔、树、墙、风车、云)。
 *
 * 为什么必须上 three.js:等距透视下的遮挡关系、柔和阴影、方块的体块感,
 * 用 2D 网格贴图模拟不出来 —— 那是"平面上的网格",不是"立体场景"。
 */

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const easeIn = (t: number) => t * t;
const easeOut = (t: number) => 1 - Math.pow(1 - t, 3);
const rand = (i: number, salt = 0) => {
  const v = Math.sin((i + 1) * 12.9898 + salt * 78.233) * 43758.5453;
  return v - Math.floor(v);
};

export type IsoEnemyKind = "spike" | "drone" | "crawler" | "bomber" | "cube";

export interface IsoWave {
  /** 占全片比例 */
  at: number;
  ability: "punch" | "spin" | "stomp" | "shield" | "sweep";
  count?: number;
}

export interface HookIsometricProps {
  /** 平台边长(格子数) */
  gridSize?: number;
  /** 角色从左到右(世界坐标) */
  fromX?: number;
  toX?: number;
  accent?: string;
  waves?: IsoWave[];
  /** 持续刷怪间隔(秒) */
  trickleSeconds?: number;
  /** 场景长出来的进度(0–1) */
  buildUntil?: number;
  /** 按秒计:场景在前 N 秒里长完(给了它就优先用) */
  buildSeconds?: number;
  cameraAngle?: number;
}

const PALETTE = {
  tile: "#F2F3FB",
  tileAlt: "#E6E7F6",
  rim: "#FFFFFF",
  pit: "#3B3A6B",
  leaf: "#8FE3AC",
  accent: "#6D8BFF",
  enemy: "#FF7A7A",
  enemy2: "#7BE0D0",
};

const ISO_WAVES: IsoWave[] = [
  { at: 0.08, ability: "punch", count: 4 },
  { at: 0.2, ability: "spin", count: 5 },
  { at: 0.32, ability: "stomp", count: 5 },
  { at: 0.45, ability: "shield", count: 4 },
  { at: 0.58, ability: "sweep", count: 6 },
  { at: 0.72, ability: "spin", count: 6 },
  { at: 0.86, ability: "stomp", count: 6 },
];

/* ─────────── 小人(机器人) ─────────── */

const IsoRobot: React.FC<{
  x: number;
  z: number;
  facing: number;
  walk: number;
  accent: string;
  lean: number;
  squash: number;
  eye: number;
  spin: number;
  shield: number;
  glow: number;
}> = ({ x, z, facing, walk, accent, lean, squash, eye, spin, shield, glow }) => {
  const legSwing = Math.sin(walk) * 0.5;
  const armSwing = -Math.sin(walk) * 0.42;
  return (
    <group position={[x, 0.32, z]} rotation={[0, facing, 0]}>
      <mesh position={[0, -0.3, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[0.22, 20]} />
        <meshBasicMaterial color="#2A2A55" transparent opacity={0.25} />
      </mesh>
      {glow > 0.02 && (
        <mesh position={[0, -0.24, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <circleGeometry args={[0.34 + glow * 0.2, 20]} />
          <meshBasicMaterial color={accent} transparent opacity={0.35 * glow} />
        </mesh>
      )}
      {shield > 0.02 && (
        <mesh position={[0, 0.16, 0]}>
          <sphereGeometry args={[0.42 + shield * 0.16, 16, 16]} />
          <meshBasicMaterial color={accent} transparent opacity={0.16 * shield} side={THREE.DoubleSide} />
        </mesh>
      )}
      <group rotation={[0, 0, spin]} scale={[1 + squash * 0.08, 1 - squash * 0.08, 1 + squash * 0.08]}>
        <group position={[-0.07, -0.04, 0]} rotation={[legSwing, 0, 0]}>
          <mesh position={[0, -0.12, 0]}>
            <boxGeometry args={[0.09, 0.24, 0.09]} />
            <meshStandardMaterial color="#C9CEDF" roughness={0.7} />
          </mesh>
        </group>
        <group position={[0.07, -0.04, 0]} rotation={[-legSwing, 0, 0]}>
          <mesh position={[0, -0.12, 0]}>
            <boxGeometry args={[0.09, 0.24, 0.09]} />
            <meshStandardMaterial color="#C9CEDF" roughness={0.7} />
          </mesh>
        </group>
        <mesh position={[0, 0.1, 0]} castShadow>
          <capsuleGeometry args={[0.13, 0.14, 6, 14]} />
          <meshStandardMaterial color="#F7F9FF" roughness={0.45} />
        </mesh>
        <mesh position={[0, 0.09, 0.12]}>
          <boxGeometry args={[0.1, 0.07, 0.03]} />
          <meshStandardMaterial color={accent} emissive={accent} emissiveIntensity={0.6} />
        </mesh>
        <group position={[-0.15, 0.16, 0]} rotation={[armSwing, 0, 0.2]}>
          <mesh position={[0, -0.08, 0]}>
            <capsuleGeometry args={[0.04, 0.14, 4, 8]} />
            <meshStandardMaterial color="#C9CEDF" roughness={0.6} />
          </mesh>
        </group>
        <group position={[0.15, 0.16, 0]} rotation={[-armSwing * 1.3, 0, -0.2]}>
          <mesh position={[0, -0.08, 0]}>
            <capsuleGeometry args={[0.04, 0.14, 4, 8]} />
            <meshStandardMaterial color="#C9CEDF" roughness={0.6} />
          </mesh>
          <mesh position={[0, -0.17, 0]}>
            <sphereGeometry args={[0.055, 12, 12]} />
            <meshStandardMaterial color={accent} emissive={accent} emissiveIntensity={0.4} />
          </mesh>
        </group>
        <group position={[0, 0.33, 0]} rotation={[0, 0, lean * 0.04]}>
          <mesh castShadow>
            <sphereGeometry args={[0.15, 18, 18]} />
            <meshStandardMaterial color="#FFFFFF" roughness={0.35} />
          </mesh>
          <mesh position={[eye * 0.05, 0.01, 0.11]}>
            <sphereGeometry args={[0.055, 14, 14]} />
            <meshStandardMaterial color="#1B1B33" roughness={0.2} />
          </mesh>
          <mesh position={[0.02, 0.01, 0.155]}>
            <sphereGeometry args={[0.016, 8, 8]} />
            <meshStandardMaterial color="#FFFFFF" emissive="#FFFFFF" emissiveIntensity={0.8} />
          </mesh>
          <mesh position={[0, 0.18, 0]}>
            <cylinderGeometry args={[0.008, 0.008, 0.12, 6]} />
            <meshStandardMaterial color="#B9C0D6" />
          </mesh>
          <mesh position={[0, 0.25, 0]}>
            <sphereGeometry args={[0.028, 10, 10]} />
            <meshStandardMaterial color={accent} emissive={accent} emissiveIntensity={0.9} />
          </mesh>
        </group>
      </group>
    </group>
  );
};

/* ─────────── 敌人 ─────────── */

const IsoEnemy: React.FC<{ kind: IsoEnemyKind; scale: number; spin: number; alpha: number }> = ({
  kind,
  scale,
  spin,
  alpha,
}) => {
  if (kind === "drone") {
    return (
      <group scale={scale}>
        <mesh castShadow rotation={[0, spin, 0]}>
          <octahedronGeometry args={[0.16, 0]} />
          <meshStandardMaterial color={PALETTE.enemy2} roughness={0.4} transparent opacity={alpha} />
        </mesh>
        <mesh position={[0, 0.05, 0]} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[0.17, 0.02, 6, 18]} />
          <meshStandardMaterial color="#FFFFFF" transparent opacity={0.8 * alpha} />
        </mesh>
      </group>
    );
  }
  if (kind === "crawler") {
    return (
      <group scale={scale}>
        <mesh castShadow position={[0, 0.06, 0]}>
          <sphereGeometry args={[0.15, 14, 10]} />
          <meshStandardMaterial color="#9BE7FF" roughness={0.5} transparent opacity={alpha} />
        </mesh>
        <mesh position={[0, 0.08, 0.12]}>
          <sphereGeometry args={[0.035, 8, 8]} />
          <meshStandardMaterial color="#123" transparent opacity={alpha} />
        </mesh>
      </group>
    );
  }
  if (kind === "bomber") {
    return (
      <group scale={scale}>
        <mesh castShadow position={[0, 0.14, 0]}>
          <sphereGeometry args={[0.17, 14, 14]} />
          <meshStandardMaterial color="#3A3A55" roughness={0.5} transparent opacity={alpha} />
        </mesh>
        <mesh position={[0, 0.33, 0]}>
          <sphereGeometry args={[0.05, 10, 10]} />
          <meshStandardMaterial color="#FFB020" emissive="#FFB020" emissiveIntensity={0.9} transparent opacity={alpha} />
        </mesh>
      </group>
    );
  }
  if (kind === "cube") {
    return (
      <mesh castShadow rotation={[spin, spin * 0.7, 0]} scale={scale} position={[0, 0.14, 0]}>
        <boxGeometry args={[0.24, 0.24, 0.24]} />
        <meshStandardMaterial color="#FF9A6B" roughness={0.5} transparent opacity={alpha} />
      </mesh>
    );
  }
  return (
    <group scale={scale} rotation={[0, spin, 0]}>
      <mesh castShadow position={[0, 0.12, 0]}>
        <coneGeometry args={[0.16, 0.28, 8]} />
        <meshStandardMaterial color={PALETTE.enemy} roughness={0.45} transparent opacity={alpha} />
      </mesh>
      <mesh position={[0, 0.02, 0.11]}>
        <sphereGeometry args={[0.03, 8, 8]} />
        <meshStandardMaterial color="#3A1020" transparent opacity={alpha} />
      </mesh>
    </group>
  );
};

/* ─────────── 场景 ─────────── */

const IsoScene: React.FC<HookIsometricProps> = ({
  gridSize = 9,
  fromX = -2.6,
  toX = 2.6,
  accent = PALETTE.accent,
  waves = ISO_WAVES,
  trickleSeconds = 0.8,
  buildUntil = 0.55,
  buildSeconds,
  cameraAngle = 0.9,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const t = frame / fps;
  const durSec = durationInFrames / fps;
  const progress = clamp01(frame / Math.max(1, durationInFrames - 1));

  const half = (gridSize - 1) / 2;
  const robotX = lerp(fromX, toX, progress);
  const walk = progress * Math.PI * 2 * 26;

  const wave = waves.find((w) => {
    const at = w.at * durSec;
    return t >= at - 0.5 && t <= at + 0.9;
  });
  const waveLocal = wave ? t - wave.at * durSec : -99;
  let spin = 0;
  let lean = 0;
  let squash = 0;
  let shield = 0;
  let glow = 0;
  if (wave) {
    if (wave.ability === "spin") {
      spin = lerp(clamp01((waveLocal + 0.15) / 0.6), 0, 1) * Math.PI * 2;
      glow = 0.7;
    } else if (wave.ability === "stomp") {
      squash = Math.max(0, 1 - Math.abs(waveLocal - 0.25) * 6);
      glow = 1;
    } else if (wave.ability === "shield") {
      shield =
        lerp(clamp01((waveLocal + 0.3) / 0.5), 0, 1) *
        (waveLocal > 0.4 ? 1 - clamp01((waveLocal - 0.4) / 0.5) : 1);
    } else if (wave.ability === "punch") {
      lean = Math.sin(clamp01((waveLocal + 0.2) / 0.6) * Math.PI) * 0.6;
    } else {
      glow = 0.6;
    }
  }

  const enemies: {
    id: number;
    kind: IsoEnemyKind;
    spawnAt: number;
    sx: number;
    sz: number;
    killedAt: number | null;
    spin: number;
  }[] = [];
  let eid = 0;
  const spawnOne = (spawnAt: number, salt: number) => {
    const ang = rand(salt, 11) * Math.PI * 2;
    const rad = 2.6 + rand(salt, 12) * 1.8;
    enemies.push({
      id: eid++,
      kind: (["spike", "drone", "crawler", "bomber", "cube"] as IsoEnemyKind[])[
        Math.floor(rand(salt, 13) * 5)
      ],
      spawnAt,
      sx: clamp01(0.5 + (Math.cos(ang) * rad) / (gridSize + 2)) * gridSize - half,
      sz: clamp01(0.5 + (Math.sin(ang) * rad) / (gridSize + 2)) * gridSize - half,
      killedAt: null,
      spin: rand(salt, 14) * 6,
    });
  };
  waves.forEach((w, wi) => {
    const at = w.at * durSec;
    const n = w.count ?? 4;
    for (let k = 0; k < n; k++) spawnOne(at - 1.4 - rand(wi * 17 + k, 4) * 0.8, wi * 17 + k);
  });
  const trickles = Math.floor(durSec / trickleSeconds) * 2;
  for (let i = 0; i < trickles; i++) {
    spawnOne(Math.floor(i / 2) * trickleSeconds + 0.3 + (i % 2) * 0.25, 1000 + i);
  }

  if (wave) {
    for (const e of enemies) {
      if (e.killedAt !== null) continue;
      const age = t - e.spawnAt;
      if (age < 0) continue;
      const k = clamp01(age / 1.8);
      const ex = lerp(e.sx, robotX, easeIn(k));
      const ez = lerp(e.sz, 1.6, easeIn(k));
      if (waveLocal >= -0.05 && Math.hypot(ex - robotX, ez - 1.6) < 1.5) e.killedAt = t;
    }
  }

  const tiles: React.ReactNode[] = [];
  for (let ix = 0; ix < gridSize; ix++) {
    for (let iz = 0; iz < gridSize; iz++) {
      const x = ix - half;
      const z = iz - half;
      const isPit = Math.abs(x) <= 1 && Math.abs(z) <= 1;
      const rim = ix === 0 || iz === 0 || ix === gridSize - 1 || iz === gridSize - 1;
      const h = isPit ? 0.06 : rim ? 0.3 : 0.18 + ((ix * 7 + iz * 3) % 5) * 0.02;
      const color = isPit
        ? PALETTE.pit
        : rim
          ? PALETTE.rim
          : (ix + iz) % 2 === 0
            ? PALETTE.tile
            : PALETTE.tileAlt;
      tiles.push(
        <mesh key={`t${ix}-${iz}`} position={[x, h / 2 - 0.16, z]} receiveShadow>
          <boxGeometry args={[0.98, h, 0.98]} />
          <meshStandardMaterial color={color} roughness={0.85} metalness={0.02} />
        </mesh>,
      );
    }
  }

  const build = buildSeconds ? clamp01(t / buildSeconds) : clamp01(progress / buildUntil);
  const deco: React.ReactNode[] = [];
  const decoDefs: {
    x: number;
    z: number;
    kind: "tree" | "block" | "tower" | "turbine" | "cloud";
    at: number;
  }[] = [
    { x: -3, z: -3, kind: "tree", at: 0.05 },
    { x: 3, z: -3, kind: "tree", at: 0.1 },
    { x: -3, z: 3, kind: "tree", at: 0.15 },
    { x: 3.4, z: 2.4, kind: "block", at: 0.2 },
    { x: -3.4, z: -1.6, kind: "block", at: 0.26 },
    { x: 2.2, z: -2.4, kind: "tower", at: 0.34 },
    { x: -1.8, z: -3.2, kind: "turbine", at: 0.42 },
    { x: 0.4, z: 3.2, kind: "cloud", at: 0.5 },
    { x: 2.6, z: 3.2, kind: "tree", at: 0.58 },
  ];
  decoDefs.forEach((d, i) => {
    const appear = clamp01((build - d.at / buildUntil) * 4);
    if (appear <= 0.01) return;
    const s = easeOut(appear);
    const y = (1 - s) * -0.6;
    if (d.kind === "tree") {
      deco.push(
        <group key={i} position={[d.x, y, d.z]} scale={s}>
          <mesh position={[0, 0.16, 0]} castShadow>
            <cylinderGeometry args={[0.05, 0.06, 0.32, 8]} />
            <meshStandardMaterial color="#C89A6A" />
          </mesh>
          <mesh position={[0, 0.44, 0]} castShadow>
            <sphereGeometry args={[0.2, 12, 10]} />
            <meshStandardMaterial color={PALETTE.leaf} roughness={0.8} />
          </mesh>
          <mesh position={[0.1, 0.58, 0.02]} castShadow>
            <sphereGeometry args={[0.13, 10, 8]} />
            <meshStandardMaterial color="#7FDCA4" roughness={0.8} />
          </mesh>
        </group>,
      );
    } else if (d.kind === "block") {
      deco.push(
        <group key={i} position={[d.x, y, d.z]} scale={s}>
          <mesh position={[0, 0.2, 0]} castShadow>
            <boxGeometry args={[0.6, 0.4, 0.6]} />
            <meshStandardMaterial color="#FFFFFF" roughness={0.7} />
          </mesh>
          <mesh position={[0.16, 0.48, 0.12]} castShadow>
            <boxGeometry args={[0.22, 0.16, 0.22]} />
            <meshStandardMaterial color={accent} roughness={0.6} />
          </mesh>
        </group>,
      );
    } else if (d.kind === "tower") {
      deco.push(
        <group key={i} position={[d.x, y, d.z]} scale={s}>
          {[0, 1, 2, 3].map((k) => (
            <mesh key={k} position={[0, 0.2 + k * 0.28, 0]} castShadow>
              <cylinderGeometry args={[0.26 - k * 0.045, 0.3 - k * 0.045, 0.26, 12]} />
              <meshStandardMaterial color={k % 2 ? "#5C6BC0" : "#8C9BE8"} roughness={0.5} />
            </mesh>
          ))}
          <mesh position={[0, 1.55, 0]}>
            <sphereGeometry args={[0.1, 12, 12]} />
            <meshStandardMaterial color="#9FF3FF" emissive="#9FF3FF" emissiveIntensity={1.2} />
          </mesh>
        </group>,
      );
    } else if (d.kind === "turbine") {
      deco.push(
        <group key={i} position={[d.x, y, d.z]} scale={s}>
          <mesh position={[0, 0.5, 0]} castShadow>
            <cylinderGeometry args={[0.04, 0.05, 1, 8]} />
            <meshStandardMaterial color="#DDE2F2" />
          </mesh>
          <group position={[0, 1, 0]} rotation={[0, t * 2.2, 0]}>
            {[0, 2.094, 4.188].map((a) => (
              <mesh
                key={a}
                rotation={[0, 0, a]}
                position={[Math.cos(a) * 0.22, 0, Math.sin(a) * 0.22]}
                castShadow
              >
                <boxGeometry args={[0.44, 0.02, 0.08]} />
                <meshStandardMaterial color="#FFFFFF" />
              </mesh>
            ))}
          </group>
        </group>,
      );
    } else {
      deco.push(
        <group key={i} position={[d.x, y + 0.9, d.z]} scale={s}>
          <mesh castShadow>
            <sphereGeometry args={[0.3, 12, 10]} />
            <meshStandardMaterial color="#FFFFFF" transparent opacity={0.85} roughness={1} />
          </mesh>
        </group>,
      );
    }
  });

  return (
    <>
      <ambientLight intensity={1.35} />
      <hemisphereLight args={["#FFFFFF", "#B9B6E0", 0.9]} />
      <directionalLight
        position={[6, 12, 8]}
        intensity={1.5}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-12}
        shadow-camera-right={12}
        shadow-camera-top={12}
        shadow-camera-bottom={-12}
      />
      <directionalLight position={[-8, 6, -6]} intensity={0.5} color="#BFD3FF" />

      <mesh position={[0, -0.42, 0]} receiveShadow>
        <boxGeometry args={[gridSize + 0.5, 0.5, gridSize + 0.5]} />
        <meshStandardMaterial color="#C9CBE8" roughness={0.9} />
      </mesh>
      {tiles}
      {deco}

      {enemies.map((e) => {
        const age = t - e.spawnAt;
        if (age < 0) return null;
        const k = clamp01(age / 1.8);
        let x = lerp(e.sx, robotX, easeIn(k));
        let z = lerp(e.sz, 1.6, easeIn(k));
        let scale = 1;
        let alpha = 1;
        let spin = e.spin + t * 2;
        if (e.killedAt !== null) {
          const after = t - e.killedAt;
          if (after > 1.0) return null;
          const kk = clamp01(after / 1.0);
          x += (e.sx > robotX ? 1 : -1) * kk * 1.1;
          z += kk * 0.9;
          scale = 1 - kk * 0.7;
          alpha = 1 - kk;
          spin += kk * 12;
        }
        return (
          <group key={e.id} position={[x, 0.22, z]} rotation={[0, spin, 0]} scale={1.35}>
            <IsoEnemy kind={e.kind} scale={scale} spin={spin} alpha={alpha} />
          </group>
        );
      })}

      <group scale={1.75}>
      <IsoRobot
        x={robotX}
        z={1.6}
        facing={Math.PI * 0.25}
        walk={walk}
        accent={accent}
        lean={lean}
        squash={squash}
        eye={wave ? 1 : 0.3}
        spin={spin}
        shield={shield}
        glow={glow}
      />
      </group>
    </>
  );
};

export const HookIsometric: React.FC<HookIsometricProps> = (props) => {
  const { width, height } = useVideoConfig();
  const portrait = height > width;
  // 相机是 ThreeCanvas 的 camera prop(真正在用的是这一台);
  // 场景整体往下移,竖屏时地台落在画面下半部,上面留给正文卡片。
  const dist = portrait ? 13 : 12;
  const fov = portrait ? 32 : 30;
  const offsetY = portrait ? -1.9 : 0;
  const scale = portrait ? 0.52 : 0.9;
  return (
    <ThreeCanvas
      width={width}
      height={height}
      camera={{ position: [dist, dist, dist], fov, near: 0.1, far: 200 }}
      gl={{ antialias: true, alpha: true }}
      shadows
      style={{ position: "absolute", inset: 0 }}
    >
      <group position={[0, offsetY, 0]} scale={scale}>
        <IsoScene {...props} />
      </group>
    </ThreeCanvas>
  );
};
