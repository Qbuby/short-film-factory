import { Composition, registerRoot } from "remotion";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import React from "react";
const Probe = () => {
  const f = useCurrentFrame();
  return <AbsoluteFill style={{background:"#E8E2D2", display:"flex", alignItems:"center", justifyContent:"center"}}>
    <div style={{fontFamily:"SimHei, sans-serif", fontSize:120, color:"#C0272D"}}>测试 {f}</div>
  </AbsoluteFill>;
};
const Root = () => <Composition id="Probe" component={Probe} durationInFrames={30} fps={30} width={1080} height={1920} />;
registerRoot(Root);
