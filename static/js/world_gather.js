<!-- static/js/gather.js -->
<script>
(() => {
  'use strict';

  const BTN_ID = 'btnGather';
  const COOLDOWN_MS = 700;

  function showToast(msg){
    if (window.pkToast) window.pkToast(msg);
    else alert(msg);
  }

  function findWrap(){
    return document.querySelector('.controls .wrap')
        || document.querySelector('#controlsBar .wrap')
        || document.querySelector('#controlsBar')
        || document.querySelector('.controls')
        || null;
  }

  function ensureButton() {
    const wrap = findWrap();
    if (!wrap || document.getElementById(BTN_ID)) return;

    const btn = document.createElement('button');
    btn.className = 'btn';
    btn.id = BTN_ID;
    btn.type = 'button';
    btn.textContent = 'Собирать';
    btn.style.marginRight = '8px';

    // слева от «Стоп» (если есть), иначе просто первым
    const first = wrap.firstElementChild;
    wrap.insertBefore(btn, first || null);

    btn.addEventListener('click', onGather);
  }

  let locked = false;
  async function onGather() {
    if (locked) return;
    locked = true;

    const btn = document.getElementById(BTN_ID);
    const oldText = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = '…'; }

    try{
      // пробуем передать биом, если ты его сохраняешь в WORLD_LAST_STATE
      const s = (window.WORLD_LAST_STATE || {});
      const payload = {};
      if (s && (s.tile || s.biome)) payload.tile = s.tile || s.biome;

      const r = await fetch('/world/gather', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify(payload)
      });
      const j = await r.json().catch(()=>({ok:false}));

      if (!j || !j.ok) {
        showToast((j && (j.error||j.message)) || 'Ошибка добычи');
        return;
      }

      // Человеческое сообщение
      let msg = 'Ничего не найдено.';
      if (j.error === 'overweight') msg = 'Перегруз. Освободите рюкзак.';
      else if (j.message) msg = j.message;
      else if (Array.isArray(j.items) && j.items.length) {
        const it = j.items[0];
        msg = `Добыто: ${it.name || it.key} ×${it.qty ?? 1}`;
      }

      showToast(msg);
      if (navigator.vibrate) { try{ navigator.vibrate(20); }catch(_){} }

      // если инвентарь открыт — обновим
      if (typeof window.WU_refreshInv === 'function') {
        window.WU_refreshInv();
      } else if (window.WorldInv && typeof window.WorldInv.refresh === 'function') {
        window.WorldInv.refresh();
      }
    }catch(e){
      showToast('Сеть недоступна');
    }finally{
      setTimeout(()=>{
        locked = false;
        if (btn) { btn.disabled = false; btn.textContent = oldText; }
      }, COOLDOWN_MS);
    }
  }

  if (document.readyState==='loading') {
    document.addEventListener('DOMContentLoaded', ensureButton);
  } else {
    ensureButton();
  }
})();
</script>
