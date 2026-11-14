import React from 'react';
import {AbsoluteFill,useCurrentFrame} from 'remotion';
export const sans='"Microsoft YaHei","Noto Sans SC",sans-serif';
export const serif='"SimSun","Noto Serif SC",serif';
export const mono='Consolas,monospace';
export const TAU=Math.PI*2;
export const cyc=(t:number,phase=0)=>Math.sin(TAU*t/5+phase);
export const reveal=(t:number,delay=0)=>{const p=Math.max(0,Math.min(1,(t-delay)/.65));return 1-Math.pow(1-p,3);};
export const Label:React.FC<{x?:number;y:number;text:string;color?:string;size?:number}>=({x=88,y,text,color='#20252b',size=22})=><text x={x} y={y} fill={color} fontFamily={mono} fontSize={size} letterSpacing={4}>{text}</text>;
export const Text:React.FC<{x?:number;y:number;children:React.ReactNode;color?:string;size?:number;weight?:number;font?:string;spacing?:number}>=({x=88,y,children,color='#20252b',size=118,weight=800,font=sans,spacing=-5})=><text x={x} y={y} fill={color} fontFamily={font} fontSize={size} fontWeight={weight} letterSpacing={spacing}>{children}</text>;
export const Canvas:React.FC<{bg:string;children:React.ReactNode}>=({bg,children})=><AbsoluteFill style={{background:bg}}><svg width="1080" height="1920" viewBox="0 0 1080 1920" style={{display:'block'}}>{children}</svg></AbsoluteFill>;
export const Rule:React.FC<{y:number;color?:string}>=({y,color='#20252b'})=><path d={`M88 ${y}H992`} stroke={color} strokeWidth={2}/>;
export function clock(){return useCurrentFrame()/30;}
