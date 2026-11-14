import React from 'react';
import {Canvas,Label,Text,Rule,sans,serif,mono,clock,cyc,reveal} from './Common';

const Phone:React.FC<{t:number}>=({t})=><g transform={`translate(330 650) rotate(${-12+cyc(t)*3} 235 360)`}>
 <rect x="-14" y="-14" width="498" height="748" rx="76" fill="#fff" stroke="#171e30" strokeWidth="3"/>
 <rect width="470" height="720" rx="62" fill="#202a42"/><rect x="24" y="28" width="422" height="664" rx="40" fill="#d9eaff"/>
 <rect x="155" y="36" width="160" height="24" rx="12" fill="#202a42"/>
 <circle cx="236" cy="295" r="135" fill="#345de7"/><path d="M181 288l42 44 77-93" fill="none" stroke="#f7e991" strokeWidth="22" strokeLinecap="round" strokeLinejoin="round"/>
 <rect x="68" y="490" width="334" height="100" rx="20" fill="#fff"/><text x="235" y="552" textAnchor="middle" fontFamily={sans} fontWeight="800" fontSize="36" fill="#202a42">灵感，已接通</text>
</g>;
const Paperclip=({t}:{t:number})=><Canvas bg="#f7f0dc">
 <Label y={115} text="CUT / PASTE / PLAY" color="#3156cf"/><Text y={330} size={172} color="#182540">别眨眼</Text>
 <Text y={465} size={88} weight={600} color="#3156cf">好点子，正在发生。</Text>
 <g transform={`translate(0 ${30*(1-reveal(t))})`}><Phone t={t}/></g>
 <g transform={`translate(80 ${820+cyc(t,1)*18}) rotate(-13)`}><rect x="-8" y="-8" width="265" height="150" rx="21" fill="#fff"/><rect width="250" height="135" rx="15" fill="#f27f62"/><text x="125" y="87" textAnchor="middle" fontFamily={sans} fontSize="62" fontWeight="900" fill="#182540">灵感爆发</text></g>
 <g transform={`translate(740 ${1380+cyc(t,2)*15}) rotate(9)`}><rect x="-10" y="-10" width="210" height="164" rx="12" fill="#fff"/><rect width="190" height="144" rx="6" fill="#eddd74"/><path d="M38 70h110m-40-38 40 38-40 38" stroke="#182540" strokeWidth="12" fill="none"/></g>
 <path d="M123 1440q-85-300 116-435m674-390q130 225-2 410" stroke="#3156cf" strokeWidth="6" strokeDasharray="13 18" fill="none"/>
 <circle cx={180+cyc(t)*15} cy="1330" r="58" fill="#345de7" stroke="#fff" strokeWidth="13"/><path d="M155 1330h50m-25-25v50" stroke="#fff" strokeWidth="7"/>
 <Rule y={1680} color="#3156cf"/><Text y={1770} size={44} spacing={0} color="#182540">剪贴之间，故事就有了形状。</Text><Label y={1840} text="STICKER STORIES / 01" color="#3156cf"/>
</Canvas>;

const Collage=({t}:{t:number})=><Canvas bg="#e6dcc3">
 <rect x="42" y="42" width="996" height="1836" fill="#f3ecd9" stroke="#2e302b" strokeWidth="2"/>
 <Label y={118} text="THE TOMORROW JOURNAL"/><Rule y={155}/><Text y={350} size={170} font={serif}>明日来信</Text><Text y={435} size={42} weight={500} spacing={8} font={serif}>把时间剪开，看看另一面。</Text>
 <g transform={`rotate(${-4+cyc(t)*1.2} 540 1050)`}><path d="M140 560l88 12 70-15 98 12 85-10 92 12 112-14 100 11 140-13-8 870-99-13-119 17-88-14-125 12-92-13-101 17-116-16z" fill="#c5c2ad"/>
 <circle cx="600" cy={800+cyc(t,1)*12} r="195" fill="#eee8d0"/>
 {Array.from({length:15},(_,i)=><g key={i}><rect x={177+i*45} y={1050-(i%5)*73} width={37} height={380+(i%5)*73} fill={i%2?'#263333':'#51605a'}/><path d={`M${188+i*45} ${1080-(i%5)*73}v260`} stroke="#d0c9ad" strokeWidth="6" strokeDasharray="8 13"/></g>)}
 <path d="M100 1410l870-200v275H100z" fill="#242c2a"/></g>
 <g transform={`translate(${cyc(t,2)*9} 0) rotate(4 790 660)`}><rect x="675" y="510" width="225" height="70" fill="#ca4936"/><text x="789" y="559" textAnchor="middle" fontFamily={mono} fontSize="31" fill="#f3ecd9">SPECIAL ISSUE</text></g>
 <path d="M120 1530h810M120 1550h750M120 1570h805M120 1590h648" stroke="#6a6a5a" strokeWidth="5"/>
 <Text y={1720} size={56} font={serif} spacing={2}>过去没有消失，只是换了一个版面。</Text><Label y={1810} text="PAPER / MEMORY / TOMORROW" color="#b24333"/>
</Canvas>;

const LineArt=({t}:{t:number})=>{const draw=reveal(t,.1);return <Canvas bg="#f8f6ee">
 <Label y={128} text="A MOMENT TO NOTICE"/><Text y={345} size={152} font={serif} weight={500}>慢一点</Text><Text y={505} size={152} font={serif} weight={500}>看清楚</Text>
 <circle cx="855" cy="260" r="84" fill="#dae765"/>
 <g fill="none" stroke="#29332f" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" strokeDasharray="5000" strokeDashoffset={5000*(1-draw)}>
 <path d="M105 1420H975M230 1410l50-320h285l32 320M280 1090l-28-55 315 6-2 49M322 1050q-42-240 72-475M377 1050q94-224 250-432M444 1040q-23-202 65-363"/>
 <path d={`M374 720q-260-145-181-262 228 34 181 262m-5 100q-228-52-205-163 192-31 205 163m31-192q35-240 160-229 36 168-160 229m51 168q68-223 198-169-3 170-198 169m67 90q165-201 244-90-81 150-244 90`}/>
 <path d="M688 1267h159v154H688zM847 1290q114-20 79 67-18 41-79 30M717 1205q-18-34 5-59m65 59q-18-34 5-59"/>
 </g><g stroke="#29332f" strokeWidth="2" opacity=".35">{Array.from({length:12},(_,i)=><path key={i} d={`M${281+i*22} 1393l25-108`}/>)}</g>
 <path d={`M590 1520q190 ${cyc(t)*12} 390-15`} stroke="#29332f" strokeWidth="2" fill="none"/>
 <Text y={1690} size={47} weight={400} spacing={3} font={serif}>风有形状，生活也有。</Text><Label y={1818} text="INK ON PAPER / 03"/>
</Canvas>;};

const Cel=({t}:{t:number})=>{const j=Math.sin(Math.floor(t*12)*2.1)*2.4;const step=cyc(t*2);return <Canvas bg="#ffc349">
 <circle cx="915" cy="345" r="220" fill="#f78137"/><Label y={118} text="GO YOUR OWN WAY" color="#362921"/>
 <Text y={355} size={152} color="#362921">走自己的路</Text><Text y={455} size={48} weight={500} spacing={4} color="#362921">不着急，也不停下。</Text>
 <g transform={`translate(${j} ${cyc(t)*12})`} stroke="#362921" strokeWidth="12" strokeLinecap="round" strokeLinejoin="round">
 <path d="M245 1370l630-60M335 1365l-50 69m507-105 55 66" fill="none"/><circle cx="326" cy="1443" r="38" fill="#362921"/><circle cx="802" cy="1389" r="38" fill="#362921"/>
 <path d={`M510 1115l${-110+step*20} 160-115 65M590 1120l${95-step*22} 115 94 74`} fill="none" strokeWidth="64"/>
 <path d="M480 823q-63 130-42 317l232 1-30-269q-39-95-160-49z" fill="#f5643c"/>
 <path d={`M471 884l-107 100-86-18M623 889l80 98 105-33`} fill="none" strokeWidth="40"/>
 <path d="M501 770l-15 77 113 9-10-90" fill="#f5e2b5"/>
 <ellipse cx="548" cy="668" rx="118" ry="131" fill="#f5e2b5"/><path d="M428 650q-21-177 111-176 140 8 129 161l-96-61-144 76z" fill="#362921"/>
 <path d="M479 671l25-5m77-2 26 6m-63 13-9 34h27m-59 25q39 41 77 0" fill="none" strokeWidth="7"/>
 <path d="M450 545q125-99 206 36" fill="none" stroke="#f3efdc" strokeWidth="14"/>
 </g><path d="M110 1100h110m-90 55h92m630-350h88m-61 55h96" stroke="#362921" strokeWidth="7" strokeLinecap="round"/>
 <Text y={1690} size={90} color="#362921">每一步，都是自己的。</Text><Label y={1815} text="DRAWN BY HAND / MOVED BY YOU" color="#362921"/>
</Canvas>;};

const Hanzi=({t}:{t:number})=><Canvas bg="#f0eee7">
 <Label y={125} text="FORM / LIFE / GROWTH"/><path d="M88 174H992" stroke="#161b19" strokeWidth="3"/>
 <text x="62" y="870" fill="#161b19" fontFamily={serif} fontWeight="900" fontSize="665" letterSpacing="-52">生</text>
 <text x="397" y="1470" fill="#161b19" fontFamily={serif} fontWeight="900" fontSize="615" letterSpacing="-52">长</text>
 <g fill="none" stroke="#c94735" strokeWidth="10" strokeLinecap="round" strokeDasharray="2500" strokeDashoffset={2500*(1-reveal(t,.15))}>
 <path d="M116 1520q334-377 461-725T851 361M580 788q192-7 248-145-186-55-248 145M486 995q-173-3-215-142 186-54 215 142M703 538q-118-47-96-164 153 11 96 164"/>
 </g><g transform={`rotate(${-4+cyc(t)*.8} 172 1220)`}><rect x="102" y="1140" width="145" height="145" fill="#c94735"/><text x="175" y="1243" fill="#f0eee7" textAnchor="middle" fontFamily={serif} fontSize="91" fontWeight="900">向</text></g>
 <Rule y={1655}/><Text y={1753} size={66} font={serif} weight={600} spacing={10}>一笔一画，自有方向。</Text><Label y={1835} text="汉字，是有生命的形状。" size={25}/>
</Canvas>;

export const EditorialShowcase:React.FC<{styleId:string}>=({styleId})=>{const t=clock();switch(styleId){case'mg-paperclip':return <Paperclip t={t}/>;case'mg-collage':return <Collage t={t}/>;case'mg-line-art':return <LineArt t={t}/>;case'mg-cel-boil':return <Cel t={t}/>;default:return <Hanzi t={t}/>;}};
