// static/js/world_ui.js — "Добывать" в отдельной строке; инвентарь ещё уже; без стамины
(() => {
  'use strict';

  const $  = (id) => document.getElementById(id);
  const q  = (sel, root=document) => root.querySelector(sel);
  const qsa= (sel, root=document) => Array.from(root.querySelectorAll(sel));

  const BOOT = (window.WORLD_BOOT || {});
  const ENDPOINTS = Object.assign({ state: '/world/state' }, BOOT.endpoints || {});

  // ============ CSS ============
  function injectCSSOnce(){
    if ($('#world-ui-css')) return;
    const s = document.createElement('style'); s.id='world-ui-css';
    s.textContent = `
      :root{
        --border: rgba(255,255,255,.10);
        --muted: rgba(255,255,255,.72);
        --brand:#3b82f6; --danger:#ff4d67; --chip:#1f2937;
        --fs-11:11px; --fs-12:12px; --fs-13:13px; --fs-14:14px;
        /* ещё компактнее инвентарь */
        --btn-h:24px; --btn-h-lg:28px; --inp-w:32px; --inp-h:24px;
        --icon-sz:20px; --gap:8px;
      }

      .wu-overlay{position:fixed;inset:0;z-index:9998;display:none;align-items:flex-end;justify-content:center}
      .wu-overlay.open{display:flex}
      .wu-backdrop{position:absolute;inset:0;background:rgba(0,0,0,.55);backdrop-filter:blur(6px);opacity:0;transition:opacity .18s ease}
      .wu-overlay.open .wu-backdrop{opacity:1}
      .wu-sheet{
        position:relative;width:min(860px,96vw);max-height:calc(86vh - env(safe-area-inset-bottom));
        overflow:auto;margin:10px;border-radius:16px;background:rgba(16,16,18,.98);
        border:1px solid var(--border);box-shadow:0 18px 50px rgba(0,0,0,.55);
        transform:translateY(8px);transition:transform .18s ease
      }
      .wu-overlay.open .wu-sheet{transform:translateY(0)}
      .wu-head{position:sticky;top:0;display:flex;align-items:center;gap:6px;padding:8px 10px;background:rgba(0,0,0,.35);backdrop-filter:blur(8px);border-bottom:1px solid rgba(255,255,255,.08);border-radius:16px 16px 0 0}
      .wu-tabs{display:flex;gap:6px;flex:1;flex-wrap:wrap}
      .wu-tab{padding:8px 10px;border-radius:10px;font-weight:800;font-size:var(--fs-13);background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.12);cursor:pointer}
      .wu-tab.active{background:var(--brand);color:#fff}
      .wu-x{margin-left:auto;background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.14);border-radius:10px;padding:6px 10px;color:#fff;cursor:pointer}
      .wu-body{padding:10px}
      .wu-panel{display:none}
      .wu-panel.active{display:block}
      .wu-overlay.open ~ #controlsBar{display:none !important}

      /* === overlay only === */
      .wu-sheet, .wu-sheet *{ box-sizing:border-box; }
      .wu-sheet .group{margin:8px 0;padding:10px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,.03)}
      .wu-sheet .kv{display:flex;justify-content:space-between;gap:10px;margin:4px 0;font-size:var(--fs-14)}
      .wu-sheet .kv b{font-variant-numeric:tabular-nums}
      .wu-sheet .muted{color:var(--muted)}
      .wu-sheet .tiny{opacity:.9;font-size:var(--fs-12)}
      .wu-sheet .micro{opacity:.85;font-size:var(--fs-11)}
      .wu-sheet .chip{display:inline-flex;align-items:center;gap:6px;padding:2px 8px;border-radius:999px;background:var(--chip);border:1px solid rgba(255,255,255,.08);font-size:var(--fs-12);color:#fff;text-decoration:none}
      .wu-sheet .pill{display:inline-block;padding:1px 6px;border-radius:999px;background:rgba(255,255,255,.12);font-size:var(--fs-11);margin-left:6px}
      .wu-sheet .badge-eq{display:inline-block;padding:1px 6px;border-radius:7px;background:var(--brand);color:#fff;font-size:11px;font-weight:700;margin-left:6px}

      .wu-sheet .progress{height:6px;background:rgba(255,255,255,.08);border-radius:999px;overflow:hidden}
      .wu-sheet .progress > i{display:block;height:100%;background:linear-gradient(90deg,#22c55e,#f59e0b,#ef4444);width:0%}

      /* Desktop inv grid */
      .wu-sheet .inv-grid{
        display:grid;gap:6px;align-items:center;
        grid-template-columns:minmax(0,1fr) 60px 68px minmax(0,1fr);
      }
      .wu-sheet .inv-row{display:contents}
      .wu-sheet .inv-name{display:flex;align-items:center;gap:6px;min-width:0}
      .wu-sheet .title-ellipsis{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .wu-sheet .inv-ico{width:18px;height:18px;border-radius:6px;background:#2b3444;border:1px solid var(--border);display:flex;align-items:center;justify-content:center;font-weight:800}

      /* Inventory buttons — ещё уже, icon-only */
      .wu-sheet .btn{
        padding:4px 8px;border-radius:9px;border:0;background:#374151;color:#fff;font-weight:800;
        cursor:pointer; min-height:var(--btn-h); height:auto; line-height:1.05; white-space:nowrap; max-width:100%;
        touch-action: manipulation;
      }
      .wu-sheet .btn.danger{background:var(--danger)}
      .wu-sheet .btn.clear{background:#2b3444}
      .wu-sheet .btn[disabled]{opacity:.5;cursor:not-allowed}
      .wu-sheet .btn.icon-sm{
        width:var(--icon-sz); height:var(--icon-sz); padding:0;
        display:inline-flex; align-items:center; justify-content:center;
        font-size:14px; border-radius:7px; line-height:1;
      }

      .wu-sheet .step{display:inline-grid;grid-template-columns:auto var(--inp-w) auto;gap:4px;align-items:center;min-width:0}
      .wu-sheet .step input{width:var(--inp-w);height:var(--inp-h);border-radius:8px;border:1px solid var(--border);background:rgba(255,255,255,.06);color:#fff;text-align:center}

      /* Mobile inv cards */
      .wu-sheet .inv-cards{display:none}
      .wu-sheet .inv-card{
        display:grid;gap:6px;padding:8px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,.02);
        width:100%; overflow:hidden;
      }
      .wu-sheet .inv-card .top{display:flex;align-items:center;gap:6px;justify-content:space-between;min-width:0}
      .wu-sheet .inv-card .name{display:flex;align-items:center;gap:6px;min-width:0}
      .wu-sheet .inv-card .title{font-weight:800;font-size:var(--fs-14);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:74vw}
      .wu-sheet .inv-card .actions{
        display:grid;grid-template-columns:1fr auto auto;gap:4px;align-items:center;min-width:0
      }
      .wu-sheet .inv-card .qty{display:grid;grid-template-columns:auto var(--inp-w) auto;gap:4px;align-items:center;min-width:0}
      .wu-sheet .inv-card .qty input{width:var(--inp-w);height:var(--btn-h-lg);border-radius:8px;border:1px solid var(--border);background:rgba(255,255,255,.06);color:#fff;text-align:center}
      .wu-sheet .inv-card button{min-height:var(--btn-h-lg);height:auto;border-radius:10px;max-width:100%}

      /* === Крафт === */
      .wu-sheet .craft-category{margin-bottom:16px}
      .wu-sheet .craft-cat-title{font-size:14px;font-weight:800;margin:0 0 8px 0;color:var(--brand)}
      .wu-sheet .craft-recipes{display:grid;gap:8px}
      .wu-sheet .craft-recipe{
        padding:10px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,.02)
      }
      .wu-sheet .craft-recipe-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
      .wu-sheet .craft-recipe-name{font-weight:800;font-size:14px}
      .wu-sheet .craft-recipe-time{font-size:12px;opacity:.8}
      .wu-sheet .craft-recipe-components{font-size:12px;margin-bottom:4px}
      .wu-sheet .craft-component{display:inline-block;padding:2px 6px;margin:2px;background:rgba(255,255,255,.08);border-radius:6px}
      .wu-sheet .craft-recipe-result{font-size:13px;color:#4ade80;margin-bottom:6px}
      .wu-sheet .craft-recipe-desc{font-size:12px;opacity:.8;margin-bottom:8px}
      .wu-sheet .craft-start{background:var(--brand);width:100%}

      .wu-sheet .craft-status{
        margin-bottom:16px;padding:12px;border:1px solid var(--border);border-radius:10px;
        background:rgba(255,255,255,.03)
      }
      .wu-sheet .craft-active .craft-name{font-weight:800;margin-bottom:4px}
      .wu-sheet .craft-active .craft-time{font-size:12px;opacity:.8;margin-bottom:8px}
      .wu-sheet .craft-progress{height:6px;background:rgba(255,255,255,.08);border-radius:3px;overflow:hidden}
      .wu-sheet .craft-progress .progress-bar{height:100%;background:var(--brand);transition:width 0.3s}
      .wu-sheet .craft-idle{text-align:center;opacity:.7;font-size:13px}
      .wu-sheet .craft-complete{background:#22c55e}
      .wu-sheet .craft-cancel{background:var(--danger)}

      @media (max-width:360px){
        .wu-sheet .inv-card .title{max-width:68vw}
        .wu-sheet .inv-card button{min-height:26px}
      }

      @media (max-width:560px){
        .wu-sheet{width:100vw;max-height:calc(86vh - env(safe-area-inset-bottom));border-radius:16px 16px 0 0;margin:0}
        .wu-sheet .inv-grid{display:none}
        .wu-sheet .inv-cards{display:grid;gap:6px}
      }
      .wu-sheet.wu-mobile .inv-grid{display:none}
      .wu-sheet.wu-mobile .inv-cards{display:grid;gap:6px}

      /* === Верхняя панель действий — Идти/Стоп/Лагерь === */
      #controlsBar{display:flex;flex-wrap:wrap;gap:var(--gap);align-items:center}
      #controlsBar .btn{
        min-height:48px; padding:10px 14px; font-size:clamp(14px, 3.8vw, 16px);
        border-radius:14px; font-weight:800; flex:1 1 calc(50% - var(--gap));
        max-width:calc(50% - var(--gap)); min-width:0; text-align:center;
        white-space:normal; overflow-wrap:anywhere; line-height:1.2;
      }
      @media (min-width:561px){
        #controlsBar .btn{ min-height:44px; font-size:15px; }
      }
      @media (max-width:380px){
        #controlsBar .btn{ flex-basis:100%; max-width:100%; }
      }
      #controlsBar .btn-go{order:1}
      #controlsBar .btn-stop{order:2}
      #controlsBar .btn-camp{order:3}

      .gather-mode-bar{
        display:flex; flex-wrap:wrap; gap:8px; justify-content:center;
        padding:0 10px; margin-top:6px;
      }
      .gather-mode-bar .mode-btn{
        border-radius:999px; border:1px solid rgba(255,255,255,.18);
        background:rgba(255,255,255,.05);
        color:#fff; font:600 13px/1.1 system-ui;
        padding:8px 12px; display:flex; align-items:center; gap:6px;
        cursor:pointer; transition:background .15s,border-color .15s,transform .15s;
      }
      .gather-mode-bar .mode-btn .ico{font-size:16px;line-height:1}
      .gather-mode-bar .mode-btn.active{
        background:#1f6feb; border-color:#3b82f6; box-shadow:0 4px 14px rgba(31,111,235,.45);
        transform:translateY(-1px);
      }
      .gather-mode-bar .mode-btn:focus-visible{outline:2px solid #3b82f6; outline-offset:2px}
      @media (max-width:420px){
        .gather-mode-bar{gap:6px}
        .gather-mode-bar .mode-btn{font-size:12px; padding:6px 10px}
      }

      /* === Отдельная строка для "Добывать" под #controlsBar === */
      #mineBar{margin-top:8px;padding:0 10px}
      #mineBar .btn{
        display:block; width:100%; max-width:540px; margin:0 auto;
        min-height:48px; padding:12px 16px; border-radius:14px; font-weight:800; text-align:center;
        font-size:clamp(15px, 4.2vw, 17px); line-height:1.15;
      }
      @supports(padding:max(0px)){
        #mineBar{padding-bottom:max(8px, env(safe-area-inset-bottom))}
      }
    `;
    document.head.appendChild(s);
  }

  // ============ helpers ============
  const fmtKg = (x) => {
    const n = Math.round(Number(x || 0) * 100) / 100;
    return String(n).replace('.', ',');
  };
  const esc = (s) => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const putText = (id, v) => { const el = $(id); if (el) el.textContent = (v==null?'':String(v)); };
  const isMobile = () => window.matchMedia && window.matchMedia('(max-width: 560px)').matches;

  async function fetchJSON(url, opts){
    try{
      const r  = await fetch(url, opts || {});
      const ct = (r.headers.get('content-type')||'').toLowerCase();
      const j  = ct.includes('application/json') ? await r.json() : null;
      if (!r.ok) return null;
      return j;
    }catch(e){ console.error('[world_ui] fetchJSON', e); return null; }
  }

  // ============ профиль/мир ============
  function guessNameSync(){
    try{
      const tg = window.Telegram?.WebApp?.initDataUnsafe?.user;
      if (tg) {
        const full = [tg.first_name, tg.last_name].filter(Boolean).join(' ').trim();
        if (full) return full;
        if (tg.username) return tg.username;
      }
    }catch(_){}
    try{ const saved = localStorage.getItem('player_name'); if (saved && saved.trim()) return saved.trim(); }catch(_){}
    return null;
  }
  async function whoami(){ const j = await fetchJSON('/accounts/whoami', {cache:'no-cache'}); return (j&&j.ok)?j.user:null; }
  async function profileApi(){ const j = await fetchJSON('/accounts/profile_api', {cache:'no-cache'}); return (j&&j.ok)?j.profile:null; }
  async function worldState(){
    try{ const s = window.WORLD_LAST_STATE; if (s && s.pos) return {pos:s.pos, fatigue:(s.fatigue??0)}; }catch(_){}
    let j = await fetchJSON(ENDPOINTS.state || '/world/state', {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    if (j&&j.ok) return {pos:j.pos||{x:0,y:0}, fatigue:j.fatigue??0};
    j = await fetchJSON(ENDPOINTS.state || '/world/state', {cache:'no-cache'});
    if (j&&j.ok) return {pos:j.pos||{x:0,y:0}, fatigue:j.fatigue??0};
    return null;
  }

  function setProfile({name,lvl,gold,pos,fat}){
    putText('pName', (name && String(name).trim()) || 'Игрок');
    putText('pLvl',  (lvl==null?1:lvl));
    putText('pGold', (gold==null?0:gold));
    putText('pPos',  `${(pos?.x??0)},${(pos?.y??0)}`);
    putText('pFat',  (fat==null?0:fat));
  }

  async function refreshOnce(){
    const hint = guessNameSync();
    if (hint) putText('pName', hint);

    const [me, st, prof] = await Promise.all([whoami(), worldState(), profileApi()]);
    if (me && (me.username || me.email)) { try { localStorage.setItem('player_name', me.username || me.email); } catch(_){} }

    const name = (me && (me.username || me.email)) || hint || 'Игрок';
    const pos  = (st && st.pos)  || {x:0,y:0};
    const fat  = (st && st.fatigue != null) ? st.fatigue : 0;
    const gold = prof?.gold ?? 0;

    setProfile({ name, lvl:1, gold, pos, fat });
  }

  // ============ Инвентарь ============
  let INV_CACHE = [];
  let INV_LOAD_SEQ = 0;

  const sortForView = (items) => items.slice().sort((a,b)=> (a.name||'').localeCompare(b.name||''));

  function invRowDesktop(it){
    const name = esc(it.name || it.item_key || 'Предмет');
    const ico  = (it.icon ? `<img src="${esc(it.icon)}" alt="" style="width:18px;height:18px;border-radius:6px;border:1px solid var(--border);object-fit:cover">`
                           : `<i class="inv-ico">${(name[0]||'?').toUpperCase()}</i>`);
    const qty  = Number(it.qty||0);
    const per  = fmtKg(it.weight_kg||0);
    const tot  = fmtKg(it.total_weight||0);
    const inv  = Number(it.inv_id||0);
    const eq   = !!it.equipped;
    return `
      <div class="inv-row" data-row="${inv}">
        <div class="inv-name">
          ${ico}
          <div class="title-ellipsis">
            <span>${name}${eq ? ' <span class="badge-eq">экип.</span>' : ''}</span>
            <span class="pill">×${qty}</span>
            ${it.type ? `<div class="micro muted">${esc(it.type)}</div>` : ''}
          </div>
        </div>
        <div class="micro muted">в/шт ${per}</div>
        <div class="micro muted"><b>${tot}</b></div>
        <div class="step">
          <button class="btn clear icon-sm" data-act="dec" ${eq?'disabled':''} aria-label="Минус">➖</button>
          <input type="number" min="1" value="1" max="${qty}" ${eq?'disabled':''} aria-label="Количество">
          <button class="btn clear icon-sm" data-act="inc" ${eq?'disabled':''} aria-label="Плюс">➕</button>
          <button class="btn danger icon-sm" data-act="drop" ${eq?'disabled':''} aria-label="Выбросить">🗑️</button>
          <button class="btn danger icon-sm" data-act="dropall" ${eq?'disabled':''} aria-label="Выбросить всё">🗑️∞</button>
        </div>
      </div>
    `;
  }

  function invCardMobile(it){
    const name = esc(it.name || it.item_key || 'Предмет');
    const ico  = (it.icon ? `<img src="${esc(it.icon)}" alt="" style="width:18px;height:18px;border-radius:6px;border:1px solid var(--border);object-fit:cover">`
                           : `<i class="inv-ico" style="width:18px;height:18px">${(name[0]||'?').toUpperCase()}</i>`);
    const qty  = Number(it.qty||0);
    const per  = fmtKg(it.weight_kg||0);
    const tot  = fmtKg(it.total_weight||0);
    const inv  = Number(it.inv_id||0);
    const eq   = !!it.equipped;
    return `
      <div class="inv-card" data-row="${inv}">
        <div class="top">
          <div class="name">
            ${ico}
            <div>
              <div class="title">${name}${eq ? ' <span class="badge-eq">экип.</span>' : ''}</div>
              <div class="tiny muted" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:80vw">
                ${it.type ? esc(it.type)+' • ' : ''}в/шт <b>${per}</b> • сум <b>${tot}</b> • <span class="pill">×${qty}</span>
              </div>
            </div>
          </div>
        </div>
        <div class="actions">
          <div class="qty">
            <button class="btn clear icon-sm" data-act="dec" ${eq?'disabled':''} aria-label="Минус">➖</button>
            <input type="number" min="1" value="1" max="${qty}" ${eq?'disabled':''} aria-label="Количество">
            <button class="btn clear icon-sm" data-act="inc" ${eq?'disabled':''} aria-label="Плюс">➕</button>
          </div>
          <button class="btn danger icon-sm" data-act="drop" ${eq?'disabled':''} aria-label="Выбросить">🗑️</button>
          <button class="btn danger icon-sm" data-act="dropall" ${eq?'disabled':''} aria-label="Выбросить всё">🗑️∞</button>
        </div>
      </div>
    `;
  }

  function bindInvHandlers(node){
    if (!node) return;
    node.onclick = async (e)=>{
      const btn = e.target.closest('button'); if(!btn) return;
      const row = e.target.closest('[data-row]'); if(!row) return;
      const act = btn.dataset.act;
      const input = row.querySelector('input[type="number"]');
      const max = Number(input?.getAttribute('max')||1);
      const inv = Number(row.dataset.row||0);
      if (act === 'inc'){ if (input) input.value = String(Math.min(max, Number(input.value||1)+1)); return; }
      if (act === 'dec'){ if (input) input.value = String(Math.max(1,   Number(input.value||1)-1)); return; }
      if (act === 'drop' || act === 'dropall'){
        const qty = (act==='dropall') ? max : Math.max(1, Math.min(max, Number(input?.value||1)));
        await dropItem(inv, qty);
      }
    };
    node.onkeydown = (e)=>{
      if (e.key !== 'Enter') return;
      const row = e.target.closest?.('[data-row]'); if(!row) return;
      const input = row.querySelector('input[type="number"]');
      const max = Number(input?.getAttribute('max')||1);
      const inv = Number(row.dataset.row||0);
      const qty = Math.max(1, Math.min(max, Number(input?.value||1)));
      dropItem(inv, qty);
    };
  }

  function renderInventoryList(items, totals, counts){
    const totalsBox = $('uiInvTotals');
    const tbl       = $('uiInvGridTbl');
    const cards     = $('uiInvCards');

    if (totalsBox){
      const pct = Number(totals.load_pct||0);
      totalsBox.innerHTML = `
        <div class="kv">
          <span>Нагрузка</span>
          <b>${fmtKg(totals.weight_kg)} / ${fmtKg(totals.capacity_kg)} кг (${pct}%)</b>
        </div>
        <div class="progress" aria-label="нагрузка"><i style="width:${Math.min(100, pct)}%"></i></div>
        <div class="micro muted" style="margin-top:4px">Слоты: ${counts.stacks} • Всего: ${counts.pieces}</div>
      `;
    }
    putText('invCount', counts.stacks);

    if (!items.length){
      const empty = '<div class="tiny">Пусто</div>';
      if (tbl)   tbl.innerHTML   = empty;
      if (cards) cards.innerHTML = empty;
      return;
    }

    if (!isMobile()){
      if (tbl) {
        tbl.innerHTML = `
          <div class="inv-row micro muted" style="font-weight:700;opacity:.8">
            <div>Предмет</div><div>в/шт</div><div>сум</div><div>действия</div>
          </div>
          ${items.map(invRowDesktop).join('')}
        `;
        bindInvHandlers(tbl);
      }
      if (cards) cards.innerHTML = '';
    } else {
      if (cards) {
        cards.innerHTML = items.map(invCardMobile).join('');
        bindInvHandlers(cards);
      }
      if (tbl) tbl.innerHTML = '';
    }
  }

  async function loadInventory(){
    const mySeq = ++INV_LOAD_SEQ;
    const tbl = $('uiInvGridTbl');
    const cards = $('uiInvCards');

    if (tbl)   tbl.innerHTML   = '';
    if (cards) cards.innerHTML = '';
    if ($('uiInvTotals')) $('uiInvTotals').innerHTML = '';

    const j = await fetchJSON('/inv/api/list', {cache:'no-cache'});
    if (mySeq !== INV_LOAD_SEQ) return;

    if (!j){
      const err = '<div class="tiny">Ошибка сети</div>';
      if (tbl)   tbl.innerHTML   = err;
      if (cards) cards.innerHTML = err;
      return;
    }
    if (!j.ok){
      const err = `<div class="tiny">Ошибка: ${esc(j.error||'unknown')}</div>`;
      if (tbl)   tbl.innerHTML   = err;
      if (cards) cards.innerHTML = err;
      return;
    }

    INV_CACHE = Array.isArray(j.items) ? j.items : [];
    const totals = j.totals || {weight_kg:0, capacity_kg:0, load_pct:0};
    const counts = j.counts || {stacks: INV_CACHE.length, pieces: INV_CACHE.reduce((s,x)=>s+(x.qty||0),0)};

    renderInventoryList(sortForView(INV_CACHE), totals, counts);
  }

  async function dropItem(inv_id, qty){
    const r = await fetchJSON('/inv/api/drop', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ inv_id, qty })
    });
    if (!r || !r.ok){
      (window.pkToast||alert)((r && (r.error||r.message)) || 'Не удалось выбросить');
      return;
    }
    await loadInventory();
  }

  // ============ убрать «Загрузка…» если где-то торчит ============
  function hideStrayLoadingText(){
    const texts = new Set(['Загрузка…','Загрузка...','Loading…','Loading...']);
    qsa('body *').forEach(el=>{
      if (el.children.length === 0){
        const t = (el.textContent || '').trim();
        if (texts.has(t)) { el.style.display = 'none'; }
      }
    });
  }

  // ============ Кнопки действий: теги и раскладка ============
  function tagActionButtons(){
    const containers = [$('#controlsBar'), $('#mineBar')].filter(Boolean);
    containers.forEach(root=>{
      root.querySelectorAll('button, a, .btn').forEach(b=>{
        const t = (b.textContent||'').toLowerCase();
        if (/идти/.test(t))      b.classList.add('btn-go');
        else if (/стоп/.test(t)) b.classList.add('btn-stop');
        else if (/лагер/.test(t))b.classList.add('btn-camp');
        else if (/добыва/.test(t)) b.classList.add('btn-mine');
      });
    });
  }
  function arrangeMainButtons(){
    const bar = $('#controlsBar'); if (!bar) return;
    const go   = bar.querySelector('.btn-go');
    const stop = bar.querySelector('.btn-stop');
    const camp = bar.querySelector('.btn-camp');
    [go, stop, camp].filter(Boolean).forEach(el=>bar.appendChild(el));
  }
  function ensureMineRow(){
    const bar = $('#controlsBar'); if (!bar) return;
    let row = $('#mineBar');
    if (!row){
      row = document.createElement('div');
      row.id = 'mineBar';
      bar.insertAdjacentElement('afterend', row);
    }
    const mineInBar = bar.querySelector('.btn-mine');
    if (mineInBar) row.appendChild(mineInBar);
  }
  function observeControls(){
    const bar = $('#controlsBar'); if (!bar) return;
    const mo = new MutationObserver(()=>{
      tagActionButtons();
      arrangeMainButtons();
      ensureMineRow();
    });
    mo.observe(bar, {childList:true, subtree:false});
    tagActionButtons();
    arrangeMainButtons();
    ensureMineRow();
  }

  // ============ UI boot ============
  const UI = { open:false, timer:null };

  function ensureOverlay(){
    injectCSSOnce();
    let root = $('#uiOverlay');
    if (!root) {
      root = document.createElement('div');
      root.id = 'uiOverlay';
      root.className = 'wu-overlay';
      root.innerHTML = `
        <div class="wu-backdrop" id="wuBackdrop"></div>
        <div class="wu-sheet" role="dialog" aria-modal="true" aria-labelledby="wuTabs">
          <div class="wu-head">
            <div class="wu-tabs" id="wuTabs">
              <button class="wu-tab active" data-tab="profile" type="button">Профиль</button>
              <button class="wu-tab" data-tab="inv" type="button">Инвентарь</button>
              <button class="wu-tab" data-tab="craft" type="button">Крафт</button>
            </div>
            <button class="wu-x" id="wuClose" aria-label="Закрыть" type="button">✕</button>
          </div>
          <div class="wu-body">
            <div class="wu-panel active" id="wu-panel-profile">
              <div class="group">
                <div class="kv"><span>Имя</span><b id="pName">—</b></div>
                <div class="kv"><span>Уров.</span><b id="pLvl">1</b></div>
                <div class="kv"><span>🪙 Золото</span><b id="pGold">0</b></div>
                <div class="kv"><span>📍 Коорд.</span><b id="pPos">0,0</b></div>
                <div class="kv"><span>😮‍💨 Устал.</span><b id="pFat">0</b></div>
              </div>
              <div class="group">
                <a class="chip" href="/accounts/logout" aria-label="Выйти">🚪 Выйти</a>
              </div>
            </div>

            <div class="wu-panel" id="wu-panel-inv">
              <div class="group">

                <div id="uiInvTotals" style="margin-top:4px" aria-live="polite"></div>
              </div>

              <div class="group">
                <div class="inv-grid" id="uiInvGridTbl"></div>
                <div class="inv-cards" id="uiInvCards"></div>
              </div>
            </div>
            <div class="wu-panel" id="wu-panel-craft">
              <div class="group">
                <div class="craft-status" id="craftStatus">
                  <div class="craft-idle">Нет активного крафта</div>
                </div>
                <div id="craftAction"></div>
              </div>

              <div class="group">
                <div id="craftRecipes">
                  <div class="tiny">Загрузка рецептов...</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      `;
      document.body.appendChild(root);
    }

    // tabs
    qsa('.wu-tab', root).forEach(btn=>{
      btn.addEventListener('click', async ()=>{
        qsa('.wu-tab', root).forEach(b=>b.classList.toggle('active', b===btn));
        const tab = btn.dataset.tab;
        qsa('.wu-panel', root).forEach(p=>p.classList.toggle('active', p.id === `wu-panel-${tab}`));
        if (tab === 'inv') await loadInventory();
        if (tab === 'craft') {
          if (window.CraftClient) {
            await window.CraftClient.refreshRecipes();
            window.CraftClient.checkStatus();
          }
        }
      });
    });

    // close
    const closeAll = () => {
      qsa('#uiOverlay').forEach(ov=>{
        ov.classList.remove('open');
        ov.setAttribute('aria-hidden','true');
      });
      UI.open = false;
      if (UI.timer) { clearInterval(UI.timer); UI.timer = null; }
      const bar = $('#tabbar');
      if (bar) {
        qsa('.tab', bar).forEach(b=>{
          const active = (b.dataset.action==='map');
          b.classList.toggle('active', active);
          b.setAttribute('aria-selected', active?'true':'false');
        });
      }
    };
    const onClick = (e) => {
      if (!UI.open) return;
      if (e.target && (e.target.id === 'wuClose' || e.target.id === 'wuBackdrop')) return closeAll();
      const sheet = q('.wu-sheet', root);
      if (sheet && !sheet.contains(e.target)) return closeAll();
    };
    const onEsc = (e) => {
      if (!UI.open) return;
      if (e.key === 'Escape' || e.key === 'Esc' || e.keyCode === 27) return closeAll();
    };
    if (!document.documentElement.dataset.wuCloseBound) {
      document.addEventListener('click', onClick, true);
      document.addEventListener('keydown', onEsc, true);
      document.documentElement.dataset.wuCloseBound = '1';
    }

    function applyResponsiveSwitch(){
      const sheet = q('.wu-sheet', root);
      if (!sheet) return;
      if (isMobile()) sheet.classList.add('wu-mobile');
      else sheet.classList.remove('wu-mobile');
    }
    window.addEventListener('resize', ()=>{ if (UI.open) applyResponsiveSwitch(); }, {passive:true});

    function open(tab){
      root.classList.add('open');
      root.setAttribute('aria-hidden','false');
      if (tab) {
        qsa('.wu-tab', root).forEach(b=>b.classList.toggle('active', b.dataset.tab===tab));
        qsa('.wu-panel', root).forEach(p=>p.classList.toggle('active', p.id===`wu-panel-${tab}`));
      }
      UI.open = true;

      applyResponsiveSwitch();
      refreshOnce();
      if (UI.timer) clearInterval(UI.timer);
      UI.timer = setInterval(()=>{ if (UI.open) refreshOnce(); }, 2500);

      const activeTab = q('.wu-tab.active', root)?.dataset.tab;
      if (activeTab === 'inv') loadInventory();
      if (activeTab === 'craft' && window.CraftClient) {
        window.CraftClient.refreshRecipes();
        window.CraftClient.checkStatus();
      }
    }

    window.WorldUI = { open: (tab)=>open(tab||'profile'), close: closeAll };
  }

  function bindTabbar(){
    const bar = $('#tabbar'); if (!bar || bar.dataset.wuBound) return;
    bar.addEventListener('click', (e)=>{
      const btn = e.target.closest('.tab'); if(!btn) return;
      const act = btn.dataset.action;
      if (act === 'map') window.WorldUI && window.WorldUI.close();
      else if (act === 'profile') window.WorldUI && window.WorldUI.open('profile');
      else if (act === 'inv') window.WorldUI && window.WorldUI.open('inv');
      else if (act === 'craft') window.WorldUI && window.WorldUI.open('craft');
    }, {passive:true});
    bar.dataset.wuBound='1';
  }

  function init(){
    injectCSSOnce();

    // спрятать случайные «Загрузка…»
    hideStrayLoadingText();
    setTimeout(hideStrayLoadingText, 800);

    ensureOverlay();
    bindTabbar();

    // разместить кнопки и вынести "Добывать" в отдельную строку
    observeControls();
  }

  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
