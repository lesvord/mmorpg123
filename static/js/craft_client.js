// static/js/craft_client.js - Клиент системы крафта
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const fmtTime = (sec) => {
    const s = Math.ceil(sec);
    return s >= 60 ? `${Math.floor(s/60)}м ${s%60}с` : `${s}с`;
  };

  const CRAFT_API = {
    recipes: '/craft/api/recipes',
    recipe: '/craft/api/recipe/',
    start: '/craft/api/start',
    complete: '/craft/api/complete',
    status: '/craft/api/status',
    cancel: '/craft/api/cancel'
  };

  let craftStatus = null;
  let craftTimer = null;

  async function fetchJSON(url, opts = {}) {
    try {
      const r = await fetch(url, opts);
      const j = await r.json();
      return r.ok ? j : null;
    } catch (e) {
      console.error('[craft_client] fetchJSON', e);
      return null;
    }
  }

  // Загружает список рецептов
  async function loadRecipes() {
    const data = await fetchJSON(CRAFT_API.recipes);
    if (!data || !data.ok) {
      console.error('Failed to load recipes');
      return {};
    }
    return data.categories || {};
  }

  // Начинает крафт
  async function startCraft(recipeKey) {
    const result = await fetchJSON(CRAFT_API.start, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ recipe_key: recipeKey })
    });

    if (!result || !result.ok) {
      const error = result?.error || 'Unknown error';
      (window.pkToast || alert)(`Не удалось начать крафт: ${error}`);
      return false;
    }

    (window.pkToast || alert)(result.message || 'Крафт начат');
    craftStatus = result.craft_status;
    startCraftTimer();
    return true;
  }

  // Завершает готовый крафт
  async function completeCraft() {
    const result = await fetchJSON(CRAFT_API.complete, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });

    if (!result || !result.ok) {
      const error = result?.error || 'Unknown error';
      (window.pkToast || alert)(`Не удалось завершить крафт: ${error}`);
      return false;
    }

    const resultItem = result.result;
    (window.pkToast || alert)(`Создано: ${resultItem?.name || 'Предмет'}`);
    craftStatus = null;
    stopCraftTimer();
    return true;
  }

  // Отменяет крафт
  async function cancelCraft() {
    const result = await fetchJSON(CRAFT_API.cancel, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });

    if (!result || !result.ok) {
      const error = result?.error || 'Unknown error';
      (window.pkToast || alert)(`Не удалось отменить крафт: ${error}`);
      return false;
    }

    (window.pkToast || alert)(result.message || 'Крафт отменен');
    craftStatus = null;
    stopCraftTimer();
    return true;
  }

  // Проверяет статус крафта
  async function checkCraftStatus() {
    const data = await fetchJSON(CRAFT_API.status);
    if (!data || !data.ok) return null;

    craftStatus = data.craft_status;
    if (craftStatus) {
      if (craftStatus.ready) {
        stopCraftTimer();
        updateCraftUI();
        // Показываем уведомление о готовности
        (window.pkToast || alert)(`${craftStatus.recipe_name} готов!`);
      } else {
        updateCraftUI();
      }
    } else {
      stopCraftTimer();
      updateCraftUI();
    }
    return craftStatus;
  }

  // Обновляет UI статуса крафта
  function updateCraftUI() {
    const statusEl = $('#craftStatus');
    const progressEl = $('#craftProgress');
    const actionEl = $('#craftAction');

    if (!statusEl) return;

    if (craftStatus) {
      const progress = Math.round(craftStatus.progress * 100);
      const remaining = fmtTime(craftStatus.remaining_sec);

      statusEl.innerHTML = `
        <div class="craft-active">
          <div class="craft-name">${craftStatus.recipe_name}</div>
          <div class="craft-time">Осталось: ${remaining}</div>
          <div class="craft-progress">
            <div class="progress-bar" style="width: ${progress}%"></div>
          </div>
        </div>
      `;

      if (actionEl) {
        if (craftStatus.ready) {
          actionEl.innerHTML = '<button class="btn craft-complete" onclick="window.CraftClient.complete()">🔨 Забрать</button>';
        } else {
          actionEl.innerHTML = '<button class="btn craft-cancel" onclick="window.CraftClient.cancel()">❌ Отменить</button>';
        }
      }
    } else {
      statusEl.innerHTML = '<div class="craft-idle">Нет активного крафта</div>';
      if (actionEl) actionEl.innerHTML = '';
    }
  }

  // Таймер для обновления крафта
  function startCraftTimer() {
    stopCraftTimer();
    craftTimer = setInterval(() => {
      if (craftStatus) {
        craftStatus.remaining_sec = Math.max(0, craftStatus.remaining_sec - 1);
        craftStatus.progress = Math.min(1, (Date.now()/1000 - craftStatus.started_at) / (craftStatus.finish_at - craftStatus.started_at));
        craftStatus.ready = craftStatus.remaining_sec <= 0;
        updateCraftUI();

        if (craftStatus.ready) {
          stopCraftTimer();
        }
      }
    }, 1000);
  }

  function stopCraftTimer() {
    if (craftTimer) {
      clearInterval(craftTimer);
      craftTimer = null;
    }
  }

  // Рендерит список рецептов
  function renderRecipesList(categories) {
    const container = $('#craftRecipes');
    if (!container) return;

    const categoryNames = {
      tools: '🔧 Инструменты',
      weapons: '⚔️ Оружие',
      armor: '🛡️ Броня',
      food: '🍽️ Еда',
      materials: '🧱 Материалы',
      misc: '📦 Разное'
    };

    let html = '';
    for (const [catKey, recipes] of Object.entries(categories)) {
      const catName = categoryNames[catKey] || catKey;
      html += `<div class="craft-category">
        <h3 class="craft-cat-title">${catName}</h3>
        <div class="craft-recipes">`;

      for (const recipe of recipes) {
        const components = recipe.components.map(c => 
          `<span class="craft-component">${c.name} ×${c.qty}</span>`
        ).join(' ');

        html += `
          <div class="craft-recipe" data-recipe="${recipe.key}">
            <div class="craft-recipe-header">
              <span class="craft-recipe-name">${recipe.name}</span>
              <span class="craft-recipe-time">${fmtTime(recipe.craft_time_sec)}</span>
            </div>
            <div class="craft-recipe-components">${components}</div>
            <div class="craft-recipe-result">→ ${recipe.result.name} ×${recipe.result.qty}</div>
            ${recipe.description ? `<div class="craft-recipe-desc">${recipe.description}</div>` : ''}
            <button class="btn craft-start" onclick="window.CraftClient.start('${recipe.key}')">🔨 Создать</button>
          </div>
        `;
      }
      html += '</div></div>';
    }

    container.innerHTML = html;
  }

  // Загружает и отображает рецепты
  async function refreshRecipes() {
    const categories = await loadRecipes();
    renderRecipesList(categories);
  }

  // Инициализация
  async function init() {
    // Проверяем статус крафта при загрузке
    await checkCraftStatus();
    
    // Периодически проверяем статус
    setInterval(checkCraftStatus, 5000);
  }

  // Публичный API
  window.CraftClient = {
    init,
    start: startCraft,
    complete: completeCraft,
    cancel: cancelCraft,
    checkStatus: checkCraftStatus,
    refreshRecipes,
    getStatus: () => craftStatus
  };

  // Автоматическая инициализация
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();