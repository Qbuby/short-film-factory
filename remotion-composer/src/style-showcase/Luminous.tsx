import React from 'react';
import {Canvas,Label,Text,Rule,sans,serif,mono,clock,cyc,reveal,TAU} from './Common';

const Hud=({t}:{t:number})=>{const sweep=(t/5)*TAU;const r=reveal(t);
return <Canvas bg="#04121a">
 <Label y={112} text="SIGNAL / 4.7 GHz" color="#17e0c4"/><Label y={150} text="0 0 1 1 0 1 1 0" color="#0f8a76"/>
 <circle cx="540" cy="830" r="380" fill="none" stroke="#17e0c4" strokeOpacity=".35" strokeWidth="2"/>
 <circle cx="540" cy="830" r="290" fill="none" stroke="#17e0c4" strokeOpacity=".28"/><circle cx="540" cy="830" r="200" fill="none" stroke="#17e0c4" strokeOpacity=".2"/><circle cx="540" cy="830" r="110" fill="#0a2a33"/>
 {Array.from({length:60},(_,i)=>{const a=i/60*TAU;const long=i%5===0;return <line key={i} x1={540+Math.cos(a)*388} y1={830+Math.sin(a)*388} x2={540+Math.cos(a)*(long?352:370)} y2={830+Math.sin(a)*(long?352:370)} stroke="#17e0c4" strokeOpacity={long?.8:.4} strokeWidth={long?3:1.6}/>;})}
 <path d={`M540 830L${540+Math.cos(sweep)*380} ${830+Math.sin(sweep)*380}`} stroke="#7ef7e2" strokeWidth="4" opacity=".9"/>
 <path d={`M540 830 L${540+Math.cos(sweep-.35)*380} ${830+Math.sin(sweep-.35)*380} A380 380 0 0 0 ${540+Math.cos(sweep)*380} ${830+Math.sin(sweep)*380}Z`} fill="#17e0c4" opacity=".12"/>
 {[[655,700],[420,760],[600,940],[390,880]].map(([x,y],i)=><g key={i}><circle cx={x} cy={y} r="6" fill="#ff9f43"/><circle cx={x} cy={y} r="13" fill="none" stroke="#ff9f43" opacity=".55"/><text x={x+22} y={y+7} fill="#ffb763" fontFamily={mono} fontSize="21">{`TGT-0${i+1}`}</text></g>)}
 <path d={`M350 500q190 ${cyc(t,1)*26} 380-6`} stroke="#17e0c4" strokeWidth="2.5" fill="none" opacity=".8"/>
 <g transform={`translate(88 1300)`}><rect width="904" height="230" fill="#062028" stroke="#124f48"/><rect width="904" height="46" fill="#0a2f36"/><text x="18" y="32" fill="#17e0c4" fontFamily={mono} fontSize="24" letterSpacing="3">SPECTRUM / REALTIME</text>
 {Array.from({length:46},(_,i)=>{const h=18+70*Math.abs(Math.sin(i*.7+t*2.2))+(i%7)*6;return <rect key={i} x={16+i*19.4} y={200-h} width="11" height={h} fill={i%4?'#0f8a76':'#17e0c4'}/>})}</g>
 <Text y={1245} size={132} color="#17e0c4" spacing={6}>看见信号</Text>
 <Text y={1650} size={44} color="#9fe8dc" weight={500} spacing={2}>噪声里，总有值得听的一束。</Text><Rule y={1692} color="#0f8a76"/><Label y={1770} text="TELEMETRY / PRECISION / 03" color="#17e0c4"/>
</Canvas>;};

const Liquid=({t}:{t:number})=>{const N=10;const blob=(cx0:number,cy0:number,r:number,seed:number)=>{const pt=(i:number)=>{const a=i/N*TAU;const w=1+.16*Math.sin(t*2.4+seed+i*1.9)+.08*Math.cos(t*1.7+i);return [cx0+Math.cos(a)*r*w,cy0+Math.sin(a)*r*1.16*w];};
const P=Array.from({length:N},(_,i)=>pt(i));let d=`M${P[0][0].toFixed(1)} ${P[0][1].toFixed(1)}`;for(let i=0;i<N;i++){const p0=P[(i+N-1)%N],p1=P[i],p2=P[(i+1)%N],p3=P[(i+2)%N];d+=` C${(p1[0]+(p2[0]-p0[0])/6).toFixed(1)} ${(p1[1]+(p2[1]-p0[1])/6).toFixed(1)} ${(p2[0]-(p3[0]-p1[0])/6).toFixed(1)} ${(p2[1]-(p3[1]-p1[1])/6).toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;}return d+' Z';};
return <Canvas bg="#f6f4ef">
 <g opacity=".9"><path d={blob(420,900,300,0)} fill="#274bd7"/><path d={blob(700,1080,260,2.2)} fill="#7b5cff" opacity=".92"/><path d={blob(560,760,150,4.4)} fill="#19d3c5" opacity=".85"/></g>
 <path d="M300 1150q240-90 470 20" stroke="#fff" strokeWidth="26" fill="none" opacity=".5" strokeLinecap="round"/>
 <Label y={122} text="KEEP IT MOVING" color="#274bd7"/>
 <Text y={355} size={158} color="#20252b">保持</Text><Text y={512} size={158} color="#274bd7">流动</Text>
 <Text y={625} size={42} weight={500} spacing={4} color="#5a6478">形状没有终点，动作就是语言。</Text>
 <g transform={`translate(88 ${1560+cyc(t,3)*10}) rotate(-2)`}><rect width="520" height="104" rx="52" fill="#274bd7"/><text x="260" y="67" textAnchor="middle" fontFamily={sans} fontWeight="800" fontSize="42" fill="#f6f4ef">不用急，也不用停。</text></g>
 <Rule y={1710} color="#274bd7"/><Text y={1800} size={38} weight={400} font={mono} color="#274bd7" spacing={5}>LIQUID / GLOSS / MOTION</Text>
</Canvas>;};

const Synth=({t}:{t:number})=>{const sun=960-((t*54)%420);const stars=Array.from({length:44},(_,i)=>{const x=(i*127)%1080;const y=90+((i*211)%620);const tw=.4+.6*Math.abs(Math.sin(t*2+i));return <circle key={i} cx={x} cy={y} r={i%5?1.8:3} fill="#cfe8ff" opacity={tw}/>;});
return <Canvas bg="#120a2a">
 {stars}
 <circle cx="540" cy={sun} r="270" fill="#ff2e9a"/><circle cx="540" cy={sun} r="270" fill="url(#sunStripes)"/>
 <defs><pattern id="sunStripes" width="10" height="36" patternUnits="userSpaceOnUse"><rect width="10" height="20" fill="#120a2a" opacity=".78"/></pattern></defs>
 <path d="M0 1180L400 1180 470 1050 540 1160 610 1010 690 1180 1080 1180V1920H0Z" fill="#1a0f3a"/>
 <path d="M300 1180 540 690 780 1180" fill="none" stroke="#25f4ee" strokeWidth="7" opacity=".9"/>
 {Array.from({length:11},(_,i)=>{const k=i/10;const y=1200+k*k*700;const w=40+k*1020;return <path key={i} d={`M${540-w/2} ${y}H${540+w/2}`} stroke="#ff2e9a" strokeWidth={2+k*2} opacity={.35+.5*k}/>;})}
 {Array.from({length:9},(_,i)=>{const k=i/8;return <path key={i} d={`M${540+(k-.5)*1200} ${1920}L540 ${1210}`} stroke="#7a2bd4" strokeWidth="2.5" opacity={.4}/>;})}
 <text x="540" y={330} textAnchor="middle" fill="#25f4ee" fontFamily={mono} fontWeight="700" fontSize="176" letterSpacing="8" style={{textShadow:'0 0 40px rgba(37,244,238,.8)'}}>驶向</text>
 <text x="540" y={500} textAnchor="middle" fill="#ff2e9a" fontFamily={mono} fontWeight="700" fontSize="176" letterSpacing="8">明天</text>
 <text x="540" y={585} textAnchor="middle" fill="#b79bff" fontFamily={mono} fontSize="30" letterSpacing="12">SYS:1986 // ONLINE</text>
 <Text y={1650} size={46} color="#e6d9ff" weight={500} spacing={3}>夜色和公路，都归你。</Text><Label y={1745} text="OUTRUN / NEON / HORIZON" color="#25f4ee"/>
</Canvas>;};

const Glass=({t}:{t:number})=>{const r=reveal(t);
return <Canvas bg="#0f1424">
 <circle cx="300" cy="620" r="330" fill="#3e7bfa" opacity=".5" filter="blur(90px)"/><circle cx="780" cy="900" r="300" fill="#b15cff" opacity=".45" filter="blur(90px)"/><circle cx="520" cy="1320" r="280" fill="#26e0c4" opacity=".4" filter="blur(90px)"/>
 <g transform={`translate(540 ${1000}) rotate(${-8+cyc(t)*4})`}>
 <rect x="-320" y="-230" width="640" height="460" rx="42" fill="rgba(255,255,255,.10)" stroke="rgba(255,255,255,.36)" strokeWidth="2.5"/>
 <rect x="-320" y="-230" width="640" height="230" rx="42" fill="rgba(255,255,255,.07)"/>
 <path d="M-320 -60h640M-140 -230v460M60 -230v460" stroke="rgba(255,255,255,.14)" strokeWidth="2"/>
 <circle cx="150" cy="-90" r="74" fill="none" stroke="#8ff7e6" strokeWidth="4" opacity=".9"/><circle cx="150" cy="-90" r="26" fill="#8ff7e6" opacity=".8"/>
 <path d="M-240 90h330" stroke="#fff" strokeWidth="9" opacity=".75" strokeLinecap="round"/><path d="M-240 140h210" stroke="#fff" strokeWidth="7" opacity=".45" strokeLinecap="round"/>
 </g>
 <g transform={`translate(${cyc(t,2)*14} ${cyc(t,3)*10})`}><rect x="640" y="500" width="300" height="210" rx="26" fill="rgba(255,255,255,.08)" stroke="rgba(255,255,255,.3)" transform="rotate(9 790 605)"/></g>
 <g transform={`translate(0 ${(1-r)*30})`}><Text y={330} size={170} color="#fff" spacing={0}>光有形状</Text><Text y={470} size={44} weight={500} spacing={6} color="#c6d2f0">安静，也是一种音量。</Text></g>
 <Text y={1680} size={54} color="#eef2ff" weight={600} spacing={4}>把氛围留给内容。</Text><Rule y={1724} color="#26e0c4"/><Label y={1810} text="AURORA / FROST / CALM" color="#8ff7e6"/>
</Canvas>;};

const Pixel=({t}:{t:number})=>{const px=(x:number,y:number,w=1,h=1,c='#0c1024')=><rect x={88+x*20} y={520+y*20} width={w*20} height={h*20} fill={c}/>;
const flame=[['#ffd23f','#ff9f1c','#ff5d1f','#c9302c'],['#ffb703','#ff7b00','#e8491d','#a4262c'],['#ffe08a','#ffa94d','#ff6b35','#8f2018']][Math.floor(t*8)%3];
return <Canvas bg="#0c1024">
 {Array.from({length:45},(_,i)=>px(i,24,1,1,'#12172c'))}{Array.from({length:45},(_,i)=>px(0,i,1,1,'#0e1226'))}
 {[[30,2],[6,5],[38,7],[14,10],[41,13],[3,16],[27,4]].map(([x,y],i)=><rect key={i} x={88+x*20} y={520+y*20} width={10} height={10} fill={i%2?'#9ff2e0':'#ffd23f'} opacity={.5+.5*Math.abs(Math.sin(t*3+i))}/>)}
 {[[14,4],[15,3],[16,4],[13,5],[17,5],[13,6],[17,6],[14,7],[15,7],[16,7]].map(([x,y],i)=><rect key={i} x={88+x*20} y={520+y*20} width={20} height={20} fill="#ff4d6d"/>)}
 <g transform={`translate(540 ${980+cyc(t)*14})`}>
 <rect x="-66" y="-220" width="132" height="260" rx="10" fill="#e8ecf5"/><rect x="-66" y="-90" width="132" height="130" fill="#274bd7"/><rect x="-40" y="-150" width="24" height="40" rx="12" fill="#0c1024"/><rect x="16" y="-150" width="24" height="40" rx="12" fill="#0c1024"/><rect x="-100" y="-40" width="34" height="130" fill="#f2713f"/><rect x="66" y="-40" width="34" height="130" fill="#f2713f"/><polygon points="-34,40 34,40 0,110" fill="#ff9f43"/>
 {[0,1,2,3].map(i=><rect key={i} x={-36+i*18} y={112+i*22} width={72-i*30} height={26} fill={flame[i%4]}/>)}{[0,1,2].map(i=><rect key={'l'+i} x={-104} y={92+i*26} width={30-i*8} height={22} fill={flame[i%4]}/>)}{[0,1,2].map(i=><rect key={'r'+i} x={74} y={92+i*26} width={30-i*8} height={22} fill={flame[(i+1)%4]}/>)}
 </g>
 {[[10,15],[16,16],[22,14],[28,16],[34,15]].map(([x,y],i)=><rect key={'st'+i} x={88+x*20} y={520+y*20} width={12} height={12} fill="#9ff2e0" opacity={.35+.5*Math.abs(Math.sin(t*2.6+i*1.3))}/>)}
 {Array.from({length:6},(_,i)=><rect key={'p'+i} x={88+(34-i*3)*20} y={520+(17+Math.floor(i/2))*20} width={14} height={10} fill="#9ff2e0" opacity={.2+.14*i}/>)}
 <text x="88" y="440" fill="#9ff2e0" fontFamily={mono} fontWeight="700" fontSize="150" letterSpacing="-2">NEW ORBIT</text>
 <text x="88" y={510} fill="#e8ecf5" fontFamily={sans} fontWeight="800" fontSize="52">像素新世界</text>
 <text x="88" y={1620} fill="#e8ecf5" fontFamily={sans} fontWeight="800" fontSize="54">去没有去过的轨道。</text>
 <Label y={1710} text="PRESS START / 1UP" color="#9ff2e0"/><rect x={88} y={1760} width={Math.abs(cyc(t))*904} height="12" fill="#9ff2e0"/>
</Canvas>;};

export const LuminousShowcase:React.FC<{styleId:string}>=({styleId})=>{const t=clock();switch(styleId){case'mg-hud':return <Hud t={t}/>;case'mg-liquid':return <Liquid t={t}/>;case'mg-synthwave':return <Synth t={t}/>;case'mg-aurora-glass':return <Glass t={t}/>;default:return <Pixel {...{t}}/>;}};
