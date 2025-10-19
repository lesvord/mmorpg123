/* Лёгкий UI инвентаря + интеграция с табом «Инвентарь» */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);

  const STYLE_ID = 'world-inv-style';
  const html = `
<div id="invModal" style="position:fixed;inset:0;z-index:120;display:none">
  <div class="inv-backdrop"></div>
  <div class="inv-sheet">
    <div class="inv-header">
      <b>Инвентарь</b>
      <button id="invClose" class="btn">Закрыть</button>
    </div>
    <div id="invStats" class="inv-stats">
      <div class="row"><span>Вес</span><span><b id="invWeight">0</b> / <span id="invCapacity">0</span> кг</span></div>
      <div class="row"><span>Нагрузка</span><span><span id="invLoad">0</span>% · ячеек: <span id="invStacks">0</span>, предметов: <span id="invPieces">0</span></span></div>
      <div class="inv-progress"><div class="fill" id="invLoadFill"></div></div>
    </div>
    <div id="invList" class="inv-items"></div>
  </div>
</div>`;

  function ensureStyle(){
    if (document.getElementById(STYLE_ID)) return;
    const s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = `
      #invModal{position:fixed;inset:0;z-index:160;display:none}
      #invModal .inv-backdrop{position:absolute;inset:0;background:rgba(0,0,0,.55);backdrop-filter:blur(2px)}
      #invModal .inv-sheet{
        position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);
        width:min(560px,94vw);max-height:80vh;overflow:auto;
        background:rgba(17,20,28,.97);border:1px solid rgba(255,255,255,.14);
        border-radius:18px;padding:18px;box-shadow:0 24px 60px rgba(0,0,0,.55);
      }
      #invModal .inv-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;gap:12px}
      #invModal .inv-header b{font:800 17px/1.2 system-ui;color:#fff}
      #invModal .inv-header .btn{min-height:auto;min-width:auto;padding:8px 14px;font-size:13px;background:#374151;border-radius:12px}
      #invModal .inv-stats{margin-bottom:16px;color:#e5e7eb;font:500 13px/1.4 system-ui}
      #invModal .inv-stats .row{display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;gap:12px}
      #invModal .inv-stats .row span:last-child{font-weight:600}
      #invModal .inv-progress{height:8px;background:rgba(255,255,255,.08);border-radius:999px;overflow:hidden;margin-top:8px}
      #invModal .inv-progress .fill{height:100%;width:0;background:linear-gradient(90deg,#22c55e,#3b82f6);transition:width .25s ease}
      #invModal .inv-items{display:grid;gap:10px;max-height:calc(60vh);overflow:auto;padding-right:4px}
      #invModal .inv-item{
        display:grid;grid-template-columns:auto 1fr auto;gap:12px;align-items:center;
        background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);
        border-radius:14px;padding:10px 12px;color:#f9fafb;
      }
      #invModal .inv-item .icon{width:42px;height:42px;border-radius:12px;background:rgba(15,118,110,.18);
        display:flex;align-items:center;justify-content:center;font-size:20px;overflow:hidden}
      #invModal .inv-item .icon img{width:100%;height:100%;object-fit:contain}
      #invModal .inv-item .meta{display:flex;flex-direction:column;gap:4px;min-width:0}
      #invModal .inv-item .meta .name{font-weight:700;font-size:15px;line-height:1.1}
      #invModal .inv-item .meta .info{font-size:12px;opacity:.8;display:flex;flex-wrap:wrap;gap:6px}
      #invModal .inv-item .drop{min-height:auto;min-width:auto;padding:8px 12px;background:#ef4444;color:#fff;border-radius:12px;font-weight:700}
      #invModal .inv-empty{opacity:.7;text-align:center;padding:20px 0;font-size:14px}
      @media (max-width:520px){
        #invModal .inv-sheet{width:94vw;max-height:82vh;padding:16px}
        #invModal .inv-items{gap:8px}
        #invModal .inv-item{grid-template-columns:auto 1fr;grid-template-areas:'icon info''drop drop'}
        #invModal .inv-item .drop{grid-area:drop;justify-self:stretch;text-align:center}
      }
    `;
    document.head.appendChild(s);
  }

  function ensureDOM() {
    ensureStyle();
    if (document.getElementById('invModal')) return;
    const wrap = document.createElement('div');
    wrap.innerHTML = html;
    document.body.appendChild(wrap.firstElementChild);
    document.getElementById('invClose').addEventListener('click', close);
    document.getElementById('invModal').addEventListener('click', (e)=>{
      if (e.target.id === 'invModal') close();
    });
  }

  function open() {
    ensureDOM();
    document.getElementById('invModal').style.display = 'block';
    refresh();
  }
  function close() {
    const m = document.getElementById('invModal');
    if (m) m.style.display = 'none';
  }

  async function refresh() {
    try{
      const r = await fetch('/inv/api/list', { headers:{'Cache-Control':'no-cache'} });
      const j = await r.json().catch(()=>({ok:false}));
      if(!j || !j.ok){ (window.pkToast||alert)(j.message||'Ошибка инвентаря'); return }
      render(j);
    }catch(e){
      (window.pkToast||alert)('Сеть недоступна');
    }
  }

  function render(data){
    const list = $('invList');
    const weightEl = $('invWeight');
    const capEl = $('invCapacity');
    const loadEl = $('invLoad');
    const loadFill = $('invLoadFill');
    const stacksEl = $('invStacks');
    const piecesEl = $('invPieces');
    if(!list) return;

    const totals = data && data.totals ? data.totals : {};
    const counts = data && data.counts ? data.counts : {};
    const items = Array.isArray(data && data.items) ? data.items : [];

    if (weightEl) weightEl.textContent = fixed(totals.weight_kg || 0);
    if (capEl) capEl.textContent = fixed(totals.capacity_kg || 0);
    if (loadEl) loadEl.textContent = Math.round(Number(totals.load_pct || 0));
    if (loadFill) loadFill.style.width = Math.max(0, Math.min(100, Number(totals.load_pct || 0))) + '%';
    if (stacksEl) stacksEl.textContent = counts.stacks || 0;
    if (piecesEl) piecesEl.textContent = counts.pieces || 0;

    list.innerHTML = '';

    if (!items.length){
      const empty = document.createElement('div');
      empty.className = 'inv-empty';
      empty.textContent = 'Пусто';
      list.appendChild(empty);
      return;
    }

    items.forEach(it=>{
      const card = document.createElement('div');
      card.className = 'inv-item';

      const icon = document.createElement('div');
      icon.className = 'icon';
      if (it.icon){
        const img = document.createElement('img');
        img.src = it.icon;
        img.alt = it.name || it.item_key || '';
        icon.appendChild(img);
      } else {
        icon.textContent = emojiFor(it.item_key || it.name || '');
      }

      const meta = document.createElement('div');
      meta.className = 'meta';
      const name = document.createElement('div');
      name.className = 'name';
      name.textContent = `${it.name || it.item_key} ×${it.qty}`;
      const info = document.createElement('div');
      info.className = 'info';
      const per = fixed(it.weight_kg || 0);
      const total = fixed(it.total_weight || 0);
      const stack = `${it.qty}/${it.stack_max || 99}`;
      info.innerHTML = `<span>Вес: ${per} кг/шт (${total} кг)</span><span>Стэк: ${stack}</span>`;
      meta.appendChild(name);
      meta.appendChild(info);

      const drop = document.createElement('button');
      drop.className = 'btn drop';
      drop.textContent = 'Выбросить';
      drop.addEventListener('click', ()=>dropItemPrompt(it.inv_id, it.qty, it.name));

      card.appendChild(icon);
      card.appendChild(meta);
      card.appendChild(drop);
      list.appendChild(card);
    });
  }

  function emojiFor(key){
    const k = String(key||'').toLowerCase();
    if (k.includes('wood') || k.includes('stick') || k.includes('log')) return '🪵';
    if (k.includes('ore') || k.includes('stone') || k.includes('gem')) return '🪨';
    if (k.includes('fish')) return '🐟';
    if (k.includes('berry')) return '🫐';
    if (k.includes('mush')) return '🍄';
    if (k.includes('herb') || k.includes('fiber') || k.includes('reed')) return '🌿';
    if (k.includes('ice')) return '🧊';
    if (k.includes('cactus')) return '🌵';
    return '🎒';
  }

  async function dropItemPrompt(itemId, maxQty, name){
    const label = name ? `${name}` : 'предмет';
    const qtyStr = prompt(`Сколько выбросить ${label}? (1..${maxQty})`, String(maxQty));
    if(qtyStr==null) return;
    const qty = Math.max(1, Math.min(maxQty, Number(qtyStr)||1));
    try{
      const r = await fetch('/inv/api/drop', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ inv_id: itemId, qty })
      });
      const j = await r.json().catch(()=>({ok:false}));
      if(!j || !j.ok){ (window.pkToast||alert)(j.message||'Не удалось выбросить'); return }
      refresh();
    }catch(e){
      (window.pkToast||alert)('Сеть недоступна');
    }
  }

  const fixed = (x)=> (Math.round(Number(x)*100)/100).toFixed(2).replace(/\.00$/,'');

  // хук в существующую навигацию
  window.WorldInv = { open, close, refresh };
  window.WorldUI = window.WorldUI || {};
  const origOpen = window.WorldUI.open;
  window.WorldUI.open = function(kind){
    if (kind==='inv') { open(); return }
    if (typeof origOpen==='function') return origOpen(kind);
  };
  const origClose = window.WorldUI.close;
  window.WorldUI.close = function(){
    close();
    if (typeof origClose==='function') return origClose();
  };
})();
