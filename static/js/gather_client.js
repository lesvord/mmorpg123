/* Улучшенный клиент добычи: прогрев + тосты с весом/названием */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const BOOT = window.WORLD_BOOT || { endpoints: {} };
  const EP = Object.assign({
    state: '/world/state',
    gatherStart: '/world/gather/start',
    gatherStop:  '/world/gather/stop',
    gatherTick:  '/world/gather/tick',
  }, BOOT.endpoints || {});

  const MODE_DEFAULTS = [
    { key:'forage', title:'Сбор', icon:'🌿', description:'Сбор трав и ягод.' },
    { key:'wood',   title:'Деревья', icon:'🌲', description:'Рубка деревьев и получение древесины.' },
    { key:'ore',    title:'Камни', icon:'🪨', description:'Добыча камня и руды.' },
  ];

  let MODES = Array.isArray(BOOT.gatherModes) && BOOT.gatherModes.length
    ? BOOT.gatherModes.slice()
    : MODE_DEFAULTS.slice();

  function findMode(key){
    if (!key) return null;
    const norm = String(key).toLowerCase();
    return MODES.find(m => String(m.key).toLowerCase() === norm) || null;
  }

  let currentMode = (() => {
    let initial = null;
    try{ const saved = localStorage.getItem('gather_mode'); if (saved) initial = saved; }catch(_){ }
    if (!initial) initial = BOOT.gatherDefaultMode || null;
    const found = findMode(initial) || MODES[0] || null;
    return found ? found.key : 'forage';
  })();

  function modeLabel(modeKey){
    const m = findMode(modeKey);
    if (!m) return '⛏️ Добывать';
    return `${m.icon || '⛏️'} ${m.title}`;
  }

  // -------- fetch helpers --------
  async function jPOST(url, data) {
    try{
      const r = await fetch(url, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: data ? JSON.stringify(data) : '{}'
      });
      const j = await r.json().catch(()=>({ok:false,error:'bad_json'}));
      if (!r.ok) j.ok = false;
      return j;
    }catch(e){
      return {ok:false,error:'network',detail:String(e)};
    }
  }

  // -------- mini UI utils --------
  function setHUDfatigue(val){
    const v = Math.max(0, Math.min(100, Number(val)||0));
    const fatEl = $('fat'); if (fatEl) fatEl.textContent = v.toFixed(0);
    const bar = $('fatFill'); if (bar) bar.style.width = Math.min(100, v) + '%';
  }

  function fmtKg(x){
    const n = Math.round(Number(x)*100)/100;
    const s = String(n);
    return s.replace('.', ',');
  }

  function iconFor(key, fallback){
    const k = String(key||'');
    if (k.includes('wood') || k.includes('stick')) return '🪵';
    if (k.includes('stone') || k.includes('ore') || k.includes('obsidian') || k.includes('gem')) return '🪨';
    if (k.includes('berries')) return '🫐';
    if (k.includes('mushroom')) return '🍄';
    if (k.includes('fish')) return '🐟';
    if (k.includes('sand')) return '⏳';
    if (k.includes('reed') || k.includes('fiber') || k.includes('herb')) return '🌿';
    if (k.includes('ice')) return '🧊';
    if (k.includes('cactus')) return '🌵';
    return fallback || '⛏️';
  }

  // -------- toast UI (injected CSS + DOM) --------
  function injectToastCSS(){
    if (document.getElementById('loot-toast-css')) return;
    const s = document.createElement('style');
    s.id = 'loot-toast-css';
    s.textContent = `
      .loot-toasts{position:fixed;left:0;right:0;bottom:calc(60px + env(safe-area-inset-bottom,0px));z-index:120;display:flex;flex-direction:column;align-items:center;gap:8px;pointer-events:none}
      .loot-toast{
        pointer-events:auto;
        display:flex; align-items:center; gap:10px;
        background:rgba(20,22,28,.95);
        border:1px solid rgba(255,255,255,.12);
        padding:10px 12px; border-radius:14px; box-shadow:0 10px 28px rgba(0,0,0,.45);
        color:#fff; font:600 14px/1.2 system-ui,Segoe UI,Roboto; transform: translateY(8px); opacity:0; transition: all .18s ease
      }
      .loot-toast.show{transform: translateY(0); opacity:1}
      .loot-toast .ico{font-size:18px;line-height:1}
      .loot-toast .name{font-weight:800}
      .loot-toast .meta{opacity:.9}
      .loot-toast.miss{opacity:.92;background:rgba(255,255,255,.08)}
      .loot-toast.success{border-color:rgba(92,204,133,.45)}
      .loot-toast.warn{border-color:rgba(255,77,103,.45)}
    `;
    document.head.appendChild(s);
  }
  function ensureToastRoot(){
    let r = document.querySelector('.loot-toasts');
    if (!r){
      r = document.createElement('div');
      r.className = 'loot-toasts';
      document.body.appendChild(r);
    }
    return r;
  }
  function showToast(opts){
    injectToastCSS();
    const root = ensureToastRoot();
    const el = document.createElement('div');
    el.className = 'loot-toast ' + (opts.variant || 'success');
    el.innerHTML = `
      <div class="ico">${opts.icon || '⛏️'}</div>
      <div class="text">
        <div class="name">${opts.title || ''}</div>
        ${opts.meta ? `<div class="meta">${opts.meta}</div>` : ``}
      </div>
    `;
    root.appendChild(el);
    // entrance
    requestAnimationFrame(()=> el.classList.add('show'));
    // auto close
    const ttl = opts.ttl || 2200;
    setTimeout(()=> {
      el.classList.remove('show');
      setTimeout(()=> el.remove(), 200);
    }, ttl);
    // vibrate a bit (if supported)
    try{ navigator.vibrate && navigator.vibrate(18); }catch(_){}
  }

  function toastFromTick(resp){
    if (resp && resp.profile) lastProfile = resp.profile;
    if (resp && resp.profile && typeof resp.profile.tick_ms === 'number'){
      TICK_MS = Math.max(2000, Number(resp.profile.tick_ms));
    }

    // успех
    if (resp && Array.isArray(resp.items) && resp.items.length){
      const it = resp.items[0];
      const kg = (typeof it.weight_kg !== 'undefined') ? fmtKg(it.weight_kg) : '—';
      const qty = Number(it.qty || 1);
      const title = `${iconFor(it.key, it.icon)} ${it.name}`;
      const metaParts = [];
      metaParts.push(`Вес: ${kg} кг/шт`);
      metaParts.push(`Количество: +${qty}`);
      if (resp.fatigue_extra){
        metaParts.push(`Усталость +${Number(resp.fatigue_extra).toFixed(2)}`);
      }
      if (resp.totals && typeof resp.totals.load_pct !== 'undefined'){
        const pct = Math.round(Number(resp.totals.load_pct) || 0);
        metaParts.push(`Нагрузка ${pct}%`);
      }
      showToast({ title, meta: metaParts.join(' · '), icon: iconFor(it.key, it.icon), variant:'success', ttl: 2600 });
      return;
    }
    // перегруз / предупреждение
    if (resp && resp.error === 'overweight'){
      showToast({ title: 'Перегруз', meta:'Освободите рюкзак', icon:'⚠️', variant:'warn', ttl: 2600 });
      return;
    }
    // промах
    showToast({ title: 'Пусто', meta: resp && resp.message || 'Ничего не найдено', icon:'🪨', variant:'miss', ttl: 1600 });
  }

  function updateModeButtons(){
    const bar = $('gatherModeBar');
    if (!bar) return;
    bar.querySelectorAll('.mode-btn').forEach(btn => {
      const active = String(btn.dataset.mode || '').toLowerCase() === String(currentMode).toLowerCase();
      btn.classList.toggle('active', active);
      if (active) btn.setAttribute('aria-pressed', 'true');
      else btn.setAttribute('aria-pressed', 'false');
    });
  }

  function renderModeButtons(){
    const bar = $('gatherModeBar');
    if (!bar) return;
    bar.innerHTML = '';
    if (!MODES.length) return;
    MODES.forEach(mode => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'mode-btn' + (mode.key === currentMode ? ' active' : '');
      btn.dataset.mode = mode.key;
      btn.innerHTML = `<span class="ico">${mode.icon || '⛏️'}</span><span>${mode.title}</span>`;
      if (mode.description) btn.title = mode.description;
      btn.setAttribute('aria-pressed', mode.key === currentMode ? 'true' : 'false');
      btn.addEventListener('click', () => {
        if (mode.key === currentMode) return;
        setMode(mode.key);
      });
      bar.appendChild(btn);
    });
    updateModeButtons();
  }

  function setMode(key){
    const found = findMode(key);
    if (!found) return false;
    currentMode = found.key;
    try{ localStorage.setItem('gather_mode', currentMode); }catch(_){ }
    updateModeButtons();
    if (state === 'idle') setBtnMiningUI(false);
    if (!window.GatherMode) window.GatherMode = {};
    window.GatherMode.current = currentMode;
    return true;
  }

  // -------- state --------
  let state = 'idle';   // 'idle' | 'windup' | 'mining'
  let windupTimer = null;
  let tickTimer   = null;
  let TICK_MS = 4200;   // ритм тиков
  let lastProfile = null;

  function setBtnMiningUI(mining, label){
    const btn = $('btnGather'); if(!btn) return;
    btn.classList.toggle('active', !!mining);
    btn.classList.toggle('gather-active', !!mining);
    btn.disabled = false;
    const idleLabel = modeLabel(currentMode);
    if (label){
      btn.textContent = label;
    } else if (mining){
      const tickSec = Math.max(2, Math.round(TICK_MS/100)/10).toFixed(1);
      btn.textContent = `⛏️ Остановить · ${tickSec}s`;
    } else {
      btn.textContent = idleLabel;
    }
  }

  function setBtnWindupUI(ms){
    const btn = $('btnGather'); if(!btn) return;
    const started = Date.now();
    btn.disabled = false;
    function tick(){
      const left = Math.max(0, ms - (Date.now() - started));
      const s = Math.ceil(left/100)/10; // десятые
      const lbl = modeLabel(currentMode);
      btn.textContent = `${lbl} · подготовка ${s.toFixed(1)}s`;
      if (left <= 0){ return; }
      windupTimer = setTimeout(tick, 80);
    }
    tick();
  }

  // -------- logic --------
  async function doTick(){
    const r = await jPOST(EP.gatherTick, { mode: currentMode });
    if (!r || !r.ok){
      (window.pkToast||alert)((r && (r.message||r.error)) || 'Ошибка добычи');
      stopMining(true);
      return;
    }
    if (r.profile) lastProfile = r.profile;
    if (r.mode) setMode(r.mode);
    if (r.profile && typeof r.profile.tick_ms === 'number'){
      TICK_MS = Math.max(2000, Number(r.profile.tick_ms));
    }
    // обновим усталость мгновенно, без доп. запроса
    if (typeof r.fatigue !== 'undefined') setHUDfatigue(r.fatigue);
    // покажем тост
    toastFromTick(r);
    // инвентарь: мягкое обновление, если UI его слушает
    if (window.WorldInv && typeof window.WorldInv.refresh === 'function') {
      try{ window.WorldInv.refresh(); }catch(_){}
    }
    // достигнут лимит усталости?
    if (typeof r.fatigue === 'number' && r.fatigue >= 100){
      setBtnMiningUI(false);
      state = 'idle';
      (window.pkToast||alert)('Вы выдохлись. Добыча остановлена.');
      return;
    }
    // расписать следующий тик
    if (state === 'mining'){
      clearTimeout(tickTimer);
      tickTimer = setTimeout(doTick, TICK_MS);
    }
  }

  async function startMining(){
    if (state !== 'idle') return;
    const r = await jPOST(EP.gatherStart, { mode: currentMode });
    if (!r || !r.ok){
      (window.pkToast||alert)( (r && (r.message||r.error)) || 'Нельзя начать добычу' );
      return;
    }
    if (r.profile) lastProfile = r.profile;
    if (Array.isArray(r.modes) && r.modes.length){
      MODES = r.modes.slice();
      if (!findMode(currentMode)) currentMode = (r.mode && findMode(r.mode) ? r.mode : (MODES[0] && MODES[0].key));
      renderModeButtons();
    }
    if (r.mode) setMode(r.mode);
    const windup = Math.max(800, Number(r.windup_ms || 2000)); // минимум 0.8s для фидбэка
    if (typeof r.tick_ms === 'number'){
      TICK_MS = Math.max(2000, Number(r.tick_ms));
    }
    state = 'windup';
    setBtnWindupUI(windup);

    clearTimeout(windupTimer);
    windupTimer = setTimeout(()=>{
      if (state !== 'windup') return;  // отменено
      state = 'mining';
      setBtnMiningUI(true);
      doTick(); // первый тик
      clearTimeout(tickTimer);
      tickTimer = setTimeout(doTick, TICK_MS);
    }, windup);
  }

  async function stopMining(silent){
    if (state === 'idle' && !silent) return;
    state = 'idle';
    clearTimeout(windupTimer); windupTimer = null;
    clearTimeout(tickTimer);   tickTimer = null;
    setBtnMiningUI(false);
    if (!silent){
      const r = await jPOST(EP.gatherStop, { mode: currentMode });
      if (r && r.ok && r.message) (window.pkToast||alert)(r.message);
    }
  }

  function bind(){
    const btn = $('btnGather');
    if (!btn) return;
    btn.dataset.gatherManaged = '1';
    renderModeButtons();
    updateModeButtons();
    setBtnMiningUI(false);
    btn.addEventListener('click', () => {
      if (state === 'idle') startMining();
      else stopMining(false);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();

  // экспорт на всякий
  window.GatherMode = window.GatherMode || {};
  window.GatherMode.getMode = () => currentMode;
  window.GatherMode.setMode = setMode;
  window.GatherMode.list = () => MODES.slice();
  window.GatherMode.current = currentMode;

  window.Gather = { start: startMining, stop: stopMining };
})();
