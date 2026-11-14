// Playwright 逐帧渲染器（短片工厂 · 竖版）
//
// 协议与 HeyChengC/wallstreet-explainer/scripts/render.mjs 完全一致：
//   window.ready  : Promise —— 字体 / 图片全部就绪后才允许截第一帧
//   window.seek(t): async (t:number) => 画出「第 t 秒那一帧」；同一个 t 永远画出同一帧
//   timeline.json : { fps, duration } —— 帧数 / 帧率 / 片长的唯一来源
//
// 相对原版补了三处（这是短片工厂必须自己做的）：
//   1. 竖版任意 W×H（原版写死 1920×1080 横版，套到 9:16 只会得到一条横带）。
//   2. 最后一环「音画合成」：原仓库只出无声画面 visual_*.mp4，
//      没有脚本把 mix_master.wav 合进去，靠 agent 手工 ffmpeg。这里直接出成片。
//   3. 浏览器优先用本机 Chrome/Edge（OE_BROWSER_EXE），这样分发包不用背 400MB
//      Chromium 缓存；实在没有才回落 Playwright 自带的 chromium。
//
// 用法（由 wallstreet_backend.py 调用，一般不用手敲）：
//   node render_playwright.mjs --dir <stage> --out <final.mp4> --work <临时目录>
//        --mode video --w 720 --h 1280 --fps 30 --duration 31.5
//        --crf 20 --workers 2 --audio <audio.wav>
//   node render_playwright.mjs --dir <stage> --out <still.png> --mode still
//        --frame 45 --w 720 --h 1280 --fps 30 --duration 31.5
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createRequire} from 'node:module';
import fsSync from 'node:fs';
import {fileURLToPath} from 'node:url';

const arg = k => { const i = process.argv.indexOf(k); return i >= 0 ? process.argv[i + 1] : null; };
const HERE = path.dirname(fileURLToPath(import.meta.url));

// Playwright 就在本目录的 node_modules 下（随分发包携带，19MB），不依赖全局安装。
function loadPlaywright() {
  const from = process.env.PLAYWRIGHT_FROM;
  for (const base of [from, path.join(HERE, 'render_playwright.mjs'), process.cwd() + '/package.json'].filter(Boolean)) {
    try { return createRequire(base)('playwright'); } catch { /* 换下一个 */ }
  }
  throw new Error('找不到 playwright：本目录应带 node_modules/playwright');
}
const {chromium} = loadPlaywright();

const FF = process.env.OE_FFMPEG || process.env.FFMPEG || 'ffmpeg';
const DIR = path.resolve(arg('--dir') || '.');
const OUT = path.resolve(arg('--out'));
const WORK = path.resolve(arg('--work') || path.join(DIR, '_render'));
const MODE = arg('--mode') || 'video';
const W = Number(arg('--w') || 720), H = Number(arg('--h') || 1280);
const FPS = Number(arg('--fps') || 30), DURATION = Number(arg('--duration') || 10);
const CRF = arg('--crf') || '20';
const WORKERS = Math.max(1, Number(arg('--workers') || 2));
const AUDIO = arg('--audio') || '';
const FRAME = Number(arg('--frame') || 0);
const PAGE = arg('--page') || 'index.html';
const WORKER = arg('--worker');           // "a:z"，父进程分好的帧区间
const PORT = Number(arg('--port') || 0);  // 0 = 自己是父进程，要起 http server

await fs.mkdir(WORK, {recursive: true});

// 本机浏览器候选：自带 chrome / edge 优先（离线、体积小），最后才用 Playwright 自带 chromium。
function browserCandidates() {
  const out = [];
  const over = process.env.OE_BROWSER_EXE;
  if (over) out.push(over);
  for (const p of [
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
    '/usr/bin/google-chrome', '/usr/bin/chromium',
  ]) if (fsSync.existsSync(p)) out.push(p);
  return out;
}
async function launch() {
  const opt = {headless: true, args: ['--force-color-profile=srgb', '--disable-lcd-text',
    '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--mute-audio']};
  for (const exe of browserCandidates()) {
    try { return await chromium.launch({...opt, executablePath: exe}); } catch { /* 换下一个 */ }
  }
  try { return await chromium.launch(opt); }
  catch (e) { return await chromium.launch({...opt, channel: 'msedge'}); }
}

const MIME = {'.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript',
  '.mjs': 'text/javascript', '.json': 'application/json', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.svg': 'image/svg+xml',
  '.ttf': 'font/ttf', '.otf': 'font/otf', '.woff2': 'font/woff2'};
let server;
if (!WORKER && !PORT) {
  server = http.createServer(async (q, r) => {
    try {
      const p = path.join(DIR, decodeURIComponent(new URL(q.url, 'http://x').pathname));
      const b = await fs.readFile(p);
      r.writeHead(200, {'Content-Type': MIME[path.extname(p)] || 'application/octet-stream'}).end(b);
    } catch { r.writeHead(404).end(); }
  });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
}
const port = PORT || server.address().port;

async function openPage() {
  const b = await launch();
  const p = await b.newPage({viewport: {width: W, height: H}, deviceScaleFactor: 1});
  const fatal = [], warns = [];
  // 只有页面脚本错误才是致命的。favicon.ico 之类的 404 会由浏览器自动发出，
  // 不能因为一条无关请求就让整条片子渲染失败（原版 render.mjs 也没把 404 当致命）。
  p.on('pageerror', e => fatal.push(e.message));
  p.on('console', m => { if (m.type() === 'error') warns.push(m.text()); });
  p.on('requestfailed', q => warns.push('请求失败 ' + q.url()));
  p.on('response', s => { if (s.status() >= 400) warns.push(s.status() + ' ' + s.url()); });
  try {
    await p.goto(`http://127.0.0.1:${port}/${PAGE}`);
    await p.evaluate(() => window.ready);
  } catch (e) {
    const msg = String(e.message).replace(/^page\.evaluate:\s*/, '').split('\n').slice(0, 20).join('\n');
    console.error('页面没跑起来：\n' + msg + (fatal.length ? '\n- ' + [...new Set(fatal)].slice(0, 8).join('\n- ') : ''));
    await b.close();
    process.exit(3);
  }
  return {b, p, fatal, warns};
}
function sh(args, opts = {}) {
  return new Promise((res, rej) => {
    const c = spawn(FF, args, {stdio: ['ignore', 'ignore', 'inherit'], ...opts});
    c.on('exit', x => x === 0 ? res() : rej(new Error('ffmpeg 退出码 ' + x)));
    c.on('error', rej);
  });
}

// ---------- 静帧（封面 / 预览关键帧） ----------
if (MODE === 'still') {
  const {b, p, warns} = await openPage();
  await p.evaluate(t => window.seek(t), FRAME / FPS);
  await p.screenshot({path: OUT, type: 'png'});
  await b.close(); server?.close();
  if (warns.length) console.log('页面请求警告：', [...new Set(warns)].slice(0, 6));
  console.log('still', FRAME, '->', OUT);
  process.exit(0);
}

// ---------- 逐帧编码：每个 worker 一个浏览器，JPEG 流直接喂 ffmpeg ----------
const N = Math.ceil(DURATION * FPS);
if (WORKER) {
  const [a, z] = WORKER.split(':').map(Number);
  const {b, p, warns} = await openPage();
  const seg = path.join(WORK, `seg_${a}.mp4`);
  const enc = spawn(FF, ['-v', 'error', '-y', '-f', 'image2pipe', '-vcodec', 'mjpeg',
    '-framerate', String(FPS), '-i', 'pipe:0', '-c:v', 'libx264', '-preset', 'medium',
    '-crf', CRF, '-pix_fmt', 'yuv420p', '-r', String(FPS), seg],
    {stdio: ['pipe', 'ignore', 'inherit']});
  for (let f = a; f < z; f++) {
    await p.evaluate(t => window.seek(t), f / FPS);
    const buf = await p.screenshot({type: 'jpeg', quality: 92});
    if (!enc.stdin.write(buf)) await once(enc.stdin, 'drain');
  }
  enc.stdin.end(); await once(enc, 'exit');
  await b.close();
  if (warns.length) console.error('页面请求警告：', [...new Set(warns)].slice(0, 6));
  process.exit(0);
}

// ---------- 父进程：分段 → concat → 音画合成 → 空画面自检 ----------
const t0 = Date.now();
const size = Math.ceil(N / WORKERS), starts = [];
const kids = [];
for (let i = 0; i < WORKERS; i++) {
  const a = i * size, z = Math.min(N, a + size);
  if (a >= z) continue;
  starts.push(a);
  kids.push(new Promise((res, rej) => {
    const c = spawn(process.execPath, [fileURLToPath(import.meta.url),
      '--dir', DIR, '--page', PAGE, '--out', OUT, '--work', WORK, '--mode', 'video',
      '--w', String(W), '--h', String(H), '--fps', String(FPS), '--duration', String(DURATION),
      '--crf', CRF, '--port', String(port), '--worker', `${a}:${z}`, '--audio', AUDIO],
      {stdio: 'inherit', env: process.env});
    c.on('exit', x => x === 0 ? res() : rej(new Error('worker ' + a + ' 退出码 ' + x)));
  }));
}
await Promise.all(kids);
starts.sort((a, b) => a - b);
const list = path.join(WORK, 'list.txt');
await fs.writeFile(list, starts.map(s => `file 'seg_${s}.mp4'`).join('\n'));
const visual = path.join(WORK, 'visual.mp4');
if (starts.length === 1) {
  await fs.copyFile(path.join(WORK, `seg_${starts[0]}.mp4`), visual);
} else {
  await sh(['-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', visual]);
}

// 原仓库缺的最后一环：把短片工厂 cmd_build 混好的 audio.wav 合进无声画面。
// audio.wav 已经是 -14 LUFS / 48k 立体声，直接转 AAC；视频流 copy，不重编码。
if (AUDIO && fsSync.existsSync(AUDIO)) {
  await sh(['-v', 'error', '-y', '-i', visual, '-i', AUDIO,
    '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
    '-shortest', '-movflags', '+faststart', OUT]);
} else {
  await fs.copyFile(visual, OUT);
}
server?.close();
console.log('rendered', N, 'frames in', ((Date.now() - t0) / 1000).toFixed(1), 's ->', OUT);

// 空画面自检：连续 ≥0.3 秒几乎纯色 = 标签没闭合 / 图片 404 / 时刻算错。
await new Promise(res => {
  const c = spawn(FF, ['-v', 'error', '-i', OUT, '-vf', 'scale=64:36',
    '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], {stdio: ['ignore', 'pipe', 'inherit']});
  const bufs = []; c.stdout.on('data', d => bufs.push(d));
  c.on('exit', () => {
    const all = Buffer.concat(bufs), n = 64 * 36, runs = []; let s = -1, f = 0;
    for (; (f + 1) * n <= all.length; f++) {
      let m = 0, q = 0;
      for (let i = f * n; i < (f + 1) * n; i++) { m += all[i]; q += all[i] * all[i]; }
      m /= n;
      const blank = Math.sqrt(Math.max(0, q / n - m * m)) < 3;
      if (blank && s < 0) s = f; else if (!blank && s >= 0) { runs.push([s, f]); s = -1; }
    }
    if (s >= 0) runs.push([s, f]);
    const bad = runs.filter(([a, z]) => z - a >= FPS * 0.3)
      .map(([a, z]) => `${(a / FPS).toFixed(2)}–${(z / FPS).toFixed(2)} 秒`);
    if (bad.length) console.log('画面是空的（几乎纯色）：' + bad.join('、') + '。查这几秒的镜头与图片路径。');
    res();
  });
});
