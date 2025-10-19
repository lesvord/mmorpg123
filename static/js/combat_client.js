(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const BOOT = window.WORLD_BOOT || { endpoints: {} };
  const EP = Object.assign({
    combatState: '/world/combat/state',
    combatEngage: '/world/combat/engage',
    combatAttack: '/world/combat/attack',
    combatFlee: '/world/combat/flee',
  }, BOOT.endpoints || {});

  const state = {
    monsters: [],
    combat: null,
    player: null,
    busy: false,
  };

  function decl(count, forms){
    const n = Math.abs(count) % 100;
    const n1 = n % 10;
    if (n > 10 && n < 20) return forms[2];
    if (n1 > 1 && n1 < 5) return forms[1];
    if (n1 === 1) return forms[0];
    return forms[2];
  }

  function summaryFor(list){
    if (!list || !list.length) return 'Спокойно';
    const bosses = list.filter(m => m.is_boss).length;
    const bossText = bosses ? ` · боссов ${bosses}` : '';
    return `${list.length} ${decl(list.length, ['монстр', 'монстра', 'монстров'])}${bossText}`;
  }

  function createMonsterRow(monster){
    const row = document.createElement('div');
    row.className = 'monster-row' + (monster.is_boss ? ' boss' : '');

    const meta = document.createElement('div');
    meta.className = 'meta';

    const title = document.createElement('div');
    title.className = 'title';
    const icon = monster.is_boss ? '👑' : '👹';
    title.textContent = `${icon} ${monster.name}`;
    meta.appendChild(title);

    const tags = document.createElement('div');
    tags.className = 'tags';
    const level = document.createElement('span');
    level.textContent = `Ур. ${monster.level}`;
    tags.appendChild(level);
    if (monster.role) {
      const role = document.createElement('span');
      role.textContent = monster.role;
      tags.appendChild(role);
    }
    if (monster.distance != null) {
      const dist = document.createElement('span');
      dist.textContent = `Дистанция ${monster.distance}`;
      tags.appendChild(dist);
    }
    if (monster.power != null) {
      const pow = document.createElement('span');
      pow.textContent = `Сила ${monster.power}`;
      tags.appendChild(pow);
    }
    if (monster.state && monster.state !== 'idle') {
      const st = document.createElement('span');
      st.textContent = monster.state === 'engaged' ? 'В бою' : monster.state;
      tags.appendChild(st);
    }
    meta.appendChild(tags);

    const actions = document.createElement('div');
    actions.className = 'actions';
    const btn = document.createElement('button');
    btn.className = 'btn';
    btn.type = 'button';
    btn.textContent = '⚔️ Сразиться';
    btn.disabled = state.busy;
    btn.addEventListener('click', () => engage(monster.id));
    actions.appendChild(btn);

    row.appendChild(meta);
    row.appendChild(actions);
    return row;
  }

  function renderMonsters(list){
    const root = $('encounterList');
    const summary = $('encSummary');
    if (summary) summary.textContent = summaryFor(list);
    if (!root) return;
    root.innerHTML = '';
    if (!list || !list.length){
      root.innerHTML = '<div class="tiny">Поблизости никого нет.</div>';
      return;
    }
    list.forEach(m => {
      try {
        root.appendChild(createMonsterRow(m));
      } catch (err){
        console.error(err);
      }
    });
  }

  function statusLabel(combat){
    if (!combat) return '—';
    if (combat.active) return 'В бою';
    switch (combat.state){
      case 'won': return 'Победа';
      case 'lost': return 'Поражение';
      case 'fled': return 'Отступление';
      default: return 'Нет боя';
    }
  }

  function setBar(el, value, max, fallbackColor){
    if (!el) return;
    const frac = (max > 0) ? Math.max(0, Math.min(1, value / max)) : 0;
    el.style.width = (frac * 100).toFixed(1) + '%';
    if (fallbackColor) el.style.background = fallbackColor;
  }

  function renderLog(log){
    const root = $('combatLog');
    if (!root) return;
    root.innerHTML = '';
    const list = Array.isArray(log) ? log.slice(-24) : [];
    if (!list.length){
      root.innerHTML = '<div class="entry system">Здесь появится журнал боя.</div>';
      return;
    }
    list.forEach(entry => {
      const div = document.createElement('div');
      div.className = 'entry system';
      if (entry.type === 'hit'){
        div.className = 'entry ' + (entry.who === 'player' ? 'player' : 'monster');
        const crit = entry.crit ? ' (крит)' : '';
        const who = entry.who === 'player' ? 'Вы' : 'Противник';
        div.textContent = `${who} наносит ${entry.value} урона${crit}`;
      } else if (entry.type === 'miss'){
        div.className = 'entry ' + (entry.who === 'player' ? 'player' : 'monster');
        const who = entry.who === 'player' ? 'Вы' : 'Противник';
        div.textContent = `${who} промахивается`;
      } else if (entry.type === 'flee'){
        div.textContent = entry.success ? 'Вы скрываетесь от монстра' : 'Попытка побега сорвалась';
        if (entry.counter){
          div.textContent += ` (получено ${entry.counter} урона)`;
        }
      } else if (entry.type === 'start'){
        div.textContent = entry.text || 'Монстр заметил вас.';
      } else if (entry.type === 'end'){
        if (entry.result === 'victory'){
          div.textContent = 'Победа!';
          if (entry.rewards){
            div.textContent += ` +${entry.rewards.xp || 0} опыта, +${entry.rewards.gold || 0} золота`;
          }
        } else if (entry.result === 'defeat'){
          div.textContent = 'Вы пали в бою.';
        }
      } else {
        div.textContent = entry.text || JSON.stringify(entry);
      }
      root.appendChild(div);
    });
    root.scrollTop = root.scrollHeight;
  }

  function renderCombat(combat){
    const card = $('combatCard');
    if (!card) return;
    state.combat = combat;

    const active = combat && (combat.active || ['won', 'lost', 'fled'].includes(combat.state));
    card.classList.toggle('hidden', !active);
    const statusEl = $('combatStatus');
    if (statusEl) statusEl.textContent = statusLabel(combat);

    const attackBtn = $('combatAttackBtn');
    const fleeBtn = $('combatFleeBtn');

    if (!active){
      if (attackBtn) attackBtn.disabled = true;
      if (fleeBtn) fleeBtn.disabled = true;
      return;
    }

    const monster = combat.monster || {};
    const player = combat.player || {};

    const title = $('combatTitle');
    if (title) title.textContent = monster && monster.name ? `Бой с ${monster.name}` : 'Бой';

    const monsterLabel = $('combatMonsterLabel');
    if (monsterLabel) monsterLabel.textContent = monster.name ? monster.name : 'Противник';

    const pHP = Number(player.hp || 0);
    const pHPMax = Number(player.hp_max || player.stats?.hp_max || 0) || 1;
    const mHP = Number(monster.hp || 0);
    const mHPMax = Number(monster.hp_max || 0) || 1;

    const pBar = $('combatPlayerHP');
    const mBar = $('combatMonsterHP');
    setBar(pBar, pHP, pHPMax);
    setBar(mBar, mHP, mHPMax);

    const pNum = $('combatPlayerNum');
    if (pNum) pNum.textContent = `${pHP} / ${pHPMax}`;
    const mNum = $('combatMonsterNum');
    if (mNum) mNum.textContent = `${mHP} / ${mHPMax}`;

    if (attackBtn) attackBtn.disabled = state.busy || !combat.active;
    if (fleeBtn) fleeBtn.disabled = state.busy || !combat.active;

    renderLog(combat.log);
  }

  function applyState(s){
    state.player = s && s.player ? s.player : null;
    state.monsters = Array.isArray(s && s.monsters) ? s.monsters.slice() : [];
    renderMonsters(state.monsters);
    renderCombat(s && s.combat ? s.combat : null);
  }

  async function engage(monsterId){
    if (!monsterId || state.busy) return;
    state.busy = true;
    try {
      const resp = await fetch(EP.combatEngage, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ monster_id: monsterId })
      });
      const data = await resp.json().catch(() => ({ ok: false }));
      if (!resp.ok || !data.ok){
        window.pkToast && pkToast(data && data.message ? `Бой: ${data.message}` : 'Не удалось начать бой');
      } else {
        renderCombat(data.combat);
        window.pkToast && pkToast('Бой начался');
        window.dispatchEvent(new Event('world:refresh'));
      }
    } catch (err){
      console.error(err);
      window.pkToast && pkToast('Ошибка подключения боя');
    } finally {
      state.busy = false;
      renderCombat(state.combat);
    }
  }

  async function attack(){
    if (state.busy) return;
    state.busy = true;
    const attackBtn = $('combatAttackBtn');
    if (attackBtn) attackBtn.disabled = true;
    try {
      const resp = await fetch(EP.combatAttack, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}' });
      const data = await resp.json().catch(() => ({ ok: false }));
      if (!resp.ok || !data.ok){
        window.pkToast && pkToast(data && data.message ? `Бой: ${data.message}` : 'Не удалось выполнить атаку');
      } else {
        renderCombat(data.combat);
        if (data.rewards){
          const gold = data.rewards.gold || 0;
          const xp = data.rewards.xp || 0;
          window.pkToast && pkToast(`Победа! +${xp} XP, +${gold} золота`);
        }
        window.dispatchEvent(new Event('world:refresh'));
      }
    } catch (err){
      console.error(err);
      window.pkToast && pkToast('Ошибка боя');
    } finally {
      state.busy = false;
      renderCombat(state.combat);
    }
  }

  async function flee(){
    if (state.busy) return;
    state.busy = true;
    const fleeBtn = $('combatFleeBtn');
    if (fleeBtn) fleeBtn.disabled = true;
    try {
      const resp = await fetch(EP.combatFlee, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}' });
      const data = await resp.json().catch(() => ({ ok: false }));
      if (!resp.ok || !data.ok){
        window.pkToast && pkToast(data && data.message ? `Отступление: ${data.message}` : 'Не удалось отступить');
      } else {
        renderCombat(data.combat);
        window.pkToast && pkToast(data.escaped ? 'Вы укрылись от монстра' : 'Не удалось оторваться');
        window.dispatchEvent(new Event('world:refresh'));
      }
    } catch (err){
      console.error(err);
      window.pkToast && pkToast('Ошибка отступления');
    } finally {
      state.busy = false;
      renderCombat(state.combat);
    }
  }

  function bindActions(){
    const attackBtn = $('combatAttackBtn');
    if (attackBtn) attackBtn.addEventListener('click', attack);
    const fleeBtn = $('combatFleeBtn');
    if (fleeBtn) fleeBtn.addEventListener('click', flee);
  }

  window.addEventListener('world:state', (ev) => {
    try {
      applyState(ev.detail || {});
    } catch (err){
      console.error(err);
    }
  });

  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', bindActions);
  } else {
    bindActions();
  }

  window.CombatUI = {
    engage,
    attack,
    flee,
    getState: () => state,
  };
})();
