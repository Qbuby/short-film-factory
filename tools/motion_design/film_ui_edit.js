/* 剪辑模式前端。独立文件,由 film_ui_edit 的 IIFE 自行绑定,不改现有 studio 逻辑。
   只打同源 /api/edit/*,不加载外部库、不上报任何东西。 */
'use strict';
(() => {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state = { doc: null, project: '', transitions: [], assets: [], scanTimer: null, renderTimer: null };

  async function api(path, body, timeout = 120000) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), timeout);
    try {
      const r = await fetch(path, {
        method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: body === undefined ? {'Accept':'application/json'} : {'Content-Type':'application/json','Accept':'application/json'},
        body: body === undefined ? undefined : JSON.stringify(body), signal: ctl.signal,
      });
      const data = await r.json();
      if (!r.ok || data.error || data.ok === false) throw new Error(data.error || `HTTP ${r.status}`);
      return data;
    } catch (e) {
      if (e.name === 'AbortError') throw new Error('请求超时，服务可能仍在处理，请稍后刷新查看。');
      throw e;
    } finally { clearTimeout(timer); }
  }
  function say(sel, text, bad = false) {
    const el = $(sel); el.textContent = text; el.classList.toggle('error-text', bad);
  }
  function fmt(t) { return `${Number(t || 0).toFixed(2)}s`; }

  // ─────────────────────────── 素材库 ───────────────────────────
  async function loadAssets() {
    try {
      const d = await api('/api/edit/library');
      state.assets = d.items || [];
      const s = d.by_status || {};
      const bad = (s.missing || 0) + (s.changed || 0);
      $('#editLibCount').textContent = `${d.total} 个素材 · ${s.ready || 0} 可用${bad ? ` · ${bad} 需处理` : ''}`;
      $('#editAssets').innerHTML = state.assets.length ? state.assets.map(a => {
        const thumb = a.thumb ? `<img src="${esc(a.thumb)}" loading="lazy" alt="">` : '';
        const warn = a.status !== 'ready' ? `<span class="edit-bad">${a.status === 'missing' ? '文件缺失' : '文件已变更'}</span>` : '';
        const u = a.understanding === 'ready' ? '已理解' : a.understanding === 'failed' ? '理解失败' : '待理解';
        const summary = a.summary ? `<small>${esc(a.summary)}</small>` : '';
        return `<div class="edit-asset" data-id="${esc(a.id)}"><div class="edit-thumb">${thumb}</div>
          <div class="edit-asset-body"><strong>${esc(a.name)}</strong> <span class="micro">${u}</span>${warn}
          <small>${esc(a.kind)} · ${fmt(a.duration)} · ${a.shots} 个语义段${a.asr ? ' · 已识别口播' : ''}</small>${summary}
          <small class="mono edit-path" title="${esc(a.path)}">${esc(a.path)}</small>
          <div class="edit-row"><input class="edit-tags" data-id="${esc(a.id)}" value="${esc(a.tags)}" aria-label="标签"><button class="text-button edit-save-tags" data-id="${esc(a.id)}">存标签</button><button class="text-button edit-understand" data-id="${esc(a.id)}">重新理解</button><button class="text-button edit-remove" data-id="${esc(a.id)}">移除</button></div></div></div>`;
      }).join('') : '<div class="empty-state">素材库是空的。把本机视频或图片的路径粘到上面，点「登记素材」。</div>';
      const banner = $('#editMissing');
      if (bad) {
        banner.hidden = false;
        $('#editMissingText').textContent = `有 ${bad} 个素材文件缺失或已变更，出片前必须重新定位或移除。原始文件不会被删除。`;
        $('#editRelocate').hidden = false;
      } else { banner.hidden = true; $('#editRelocate').hidden = true; }
    } catch (e) { say('#editScanMsg', `素材库读取失败：${e.message}`, true); }
  }

  async function register() {
    const paths = $('#editPaths').value.split(/[\r\n]+/).map(s => s.trim()).filter(Boolean);
    if (!paths.length) { say('#editScanMsg', '请先填写至少一个文件或文件夹路径。', true); return; }
    const btn = $('#btnRegister'); btn.disabled = true;
    say('#editScanMsg', '正在登记…');
    try {
      const r = await api('/api/edit/register', {paths, tag: $('#editTag').value, asr: $('#editAsr').checked});
      $('#btnRegister').disabled = false;
      pollScan(r.task);
    } catch (e) { btn.disabled = false; say('#editScanMsg', `登记失败：${e.message}`, true); }
  }

  function pollScan(id) {
    clearInterval(state.scanTimer);
    state.scanTimer = setInterval(async () => {
      try {
        const j = await api(`/api/edit/scan?id=${encodeURIComponent(id)}`, undefined, 15000);
        if (j.status === 'running') {
          say('#editScanMsg', `正在分析 ${j.done}/${j.total}：${j.current}`);
          return;
        }
        clearInterval(state.scanTimer);
        if (j.status === 'failed') { say('#editScanMsg', `登记失败：${j.error}`, true); return; }
        const r = j.result || {};
        say('#editScanMsg', `已登记 ${r.added} 个，更新 ${r.updated} 个，跳过 ${r.skipped} 个。`);
        $('#editPaths').value = '';
        loadAssets();
      } catch (e) { clearInterval(state.scanTimer); say('#editScanMsg', `进度查询失败：${e.message}`, true); }
    }, 900);
  }

  async function checkStatus() {
    try {
      const s = await api('/api/edit/status');
      say('#editScanMsg', `检查完成：${s.ready}/${s.total} 可用；缺失 ${s.missing.length}，变更 ${s.changed.length}。`);
      loadAssets();
    } catch (e) { say('#editScanMsg', `检查失败：${e.message}`, true); }
  }

  // ─────────────────────────── 需求 → 时间轴 ───────────────────────────
  async function plan() {
    const requirement = $('#editRequirement').value.trim();
    if (!requirement) { say('#editPlanMsg', '请写一句需求，例如「海边黄昏开头，接产品特写」。', true); return; }
    const btn = $('#btnPlan'); btn.disabled = true;
    say('#editPlanMsg', '正在理解需求并锁定素材…');
    try {
      const r = await api('/api/edit/plan', {
        project: state.project || undefined, requirement,
        duration: Number($('#editDuration').value) || 15,
        title: requirement.slice(0, 24), width: 1080, height: 1920, fps: 30,
        allow_web: $('#editAllowWeb').checked,
      });
      state.project = r.project;
      await pollTask(r.task, (msg) => say('#editPlanMsg', msg), async () => {
        const d = await api(`/api/edit/doc?project=${encodeURIComponent(state.project)}`);
        state.doc = d.doc;
        renderTimeline();
      });
    } catch (e) { say('#editPlanMsg', `锁定失败：${e.message}`, true); }
    finally { btn.disabled = false; }
  }

  async function pollTask(tid, onProgress, onDone) {
    clearInterval(state.renderTimer);
    return new Promise((resolve) => {
      state.renderTimer = setInterval(async () => {
        let t;
        try { t = await api(`/api/task?id=${encodeURIComponent(tid)}`, undefined, 15000); }
        catch (e) { clearInterval(state.renderTimer); onProgress(`任务状态查询失败：${e.message}`); resolve(false); return; }
        if (t.status === 'running') {
          onProgress(`进行中：${t.stage?.name || '处理中'} · ${Math.round(t.logs?.length || 0)} 行日志`);
          return;
        }
        clearInterval(state.renderTimer);
        if (t.status === 'failed') {
          const tail = (t.logs || []).slice(-3).join(' | ').slice(0, 400);
          onProgress(`失败：${tail || '未知原因'}`);
          resolve(false);
          return;
        }
        onProgress('完成。');
        try { await onDone(t); } catch (e) { onProgress(`读取结果失败：${e.message}`); }
        resolve(true);
      }, 1000);
    });
  }

  const TRANS_OPTIONS = ['硬切','淡入淡出','黑场过渡','白场过渡','左擦除','右擦除','上擦除','下擦除','左推入','右推入','上推入','下推入','圆形展开','圆形收拢','径向','溶解','像素化'];

  function renderTimeline() {
    const doc = state.doc;
    const box = $('#editTimeline');
    if (!doc || !(doc.cuts || []).length) {
      box.innerHTML = '<div class="empty-state">没有锁定到素材。先登记素材，再写需求试试。</div>';
      $('#editTlActions').hidden = true; $('#editTotal').textContent = '—';
      return;
    }
    state.transitions = doc.transitions || TRANS_OPTIONS;
    $('#editTotal').textContent = `${doc.cuts.length} 段 · ${fmt(doc.total)}${doc.mode === 'rules' ? ' · 受限模式（关键词匹配）' : ' · 模型规划'}`;
    box.innerHTML = doc.cuts.map((c, i) => {
      const name = c.source ? c.source.split(/[\\/]/).pop() : `文字卡：${(c.overlay?.text || '').slice(0, 16)}`;
      const tr = c.transition_in?.type || '硬切';
      const opts = state.transitions.map(t => `<option value="${esc(t)}"${t === tr ? ' selected' : ''}>${esc(t)}</option>`).join('');
      return `<div class="edit-cut" data-index="${i}">
        <div class="edit-cut-head"><strong>${i + 1}. ${esc(name)}</strong><span class="micro">${fmt(c.timeline_duration)} · 起 ${fmt(c.timeline_start)} · 层 ${c.layer}</span></div>
        <p class="hint">${esc(c.reason || '未记录命中原因')}</p>
        <div class="edit-fields">
          <label>入点 <input type="number" step="0.1" min="0" data-field="source_in" value="${Number(c.source_in || 0).toFixed(2)}"></label>
          <label>出点 <input type="number" step="0.1" min="0" data-field="source_out" value="${Number(c.source_out || 0).toFixed(2)}"></label>
          <label>变速 <input type="number" step="0.05" min="0.25" max="4" data-field="speed" value="${Number(c.speed || 1).toFixed(2)}"></label>
          <label>转场 <select data-field="transition_in">${opts}</select></label>
          <label>时长 <input type="number" step="0.1" min="0.1" max="2" data-field="trans_duration" value="${Number(c.transition_in?.duration || 0.4).toFixed(2)}"></label>
          <label>层 <input type="number" step="1" min="0" max="8" data-field="layer" value="${c.layer || 0}"></label>
          <label>画中画起 <input type="number" step="0.1" min="0" data-field="pip_start" value="${Number(c.pip_start || 0).toFixed(2)}"></label>
        </div>
        <div class="edit-row"><button class="text-button edit-up" data-index="${i}"${i === 0 ? ' disabled' : ''}>上移</button><button class="text-button edit-down" data-index="${i}"${i === doc.cuts.length - 1 ? ' disabled' : ''}>下移</button><button class="text-button edit-pip" data-index="${i}">复制为画中画</button><button class="text-button edit-del" data-index="${i}">移除</button></div>
      </div>`;
    }).join('');
    $('#editTlActions').hidden = false;
    $('#editCandidates').innerHTML = (doc.candidates || []).length
      ? `<div class="section-heading"><h3>可替换的候选片段</h3><span class="micro">点「用这个」换掉对应镜头</span></div>` +
        doc.candidates.slice(0, 8).map((h, i) => `<div class="edit-cand" data-index="${i}">
          <span>${esc(h.name)} · ${fmt(h.in_seconds)}–${fmt(h.out_seconds)}</span>
          <small>${esc(h.reason)}</small><button class="small-button edit-pick" data-index="${i}">用这个</button></div>`).join('')
      : '';
  }

  function collect() {
    if (!state.doc) return null;
    $$('#editTimeline .edit-cut').forEach((row, i) => {
      const c = state.doc.cuts[i];
      row.querySelectorAll('[data-field]').forEach(el => {
        const f = el.dataset.field;
        if (f === 'transition_in') {
          c.transition_in = c.transition_in || {};
          c.transition_in.type = el.value;
        } else if (f === 'trans_duration') {
          c.transition_in = c.transition_in || {};
          c.transition_in.duration = Number(el.value) || 0;
        } else if (f === 'layer' || f === 'speed' || f === 'source_in' || f === 'source_out' || f === 'pip_start') {
          c[f] = Number(el.value);
        }
      });
      // 时间轴字段由后端契约重算,前端不伪造
    });
    return state.doc;
  }

  async function saveDoc() {
    const doc = collect();
    if (!doc) return false;
    try {
      await api('/api/edit/save', {project: state.project, doc});
      say('#editRenderMsg', '时间轴已保存。');
      return true;
    } catch (e) { say('#editRenderMsg', `保存失败：${e.message}`, true); return false; }
  }

  async function render(preview) {
    if (!await saveDoc()) return;
    $('#editRenderMsg').textContent = preview ? '正在出预览…' : '正在出成片…';
    try {
      const r = await api('/api/edit/render', {project: state.project, preview});
      await pollTask(r.task, (m) => say('#editRenderMsg', m, m.startsWith('失败')), async () => {
        const v = await api(`/api/edit/video?project=${encodeURIComponent(state.project)}`);
        $('#editPlayer').hidden = false;
        $('#editVideo').src = v.url;
        $('#editVideo').load();
        say('#editRenderMsg', preview ? '预览已生成。' : '成片已生成，可在作品库查看与归档。');
      });
    } catch (e) { say('#editRenderMsg', `出片失败：${e.message}`, true); }
  }

  // ─────────────────────────── 事件 ───────────────────────────
  $('#btnRegister').onclick = register;
  $('#btnEditStatus').onclick = checkStatus;
  $('#btnEditRefresh').onclick = loadAssets;
  $('#btnRelocate').onclick = async () => {
    try {
      const r = await api('/api/edit/relocate', {old: $('#editOld').value, new: $('#editNew').value});
      say('#editScanMsg', `已重定位 ${r.moved} 个${r.failed.length ? `，${r.failed.length} 个目标文件不存在` : ''}。`);
      loadAssets();
    } catch (e) { say('#editScanMsg', `重定位失败：${e.message}`, true); }
  };
  $('#editAssets').onclick = async (e) => {
    const rm = e.target.closest('.edit-remove');
    const tg = e.target.closest('.edit-save-tags');
    const ud = e.target.closest('.edit-understand');
    if (rm) {
      await api('/api/edit/remove', {id: rm.dataset.id}); loadAssets(); return;
    }
    if (tg) {
      const input = $(`.edit-tags[data-id="${CSS.escape(tg.dataset.id)}"]`);
      await api('/api/edit/tags', {id: tg.dataset.id, tags: input.value});
      say('#editScanMsg', '标签已保存。'); return;
    }
    if (ud) {
      ud.disabled = true; say('#editScanMsg', '正在让模型重新理解这条素材（约十几秒）…');
      try {
        const r = await api('/api/edit/understand', {id: ud.dataset.id, force: true}, 180000);
        say('#editScanMsg', `理解完成：${r.segments || 0} 个语义段。`);
        loadAssets();
      } catch (err) { say('#editScanMsg', `理解失败：${err.message}`, true); ud.disabled = false; }
    }
  };
  $('#btnPlan').onclick = plan;
  $('#btnEditSave').onclick = saveDoc;
  $('#btnEditPreview').onclick = () => render(true);
  $('#btnEditRender').onclick = () => render(false);
  $('#editTimeline').onclick = (e) => {
    const i = Number((e.target.closest('[data-index]') || {}).dataset?.index);
    if (Number.isNaN(i) || !state.doc) return;
    if (e.target.closest('.edit-up') && i > 0) {
      [state.doc.cuts[i - 1], state.doc.cuts[i]] = [state.doc.cuts[i], state.doc.cuts[i - 1]];
      renderTimeline();
    } else if (e.target.closest('.edit-down') && i < state.doc.cuts.length - 1) {
      [state.doc.cuts[i + 1], state.doc.cuts[i]] = [state.doc.cuts[i], state.doc.cuts[i + 1]];
      renderTimeline();
    } else if (e.target.closest('.edit-del')) {
      state.doc.cuts.splice(i, 1); renderTimeline();
    } else if (e.target.closest('.edit-pip')) {
      const copy = JSON.parse(JSON.stringify(state.doc.cuts[i]));
      copy.id = `pip${Date.now().toString(36)}`;
      copy.layer = 1; copy.pip_start = 0;
      copy.transition_in = {type: '硬切', duration: 0};
      copy.transform = {...(copy.transform || {}), position: [0.75, 0.18]};
      state.doc.cuts.push(copy); renderTimeline();
    }
  };
  $('#editCandidates').onclick = (e) => {
    const b = e.target.closest('.edit-pick');
    if (!b || !state.doc) return;
    const h = (state.doc.candidates || [])[Number(b.dataset.index)];
    if (!h) return;
    const first = state.doc.cuts.find(c => c.layer === 0);
    if (!first) return;
    Object.assign(first, {
      source: h.path, source_in: h.in_seconds,
      source_out: Math.min(h.out_seconds, h.in_seconds + 4), speed: 1,
      reason: h.reason,
    });
    renderTimeline();
    say('#editRenderMsg', `已用「${h.name}」替换第 1 段，记得保存时间轴。`);
  };

  // 首次进入剪辑页时加载素材库;导航由主脚本的 setView 负责。
  window.addEventListener('hashchange', () => { if (location.hash === '#edit') loadAssets(); });
  if (location.hash === '#edit') loadAssets();
  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-view="edit"]')) loadAssets();
  });
  // 供主脚本在切换到剪辑页时调用(不侵入它的代码)
  window.editModeLoad = loadAssets;
})();
