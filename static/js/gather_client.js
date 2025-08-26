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
    // успех
    if (resp && Array.isArray(resp.items) && resp.items.length){
      const it = resp.items[0];
      const kg = (typeof it.weight_kg !== 'undefined') ? fmtKg(it.weight_kg) : '—';
      const title = `${iconFor(it.key, it.icon)} ${it.name}`;
      const meta  = `Вес: ${kg} кг · +1 шт`;
      showToast({ title, meta, icon: iconFor(it.key, it.icon), variant:'success', ttl: 2600 });
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

  // -------- state --------
  let state = 'idle';   // 'idle' | 'windup' | 'mining'
  let windupTimer = null;
  let tickTimer   = null;
  let TICK_MS = 4000;   // ритм тиков

  function setBtnMiningUI(mining, label){
    const btn = $('btnGather'); if(!btn) return;
    btn.classList.toggle('active', !!mining);
    btn.disabled = false;
    btn.textContent = label || (mining ? '⛏️ Остановить' : '⛏️ Добывать');
  }

  function setBtnWindupUI(ms){
    const btn = $('btnGather'); if(!btn) return;
    const started = Date.now();
    btn.disabled = false;
    function tick(){
      const left = Math.max(0, ms - (Date.now() - started));
      const s = Math.ceil(left/100)/10; // десятые
      btn.textContent = `⛏️ Подготовка ${s.toFixed(1)}s`;
      if (left <= 0){ return; }
      windupTimer = setTimeout(tick, 80);
    }
    tick();
  }

  // -------- logic --------
  async function doTick(){
    const r = await jPOST(EP.gatherTick, {});
    if (!r || !r.ok){
      (window.pkToast||alert)((r && (r.message||r.error)) || 'Ошибка добычи');
      stopMining(true);
      return;
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
    const r = await jPOST(EP.gatherStart, {});
    if (!r || !r.ok){
      (window.pkToast||alert)( (r && (r.message||r.error)) || 'Нельзя начать добычу' );
      return;
    }
    const windup = Math.max(800, Number(r.windup_ms || 2000)); // минимум 0.8s для фидбэка
    state = 'windup';
    setBtnWindupUI(windup);

    clearTimeout(windupTimer);
    windupTimer = setTimeout(()=>{
      if (state !== 'windup') return;  // отменено
      state = 'mining';
      setBtnMiningUI(true, '⛏️ Остановить');
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
    setBtnMiningUI(false, '⛏️ Добывать');
    if (!silent){
      const r = await jPOST(EP.gatherStop, {});
      if (r && r.ok && r.message) (window.pkToast||alert)(r.message);
    }
  }

  function bind(){
    const btn = $('btnGather');
    if (!btn) return;
    btn.addEventListener('click', () => {
      if (state === 'idle') startMining();
      else stopMining(false);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();

  // экспорт на всякий
  window.Gather = { start: startMining, stop: stopMining };
})();
