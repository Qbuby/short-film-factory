/* Local desktop studio. No external libraries, telemetry or credential persistence. */
'use strict';
(() => {
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const EXPECTED = {api: 2, version: '1.3.0'};
  const state = {
    view: 'new', health: false, catalog: false, settings: 'loading', configured: false,
    styles: [], types: [], voices: [], ratios: [], resolutions: [], fps: [], tiers: [], tier: 'standard',
    style: 'mg-paperclip', narration: 'voice', frameRate: '30', minDuration: 1, maxDuration: 120,
    audio: null, audioReading: false, audioRevision: 0, player: null, auditionRevision: 0,
    auditionLoading: false, activeTask: null, pending: false, uncertain: false,
    taskTimer: null, elapsedTimer: null, taskEpoch: 0, healthCount: 0,
    project: null, projectRequest: 0, projectLoading:false, editorSaving:false, scriptNeedsVoice:false, tab: 'script', drafts: {}, saved: {},
    projects: [], secrets: new Set(), settingsBusy: false, catalogBusy: false, healthBusy: false,
  };
  const previews = new StylePreviewPlayer();
  const icon = (name) => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  function redact(value) {
    let text = String(value ?? '');
    for (const secret of state.secrets) if (secret) text = text.split(secret).join('[密钥已隐藏]');
    return text.replace(/\b(?:sk-|sk_)[A-Za-z0-9_\-]{8,}/g, '[密钥已隐藏]')
      .replace(/(Bearer\s+)[A-Za-z0-9._~+\/-]+/gi, '$1[密钥已隐藏]')
      .replace(/((?:api[_-]?key|token|authorization)\s*[=:]\s*)[^\s&,;]+/gi, '$1[已隐藏]');
  }
  function message(selector, text, error = false) {
    const element = $(selector);
    element.textContent = redact(text);
    element.classList.toggle('error-text', error);
    if (element.classList.contains('notice')) element.classList.toggle('error', error);
  }
  function flash(text) {
    $('#flash').textContent = redact(text); $('#flash').classList.add('on');
    clearTimeout(flash.timer); flash.timer = setTimeout(() => $('#flash').classList.remove('on'), 3500);
  }
  function localMedia(value) {
    if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return '';
    try {
      const url = new URL(value, location.origin);
      return url.origin === location.origin && /^\/(media|voice-preview)\//.test(url.pathname) ? url.href : '';
    } catch { return ''; }
  }
  async function api(path, body, timeout = 25000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    let response;
    try {
      response = await fetch(path, {
        method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: body === undefined ? {'Accept':'application/json'} : {'Content-Type':'application/json', 'Accept':'application/json'},
        body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal,
      });
      let data;
      try { data = await response.json(); } catch { throw new Error(`服务返回了无法识别的响应（HTTP ${response.status}），请确认运行的是新版短片工厂。`); }
      if (!data || typeof data !== 'object') throw new Error('服务响应为空或格式错误。');
      if (!response.ok || data.error || data.ok === false) {
        const detail = typeof data.error === 'string' ? data.error : (typeof data.message === 'string' ? data.message : `请求失败（HTTP ${response.status}）`);
        const error = new Error(redact(detail));
        error.status = response.status;
        error.definitive = response.status >= 400 && response.status < 500;
        throw error;
      }
      return data;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('请求超时。服务可能仍在处理，请先核对任务状态，不要重复提交。');
      if (error instanceof TypeError) throw new Error('无法连接本地服务，请检查程序是否仍在运行，然后重试。');
      throw error;
    } finally { clearTimeout(timer); }
  }
  function rows(value, name) {
    let list;
    if (Array.isArray(value)) list = value;
    else if (value && typeof value === 'object') list = Object.entries(value).map(([id, item]) => ({...item, id}));
    else throw new Error(`${name}数据缺失。`);
    if (!list.length || list.some(item => !item || typeof item !== 'object' || item.id == null || String(item.id).trim() === '')) throw new Error(`${name}数据格式不完整。`);
    list = list.map(item => ({...item, id: String(item.id)}));
    if (new Set(list.map(item => item.id)).size !== list.length) throw new Error(`${name}标识重复。`);
    return list;
  }
  function options(selector, list, preferred, label) {
    const select = $(selector); const previous = select.value;
    select.innerHTML = list.map(item => `<option value="${esc(item.id)}">${esc(label(item))}</option>`).join('');
    select.value = list.some(item => item.id === previous) ? previous : (list.some(item => item.id === preferred) ? preferred : list[0].id);
  }
  function renderSegments(selector, list, selected, callback) {
    const element = $(selector);
    element.innerHTML = list.map(item => `<button type="button" data-value="${esc(item.id)}" aria-pressed="${item.id === selected}" title="${esc(item.desc || item.zh)}">${esc(item.zh)}</button>`).join('');
    element.onclick = (event) => {
      const button = event.target.closest('button[data-value]'); if (!button) return;
      callback(button.dataset.value);
      element.querySelectorAll('button').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
      updateHint();
    };
  }
  // 档位用卡片而不是分段控件:每档要回答「选它会得到什么」,一行文字放不下。
  function renderTierCards(selected) {
    const element = $('#pTier');
    element.innerHTML = state.tiers.map(item => {
      const rounds = Number(item.script_rounds || 0);
      const rule = item.review || {};
      const strict = Number(rule.lufs_tol || 1) <= 0.6 ? '评审最严' : (Number(rule.lufs_tol || 1) >= 1.6 ? '评审最宽' : '评审适中');
      // 徽章只放短标签(轮次);完整描述放在副标题里,避免长句挤爆卡片。
      const badge = rounds ? `复审 ${rounds} 轮` : '不复审';
      return `<button type="button" class="tier-card" role="radio" data-value="${esc(item.id)}" aria-checked="${item.id === selected}" tabindex="${item.id === selected ? 0 : -1}"><span><span class="tier-name">${esc(item.zh)}</span><span class="tier-sub">${esc(item.desc || '')} · ${esc(strict)}</span></span><span class="tier-badge">${esc(badge)}</span></button>`;
    }).join('');
    element.onclick = (event) => {
      const button = event.target.closest('[data-value]'); if (!button) return;
      state.tier = button.dataset.value;
      element.querySelectorAll('.tier-card').forEach(card => {card.setAttribute('aria-checked', String(card === button)); card.tabIndex = card === button ? 0 : -1;});
      updateHint();
    };
    // 单选组:左右方向键换档,符合 radiogroup 的键盘约定。
    element.onkeydown = (event) => {
      if (!['ArrowRight','ArrowLeft','ArrowUp','ArrowDown'].includes(event.key)) return;
      const cards=[...element.querySelectorAll('.tier-card')];
      const current=cards.findIndex(card=>card.getAttribute('aria-checked')==='true');
      if(current<0)return;
      event.preventDefault();
      const step=(event.key==='ArrowRight'||event.key==='ArrowDown')?1:-1;
      const next=(current+step+cards.length)%cards.length;
      cards[next].click();
      cards[next].focus();
    };
  }
  // 阶段追踪:完全由后端报告的真实阶段驱动。
  // 后端每进入一个阶段就打印一行标记,这里按顺序渲染,当前阶段高亮。
  function renderStages(stages, status) {
    const track = $('#taskStages');
    if (!stages || !stages.length) { track.hidden = true; track.innerHTML = ''; return; }
    track.hidden = false;
    const signature = JSON.stringify([stages, status]);
    if (track.dataset.signature === signature) return;
    track.dataset.signature = signature;
    track.innerHTML = stages.map((item, index) => {
      const isLast = index === stages.length - 1;
      const phase = !isLast || status === 'done' ? 'done' : status === 'failed' ? 'failed' : 'active';
      const seconds = Math.max(0, Math.round(Number(item.at) || 0));
      const time = seconds >= 60 ? `${Math.floor(seconds / 60)}分${String(seconds % 60).padStart(2, '0')}秒` : `${seconds}秒`;
      return `<li class="stage-item ${phase}"><span class="stage-dot"></span><span><span class="stage-name">${esc(item.name)}${phase === 'failed' ? ' · 未完成' : ''}</span>${item.note ? ` <span class="stage-note">${esc(item.note)}</span>` : ''}</span><span class="stage-time" title="进入此阶段时的累计用时">${time}开始</span></li>`;
    }).join('');
  }
  function activeTasks(data) {
    const raw = data.active_tasks;
    if (Array.isArray(raw)) return raw.map(t => typeof t === 'string' ? {id:t, status:'running'} : t).filter(t => t && (t.id || t.task) && (!t.status || ['running','queued','pending'].includes(t.status)));
    if (raw && typeof raw === 'object') return Object.entries(raw).map(([id, item]) => typeof item === 'object' && item ? {id,...item} : {id,status:'running'}).filter(t => !t.status || ['running','queued','pending'].includes(t.status));
    return [];
  }
  async function loadHealth({recover = true} = {}) {
    if (state.healthBusy) return;
    state.healthBusy = true; $('#retryHealth').disabled = true;
    try {
      const data = await api('/api/health');
      if (Number(data.api_version) !== EXPECTED.api || data.version !== EXPECTED.version) throw new Error(`服务版本不兼容：需要 ${EXPECTED.version} / API ${EXPECTED.api}，当前为 ${data.version || '未知'} / API ${data.api_version ?? '未知'}。请关闭旧程序并启动新版。`);
      if (!('active_tasks' in data) || !(Array.isArray(data.active_tasks) || (typeof data.active_tasks === 'number' && Number.isInteger(data.active_tasks) && data.active_tasks >= 0) || (data.active_tasks && typeof data.active_tasks === 'object'))) throw new Error('健康检查缺少有效的任务状态，请重启新版服务。');
      state.health = true; $('#healthError').hidden = true;
      const tasks = activeTasks(data);
      state.healthCount = typeof data.active_tasks === 'number' ? Math.max(0, data.active_tasks) : tasks.length;
      $('#healthPill').textContent = state.healthCount ? `服务就绪 · ${state.healthCount} 个任务` : '本地服务就绪';
      $('#healthPill').className = 'status-dot ready'; $('#versionLabel').textContent = `v${EXPECTED.version} · API ${EXPECTED.api}`;
      if (recover && !state.activeTask && !state.pending) {
        const stored = restoredTask();
        if (stored?.id) beginTask(stored, stored.queue || []);
        else if (tasks.length) {
          const task = tasks[0]; beginTask({id:task.id || task.task, project:task.project || '', label:task.label || '恢复生产任务', started:task.started});
        } else if (state.healthCount > 0 || stored?.uncertain) {
          state.uncertain = true; taskVisible('恢复生产状态', ''); taskStatus('状态待核对');
          message('#taskMessage', state.healthCount > 0 ? '服务仍有活动任务。本窗口没有对应任务标识，请等待任务完成后重新获取状态；不会重复提交。' : '上次提交未得到明确响应。请重新获取状态并核对作品库。');
          $('#retryTask').hidden = false;
        }
      }
      return tasks;
    } catch (error) {
      state.health = false; $('#healthError').hidden = false; $('#healthErrorText').textContent = redact(error.message);
      $('#healthPill').textContent = '服务不可用'; $('#healthPill').className = 'status-dot failed'; $('#versionLabel').textContent = '连接失败 · 请重试';
      return null;
    } finally { state.healthBusy = false; $('#retryHealth').disabled = false; updateHint(); }
  }
  async function loadPresets() {
    if (state.catalogBusy) return;
    state.catalogBusy = true; state.catalog = false; $('#parameters').disabled = true; $('#retryCatalog').disabled = true; updateHint();
    try {
      const [styles, presets] = await Promise.all([api('/api/styles'), api('/api/presets')]);
      const next = {
        styles: rows(styles.styles, '风格'), types: rows(presets.types, '叙事类型'), voices: rows(presets.voices, '音色'),
        ratios: rows(presets.ratios, '画面比例'), resolutions: rows(presets.resolutions, '分辨率'), fps: rows(presets.fps, '帧率'),
        tiers: rows(presets.tiers, '制作档位'),
      };
      if (next.styles.some(item => !/^[a-zA-Z0-9_-]+$/.test(item.id) || !item.zh || !item.backend)) throw new Error('风格目录格式不完整。');
      if (next.fps.some(item => !Number.isInteger(Number(item.id)) || Number(item.id) < 1 || Number(item.id) > 240)) throw new Error('帧率预设不合法。');
      if (next.ratios.some(item => !/^\d+:\d+$/.test(item.id) || Number(item.id.split(':')[0]) <= 0 || Number(item.id.split(':')[1]) <= 0)) throw new Error('画面比例预设不合法。');
      const min = Number(presets.min_duration ?? 1), max = Number(presets.max_duration ?? 120);
      if (!Number.isInteger(min) || !Number.isInteger(max) || min < 1 || max < min) throw new Error('时长范围不合法。');
      Object.assign(state, next, {minDuration:Math.max(1,min), maxDuration:Math.min(120,max)});
      if (state.minDuration > state.maxDuration) throw new Error('服务时长范围与工作室不兼容。');
      if (!state.styles.some(item => item.id === state.style)) state.style = state.styles[0].id;
      options('#pType', state.types, 'explain', item => item.zh || item.id);
      options('#pVoice', state.voices, '', item => `${item.cn || item.zh || item.id}${item.gender ? ` · ${item.gender}` : ''}${item.locale ? ` / ${item.locale}` : ''}`);
      options('#pRatio', [...state.ratios, {id:'custom',zh:'自定义尺寸'}], '9:16', item => item.zh || item.id);
      options('#pResolution', state.resolutions, '1080p', item => item.zh || item.id);
      if (!state.fps.some(item => item.id === state.frameRate)) state.frameRate = state.fps.some(item => item.id === '30') ? '30' : state.fps[0].id;
      if (!state.tiers.some(item => item.id === state.tier)) state.tier = state.tiers.some(item => item.id === (presets.default_tier || 'standard')) ? (presets.default_tier || 'standard') : state.tiers[0].id;
      renderTierCards(state.tier);
      renderSegments('#pNarration', [{id:'voice',zh:'有口播'},{id:'silent',zh:'无口播'}], state.narration, value => {state.narration=value; applyNarration();});
      renderSegments('#pFps', state.fps, state.frameRate, value => {state.frameRate=value;});
      $('#pDuration').min = state.minDuration; $('#pDuration').max = state.maxDuration;
      $('#durationRange').textContent = `/ ${state.minDuration}–${state.maxDuration} 秒`;
      commitDuration(); renderStyles(); state.catalog = true;
      $('#catalogError').hidden = true; $('#parameters').disabled = false; applyNarration();
    } catch (error) {
      $('#catalogError').hidden = false; $('#catalogErrorText').textContent = `风格与参数加载失败：${redact(error.message)}`;
      $('#styleName').textContent = '风格暂不可用'; $('#styleFeel').textContent = '重新加载后继续，已输入的素材不会丢失。';
    } finally { state.catalogBusy = false; $('#retryCatalog').disabled = false; updateHint(); }
  }
  function renderStyles() {
    for (const element of [...previews.entries.keys()]) previews.unregister(element);
    $('#styleCount').textContent = `${state.styles.length} 种`;
    $('#styles').innerHTML = state.styles.map((style) => `<button class="style-tile" type="button" data-style="${esc(style.id)}" aria-pressed="${state.style === style.id}" aria-label="${esc(style.zh)}，悬停播放风格演示"><span class="tile-image"><img src="/styles/${encodeURIComponent(style.id)}.png" loading="lazy" alt="${esc(style.zh)}风格演示封面"><video class="tile-video" muted loop playsinline preload="none" aria-hidden="true" tabindex="-1"><source src="/styles/${encodeURIComponent(style.id)}.mp4" type="video/mp4"></video><span class="image-fallback" hidden>封面暂不可用</span><span class="tile-play" aria-hidden="true"><svg class="icon"><use href="#i-play"/></svg></span></span><span class="tile-caption">${esc(style.zh)}</span></button>`).join('');
    $$('#styles .style-tile').forEach(tile => previews.register(tile, {
      video: tile.querySelector('video'), poster: tile.querySelector('img'), fallback: tile.querySelector('.image-fallback'),
      isEnabled: () => state.view === 'new' && $('#styleGallery').open,
    }));
    applyStyleHint();
  }
  function canRender(style) {return style && ['remotion:StickerFilm','remotion:StyleFilm'].includes(style.backend);}
  function applyStyleHint() {
    const style = state.styles.find(item => item.id === state.style); if (!style) return;
    $('#styleName').textContent = style.zh; $('#styleFeel').textContent = style.feel || '';
    $('#styleBest').textContent = style.best_for ? `适合：${style.best_for}` : '';
    $('#styleBackend').textContent = canRender(style) ? '可生成' : '渲染后端尚未接入';
    $('#styleBackend').classList.toggle('unavailable', !canRender(style));
    const stage = $('#selectedPreview');
    previews.unregister(stage);
    const image = $('#styleImage'); image.hidden = false; $('#styleImageFallback').hidden = true;
    image.alt = `${style.zh} · 风格演示封面`; image.src = `/styles/${encodeURIComponent(style.id)}.png`;
    const video = $('#styleVideo');
    video.src = `/styles/${encodeURIComponent(style.id)}.mp4`;
    video.load();
    previews.register(stage, {video, poster:image, fallback:$('#styleImageFallback'), isEnabled:()=>state.view==='new'});
    $$('#styles [data-style]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.style === state.style)));
    updateHint();
  }
  function commitDuration() {
    const input = $('#pDuration'); const raw = Number(input.value);
    const valid = input.value.trim() !== '' && Number.isFinite(raw);
    const value = Math.max(state.minDuration, Math.min(state.maxDuration, valid ? Math.round(raw) : 30));
    input.value = value;
    message('#durationHint', !valid || value !== raw ? `已调整为 ${value} 秒（范围 ${state.minDuration}–${state.maxDuration} 秒）。` : '');
    updateHint(); return value;
  }
  function ratioError() {
    if ($('#pRatio').value !== 'custom') return '';
    const width = Number($('#pCW').value), height = Number($('#pCH').value);
    if (![width,height].every(value => Number.isInteger(value) && value >= 64 && value <= 4000)) return '宽和高需为 64–4000 之间的整数。';
    if (width % 2 || height % 2) return '编码需要偶数尺寸，请将宽和高设为偶数。';
    if (width/height < .25 || width/height > 4) return '请使用 1:4 至 4:1 之间的画面比例。';
    return '';
  }
  function applyNarration() {
    const silent = state.narration === 'silent';
    stopAudition();
    if (silent) clearAudio();
    $('#pVoice').disabled = silent; $('#btnAudition').disabled = silent || !state.catalog;
    $('#drop').disabled = silent; $('#file').disabled = silent;
    message('#voiceHint', silent ? '无口播 · 不生成配音，也不使用录音。' : '');
    message('#uploadHint', silent ? '切换为有口播后，可使用自己的录音。' : '可选。上传录音后，画面将与真实语速对齐。');
    updateHint();
  }
  function currentSpec() {
    const silent = state.narration === 'silent';
    return {silent, duration:Number($('#pDuration').value), resolution:$('#pResolution').value,
      fps:Number(state.frameRate), tier:state.tier,
      ratio:$('#pRatio').value === 'custom' ? `custom:${$('#pCW').value}x${$('#pCH').value}` : $('#pRatio').value,
      voice:silent ? '' : $('#pVoice').value, video_type:$('#pType').value};
  }
  function tierSpec() {return state.tiers.find(item => item.id === state.tier) || {};}
  // 引导:三步。完成哪一步由**真实状态**决定(有没有素材 / 能不能生成),
  // 不靠计时或猜测。收起后可以用按钮再打开。
  const GUIDE_KEY = 'film-studio-guide-v1';
  function guideDismissed() {
    try { return localStorage.getItem(GUIDE_KEY) === 'off'; } catch { return false; }
  }
  function dismissGuide() {
    try { localStorage.setItem(GUIDE_KEY, 'off'); } catch { /* Private windows may block storage. */ }
    $('#guide').classList.add('collapsed');
    $('#guideRestore').hidden = false;
  }
  function restoreGuide() {
    try { localStorage.removeItem(GUIDE_KEY); } catch { /* Private windows may block storage. */ }
    $('#guide').classList.remove('collapsed');
    $('#guideRestore').hidden = true;
    updateGuide();
  }
  function updateGuide() {
    if ($('#guide').classList.contains('collapsed')) return;
    const hasSource = Boolean($('#source').value.trim());
    const reason = blockingReason();
    const canShip = !reason;
    const steps = [
      {key:'source', done: hasSource, active: !hasSource},
      {key:'style', done: hasSource && canShip, active: hasSource && !canShip},
      {key:'render', done: false, active: hasSource && canShip},
    ];
    $$('#guide .guide-step').forEach(step => {
      const info = steps.find(item => item.key === step.dataset.guide);
      step.classList.toggle('done', Boolean(info?.done));
      step.classList.toggle('active', Boolean(info?.active));
    });
  }
  function blockingReason() {
    if (!state.health) return '请先连接兼容的本地服务';
    if (!state.catalog) return state.catalogBusy ? '正在加载风格与参数' : '风格或参数未加载，请重试';
    if (state.pending) return '正在提交，请勿重复操作';
    if (state.editorSaving) return '正在保存项目文件';
    if (state.activeTask) return '任务进行中，完成后可继续创作';
    if (state.uncertain) return '提交结果待核对，请查看上方任务提示';
    if (state.healthCount > 0) return '服务正在处理任务，请刷新连接以恢复状态';
    if (state.audioReading) return '正在读取录音';
    if (!canRender(state.styles.find(item => item.id === state.style))) return '当前风格尚未接入渲染';
    const duration = Number($('#pDuration').value);
    if (!Number.isInteger(duration) || duration < state.minDuration || duration > state.maxDuration) return `时长应为 ${state.minDuration}–${state.maxDuration} 秒`;
    if (ratioError()) return ratioError();
    if (!$('#source').value.trim()) return '请先放入正文素材，再开始生成';
    if (!$('#offline').checked && state.settings !== 'ready') return '模型状态未读取；请重试或选择纯文字排版';
    if (!$('#offline').checked && !state.configured) return '请配置模型，或选择「纯文字排版」';
    return '';
  }
  function updateHint() {
    const sp = currentSpec(); const ratio = $('#pRatio').value === 'custom' ? `${$('#pCW').value}×${$('#pCH').value}` : $('#pRatio').value;
    $('#pRatioCustom').hidden = $('#pRatio').value !== 'custom';
    const error = ratioError(); message('#ratioHint', error, Boolean(error));
    const type = state.types.find(item => item.id === sp.video_type);
    message('#typeHint', type?.desc || '');
    message('#qualityHint', state.resolutions.find(item => item.id === sp.resolution)?.desc || '');
    const tier = tierSpec();
    const rounds = Number(tier.script_rounds || 0);
    const rule = tier.review || {};
    const strict = Number(rule.lufs_tol || 1) <= 0.6 ? '评审最严' : (Number(rule.lufs_tol || 1) >= 1.6 ? '评审最宽' : '评审适中');
    const offlineNote = rounds && $('#offline').checked ? '纯文字排版不调用模型,本档复审不会执行。' : '';
    const quality = Number(rule.sfx_min_ratio || 0) > 0 ? `音效落点需达到 ${Math.round(Number(rule.sfx_min_ratio) * 100)}%` : '音效落点不额外要求';
    message('#tierHint', tier.desc ? `${tier.desc}。复审改稿 ${rounds} 轮,${strict},${quality}。${offlineNote}` : '');
    $('#sourceCount').textContent = $('#source').value.length ? `${$('#source').value.length.toLocaleString()} 字` : '不编造数字';
    $('#paramHint').textContent = state.catalog ? `${sp.duration || '—'}s · ${ratio} · ${sp.resolution.toUpperCase()} · ${sp.fps}fps · ${tierSpec().zh || '标准'}\n${sp.silent ? '无口播' : state.audio ? '真人录音' : 'AI 配音'} / ${type?.zh || sp.video_type}` : '正在加载出片规格…';
    $('#settingsWarning').textContent = $('#offline').checked ? '原文分句排版，不自动配内容画面。' : state.settings === 'error' ? '模型状态读取失败；素材解析仍可单独使用。' : state.configured ? '已连接文本模型，依据素材自动写稿。' : '模型未配置。可前往设置，或启用纯文字排版。';
    const reason = blockingReason(); $('#go').disabled = Boolean(reason);
    $('#goHint').textContent = reason || '参数已就绪，可以生成';
    $('#goHint').classList.toggle('error-text', !state.health || Boolean(error));
    updateGuide();
    const locked = Boolean(state.pending || state.activeTask || state.uncertain || state.projectLoading || state.editorSaving);
    $$('.result-actions button, .editor-actions button').forEach(button => {button.disabled = locked || !state.project;});
    if (state.project && !localMedia(state.project.video)) $('#btnShip').disabled=true;
    $('#btnAudition').disabled = !state.catalog || sp.silent || state.audioReading;
    $('#outputMode').textContent = state.view === 'works' ? '右侧生成将新建项目' : '新建项目';
  }
  async function loadSettings() {
    if (state.settingsBusy) return;
    state.settings = 'loading'; $('#llmPill').textContent = '模型检查中'; $('#retrySettings').disabled = true; updateHint();
    try {
      const data = await api('/api/settings');
      if (typeof data.configured !== 'boolean') throw new Error('模型状态响应格式不正确。');
      $('#setBase').value = typeof data.base === 'string' ? data.base : '';
      $('#setModel').value = typeof data.model === 'string' ? data.model : '';
      // Never render data.key, data.keyHint, or any returned credential fragment.
      $('#setKey').value = ''; $('#setKey').placeholder = data.hasKey ? '已保存密钥，留空保留' : '输入密钥';
      $('#keyState').textContent = data.hasKey ? '已保存' : '未配置';
      state.configured = data.configured; state.settings = 'ready';
      $('#llmPill').textContent = data.configured ? '模型已配置' : '配置文本模型';
      message('#setHint', data.configured ? '配置已读取。可测试连接，或返回工作区开始创作。' : '尚未配置完整的文本模型。可填写后保存，或使用纯文字排版。');
    } catch (error) {
      state.settings = 'error'; state.configured = false; $('#llmPill').textContent = '模型状态读取失败';
      message('#setHint', `设置读取失败：${error.message}。可重新读取；不会影响素材解析。`, true);
    } finally { $('#retrySettings').disabled = false; updateHint(); }
  }
  function settingsPayload() {
    const key = $('#setKey').value.trim(); if (key) state.secrets.add(key);
    return {base:$('#setBase').value.trim(), model:$('#setModel').value.trim(), key};
  }
  async function saveSettings(event) {
    event.preventDefault(); if (state.settingsBusy || !$('#settingsForm').reportValidity()) return;
    state.settingsBusy = true; settingsControls(true); message('#setHint','正在保存设置…');
    try {
      const data = await api('/api/settings', settingsPayload());
      if (typeof data.configured !== 'boolean') throw new Error('设置保存响应缺少配置状态，请重新读取核对。');
      $('#setKey').value = ''; state.configured = data.configured; state.settings = 'ready';
      $('#llmPill').textContent = data.configured ? '模型已配置' : '配置文本模型';
      $('#keyState').textContent = data.hasKey || data.configured ? '已保存' : '未配置';
      $('#setKey').placeholder = '已有密钥将保留，输入新值可替换';
      message('#setHint', data.configured ? '设置已保存。建议测试连接，确认模型可用。' : '设置已保存，但仍缺少配置字段。'); flash('模型设置已保存');
    } catch (error) { message('#setHint', `保存失败：${error.message}`, true); }
    finally { state.settingsBusy = false; settingsControls(false); updateHint(); }
  }
  function settingsControls(disabled) {['#btnTest','#btnSaveSettings','#retrySettings'].forEach(selector => {$(selector).disabled=disabled;});}
  async function testSettings() {
    if (state.settingsBusy || !$('#settingsForm').reportValidity()) return;
    state.settingsBusy = true; settingsControls(true); message('#setHint', '正在探测端点并测试推理；带思考的模型可能需要更长时间…');
    try {
      const data = await api('/api/settings/test', settingsPayload(), 180000);
      const probe = data.probe_ms != null ? `端点 ${data.probe_ms} ms` : '端点未开放独立探测';
      const inference = data.latency_ms != null ? ` · 推理 ${data.latency_ms} ms` : '';
      message('#setHint', `连接成功 · ${probe}${inference}${data.model_found === false ? ' · 提醒：模型名不在端点列表中' : ''}${data.note ? ` · ${data.note}` : ''}。测试不会保存当前输入。`);
    } catch (error) { message('#setHint', `连接测试失败：${error.message}`, true); }
    finally { state.settingsBusy = false; settingsControls(false); }
  }
  async function parseSource() {
    const value = $('#url').value.trim();
    try { const parsed = new URL(value); if (!['http:','https:'].includes(parsed.protocol)) throw new Error(); }
    catch { message('#parseMsg','请先输入完整的 http / https 链接。',true); $('#url').focus(); return; }
    if ($('#source').value.trim() && !confirm('解析成功后将替换当前正文素材，是否继续？')) return;
    const original = $('#source').value; const submitted = value;
    $('#btnParse').disabled = true; message('#parseMsg','正在解析来源。普通网页几秒就好；抖音这类需要真渲染的页面要 1~2 分钟，已有正文会保留到解析成功。');
    try {
      const data = await api('/api/parse', {url:value}, 180000);
      if (typeof data.text !== 'string' || !data.text.trim()) throw new Error('没有解析到正文，请直接粘贴素材或换一个链接。');
      if ($('#source').value !== original && !confirm('解析期间正文已被编辑。是否用解析内容替换？')) {message('#parseMsg','已保留你编辑的正文；需要时可重新解析。'); return;}
      $('#source').value = data.text;
      if (!$('#title').value.trim() && typeof data.title === 'string') $('#title').value = data.title;
      message('#parseMsg', `解析完成 · ${data.platform || '网页'} · ${data.text.length.toLocaleString()} 字符${$('#url').value.trim() !== submitted ? '（来自刚才提交的链接）' : ''}`);
    } catch (error) {message('#parseMsg', `解析失败：${error.message} · 原正文未改动，可重试或直接粘贴。`,true);}
    finally { $('#btnParse').disabled = false; updateHint(); }
  }
  function clearAudio() {
    state.audioRevision++; state.audio = null; state.audioReading = false;
    $('#file').value = ''; $('#audioSelection').hidden = true; $('#fileName').textContent = ''; updateHint();
  }
  function pickFile(file) {
    if (state.narration === 'silent') return;
    if (!file || !/\.(wav|mp3|m4a|aac|ogg|opus|flac|aiff?|wma|webm)$/i.test(file.name)) {message('#uploadHint','请选择有效的音频文件（如 WAV / MP3）。',true); return;}
    if (!file.size || file.size > 60*1024*1024) {message('#uploadHint','录音不能为空，且不能超过 60 MB。',true); return;}
    const revision = ++state.audioRevision; const reader = new FileReader();
    state.audioReading = true; stopAudition(); message('#uploadHint','正在读取录音…'); updateHint();
    reader.onload = () => {
      if (revision !== state.audioRevision || state.narration === 'silent') return;
      state.audio = {name:file.name,b64:reader.result}; state.audioReading = false;
      $('#fileName').textContent = `${file.name} · ${(file.size/1024/1024).toFixed(1)} MB`; $('#audioSelection').hidden = false;
      message('#uploadHint','录音已就绪，生成时上传。将使用你的录音，而非 AI 配音。'); updateHint();
    };
    reader.onerror = () => {if (revision !== state.audioRevision) return; state.audioReading=false; message('#uploadHint','文件读取失败，请重新选择。',true); updateHint();};
    reader.readAsDataURL(file);
  }
  function stopAudition() {
    state.auditionRevision++; state.auditionLoading = false;
    if (state.player) {state.player.pause(); state.player.removeAttribute('src'); state.player.load(); state.player=null;}
    $('#btnAudition').innerHTML = icon('play'); $('#btnAudition').setAttribute('aria-label','试听音色'); $('#btnAudition').title='试听音色';
  }
  async function audition() {
    if (state.player || state.auditionLoading) {stopAudition(); message('#voiceHint','试听已停止。'); return;}
    const revision = ++state.auditionRevision; const voice = $('#pVoice').value;
    state.auditionLoading=true; $('#btnAudition').innerHTML=icon('stop'); $('#btnAudition').setAttribute('aria-label','停止试听'); $('#btnAudition').title='停止试听';
    message('#voiceHint','正在合成试听，可点击停止。');
    try {
      const data = await api(`/api/voice-preview?voice=${encodeURIComponent(voice)}`, undefined, 90000);
      if (revision !== state.auditionRevision || state.narration === 'silent') return;
      const url = localMedia(data.url); if (!url) throw new Error('试听服务未返回有效的本地音频地址。');
      const player = new Audio(url); state.player=player; state.auditionLoading=false;
      player.addEventListener('ended', () => {if (state.player===player) {stopAudition(); message('#voiceHint','试听结束。');}});
      player.addEventListener('error', () => {if (state.player===player) {stopAudition(); message('#voiceHint','音频播放失败，请重新试听。',true);}});
      await player.play();
      if (revision === state.auditionRevision && state.player === player) message('#voiceHint','正在播放试听 · 再点一次停止');
    } catch (error) {if (revision !== state.auditionRevision) return; stopAudition(); message('#voiceHint',`试听失败：${error.message}`,true);}
  }
  function taskVisible(title, project) {
    $('#taskPanel').hidden=false; $('#taskTitle').textContent=title || '生产任务'; $('#taskProject').textContent=project || '';
    $('#retryTask').hidden=true; $('#taskMessage').textContent=''; $('#log').textContent='';
    $('#taskStages').hidden=true; $('#taskStages').innerHTML=''; delete $('#taskStages').dataset.signature;
  }
  function elapsed(started) {
    clearInterval(state.elapsedTimer);
    const raw = Number(started); const start = Number.isFinite(raw) && raw > 0 ? (raw < 1e12 ? raw*1000 : raw) : Date.now();
    const draw = () => {const seconds=Math.max(0,Math.floor((Date.now()-start)/1000)); $('#elapsed').textContent=`已用 ${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;};
    draw(); state.elapsedTimer=setInterval(draw,1000);
  }
  function taskStatus(text, running=false) {$('#taskState').textContent=text; $('#taskState').classList.toggle('running',running);}
  // Persist only non-secret task coordinates, never source, audio or settings.
  function persistTask(task) {
    try {if (task) sessionStorage.setItem('film-studio-task-v2', JSON.stringify(task)); else sessionStorage.removeItem('film-studio-task-v2');} catch { /* Private windows may disable storage. */ }
  }
  function restoredTask() {
    try {
      const task = JSON.parse(sessionStorage.getItem('film-studio-task-v2') || 'null');
      if (!task || typeof task !== 'object') return null;
      if (task.uncertain === true) return {uncertain:true};
      if (typeof task.id !== 'string' || !/^[a-zA-Z0-9_-]{1,128}$/.test(task.id)) return null;
      const queue = Array.isArray(task.queue) ? task.queue.filter(item => item && ['voice','build','render'].includes(item.action)).map(item => ({action:item.action,label:ACTION_LABELS[item.action]})) : [];
      return {id:task.id, project:typeof task.project === 'string' ? task.project : '',label:typeof task.label === 'string' ? task.label : '恢复生产任务',started:task.started,queue};
    } catch {return null;}
  }
  function beginTask(task, queue = []) {
    clearTimeout(state.taskTimer); const epoch = ++state.taskEpoch;
    state.activeTask={...task, queue}; persistTask(state.activeTask); state.pending=false; state.uncertain=false;
    taskVisible(task.label,task.project); taskStatus('运行中',true); elapsed(task.started);
    $('#taskDetails').open=false; updateHint(); pollTask(epoch);
  }
  async function pollTask(epoch) {
    const active=state.activeTask; if (!active || epoch !== state.taskEpoch) return;
    $('#retryTask').hidden=true;
    try {
      const task=await api(`/api/task?id=${encodeURIComponent(active.id)}`);
      if (epoch !== state.taskEpoch) return;
      if (!['running','queued','pending','done','failed'].includes(task.status)) throw new Error('无法识别任务状态；请重新获取。');
      if (!active.project && task.project) {active.project=task.project; $('#taskProject').textContent=task.project;}
      if (task.started && !active.started) {active.started=task.started; elapsed(task.started);}
      const logs=$('#log'), nearEnd=logs.scrollHeight-logs.scrollTop-logs.clientHeight < 45;
      logs.textContent=redact((Array.isArray(task.logs) ? task.logs : []).join('\n'));
      if (nearEnd) logs.scrollTop = logs.scrollHeight;
      const running = ['running','queued','pending'].includes(task.status);
      renderStages(task.stages, task.status);
      if (running) {
        taskStatus(task.status==='running' ? '运行中' : '排队中',true);
        const current = task.stage && task.stage.name ? `正在${task.stage.name}` : '正在准备';
        message('#taskMessage', current === '正在准备'
          ? '显示实际任务状态。耗时取决于模型响应、素材和本机渲染性能。'
          : `${current}${task.stage?.note ? ` · ${task.stage.note}` : ''}。下方是本次已完成的阶段。`);
        state.taskTimer=setTimeout(()=>pollTask(epoch),1100); return;
      }
      clearInterval(state.elapsedTimer);
      if (task.status==='done' && active.queue.length) {
        const [next,...rest]=active.queue;
        message('#taskMessage',`上一步已完成，正在提交${next.label}…`); taskStatus('下一步');
        state.activeTask=null;
        await submitAction(next.action,active.project,rest,next.label); return;
      }
      state.activeTask=null; state.healthCount=0; persistTask(null);
      if(task.status==='done' && state.project?.name===active.project && active.label===ACTION_LABELS.render) state.scriptNeedsVoice=false;
      const reviewFailed = task.status === 'done' && task.detail?.review?.verdict === 'FAIL';
      taskStatus(task.status==='done' ? (reviewFailed ? '已完成 · 评审未通过' : '已完成') : '失败');
      if (task.status === 'failed') $('#taskDetails').open = true;
      message('#taskMessage',task.status==='done' ? (reviewFailed ? '处理已完成，但成片未通过客观评审。请查看作品详情中的问题清单；没有自动重新生成。' : '任务已完成，作品库已刷新。') : `任务失败（退出码 ${task.rc ?? '未知'}）。请查看实际日志，修正问题后再运行。`,task.status!=='done' || reviewFailed);
      updateHint(); await loadArchive();
      if (active.project) await showProject(active.project,{navigate:task.status==='done',force:true});
      await loadHealth({recover:false});
      if (task.status==='done') flash('任务已完成');
    } catch (error) {
      if (epoch !== state.taskEpoch) return;
      // A definitive 404 follows a service restart; it is not a running task.
      if (error.status === 404) {
        state.activeTask=null; state.uncertain=true; persistTask({uncertain:true}); clearInterval(state.elapsedTimer);
        taskStatus('任务记录已失效'); message('#taskMessage','服务已不再保存此任务记录（可能已重启）。请重新获取服务状态，并在作品库核对产物。',true);
        $('#retryTask').hidden=false; updateHint(); return;
      }
      // Keep the task ID and lock generation; a lost HTTP response is not task failure.
      taskStatus('状态待恢复'); message('#taskMessage',`暂时无法读取任务：${error.message}。任务可能仍在运行。`,true);
      $('#retryTask').hidden=false; updateHint();
    }
  }
  function submittedError(error) {
    state.pending=false; state.uncertain=!error.definitive; state.activeTask=null;
    clearInterval(state.elapsedTimer); taskStatus(error.definitive ? '请求未受理' : '提交结果待核对');
    message('#taskMessage', error.definitive ? `${error.message}。请修正后再试。` : `${error.message}。未自动重复提交，以免重复生产。请先重新获取任务状态。`,true);
    if (state.uncertain) persistTask({uncertain:true}); else persistTask(null);
    $('#retryTask').hidden=!state.uncertain; updateHint();
  }
  async function generate() {
    commitDuration(); const reason=blockingReason(); if (reason) {flash(reason); return;}
    stopAudition(); state.pending=true; persistTask({uncertain:true}); taskVisible('生成短片','正在创建独立项目'); taskStatus('提交中',true); elapsed(); updateHint();
    const spec=currentSpec();
    const body={title:$('#title').value.trim(),style:state.style,source:$('#source').value,offline:$('#offline').checked,
      duration:spec.duration,ratio:spec.ratio,voice:spec.voice,video_type:spec.video_type,narration:state.narration,resolution:spec.resolution,fps:spec.fps,tier:spec.tier};
    if (!spec.silent && state.audio) body.audio=state.audio;
    try {
      const data=await api('/api/make',body,180000);
      if (!data.task || !data.project) throw new Error('生成响应缺少任务或项目标识。');
      beginTask({id:data.task,project:data.project,label:'生成短片'});
    } catch (error) {submittedError(error);}
  }
  async function retryTask() {
    if (state.activeTask) {taskStatus('恢复连接中',true); pollTask(state.taskEpoch); return;}
    $('#retryTask').disabled=true;
    try {
      const tasks=await loadHealth();
      if (tasks === null || state.activeTask) return;
      if (state.healthCount > 0) {message('#taskMessage','服务报告仍有活动任务，但未返回可恢复的任务标识。请稍后重新获取。',true); return;}
      if (state.uncertain && confirm('服务当前未报告活动任务。之前的请求可能已经完成，请先在作品库核对。是否解除提交锁定？这不会重发原请求。')) {
        state.uncertain=false; persistTask(null); taskStatus('已解除提交锁定'); message('#taskMessage','未重发原请求。请在作品库确认产物，再决定是否新建。'); $('#retryTask').hidden=true; await loadArchive(); updateHint();
      }
    } finally {$('#retryTask').disabled=false;}
  }
  const ACTION_LABELS={check:'重新评审',ship:'归档到 final',stills:'导出关键帧',preview:'快速预览',voice:'重新生成配音',build:'构建画面',render:'渲染视频'};
  async function submitAction(action, project, queue=[], label=ACTION_LABELS[action]) {
    if (!project || state.pending || state.activeTask || state.uncertain) return;
    state.pending=true; persistTask({uncertain:true}); taskVisible(label,project); taskStatus('提交中',true); elapsed(); updateHint();
    try {
      const data=await api('/api/action',{project,action},180000);
      if (!data.task) throw new Error('服务未返回任务标识。');
      beginTask({id:data.task,project,label},queue);
    } catch (error) {submittedError(error);}
  }
  function editorDirty() {return state.project && Object.keys(state.drafts).some(key => state.drafts[key] !== state.saved[key]);}
  function captureDraft() {if (state.project && !$('#editor').hidden) state.drafts[state.tab]=$('#editBox').value;}
  async function showProject(name,{navigate=true,force=false}={}) {
    captureDraft();
    if (!force && editorDirty() && !confirm('有尚未保存的 JSON 改动。打开作品将放弃这些改动，是否继续？')) return;
    const request=++state.projectRequest; state.projectLoading=true; updateHint();
    $('#projectError').hidden=true;
    try {
      const data=await api(`/api/project?name=${encodeURIComponent(name)}`);
      if (request !== state.projectRequest) return;
      const same=state.project?.name===name; const retainDraft=same && editorDirty();
      if (!same) {state.scriptNeedsVoice=false;$('#editor').hidden=true;$('#btnEdit').setAttribute('aria-expanded','false');}
      state.project={...data,name};
      if (!retainDraft) {
        state.saved={script:data.files?.['script.json'] || '{}',film:data.files?.['film.json'] || '{}'};
        state.drafts={...state.saved}; state.tab='script';
      }
      $('#resultStep').hidden=false; $('#projectName').textContent=name; $('#resultTitle').textContent=data.title || name;
      const video=$('#video'); const url=localMedia(data.video);
      video.pause(); if (url) {video.src=url; video.hidden=false; $('#noVideo').hidden=true;} else {video.removeAttribute('src'); video.load(); video.hidden=true; $('#noVideo').hidden=false;}
      const silent=data.voice_mode==='silent' || data.narration==='silent';
      const voiceMode=silent ? '无口播' : data.voice_mode==='human' ? '真人录音' : data.voice_mode==='tts' ? 'AI 配音' : '未记录';
      const review=data.review;
      // 评审结论要能一眼读懂:PASS/FAIL + 四个可核对的事实 + 具体问题清单。
      // 没有评审就说「尚未评审」,不显示假数据。
      const reviewText = review ? (() => {
        const verdict = review.verdict || '未知';
        const chip = `<span class="verdict-chip ${verdict==='PASS'?'pass':verdict==='FAIL'?'fail':'unknown'}">${esc(verdict)}</span>`;
        const defect = (label, value) => ({label, value:value ?? '—', tone:value == null ? '' : Number(value)>0 ? 'bad' : 'good'});
        const cells = [
          defect('死场', review.dead), defect('黑帧', review.black), defect('静音', review.silence),
          {label:'音效落点', value:review.sfx ?? '—', tone:''},
          {label:'响度', value:review.lufs != null ? `${review.lufs} LUFS` : '—', tone:''},
        ];
        const grid = `<div class="review-grid">${cells.map(cell => `<span class="review-cell ${cell.tone}"><b>${esc(cell.value)}</b><small>${esc(cell.label)}</small></span>`).join('')}</div>`;
        const issues = Array.isArray(review.issues) && review.issues.length
          ? `<ul class="review-issues">${review.issues.map(issue => `<li>${esc(issue)}</li>`).join('')}</ul>` : '';
        return `${chip}${grid}${issues}`;
      })() : '尚未评审';
      const style=state.styles.find(item=>item.id===data.style)?.zh || data.style || '未记录';
      // 规格:优先显示成片的**真实**时长/尺寸,目标时长只作参考。
      // 两者不一致时必须写明,否则用户会以为片子就是那么长。
      const actual = review && review.actual_duration ? Number(review.actual_duration) : null;
      const target = Number(data.duration) || 0;
      const actualSize = review && Array.isArray(review.actual_size) && review.actual_size[0] ? `${review.actual_size[0]}×${review.actual_size[1]}` : '';
      const specParts = [];
      if (actual) {
        specParts.push(`${actual.toFixed(1)}s`);
        if (target && Math.abs(actual - target) > 0.3) specParts.push(`目标 ${target}s`);
      } else {
        specParts.push(`${target || '—'}s`);
      }
      specParts.push(esc(data.ratio || '未记录'));
      if (actualSize) specParts.push(actualSize); else if (data.resolution) specParts.push(esc(data.resolution));
      if (data.fps) specParts.push(`${esc(data.fps)}fps`);
      if (data.tier_zh) specParts.push(`${esc(data.tier_zh)}档`);
      const specText = specParts.join(' · ');
      const reviewRows = data.tier_review && data.tier_review.rounds_planned
        ? `<dt>复审</dt><dd>${esc(data.tier_review.rounds_done || 0)}/${esc(data.tier_review.rounds_planned)} 轮${data.tier_review.note ? `<br>${esc(data.tier_review.note)}` : ''}</dd>` : '';
      // 专属画面 vs 通用模板:观感差得很远,必须写明这条片子用的是哪一种。
      const scene = data.scene || {};
      const sceneRows = scene.status === 'failed'
        ? `<dt>画面</dt><dd class="warn-text">通用模板渲染<br><span class="micro">专属画面未生成：${esc(scene.reason || '原因未记录')}</span></dd>`
        : scene.status === 'partial'
          ? `<dt>画面</dt><dd>模型专属画面<br><span class="micro">部分拍用兜底画面：${esc(scene.reason || '')}</span></dd>`
          : scene.status === 'ok'
            ? `<dt>画面</dt><dd>模型专属画面</dd>`
            : '';
      $('#kv').innerHTML=`<dt>风格</dt><dd>${esc(style)}</dd><dt>规格</dt><dd>${specText}</dd><dt>口播</dt><dd>${esc(voiceMode)}${!silent && (data.voice_cn || data.voice) ? `<br>${esc(data.voice_cn || data.voice)}` : ''}</dd>${reviewRows}${sceneRows}<dt>评审</dt><dd>${reviewText}</dd>${data.video_path ? `<dt>文件</dt><dd class="mono">${esc(data.video_path)}</dd>` : ''}`;
      const links=[];
      if (url) links.push(`<a href="${esc(url)}" download>${icon('download')}下载 MP4</a>`);
      const report=localMedia(data.report); if (report) links.push(`<a href="${esc(report)}" target="_blank" rel="noopener">查看生产报告</a>`);
      const preview=localMedia(data.preview);
      if (preview) links.push(`<button type="button" id="playPreview" class="text-button">播放低清预览</button><a href="${esc(preview)}" download>下载预览</a>`);
      $('#downloads').innerHTML=links.join('');
      if (preview) $('#playPreview').onclick=()=>{video.pause();video.src=preview;video.hidden=false;$('#noVideo').hidden=true;video.play().catch(()=>{});};
      $('#btnShip').disabled=!url; selectEditorTab(state.tab); updateHint();
      if (navigate) {setView('works'); $('#resultStep').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});}
    } catch (error) {if(request!==state.projectRequest)return;$('#resultStep').hidden=false; $('#projectError').hidden=false; message('#projectError',`项目读取失败：${error.message}。请在作品库重新选择此作品。`,true); if(navigate) setView('works');}
    finally {if(request===state.projectRequest){state.projectLoading=false;updateHint();}}
  }
  function selectEditorTab(tab) {
    captureDraft(); state.tab=tab; $('#editBox').value=state.drafts[tab] || '{}';
    $$('.editor-tabs button').forEach(button=>{const selected=button.dataset.tab===tab;button.classList.toggle('on',selected);button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;});
    $('#editorPanel').setAttribute('aria-labelledby',tab==='script'?'tabScript':'tabFilm');
  }
  async function saveEditor() {
    if (!state.project || state.activeTask || state.pending || state.uncertain) return;
    captureDraft(); const tab=state.tab, text=state.drafts[tab], project=state.project.name;
    try {JSON.parse(text);} catch (error) {message('#saveHint',`JSON 格式错误：${error.message}`,true); return;}
    state.editorSaving=true; updateHint(); message('#saveHint','正在保存 JSON…');
    try {
      const data=await api('/api/save',{project,[tab]:text}); if (!data.ok) throw new Error('保存未获服务确认。');
      if (state.project?.name===project) {if(tab==='script' && state.saved[tab]!==text)state.scriptNeedsVoice=true;state.saved[tab]=text; message('#saveHint','JSON 已保存，现有视频未改变。稿件修改请「重建并渲染此项目」；主生成按钮始终新建项目。');}
      flash('JSON 已保存');
    } catch (error) {message('#saveHint',`保存失败：${error.message}`,true);}
    finally {state.editorSaving=false;updateHint();}
  }
  async function rebuild() {
    captureDraft(); if (!state.project) return;
    if (editorDirty()) {message('#saveHint','请先分别保存有改动的文件，再重建项目。',true); return;}
    if (state.scriptNeedsVoice && state.project.voice_mode==='human') {
      message('#saveHint','真人录音项目的稿件修改需要重新对齐原录音；当前 API 不提供复用录音重对齐。请在新建工作区上传录音重新生成。现有项目不会被悄悄切换成 AI 配音。',true); return;
    }
    const withVoice=state.scriptNeedsVoice;
    if (!confirm(withVoice ? '将重新生成配音、构建画面并渲染，覆盖当前项目输出。不会重新用模型写稿。是否继续？' : '将保留已有配音，重新构建画面并渲染，覆盖当前项目输出。是否继续？')) return;
    const project=state.project.name;
    if(withVoice) await submitAction('voice',project,[{action:'build',label:'构建画面'},{action:'render',label:'渲染视频'}]);
    else await submitAction('build',project,[{action:'render',label:'渲染视频'}]);
  }
  async function loadArchive() {
    $('#refreshArchive').disabled=true; $('#retryArchive').hidden=true; message('#archiveMsg','正在读取本地项目…');
    const previousArchive = $('#archive').innerHTML;
    $('#archive').setAttribute('aria-busy', 'true');
    if (!state.projects.length) $('#archive').innerHTML = Array.from({length:3}, () => `<div aria-hidden="true"><div class="skeleton skeleton-card"></div><div class="skeleton skeleton-line" style="width:70%"></div><div class="skeleton skeleton-line" style="width:40%"></div></div>`).join('');
    try {
      const data=await api('/api/projects'); if (!Array.isArray(data.projects)) throw new Error('项目列表响应格式错误。');
      state.projects=data.projects.filter(project=>project && typeof project.name==='string');
      $('#archiveMsg').textContent='';
      $('#archive').innerHTML=state.projects.length ? state.projects.map(project=>{
        const cover=localMedia(project.cover); const style=state.styles.find(item=>item.id===project.style)?.zh || project.style || '未记录风格';
        return `<button type="button" class="project-card" data-project="${esc(project.name)}"><span class="project-cover">${cover ? `<img src="${esc(cover)}" loading="lazy" alt="${esc(project.title || project.name)}封面">` : icon('film')}<span class="project-label">${project.video?'有成片':'待生成成片'}</span></span><h3>${esc(project.title || project.name)}</h3><p>${esc(style)} · ${esc(project.review?.verdict || '未评审')}</p></button>`;
      }).join('') : `<div class="empty-state">${icon('film')}<h3>第一支短片，从这里开始。</h3><p>你的真实项目和成片会保存在这里。</p><button class="small-button" data-view="new">新建短片 ${icon('arrow')}</button></div>`;
      $$('#archive img').forEach(image=>image.addEventListener('error',()=>{image.replaceWith(Object.assign(document.createElement('span'),{className:'image-fallback',textContent:'封面暂不可用'}));}));
    } catch (error) {$('#archive').innerHTML = previousArchive; message('#archiveMsg',`作品库读取失败：${error.message}。已有作品仍保留在本地。`,true); $('#retryArchive').hidden=false;}
    finally {$('#refreshArchive').disabled=false; $('#archive').setAttribute('aria-busy', 'false');}
  }
  function setView(view) {
    if (!['new','edit','works','settings'].includes(view)) return;
    previews.stopAll();
    stopAudition(); if (state.project && view!=='works') $('#video').pause();
    state.view=view;
    // 剪辑页不使用「出片参数」面板,加个类让主区占满宽度。
    document.querySelector('.studio')?.classList.toggle('editing', view==='edit');
    for (const key of ['new','edit','works','settings']) $(`#${key}View`).hidden=key!==view;
    $$('.nav-item').forEach(button=>{const on=button.dataset.view===view;button.classList.toggle('on',on); if(on)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');});
    $('#viewLabel').textContent={new:'新建短片',edit:'剪辑',works:'作品库',settings:'模型设置'}[view];
    if (view==='edit' && typeof window.editModeLoad==='function') window.editModeLoad();
    if (location.hash!==`#${view}`) history.replaceState(null,'',`${location.pathname}${location.search}#${view}`);
    $('#main').scrollTop=0; updateHint();
  }
  document.addEventListener('click',event=>{const button=event.target.closest('[data-view]'); if(button) setView(button.dataset.view);});
  $('#styleGallery').addEventListener('toggle', () => { if (!$('#styleGallery').open) previews.stopAll(); });
  $('#styles').onclick=event=>{const button=event.target.closest('[data-style]'); if(!button)return;state.style=button.dataset.style;applyStyleHint();};
  // 风格库是一张 15 格网格:鼠标只能选,键盘用户就选不了。
  // 方向键在网格里移动,Enter/Space 选中,Home/End 到首尾。
  // 列数不能写死(网格是自适应列数),按实际排版算:同一行的卡片 top 相同。
  $('#styles').onkeydown=event=>{
    const button=event.target.closest('[data-style]'); if(!button)return;
    const tiles=[...$$('#styles [data-style]')];
    const index=tiles.indexOf(button);
    if(index<0)return;
    const tops=tiles.map(tile=>tile.offsetTop);
    const rowStart=tops.indexOf(tops[index]);
    let rowEnd=rowStart; while(rowEnd<tops.length&&tops[rowEnd]===tops[rowStart])rowEnd++;
    const columns=Math.max(1,rowEnd-rowStart);
    let next=-1;
    if(event.key==='ArrowRight')next=index+1;
    else if(event.key==='ArrowLeft')next=index-1;
    else if(event.key==='ArrowDown')next=index+columns;
    else if(event.key==='ArrowUp')next=index-columns;
    else if(event.key==='Home')next=0;
    else if(event.key==='End')next=tiles.length-1;
    else if(event.key==='Enter'||event.key===' '){event.preventDefault();state.style=button.dataset.style;applyStyleHint();button.focus();return;}
    else return;
    event.preventDefault();
    if(next>=0&&next<tiles.length){tiles[next].focus();}
  };
  $('#styleImage').onerror=()=>{$('#styleImage').hidden=true;$('#styleImageFallback').hidden=false;$('#styleImageFallback').textContent='该风格样张暂不可用';};
  $('#styleImage').onload=()=>{$('#styleImage').hidden=false;$('#styleImageFallback').hidden=true;};
  $('#retryHealth').onclick=()=>loadHealth(); $('#healthPill').onclick=()=>loadHealth(); $('#retryCatalog').onclick=loadPresets;
  $('#retrySettings').onclick=loadSettings; $('#settingsForm').onsubmit=saveSettings; $('#btnTest').onclick=testSettings;
  $('#btnParse').onclick=parseSource; $('#source').addEventListener('input',updateHint);
  $('#guideClose').onclick=dismissGuide; $('#guideRestore').onclick=restoreGuide;
  $('#pDuration').addEventListener('blur',commitDuration); $('#pDuration').addEventListener('input',updateHint);
  ['#pType','#pRatio','#pResolution','#offline'].forEach(selector=>$(selector).addEventListener('change',updateHint));
  ['#pCW','#pCH'].forEach(selector=>$(selector).addEventListener('input',updateHint));
  $('#pVoice').addEventListener('change',()=>{stopAudition();message('#voiceHint',state.voices.find(item=>item.id===$('#pVoice').value)?.desc || '');updateHint();});
  $('#btnAudition').onclick=audition; $('#drop').onclick=()=>$('#file').click();
  $('#file').onchange=event=>{if(event.target.files[0])pickFile(event.target.files[0]);};
  $('#drop').ondragover=event=>{event.preventDefault();if(state.narration!=='silent')$('#drop').classList.add('over');};
  $('#drop').ondragleave=()=>$('#drop').classList.remove('over');
  $('#drop').ondrop=event=>{event.preventDefault();$('#drop').classList.remove('over');if(event.dataTransfer.files[0])pickFile(event.dataTransfer.files[0]);};
  $('#removeAudio').onclick=()=>{clearAudio();message('#uploadHint','录音已移除，将使用所选 AI 音色。');};
  $('#go').onclick=generate; $('#retryTask').onclick=retryTask;
  $('#refreshArchive').onclick=loadArchive; $('#retryArchive').onclick=loadArchive;
  $('#archive').onclick=event=>{const button=event.target.closest('[data-project]');if(button)showProject(button.dataset.project);};
  for (const [id,action] of [['btnCheck','check'],['btnShip','ship']]) $(`#${id}`).onclick=()=>submitAction(action,state.project?.name);
  $('#btnEdit').onclick=()=>{$('#editor').hidden=!$('#editor').hidden;$('#btnEdit').setAttribute('aria-expanded',String(!$('#editor').hidden));if(!$('#editor').hidden){$('#editBox').value=state.drafts[state.tab] || '{}';$('#editBox').focus();}};
  $$('.editor-tabs button').forEach(button=>{button.onclick=()=>selectEditorTab(button.dataset.tab);button.onkeydown=event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const target=event.key==='Home'?'script':event.key==='End'?'film':state.tab==='script'?'film':'script';selectEditorTab(target);$(target==='script'?'#tabScript':'#tabFilm').focus();}};});
  $('#editBox').addEventListener('input',()=>{state.drafts[state.tab]=$('#editBox').value;message('#saveHint','有未保存的 JSON 改动。保存不会自动改变现有成片。');});
  $('#btnSave').onclick=saveEditor; $('#btnRebuild').onclick=rebuild;
  $('#btnRender').onclick=()=>{captureDraft();if(editorDirty()){message('#saveHint','请先保存改动。仅渲染使用已有构建产物；JSON 改动请用「重建并渲染」。',true);return;}submitAction('render',state.project?.name);};
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){stopAudition();if(!$('#shortcutsPanel').hidden)toggleShortcuts(false);return;}if(event.key.toLowerCase()==='n' && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey && !event.target.closest('input,textarea,select,[contenteditable=true]')){event.preventDefault();setView('new');$('#title').focus();return;}});
  // 快捷键面板
  let shortcutTrigger = null;
  function toggleShortcuts(show) {
    const panel = $('#shortcutsPanel');
    if (show) {shortcutTrigger = document.activeElement; panel.hidden = false; $('#shortcutsClose').focus();}
    else {panel.hidden = true; if(shortcutTrigger?.isConnected)shortcutTrigger.focus();}
  }
  $('#shortcuts').onclick = () => toggleShortcuts($('#shortcutsPanel').hidden);
  $('#shortcutsClose').onclick = () => toggleShortcuts(false);
  document.addEventListener('keydown', event => {
    if (event.key !== '?' || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.target.closest('input,textarea,select,[contenteditable=true]')) return;
    event.preventDefault();
    toggleShortcuts($('#shortcutsPanel').hidden);
  });
  window.addEventListener('hashchange',()=>setView(location.hash.slice(1)));
  window.addEventListener('beforeunload',event=>{captureDraft();if(editorDirty() || state.pending || state.uncertain){event.preventDefault();event.returnValue='';}});
  window.addEventListener('pagehide',()=>{stopAudition();clearTimeout(state.taskTimer);clearInterval(state.elapsedTimer);});
  setView(['new','edit','works','settings'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'new');
  // 引导默认展开;用户收起后记住选择(只存这个偏好,不放素材或任何凭据)。
  if (guideDismissed()) { $('#guide').classList.add('collapsed'); $('#guideRestore').hidden=false; }
  // Independent loads: a model or archive error must not swallow source/catalog initialization.
  Promise.allSettled([loadHealth(), loadPresets(), loadSettings(), loadArchive()]).then(() => {
    $('.inspector-scroll').scrollTop = 0;
    updateGuide();
  });
})();
