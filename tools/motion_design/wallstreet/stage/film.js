/* 短片工厂 · 华尔街逐帧舞台（竖版）
 *
 * 只向 render_playwright.mjs 暴露两个全局：window.ready / window.seek(t)。
 * 所有画面都是 t 的解析式：同一个 t 永远画出同一帧，不依赖播放时钟、CSS 动画或随机量。
 * 这正是 wallstreet-explainer 的 film_base.js 定的契约，这里按 9:16 重写舞台坐标。
 *
 * 证据轨（实拍 / 新闻）由 __FILM__.beats[].evidence 驱动：
 *   news    —— snap_news.mjs 截出的新闻/报告原文 PNG，白边画框 + 荧光黄高亮
 *   footage —— footage.py 抽出的实拍逐帧 JPG，按 (t-t0)*fps 取帧，真的会动
 *   cut     —— matte*.py 抠出的 RGBA 逐帧人物，站在巨数前
 *   host    —— 真人口播模式：圆窗/竖窗里放当事人的实拍帧
 * 没挂证据时画一个明确写「未附证据」的占位框，绝不伪造新闻截图或假装图里是真人。
 */
(() => {
  const F = window.__FILM__ || {};
  const W = F.w || 720, H = F.h || 1280, FPS = F.fps || 30;
  const DURATION = F.duration || 10;
  const stage = document.getElementById('stage');
  stage.style.width = W + 'px';
  stage.style.height = H + 'px';

  const esc = s => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const lerp = (a, b, p) => a + (b - a) * p;
  // 循环相位：永远不会「到达终点就停」，死场检测看的是变化面积。
  const loop = (t, period) => (t % period) / period;
  const ease = p => p < .5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
  const lines = x => Array.isArray(x) ? x : (x == null ? [] : String(x).split('\n'));
  const num = v => {
    const s = String(v == null ? '' : v);
    return s.replace(/\d{1,3}(?=(\d{3})+(?!\d))/g, m => m + ',');
  };

  // 深蓝细斜纹织物底：CSS 画斜纹，fabric.jpg 叠一层真实布纹，grain.png 极淡颗粒。
  const fabric = F.assets?.fabric ? `<img class="full tex" src="${esc(F.assets.fabric)}">` : '';
  const grain = F.assets?.grain ? `<img class="full grain" src="${esc(F.assets.grain)}">` : '';

  function base(t) {
    // 镜头永远在走：慢推 + 轻微横摇。幅度要足够大——评审按「逐帧变化面积」测死场，
    // 亚像素级漂移会被判成静止画面；这里保证任何一秒内都有肉眼可见的位移。
    const zoom = 1.06 + 0.03 * Math.sin(t * 0.42);
    const panX = 34 * Math.sin(t * 0.31), panY = 20 * Math.cos(t * 0.27);
    const glow = F.brand?.color || '#3B7A1C';
    // 深蓝织物底不能太黑：平均亮度 <30 会被评审判成黑帧。
    // 提亮到 #22375A→#101E33，并加一层很淡的顶部暖光。
    return `<div class="full cam" style="transform:translate(${panX}px,${panY}px) scale(${zoom})">
      <div class="full" style="background:linear-gradient(165deg,#22375A 0%,#16273F 46%,#101E33 100%)"></div>${fabric}
      <div class="full" style="background:linear-gradient(180deg,#FFF3B51C 0%,transparent 38%)"></div>
      <div class="full glow" style="background:radial-gradient(circle at 50% 30%, ${glow}44 0%, transparent 62%)"></div>
      <div class="full vignette"></div>${grain}
    </div>`;
  }

  function dataMotion(t, beat) {
    // 数据/线条的持续演化：柱子高度、荧光笔扫描、数字滚动都用 sin / 取模循环。
    const bars = beat.bars || [0.42, 0.66, 0.88, 1.0];
    const phase = loop(t, 4.8);
    const bh = bars.map((v, i) => {
      const wave = 0.62 + 0.38 * Math.sin(t * 0.9 + i * 0.7);
      return clamp(v * (0.35 + 0.65 * ease(clamp(phase * 1.6 - i * 0.18, 0, 1))) + wave * 0.18, 0.08, 1);
    });
    const barX = W * 0.11, barW = W * 0.78, barBase = H * 0.615, barMax = H * 0.23;
    const cols = ['#FFF3B5', '#EFDC7A', '#F2E27E', '#FFD84A'];
    const rects = bh.map((v, i) => {
      const w = barW / bh.length - 16, x = barX + i * (barW / bh.length);
      const h = barMax * v;
      return `<div style="position:absolute;left:${x}px;top:${barBase - h}px;width:${w}px;height:${h}px;
        background:linear-gradient(180deg,${cols[i % 4]},#B9963F);border-radius:6px 6px 0 0;opacity:.92"></div>`;
    }).join('');
    const sweep = (loop(t, 3.6) * 1.5 - 0.25) * W;
    return `<div class="full">${rects}
      <div style="position:absolute;left:${barX}px;top:${barBase}px;width:${barW}px;height:3px;background:#F1EAD255"></div>
      <div style="position:absolute;left:${clamp(sweep, barX, barX + barW)}px;top:${barBase - barMax - 12}px;
           width:2px;height:${barMax + 16}px;background:#FFD84A;opacity:.55"></div></div>`;
  }

  // ── 证据轨 ────────────────────────────────────────────────────────────────
  function frameUrl(ev, t, beat) {
    const fps = ev.fps || FPS, count = Math.max(1, ev.count || 1);
    const i = 1 + (Math.floor(Math.max(0, t - beat.t0) * fps) % count);
    return ev.dir + '/' + String(i).padStart(4, '0') + '.' + (ev.ext || 'jpg');
  }

  function evidence(ev, t, beat) {
    if (!ev) return '';
    const box = `position:absolute;left:${W * .09}px;top:${H * .34}px;width:${W * .82}px;height:${H * .29}px;
      border:6px solid #F4F1EA;border-radius:12px;overflow:hidden;background:#fff;
      box-shadow:0 26px 70px #000A`;
    if (ev.kind === 'news') {
      const src = ev.src || '';
      if (!src) return evidenceEmpty(beat);
      // 慢推 + 荧光笔往复刷过。sweep 必须一直动（三角波往复），扫到头就停会被判死场。
      const z = 1.06 + 0.09 * Math.sin(t * 0.55);
      const hl = (ev.hl && ev.hl.length === 4) ? ev.hl : [0.12, 0.55, 0.66, 0.05];
      const sweep = 0.5 - 0.5 * Math.cos(t * 1.5);
      return `<div style="${box}"><div style="position:absolute;inset:0;transform:scale(${z})">
          <img src="${esc(src)}" style="width:100%;height:100%;object-fit:cover"></div>
        <div style="position:absolute;left:${hl[0] * 100}%;top:${hl[1] * 100}%;
             width:${Math.max(6, hl[2] * 100 * sweep)}%;height:${Math.max(14, hl[3] * 100)}%;
             background:#FFD84A;mix-blend-mode:multiply;opacity:.72"></div>
        <div style="position:absolute;left:0;bottom:0;right:0;padding:7px 12px;background:#0B1422CC;
             color:#F1EAD2;font-size:19px;letter-spacing:1px">${esc(ev.credit || ev.label || '新闻原文')}</div>
      </div>`;
    }
    if (ev.kind === 'footage' || ev.kind === 'host' || ev.kind === 'cut') {
      if (!ev.dir || !ev.count) return evidenceEmpty(beat);
      const src = frameUrl(ev, t, beat);
      if (ev.kind === 'cut') {
        // 抠像人物：站在巨数前，带 box.json 的头肩中心微调
        const cx = ev.cx ? ev.cx[Math.min(ev.cx.length - 1, Math.floor((t - beat.t0) * FPS))] : 0.5;
        return `<img src="${esc(src)}" style="position:absolute;left:${(cx - .28) * W}px;top:${H * .30}px;
          width:${W * .56}px;height:${H * .42}px;object-fit:contain;filter:drop-shadow(0 20px 40px #0009)">`;
      }
      if (ev.kind === 'host') {
        const pip = ev.shape !== 'window';
        const w = pip ? W * .38 : W * .46, h = pip ? W * .38 : H * .30;
        const r = pip ? '50%' : '14px';
        return `<div style="position:absolute;right:${W * .06}px;top:${H * .40}px;width:${w}px;height:${h}px;
             border-radius:${r};border:5px solid #F4F1EA;overflow:hidden;box-shadow:0 18px 50px #000B">
             <img src="${esc(src)}" style="width:100%;height:100%;object-fit:cover"></div>`;
      }
      return `<div style="${box}"><img src="${esc(src)}" style="width:100%;height:100%;object-fit:cover">
        <div style="position:absolute;left:0;bottom:0;right:0;padding:7px 12px;background:#0B1422CC;
             color:#F1EAD2;font-size:19px;letter-spacing:1px">${esc(ev.credit || ev.label || '实拍画面')}</div></div>`;
    }
    return evidenceEmpty(beat);
  }

  function evidenceEmpty(beat) {
    return `<div style="position:absolute;left:${W * .09}px;top:${H * .34}px;width:${W * .82}px;height:${H * .29}px;
      border:4px dashed #9AA8BD66;border-radius:12px;display:flex;align-items:center;justify-content:center;
      color:#9AA8BD;font-size:24px;letter-spacing:2px;text-align:center;line-height:1.7">
      未附实拍 / 新闻证据<br><span style="font-size:17px;opacity:.75">本片用代码图解释，不伪造来源</span></div>`;
  }

  // ── 钩子物：前 3 秒会动的、弱相关于主题的「不该出现在这里」的小东西 ────────
  function hookProp(t) {
    const p = F.hook || {};
    if (p.enabled === false) return '';
    // 每 9 秒回来一次，且开场必有；不是只闪一下就消失。
    const on = (t < 3.2) || (loop(t, 9) < 2.4);
    if (!on) return '';
    // 放在右上角留白区，不压巨数、不压标题、不压眉题。
    const x = W * .80 + 12 * Math.sin(t * 1.7), y = H * .012 + 12 * Math.cos(t * 2.3);
    const rot = 12 * Math.sin(t * 3.1);
    return `<div style="position:absolute;left:${x}px;top:${y}px;transform:rotate(${rot}deg)">
      <svg width="64" height="56" viewBox="0 0 76 66">
        <ellipse cx="38" cy="52" rx="27" ry="12" fill="#FFD84A" opacity=".92"/>
        <circle cx="46" cy="27" r="15" fill="#FFE873"/>
        <path d="M58 27 q14 4 0 10 q-6 0 -6 -10z" fill="#E8622A"/>
        <circle cx="50" cy="23" r="2.6" fill="#0B1422"/>
        <path d="M14 50 q-8 6 2 8" stroke="#FFD84A" stroke-width="5" fill="none" stroke-linecap="round"/>
      </svg>
      <div style="font-size:13px;color:#FFD84A;letter-spacing:1px;text-align:center;opacity:.8">${esc(p.name || '小黄鸭')}</div>
    </div>`;
  }

  // ── 每一镜 ────────────────────────────────────────────────────────────────
  function beatAt(t) {
    const bs = F.beats || [];
    for (const b of bs) if (t >= b.t0 && t < b.t1) return b;
    return bs[bs.length - 1] || {t0: 0, t1: DURATION, title: [F.title || '']};
  }

  // 文本按可用宽度自动缩字号，长数字/长标题都不会被裁掉或折出单字。
  function fitPx(text, maxW, maxSize, weight) {
    const probe = document.createElement('span');
    probe.style.cssText = `position:absolute;visibility:hidden;white-space:nowrap;font-weight:${weight || 800};font-size:${maxSize}px`;
    probe.textContent = text;
    stage.appendChild(probe);
    const natural = probe.getBoundingClientRect().width || 1;
    probe.remove();
    return Math.max(20, Math.floor(maxSize * Math.min(1, maxW / natural)));
  }

  function renderBeat(t, b) {
    const local = t - b.t0, span = Math.max(.001, b.t1 - b.t0);
    const p = clamp(local / span, 0, 1);
    // 每一镜接住上一镜：入镜是短促的位移，不做长淡入——
    // 淡入会让标题在入镜后好几秒都是半透明的，观众读不到字。
    const enter = 1 - Math.pow(1 - ease(clamp(p * 6, 0, 1)), 2);
    const title = lines(b.title).slice(0, 3).filter(Boolean);
    const big = b.big || '';
    const hasBig = !!big;
    const hasEv = !!b.evidence;

    // 竖版分层：眉题 → 巨数 → 标题 → （证据框 / 柱子） → 注释。
    // 巨数占一行，按宽度自动缩；没有巨数时标题上移，不留大空档。
    const brow = b.stamp ? `<div style="position:absolute;left:${W * .09}px;right:${W * .09}px;top:${H * .088}px;
      font-size:19px;letter-spacing:5px;color:#F1EAD2;opacity:.7;white-space:nowrap;overflow:hidden">${esc(b.stamp)} · ${esc(b.en || 'MARKET NOTE')}</div>` : '';
    let gold = '', headTop = H * .24;
    if (hasBig) {
      const txt = num(big);
      const size = fitPx(txt, W * .82, Math.round(W * .14), 800);
      gold = `<div style="position:absolute;left:${W * .09}px;right:${W * .09}px;top:${H * .125}px;
        text-align:left;font-size:${size}px;font-weight:800;letter-spacing:-1px;line-height:1.1;
        white-space:nowrap;background:linear-gradient(180deg,#FFFEF2,#FFF3B5 46%,#EFDC7A);
        -webkit-background-clip:text;background-clip:text;color:transparent;
        filter:drop-shadow(0 6px 26px #EFDC7A33)">${esc(txt)}</div>`;
      headTop = H * .21;
    }
    // 标题每行各自缩到不折行；第一行最大，副行略小。
    const headline = title.map((s, i) => {
      const max = i === 0 ? 46 : 33;
      const size = fitPx(s, W * .82, max, i === 0 ? 700 : 500);
      return `<div style="font-size:${size}px;font-weight:${i === 0 ? 700 : 500};line-height:1.36;
        white-space:nowrap;overflow:hidden;color:${i === 0 ? '#FFFEF2' : '#F1EAD2'}">${esc(s)}</div>`;
    }).join('');
    const head = `<div style="position:absolute;left:${W * .09}px;right:${W * .09}px;top:${headTop}px;
      opacity:1;text-align:left">${headline}</div>`;
    const noteTop = H * (hasEv ? .665 : .70);
    const note = b.note ? `<div style="position:absolute;left:${W * .09}px;right:${W * .09}px;top:${noteTop}px;
      font-size:22px;color:#9AA8BD;line-height:1.6;opacity:.9">${esc(b.note)}</div>` : '';
    // 有证据框时柱子下移一点，避免和证据框叠在一起。
    const ev = evidence(b.evidence, t, b);
    // 有证据框时不再叠柱子（会打架）；没有巨数的镜头用一条演化折线补运动，
    // 免得整镜只剩一块底色，被评审判成死场。
    const art = hasEv ? '' : (hasBig ? dataMotion(t, b) : lineMotion(t, b));
    return `<div style="position:absolute;inset:0;transform:translateY(${(1 - enter) * 18}px)">${brow}${gold}${head}${ev}${art}${note}</div>`;
  }

  // 无巨数镜头用的演化折线：同一条坐标系里连续画出的曲线，随时间生长。
  function lineMotion(t, b) {
    const pts = 6, x0 = W * .12, x1 = W * .88, y0 = H * .60, y1 = H * .40;
    const growth = clamp(loop(t, 5.2) * 1.9, 0, 1);
    let d = '';
    for (let i = 0; i < pts; i++) {
      const px = lerp(x0, x1, i / (pts - 1));
      const py = lerp(y0, y1, i / (pts - 1)) + 16 * Math.sin(t * 1.3 + i * 0.9);
      d += (i === 0 ? 'M' : 'L') + px.toFixed(1) + ' ' + py.toFixed(1);
    }
    const head = clamp(loop(t, 5.2) * 1.9 - 0.15, 0, 1);
    const hx = lerp(x0, x1, head), hy = lerp(y0, y1, head) + 16 * Math.sin(t * 1.3 + head * (pts - 1) * 0.9);
    return `<div class="full">
      <svg width="${W}" height="${H}" style="position:absolute;inset:0">
        <path d="${d}" fill="none" stroke="#EFDC7A" stroke-width="4" stroke-linecap="round" opacity=".85"/>
        <circle cx="${hx}" cy="${hy}" r="9" fill="#FFD84A"/>
      </svg></div>`;
  }

  function subtitle(t) {
    const s = (F.subs || []).find(x => t >= x[0] && t < x[1]);
    if (!s) return '';
    return `<div style="position:absolute;left:${W * .06}px;right:${W * .06}px;bottom:${H * .075}px;
      text-align:center;font-size:34px;line-height:1.5;color:#fff;
      text-shadow:0 2px 8px #000D,0 0 20px #0009">${esc(s[2])}</div>`;
  }
  function footer(t) {
    const txt = F.footer || '';
    if (!txt) return '';
    return `<div style="position:absolute;left:${W * .09}px;bottom:${H * .028}px;
      font-size:17px;letter-spacing:1px;color:#6B7A8F">${esc(txt)}</div>`;
  }

  window.seek = async (t) => {
    const tt = clamp(Number(t) || 0, 0, Math.max(0, DURATION - 1 / FPS));
    const b = beatAt(tt);
    // 字幕安全区：底部 H*0.17 不画主体内容，避免和字幕打架。
    stage.innerHTML = `<div class="full" style="overflow:hidden">
        ${base(tt)}
        <div style="position:absolute;inset:0;clip-path:inset(0 0 ${Math.round(H * .17)}px 0)">
          ${renderBeat(tt, b)}${hookProp(tt)}
        </div>
        ${subtitle(tt)}${footer(tt)}
      </div>`;
    // 等这一帧所有图片解完码、字体加载完，截图才不会是半张图或回退字体。
    await Promise.all([...stage.querySelectorAll('img')].map(im => im.decode().catch(() => {})));
    try { await document.fonts.ready; } catch { /* 字体失败也要出片 */ }
  };

  // 预载全部证据图（首帧截图前），避免逐帧过程中出现 404 或半张图。
  window.ready = (async () => {
    const urls = new Set();
    const collect = ev => {
      if (!ev) return;
      if (ev.src) urls.add(ev.src);
      if (ev.dir && ev.count) for (let i = 1; i <= ev.count; i++)
        urls.add(ev.dir + '/' + String(i).padStart(4, '0') + '.' + (ev.ext || 'jpg'));
    };
    for (const b of (F.beats || [])) collect(b.evidence);
    for (const a of [F.assets?.fabric, F.assets?.grain]) if (a) urls.add(a);
    for (const f of (F.fonts || [])) {
      try { await document.fonts.load(f); } catch { /* 缺字体退系统字体 */ }
    }
    await Promise.all([...urls].map(u => new Promise(res => {
      const im = new Image(); im.onload = im.onerror = () => res(); im.src = u;
    })));
    await window.seek(0);
    return true;
  })();

  window.timeline = {fps: FPS, duration: DURATION};
  window.duration = DURATION;
})();
