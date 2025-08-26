/* Лёгкий UI инвентаря + интеграция с табом «Инвентарь» */
(() => {
  'use strict';

  const html = `
<div id="invModal" style="position:fixed;inset:0;z-index:120;display:none">
  <div style="position:absolute;inset:0;background:rgba(0,0,0,.5)"></div>
  <div style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);
              width:min(540px,92vw);max-height:78vh;overflow:auto;
              background:rgba(16,18,24,.96);border:1px solid rgba(255,255,255,.12);
              border-radius:16px;padding:14px">
    <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px">
      <b style="font:800 16px/1.2 system-ui">Инвентарь</b>
      <button id="invClose" class="btn" style="min-height:auto;min-width:auto;padding:8px 12px;background:#374151">Закрыть</button>
    </div>
    <div id="invStats" style="margin:6px 0 12px;opacity:.9"></div>
    <div id="invList" style="display:grid;grid-template-columns:1fr auto auto;gap:8px;align-items:center"></div>
  </div>
</div>`;

  function ensureDOM() {
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
      const r = await fetch('/world/inventory');
      const j = await r.json().catch(()=>({ok:false}));
      if(!j || !j.ok){ (window.pkToast||alert)(j.message||'Ошибка инвентаря'); return }
      render(j.inventory);
    }catch(e){
      (window.pkToast||alert)('Сеть недоступна');
    }
  }

  function render(inv){
    const list = document.getElementById('invList');
    const stats = document.getElementById('invStats');
    if(!list||!stats) return;

    stats.textContent = `Вес: ${fixed(inv.weight)} / ${fixed(inv.capacity)} кг, ячеек: ${inv.items.length}`;
    list.innerHTML = '';

    if (!inv.items.length){
      const p = document.createElement('div');
      p.style.opacity='.9'; p.textContent='Пусто';
      p.style.gridColumn='1 / -1';
      list.appendChild(p);
      return;
    }

    inv.items.forEach(it=>{
      const name = document.createElement('div');
      name.textContent = `${it.name} ×${it.qty}`;
      const w = document.createElement('div');
      w.style.opacity='.85';
      w.textContent = `${fixed(it.total_weight)} кг`;
      const drop = document.createElement('button');
      drop.className='btn';
      drop.style.cssText='min-height:auto;min-width:auto;padding:8px 12px;background:#ff4d67';
      drop.textContent='Выбросить';
      drop.addEventListener('click', ()=>dropItemPrompt(it.id, it.qty));

      list.appendChild(name);
      list.appendChild(w);
      list.appendChild(drop);
    });
  }

  async function dropItemPrompt(itemId, maxQty){
    const qtyStr = prompt(`Сколько выбросить? (1..${maxQty})`, String(maxQty));
    if(qtyStr==null) return;
    const qty = Math.max(1, Math.min(maxQty, Number(qtyStr)||1));
    try{
      const r = await fetch('/world/inventory/drop', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ item: itemId, qty })
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
