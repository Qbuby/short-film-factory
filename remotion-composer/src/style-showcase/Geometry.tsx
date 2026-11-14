import React from 'react';
import {Canvas,Label,Text,Rule,sans,mono,clock,cyc,reveal,TAU} from './Common';

const Flat=({t}:{t:number})=>{const r=reveal(t);const parts=[[128,560,300,'#274bd7','#3a63f5','circle'],[520,560,300,'#ff7e52','#ff9270','sq'],[128,1000,300,'#ffc838','#ffd766','sq'],[520,1000,300,'#14b88a','#1ed29c','circle']] as const;
return <Canvas bg="#f4f2ec">
 <Label y={120} text="BUILT FROM SIMPLE PARTS" color="#274bd7"/><Text y={340} size={150} color="#20252b">灵感</Text><Text y={500} size={150} color="#274bd7">拼起来</Text>
 <g transform={`translate(0 ${(1-r)*40})`}>{parts.map(([x,y,s,c1,c2,shape],i)=>{const k=reveal(t,.2+i*.12);const gy=cyc(t,i*1.1)*10;
 return <g key={i} transform={`translate(${x+s/2} ${y+s/2+gy})`}>{shape==='circle'
 ?<><circle r={s/2*k} fill={c1}/><circle r={s/2*.6*k} fill={c2} opacity=".45"/><rect x={-s*.34*k} y={-s*.06} width={s*.68*k} height={s*.12} rx={s*.06} fill="#f4f2ec"/></>
 :<><rect x={-s/2*k} y={-s/2*k} width={s*k} height={s*k} rx={64} fill={c1}/><rect x={-s*.3*k} y={-s*.3*k} width={s*.6*k} height={s*.6*k} rx={40} fill={c2} opacity=".4"/><circle r={s*.12*k} fill="#f4f2ec"/></>}</g>})}</g>
 <path d={`M428 710H520M428 1150H520`} stroke="#20252b" strokeWidth="7" strokeDasharray="10 14" fill="none"/>
 <g transform={`translate(430 ${1405+cyc(t,3)*14}) rotate(-4)`}><rect width="220" height="96" rx="20" fill="#274bd7"/><text x="110" y="63" textAnchor="middle" fontFamily={sans} fontWeight="900" fontSize="42" fill="#f4f2ec">完成！</text></g>
 <Rule y={1640} color="#274bd7"/><Text y={1750} size={50} weight={500} spacing={2}>把复杂的事，拆成会动的简单形状。</Text><Label y={1832} text="FLAT / GEOMETRIC / ALIVE" color="#274bd7"/>
</Canvas>;};

const Iso=({t}:{t:number})=>{const r=reveal(t,.15);const bob=(i:number)=>cyc(t,i)*8;
const cube=(x:number,y:number,s:number,top:string,left:string,right:string,key:number)=><g key={key} transform={`translate(${x} ${y+bob(key)})`}>
 <path d={`M0 ${-s*.5}l${s*.5} ${s*.25}L0 0l${-s*.5} ${-s*.25}z`} fill={top}/><path d={`M${-s*.5} ${-s*.25}L0 0v${s*.5}l${-s*.5} ${-s*.25}z`} fill={left}/><path d={`M${s*.5} ${-s*.25}L0 0v${s*.5}l${s*.5} ${-s*.25}z`} fill={right}/></g>;
return <Canvas bg="#dfe9ec">
 <Label y={118} text="SYSTEMS, VISIBLE" color="#177e71"/><Text y={335} size={145} color="#243b50">让系统</Text><Text y={490} size={145} color="#177e71">运转起来</Text>
 <g transform={`translate(540 ${880+(1-r)*50}) scale(${.8+.2*r})`}>
 <path d="M-470 60l470-235 470 235-470 235z" fill="#eef4f5" stroke="#9db6bd" strokeWidth="2"/>
 <path d="M-240 20l240 120 240-120" stroke="#177e71" strokeWidth="4" fill="none" strokeDasharray={`${150*r} 999`} strokeLinecap="round"/>
 {cube(-240,-40,150,'#17847a','#0d5a52','#2fae9f',0)}{cube(240,60,130,'#ffc838','#c79312','#ffdf7a',1)}{cube(0,150,110,'#274bd7','#18357f','#4a6ff0',2)}
 <path d={`M20 120l${120} ${60}`} stroke="#274bd7" strokeWidth="5" fill="none" strokeDasharray={`${120*Math.abs(cyc(t,2))} 999`}/>
 <circle cx={240*Math.abs(cyc(t,1.3))-220} cy={40*Math.abs(cyc(t,1.3))-20} r="11" fill="#f78137"/>
 <g transform={`translate(120 -350) scale(.55)`}>{cube(0,0,150,'#fff','#d8dee0','#f4f7f8',5)}{cube(-150,80,110,'#fff','#d8dee0','#f4f7f8',6)}{cube(150,80,110,'#fff','#d8dee0','#f4f7f8',7)}<rect x="-60" y="-38" width="120" height="76" rx="10" fill="#177e71"/><rect x="-200" y="42" width="100" height="66" rx="10" fill="#274bd7"/><rect x="100" y="42" width="100" height="66" rx="10" fill="#ffc838"/></g>
 </g>
 <g transform={`translate(88 ${1560})`}><rect width="904" height="86" rx="18" fill="#243b50"/><text x="452" y="58" textAnchor="middle" fontFamily={sans} fontWeight="800" fontSize="40" fill="#dfe9ec">从接入到交付，一条看得见的线。</text></g>
 <Label y={1730} text="ISOMETRIC / PROCESS / CLARITY" color="#177e71"/><Text y={1820} size={42} weight={400} spacing={6} color="#243b50">小场景，讲清大流程。</Text>
</Canvas>;};

const ThreeD=({t}:{t:number})=>{const spin=t*.9;const R=330;const tube=95;const N=64;const pts:(React.ReactNode)[]=[];
for(let i=0;i<N;i++){const u=i/N*TAU;const x=Math.cos(u+spin)*R;const z=Math.sin(u+spin)*R;const y=Math.sin(u*2+spin*1.6)*170;const depth=(z/ (R+tube)+1)/2;const light=.55+.45*depth;
pts.push(<ellipse key={i} cx={540+x} cy={1050+y} rx={tube} ry={tube*.38} fill={`rgb(${Math.round(88+130*light)},${Math.round(120+110*light)},${Math.round(220+30*light)})`} opacity={.35+.6*depth}/>);}
const r=reveal(t);return <Canvas bg="#0e1526">
 <circle cx="540" cy="1020" r={430} fill="#16203a"/><circle cx="540" cy="1020" r={430} fill="none" stroke="#5f86ff" strokeOpacity=".25" strokeWidth="2"/>
 {pts}
 <g transform={`translate(0 ${(1-r)*30})`}>
 <circle cx="262" cy="520" r="120" fill="#ff5d8f" opacity=".92"/><circle cx="806" cy="470" r="150" fill="#5f86ff" opacity=".9"/>
 <text x="88" y="330" fill="#eef2ff" fontFamily={sans} fontWeight="900" fontSize="148" letterSpacing="-4">触见</text><text x="88" y="470" fill="#8fd0ff" fontFamily={sans} fontWeight="900" fontSize="148" letterSpacing="-4">未来</text>
 <text x="92" y="560" fill="#aab6d8" fontFamily={mono} fontSize="30" letterSpacing="6">MATERIAL / LIGHT / FORM</text></g>
 <Text y={1620} size={54} color="#eef2ff" weight={600} spacing={4}>光落在形状上，才叫材质。</Text><Label y={1698} text="STUDIO SHADING / 07" color="#8fd0ff"/><Text y={1758} size={34} color="#66719c" weight={400}>渲染层由真实投影计算，不是贴图。</Text>
</Canvas>;};

const Morph=({t}:{t:number})=>{const N=36;const p=cyc(t);const k=(1-p)/2;const path=(rx:number,ry:number,petals:number,seed:number)=>Array.from({length:N},(_,i)=>{const a=i/N*TAU;const wob=1+.28*Math.cos(petals*a+seed)+.1*Math.sin(a*3+seed);return `${(540+Math.cos(a)*rx*wob).toFixed(1)},${(1050+Math.sin(a)*ry*wob).toFixed(1)}`;});
const A=path(300,300,0,0),B=path(300,340,3,1.2);
const mix=(i:number)=>{const[a1,b1]=A[i].split(',').map(Number);const[a2,b2]=B[i].split(',').map(Number);return `${(a1*k+a2*(1-k)).toFixed(1)},${(b1*k+b2*(1-k)).toFixed(1)}`;};const pts=Array.from({length:N},(_,i)=>mix(i)).join(' ');
return <Canvas bg="#fdf6ee">
 <Label y={120} text="ONE SHAPE BECOMES ANOTHER" color="#f2713f"/><Text y={340} size={152} color="#33281f">形变</Text><Text y={470} size={46} weight={500} spacing={5} color="#8d7a68">没有边界，只有过渡。</Text>
 <polygon points={pts} fill="#f2713f" opacity=".92" transform={`translate(0 40)`}/><polygon points={pts} fill="none" stroke="#33281f" strokeWidth="5" transform={`translate(0 40)`}/>
 <g opacity={.85} transform={`translate(0 40)`}><circle cx={540+cyc(t,1)*300} cy={1050+cyc(t,2)*230} r="34" fill="#1fb6c9"/><circle cx={540-cyc(t,1)*300} cy={1050-cyc(t,2)*230} r="26" fill="#ffc838"/></g>
 <path d="M88 1560H992" stroke="#33281f" strokeWidth="3"/>
 <Text y={1690} size={78} color="#33281f">过程，本身就是内容。</Text><Label y={1770} text="MORPH / EVOLUTION / FLOW" color="#f2713f"/>
</Canvas>;};

const Bauhaus=({t}:{t:number})=>{const r=reveal(t);
return <Canvas bg="#f1ebe0">
 <Label y={122} text="ORDER / BALANCE / 1919" color="#d62828"/>
 <g transform={`translate(0 ${(1-r)*36})`}>
 <circle cx="330" cy="880" r="255" fill="#1d3557"/>
 <rect x="560" y="470" width="330" height="330" fill="#e9c46a" transform={`rotate(${14+t*16} 725 635)`}/>
 <polygon points="830,990 975,1240 685,1240" fill="#d62828"/>
 <rect x="88" y="1258" width="904" height="16" fill="#161616"/>
 <rect x="88" y="470" width="140" height="620" fill="#1d3557"/>
 <text x="88" y="430" fill="#161616" fontFamily={mono} fontWeight="700" fontSize="330" letterSpacing="-14">03</text>
 </g>
 <Text y={1490} size={168} color="#161616" spacing={6}>秩序即美</Text>
 <Text y={1600} size={44} weight={500} spacing={4} color="#6b6152">大字，原色，克制的动。</Text>
 <Rule y={1660} color="#161616"/><Text y={1765} size={48} font={mono} color="#d62828">BAUHAUS · GEOMETRIC · POSTER</Text>
 <rect x={840+cyc(t)*40} y={1720} width="152" height="90" fill="#161616"/><rect x={856+cyc(t)*40} y={1736} width="120" height="58" fill="none" stroke="#f1ebe0" strokeWidth="3"/>
</Canvas>;};

export const GeometryShowcase:React.FC<{styleId:string}>=({styleId})=>{const t=clock();switch(styleId){case'mg-flat-vector':return <Flat t={t}/>;case'mg-isometric':return <Iso t={t}/>;case'mg-3d-render':return <ThreeD t={t}/>;case'mg-morph':return <Morph t={t}/>;default:return <Bauhaus t={t}/>;}};
