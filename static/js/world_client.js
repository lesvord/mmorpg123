(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  function showDiag(html){ const b=$('diagBox'), w=$('diagOverlay'); if(!b||!w) return; b.innerHTML=html; w.style.display='block' }
  function hideDiag(){ const w=$('diagOverlay'); if(w) w.style.display='none' }
  if (!window.pkToast) window.pkToast = (msg) => { try { console.log(msg); } catch(e){} };

  const BOOT = window.WORLD_BOOT || {tileVersions:{}, endpoints:{}};
  const ENDPOINTS = Object.assign({
    state:'/world/state', setDest:'/world/set_dest', stop:'/world/stop',
    campStart:'/world/camp/start', campLeave:'/world/camp/leave',
    tileVersions:'/world/tile_versions', patchView:'/world/patch', stateGet:'',
    // Новые эндпойнты добычи/инвентаря (можешь переопределить в WORLD_BOOT)
    gatherStart:'/world/gather/start',
    gatherStop:'/world/gather/stop',
    gatherTick:'/world/gather/tick',
    invGet:'/world/inventory',
    invDrop:'/world/inventory/drop',
  }, BOOT.endpoints || {});

  const VERS = Object.assign({}, BOOT.tileVersions || {}); let VERS_GEN = 0;

  /* ——— словари ——— */
  const RU = {
    tiles:{
      grass:'трава', meadow:'луг', forest:'лес', swamp:'болото', sand:'песок',
      desert:'пустыня', water:'вода', rock:'скалы', snow:'снег', lava:'лава',
      road:'дорога', town:'город', tavern:'таверна', camp:'лагерь'
    },
    weather:{
      clear:'ясно', rain:'дождь', fog:'туман', wind:'ветер',
      storm:'шторм', snow:'снег', heat:'жара'
    },
    climate:{
      temperate:'умеренный', continental:'континентальный', oceanic:'океанический',
      mediterranean:'средиземноморский', tropical:'тропический', monsoon:'муссонный',
      arid:'засушливый', steppe:'степной', desert:'пустынный', cold:'холодный',
      polar:'полярный', tundra:'тундровый', alpine:'высокогорный',
      humid:'влажный', dry:'сухой'
    }
  };

  function prettyTileName(k){
    if(!k) return '—';
    if(k.endsWith('_snow')){ const base=k.slice(0,-5); return `${RU.tiles[base]||base} (снег)`; }
    return RU.tiles[k]||k;
  }
  const prettyWeatherName = (w) => {
    if(!w) return '—';
    const key=(typeof w==='string')?w:(w.key||w.name||'clear');
    return RU.weather[key]||(w.name||key);
  };
  const WX_ICON = { clear:'🌤️', rain:'🌧️', fog:'🌫️', wind:'💨', storm:'⛈️', snow:'❄️', heat:'🥵' };
  const wxIconFor = (key) => WX_ICON[key] || '🌤️';

  function pickText(v){
    if (v == null) return '';
    if (typeof v === 'string') return v;
    if (typeof v === 'object'){
      if (typeof v.ru === 'string') return v.ru;
      if (typeof v.en === 'string') return v.en;
      for (const val of Object.values(v)) if (typeof val === 'string') return val;
    }
    return String(v);
  }
  function prettyClimateName(cl){
    if (!cl) return '—';
    if (typeof cl === 'string'){ const k = cl.toLowerCase(); return (RU.climate && RU.climate[k]) || cl; }
    if (Array.isArray(cl)){ for (const item of cl){ const s = prettyClimateName(item); if (s && s !== '—') return s; } return '—'; }
    if (typeof cl === 'object'){ const keyRaw = cl.key || cl.id || pickText(cl.name); const key = (keyRaw || '').toString().toLowerCase(); const human = pickText(cl.name) || keyRaw; return (RU.climate && RU.climate[key]) || human || '—'; }
    return String(cl);
  }
  function climateFromTile(tile){
    const t=(tile||'').replace(/_snow$/,'');
    if (t==='desert' || t==='sand' || t==='lava') return 'arid';
    if (t==='snow') return 'polar';
    if (t==='water') return 'oceanic';
    if (t==='rock') return 'continental';
    if (t==='swamp' || t==='meadow') return 'temperate';
    if (t==='forest' || t==='grass') return 'temperate';
    return 'temperate';
  }

  /* ——— server time ——— */
  const TimeSync={serverNow:0,perf0:0,inited:false,init(t){this.serverNow=Number(t)||Date.now()/1000;this.perf0=performance.now();this.inited=true},now(){if(!this.inited)this.init(Date.now()/1000);return this.serverNow+(performance.now()-this.perf0)/1000},blendTo(t){if(!this.inited){this.init(t);return}const d=Number(t)-this.now();const a=Math.max(-.12,Math.min(.12,d));this.serverNow+=a}};

  /* ——— state ——— */
  const S={tiles:null,blds:null,me:null,aim:null,hov:null,camG:null,ox:0,oy:0,w:15,h:9,cell:18,screenW:15,screenH:9,
    pos:{x:0,y:0},hover:{x:null,y:null},aimTo:{x:null,y:null},longPressTimer:null,dragging:false,lastSetAt:0,
    anim:null,raf:null,meCircle:null,meImg:null,camX:0,camY:0,camOffX:0,camOffY:0,lastRAFts:0,lastPatchSig:"",lastPatch:null,lastVersGen:-1,
    hideHero:false,didIdlePrefetch:false,lastResting:false,lastPathLeft:0,tickInFlight:false,tickTimer:null,lastDataNow:0,
    arriveLockUntil:0, wasMoving:false,
    campHere:false, campMine:false, wxOpen:false, hudCollapsed:false,
    plan:{active:false,start:{x:0,y:0},dirs:'',idx:0,stepT:.6,ts:0,stopAt:null,cur:{x:0,y:0}},
    // добыча
    gatherActive:false, gatherTimer:null
  };

  /* ——— textures ——— */
  const VARS={grass:3,meadow:2,forest:3,swamp:2,sand:2,desert:2,water:2,rock:2,snow:2,lava:1,road:1,town:1,tavern:1,camp:1,hero:1,grass_snow:3,meadow_snow:2,forest_snow:3,swamp_snow:2,sand_snow:2,desert_snow:2,rock_snow:2,road_snow:1};
  const NON_BIOME=new Set(['camp','town','tavern']);
  function h2(x,y){ return (((x*73856093)^(y*19349663))>>>0) }
  function varCountFor(tile){ if(Object.prototype.hasOwnProperty.call(VARS,tile)) return VARS[tile]; if(tile&&tile.endsWith('_snow')){ const b=tile.slice(0,-5); if(Object.prototype.hasOwnProperty.call(VARS,b)) return VARS[b]; return VARS['snow']||1 } return 1 }
  const EXT_ORDER=["avif","webp","png"]; const SCALE_ORDER=(window.devicePixelRatio||1)>=1.5?["@2x","@1x",""]:["@1x","@2x",""]; const RESOLVED=new Map(); const BAD=new Set(); const TILE_IMAGES=new Map();
  function candidateList(tile,idx){ const L=[]; for(const ext of EXT_ORDER){ for(const sc of SCALE_ORDER) L.push(`${tile}_${idx}${sc}.${ext}`) } return L }
  function chooseName(tile,idx){ const key=`${tile}:${idx}`; const r=RESOLVED.get(key); if(r) return r; const list=candidateList(tile,idx); for(const n of list){ if(BAD.has(n)) continue; if(Object.prototype.hasOwnProperty.call(VERS,n)) return n } if(tile&&tile.endsWith('_snow')){ const fall=candidateList('snow',idx); for(const n of fall){ if(BAD.has(n)) continue; if(Object.prototype.hasOwnProperty.call(VERS,n)) return n } } for(const n of list){ if(!BAD.has(n)) return n } return list[list.length-1] }
  function urlForName(name){ const v=VERS[name]||Date.now(); return `/static/tiles/${name}?v=${v}` }
  function ensurePreloaded(tile,idx){ const key=`${tile}:${idx}`; const tryChain=(names,k=0)=>{ if(k>=names.length) return; const name=names[k]; if(BAD.has(name)) return tryChain(names,k+1); const ver=VERS[name]||0; if(TILE_IMAGES.get(name)===ver){ RESOLVED.set(key,name); return } const img=new Image(); img.decoding='async'; img.fetchPriority='low'; img.onload=()=>{ TILE_IMAGES.set(name,ver); RESOLVED.set(key,name); if(S.lastPatch) renderPatch(S.lastPatch,true) }; img.onerror=()=>{ BAD.add(name); tryChain(names,k+1) }; img.src=urlForName(name) };
    const list=candidateList(tile,idx); const fall=(tile&&tile.endsWith('_snow'))?candidateList('snow',idx):[]; tryChain(list.concat(fall)) }
  function haveTilePng(tile,idx){ const name=RESOLVED.get(`${tile}:${idx}`); if(!name) return false; const ver=VERS[name]||0; return TILE_IMAGES.get(name)===ver }
  function pngPath(tile,idx){ const name=RESOLVED.get(`${tile}:${idx}`)||chooseName(tile,idx); return urlForName(name) }
  function tilePatternId(tile){ return (tile && tile.endsWith('_snow')) ? 'url(#tx-snow)' : `url(#tx-${tile})` }

  /* ——— preload hints ——— */
  const PRELOAD_CLASS='wx-preload-tile';
  function clearPreloadHints(){ document.head.querySelectorAll(`link.${PRELOAD_CLASS}[rel="preload"][as="image"]`).forEach(n=>n.remove()) }
  function uniqueTilesInPatch(pt){ const set=new Set(); for(let j=0;j<pt.h;j++){ for(let i=0;i<pt.w;i++){ let tile=pt.tiles[j][i]; if(NON_BIOME.has(tile)) tile='grass'; const n=varCountFor(tile); const gx=pt.ox+i, gy=pt.oy+j; const idx=n>1?(h2(gx,gy)%n):0; set.add(`${tile}:${idx}`) } } for(const b of (pt.buildings||[])) set.add(`${b.kind}:0`); return Array.from(set).map(s=>s.split(':')) }
  function addPreloadHints(pt,limit=6){ clearPreloadHints(); const hot=uniqueTilesInPatch(pt).slice(0,limit); for(const [tile,idxStr] of hot){ const link=document.createElement('link'); link.rel='preload'; link.as='image'; link.href=pngPath(tile,+idxStr); link.fetchpriority='high'; link.className=PRELOAD_CLASS; document.head.appendChild(link) } }
  function preloadForPatch(pt){ for(const [tile,idxStr] of uniqueTilesInPatch(pt)) ensurePreloaded(tile,+idxStr) }
  function prefetchAllIdle(){ const task=()=>{ for(const t in VARS){ const n=VARS[t]||1; for(let i=0;i<n;i++) ensurePreloaded(t,i) } }; (window.requestIdleCallback?requestIdleCallback(task):setTimeout(task,400)) }

  /* ——— эффекты/климат ——— */
  function computeEffects(tileKey, weatherKey, notes){
    const baseKey=(tileKey||'').endsWith('_snow')?'snow':tileKey;
    const tMap={grass:'🌿 удобно', meadow:'🌾 приятно', forest:'🌲 густо', swamp:'💧 вязко', sand:'🏖️ тяжело',
                desert:'🏜️ жажда', rock:'🪨 неровно', snow:'❄️ скользко', water:'🌊 непроходимо',
                lava:'🔥 опасно', road:'🛣️ быстрее', town:'🏠 отдых', tavern:'🏠 отдых', camp:'🏕️ отдых'};
    const wMap={clear:'☀️ хорошая погода', rain:'🌧️ усталость↑', fog:'🌫️ видимость↓', wind:'💨 порывы',
                storm:'⛈️ скорость↓', snow:'❄️ скорость↓', heat:'🥵 усталость↑'};
    const list=[]; if(tMap[baseKey]) list.push(tMap[baseKey]); if(wMap[weatherKey]) list.push(wMap[weatherKey]); if(notes && String(notes).trim()) list.push('🛈 '+notes);
    return 'Эффекты: ' + (list.length?list.join(' · '):'—');
  }

  // Баннер "Сейчас — ..."
  function updateWeatherBanner(s){
    const wInline = $('wNowInline');
    const iconEl  = $('wxIcon');
    const key = (s && s.weather) ? (s.weather.key || s.weather.name || 'clear') : 'clear';
    const text = prettyWeatherName(s && s.weather);
    if (wInline) wInline.textContent = text || '—';
    if (iconEl)  iconEl.textContent  = wxIconFor(String(key).toLowerCase());
  }

  /* ——— индикатор движения ——— */
  function setMoveIndicator(moving,resting,progress){
    const pill=$('movePill'), spin=$('moveSpin'), label=$('moveText'); if(!pill||!spin||!label) return;
    if(resting){ pill.className='pill resting'; spin.style.display='none'; label.textContent='Отдыхает'; return }
    if(moving){ pill.className='pill moving'; spin.style.display='inline-block';
      if(progress!=null && isFinite(progress)){ const perc=Math.min(99, Math.floor(Math.max(0,Math.min(1,progress))*100)); label.textContent='Идёт… '+perc+'%' }
      else label.textContent='Идёт…'
    } else { pill.className='pill idle'; spin.style.display='none'; label.textContent='Стоит' }
  }

  /* ——— API helpers ——— */
  async function apiPOST(path,data){
    try{
      const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:data?JSON.stringify(data):'{}'});
      let j=null; try{ j=await r.json() }catch(e){ j={ok:false,error:'bad_json'} }
      if(!r.ok) j.ok=false; j.__http=r.status; return j;
    }catch(e){ return {ok:false,error:'network_error',detail:String(e)} }
  }
  async function apiGET(path){
    try{
      const r=await fetch(path,{method:'GET',headers:{'Cache-Control':'no-cache'}});
      let j=null; try{ j=await r.json() }catch(e){ j={ok:false,error:'bad_json'} }
      if(!r.ok) j.ok=false; j.__http=r.status; return j;
    }catch(e){ return {ok:false,error:'network_error',detail:String(e)} }
  }
  async function pollTileVersions(){
    if(!ENDPOINTS.tileVersions) return;
    const j=await apiGET(ENDPOINTS.tileVersions);
    if(j&&j.ok&&j.versions){
      let changed=false; for(const [fn,v] of Object.entries(j.versions)){ if(VERS[fn]!==v){ VERS[fn]=v; changed=true } }
      if(changed){ VERS_GEN++; if(S.lastPatch){ preloadForPatch(S.lastPatch); renderPatch(S.lastPatch,true) } if(!S.didIdlePrefetch){ S.didIdlePrefetch=true; prefetchAllIdle() } }
    }
  }

  /* ——— render patch ——— */
  function patchSignature(pt){ let s=`${pt.ox}|${pt.oy}|${pt.w}|${pt.h}|`; for(let j=0;j<pt.h;j++) s+=pt.tiles[j].join(',')+'|'; if(pt.buildings&&pt.buildings.length){ for(const b of pt.buildings) s+=`${b.kind}:${b.x},${b.y}|` } return s }
  function renderPatch(pt,force=false){
    if(!pt||!pt.tiles) return;
    S.lastPatch=pt; const sig=patchSignature(pt);
    if(!force && sig===S.lastPatchSig && S.lastVersGen===VERS_GEN) return;
    S.ox=pt.ox; S.oy=pt.oy; S.w=pt.w; S.h=pt.h;

    const frag=document.createDocumentFragment();
    for(let j=0;j<pt.h;j++){
      for(let i=0;i<pt.w;i++){
        let tile=pt.tiles[j][i]; if(NON_BIOME.has(tile)) tile='grass';
        const gx=pt.ox+i, gy=pt.oy+j; const x=i*S.cell, y=j*S.cell; const n=varCountFor(tile); const idx=n>1?(h2(gx,gy)%n):0;
        if(haveTilePng(tile,idx)){
          const img=document.createElementNS('http://www.w3.org/2000/svg','image');
          img.setAttribute('x',x); img.setAttribute('y',y); img.setAttribute('width',S.cell); img.setAttribute('height',S.cell);
          img.setAttributeNS('http://www.w3.org/1999/xlink','href', pngPath(tile,idx));
          img.setAttribute('preserveAspectRatio','xMidYMid slice'); img.setAttribute('style','pointer-events:none;image-rendering:auto');
          frag.appendChild(img);
        } else {
          const r=document.createElementNS('http://www.w3.org/2000/svg','rect');
          r.setAttribute('x',x); r.setAttribute('y',y); r.setAttribute('width',S.cell); r.setAttribute('height',S.cell);
          r.setAttribute('fill', tilePatternId(tile)); frag.appendChild(r);
        }
      }
    }
    S.tiles.innerHTML=''; S.tiles.appendChild(frag);

    const fragB=document.createDocumentFragment();
    for(const b of (pt.buildings||[])){
      const x=(b.x-S.ox)*S.cell+1, y=(b.y-S.oy)*S.cell+1, kind=b.kind;
      if(haveTilePng(kind,0)){
        const img=document.createElementNS('http://www.w3.org/2000/svg','image');
        img.setAttribute('x',x); img.setAttribute('y',y); img.setAttribute('width',S.cell-2); img.setAttribute('height',S.cell-2);
        img.setAttributeNS('http://www.w3.org/1999/xlink','href', pngPath(kind,0));
        img.setAttribute('preserveAspectRatio','xMidYMid meet'); img.setAttribute('style','pointer-events:none;image-rendering:auto');
        fragB.appendChild(img);
      }
    }
    S.blds.innerHTML=''; S.blds.appendChild(fragB);

    S.lastPatchSig=sig; S.lastVersGen=VERS_GEN;
  }

  /* ——— герой ——— */
  function ensureMeImage(){ if(S.meImg) return; S.me.innerHTML=''; const img=document.createElementNS('http://www.w3.org/2000/svg','image'); img.setAttribute('width',S.cell*.9); img.setAttribute('height',S.cell*.9); img.setAttribute('preserveAspectRatio','xMidYMid meet'); img.setAttribute('style','pointer-events:none'); S.meImg=img; S.me.appendChild(img) }
  function ensureMeCircle(){ if(S.meCircle) return; S.me.innerHTML=''; const c=document.createElementNS('http://www.w3.org/2000/svg','circle'); c.setAttribute('r',S.cell*.35); c.setAttribute('fill','#ffcd4d'); c.setAttribute('class','me'); S.meCircle=c; S.me.appendChild(c) }
  function drawMeAt(tx,ty){
    if(S.hideHero){ S.me.setAttribute('display','none'); return } else S.me.removeAttribute('display');
    const cx=(tx-S.ox)*S.cell+S.cell/2, cy=(ty-S.oy)*S.cell+S.cell/2;
    if(haveTilePng('hero',0)){ ensureMeImage(); S.meImg.setAttributeNS('http://www.w3.org/1999/xlink','href', pngPath('hero',0)); S.meImg.setAttribute('x', cx-(S.cell*.9)/2); S.meImg.setAttribute('y', cy-(S.cell*.9)/2) }
    else{ ensureMeCircle(); S.meCircle.setAttribute('cx',cx); S.meCircle.setAttribute('cy',cy) }
  }

  /* ——— камера + анимация ——— */
  const dirDXDY=(ch)=> (ch==='R')?[1,0] : (ch==='L')?[-1,0] : (ch==='D')?[0,1] : (ch==='U')?[0,-1] : [0,0];
  async function ensurePatchFor(x,y){
    const pt=S.lastPatch; if(!pt) return;
    const padX=(pt.pad && typeof pt.pad.x==='number')?pt.pad.x:8;
    const padY=(pt.pad && typeof pt.pad.y==='number')?pt.pad.y:5;
    const nearLeft=x<=pt.ox+padX, nearRight=x>=pt.ox+pt.w-1-padX, nearTop=y<=pt.oy+padY, nearBottom=y>=pt.oy+pt.h-1-padY;
    if(!(nearLeft||nearRight||nearTop||nearBottom)) return;
    const j=await apiGET(`${ENDPOINTS.patchView}?cx=${x}&cy=${y}`);
    if(j&&j.ok&&j.patch){ renderPatch(j.patch,true); addPreloadHints(j.patch); preloadForPatch(j.patch) }
  }
  function applyCamTransform(){
    const viewPX=(S.screenW*S.cell), viewPY=(S.screenH*S.cell);
    const targetPX=(S.camX-S.ox)*S.cell+S.cell/2, targetPY=(S.camY-S.oy)*S.cell+S.cell/2;
    S.camOffX=(viewPX/2)-targetPX; S.camOffY=(viewPY/2)-targetPY;
    S.camG.setAttribute('transform', `translate(${S.camOffX},${S.camOffY})`);
  }

  /* ——— UI лагерь + блок движений ——— */
  function updateCampUI(){
    const btnCamp = $('btnCamp'), btnGo = $('btnGo');
    if (btnCamp) {
      if (S.campHere) { btnCamp.textContent = '🎒 Свернуть'; btnCamp.setAttribute('aria-pressed','true'); }
      else { btnCamp.textContent = '🏕️ Лагерь'; btnCamp.removeAttribute('aria-pressed'); }
    }
    if (btnGo) {
      btnGo.disabled = !!S.campHere;
      btnGo.style.opacity = btnGo.disabled ? '0.6' : '';
      btnGo.style.pointerEvents = btnGo.disabled ? 'none' : '';
      btnGo.title = btnGo.disabled ? 'Сначала сверните лагерь' : '';
    }
    const campPill = $('camp');
    if (campPill) campPill.textContent = S.campHere ? (S.campMine ? 'мой' : 'чужой') : '—';
  }

  /* ——— трей погоды (опционален) ——— */
  function updateWeatherTray(s){
    const tNow = $('wxNow'), tMods = $('wxMods'), tUrban = $('wxUrban'), tExplain = $('wxExplain');
    const wxKey = (s && s.weather) ? (s.weather.key || s.weather.name || 'clear') : 'clear';
    const nowStr = prettyWeatherName(s && s.weather);

    let modsStr = '—';
    const mods = s && s.weather && (s.weather.mods || s.weather.modifiers || s.weather.effects);
    if (Array.isArray(mods) && mods.length) modsStr = mods.map(pickText).join(' · ');
    else if (typeof mods === 'string') modsStr = mods;
    else if (s && s.weather && s.weather.note) modsStr = pickText(s.weather.note);

    let urbanStr = '—';
    if (s && (s.tile==='town' || s.tile==='tavern')) urbanStr = 'городская зона';

    let climateRaw = (s && s.climate != null) ? s.climate : null;
    if (climateRaw == null && s && s.weather) climateRaw = s.weather.climate || s.weather.climate_key || s.weather.climateName || null;
    if (climateRaw == null) climateRaw = climateFromTile(s && s.tile);

    if (tNow) tNow.textContent = nowStr;
    if (tMods) tMods.textContent = modsStr;
    if (tUrban) tUrban.textContent = urbanStr;

    const explain = `Климат: ${prettyClimateName(climateRaw)} · ${
      computeEffects(s && s.tile, wxKey, s && s.weather && s.weather.note).replace(/^Эффекты:\s*/, '')
    }`;
    if (tExplain) tExplain.textContent = explain;
  }

  function bindToggles(){
    const wxToggle = $('wxToggle');
    const wxTray = $('wxTray');
    if (wxToggle && wxTray){
      wxToggle.addEventListener('click', ()=>{
        S.wxOpen = !S.wxOpen;
        wxTray.classList.toggle('open', S.wxOpen);
        wxTray.setAttribute('aria-hidden', S.wxOpen ? 'false' : 'true');
      });
    }
    const hudToggle = $('hudToggle');
    const hudRoot = $('hudRoot');
    if (hudToggle && hudRoot){
      hudToggle.addEventListener('click', ()=>{
        S.hudCollapsed = !S.hudCollapsed;
        hudRoot.classList.toggle('collapsed', S.hudCollapsed);
        hudToggle.textContent = S.hudCollapsed ? 'Показать ↓' : 'Скрыть ↑';
        hudToggle.setAttribute('aria-expanded', S.hudCollapsed ? 'false' : 'true');
      });
    }
  }

  /* ===== Добыча ресурсов (кнопка, цикл 5 сек, стоп при движении/лагере) ===== */
  function lastClimateKey(s){
    let c = null;
    if (s && s.climate != null) c = s.climate;
    if (!c && s && s.weather) c = s.weather.climate || s.weather.climate_key || s.weather.climateName;
    if (!c) c = climateFromTile(s && s.tile);
    if (typeof c === 'string') return c.toLowerCase();
    if (typeof c === 'object'){ return (c.key || c.id || pickText(c.name) || '').toString().toLowerCase(); }
    return 'temperate';
  }

  let LAST_STATE = null;
  function publishWorldState(s){
    LAST_STATE = s;
    try{
      window.__WORLD_LAST_TILE = s.tile || null;
      window.dispatchEvent(new CustomEvent('world:state', { detail: s }));
    }catch(_){}
  }

  function setGatherUI(active){
    const btn = $('btnGather');
    if (!btn) return;
    btn.textContent = active ? '⛏️ Стоп' : '⛏️ Добывать';
    btn.style.background = active ? '#ef4444' : '#1f6feb';
  }

  function gatherModeKey(){
    const gm = window.GatherMode;
    if (gm && typeof gm.getMode === 'function'){ try{ return gm.getMode(); }catch(_){ return gm.current; } }
    return (window.WORLD_BOOT && window.WORLD_BOOT.gatherDefaultMode) || 'forage';
  }

  async function gatherTick(){
    if (!S.gatherActive) return;
    const s = LAST_STATE || {};
    const tile = s.tile || 'grass';
    const weather = (s.weather && (s.weather.key || s.weather.name)) || 'clear';
    const climate = lastClimateKey(s);

    const payload = { tile, weather, climate, mode: gatherModeKey() };
    const j = await apiPOST(ENDPOINTS.gatherTick, payload);
    if (!j || !j.ok){
      pkToast('Добыча: ошибка');
      S.gatherActive = false;
      setGatherUI(false);
      return;
    }
    if (j.mode && window.GatherMode && typeof window.GatherMode.setMode === 'function'){
      try{ window.GatherMode.setMode(j.mode); }catch(_){ window.GatherMode.current = j.mode; }
    }
    // обновим усталость в HUD, если есть
    if (typeof j.fatigue === 'number'){
      const fatEl=$('fat'); if(fatEl) fatEl.textContent=j.fatigue.toFixed(0);
      const fatFill=$('fatFill'); if(fatFill) fatFill.style.width=Math.min(100, j.fatigue)+'%';
    }
    if (j.full){
      pkToast('Инвентарь переполнен');
      S.gatherActive = false;
      setGatherUI(false);
      return;
    }
    if (j.found && j.found.name){
      const qty = j.found.qty || 1;
      pkToast(`Найдено: ${j.found.name} x${qty}`);
    } else {
      pkToast('Ничего не найдено');
    }
    // следующий тик через 5 секунд
    if (S.gatherActive){
      clearTimeout(S.gatherTimer);
      S.gatherTimer = setTimeout(gatherTick, 5000);
    }
  }

  async function startGather(){
    if (S.campHere){ pkToast('Сверните лагерь для добычи'); return; }
    if (S.anim && S.anim.moving){ pkToast('Остановитесь, чтобы начать добычу'); return; }
    const r = await apiPOST(ENDPOINTS.gatherStart, { mode: gatherModeKey() });
    if (!r || !r.ok){ pkToast('Не удалось начать добычу'); return; }
    if (r.mode && window.GatherMode && typeof window.GatherMode.setMode === 'function'){
      try{ window.GatherMode.setMode(r.mode); }catch(_){ window.GatherMode.current = r.mode; }
    }
    S.gatherActive = true;
    setGatherUI(true);
    clearTimeout(S.gatherTimer);
    S.gatherTimer = setTimeout(gatherTick, 10);
  }
  async function stopGather(){
    clearTimeout(S.gatherTimer);
    S.gatherTimer = null;
    S.gatherActive = false;
    setGatherUI(false);
    await apiPOST(ENDPOINTS.gatherStop, { mode: gatherModeKey() }).catch(()=>{});
  }
  function toggleGather(){ S.gatherActive ? stopGather() : startGather(); }

  // авто-стоп добычи при движении/лагере
  window.addEventListener('pk:movement', stopGather);
  // если лагерь развернули — тоже стопнем в onCampToggle()

  function startRAF(){
    if(S.raf) return; S.lastRAFts=performance.now();
    const loop=async()=>{
      const now=performance.now(), dt=Math.min(100, now-S.lastRAFts)/1000; S.lastRAFts=now;

      if(S.plan.active && S.anim && S.anim.moving){
        const srvNow=TimeSync.now(); let T=Math.max(.05, S.anim.t||S.plan.stepT); let p=(srvNow-S.anim.ts)/T;
        let safety=16;
        while(p>=1 && safety-- > 0){
          S.pos = { x:S.anim.to.x, y:S.anim.to.y };
          S.plan.cur={...S.anim.to}; S.plan.idx+=1;
          const finished=(S.plan.idx>=S.plan.dirs.length);
          const needStop=(S.plan.stopAt!=null && S.plan.idx>=S.plan.stopAt);
          if(finished||needStop){
            S.plan.active=false;
            S.anim=null;
            S.arriveLockUntil = TimeSync.now() + 0.7;
            scheduleTickSoon(30);
            break;
          } else {
            const [dx,dy]=dirDXDY(S.plan.dirs[S.plan.idx]);
            const tsNext=(S.anim.ts+T);
            S.anim={moving:true,frm:{x:S.plan.cur.x,y:S.plan.cur.y},to:{x:S.plan.cur.x+dx,y:S.plan.cur.y+dy},t:S.plan.stepT,ts:tsNext,key:`${S.plan.cur.x},${S.plan.cur.y}->${S.plan.cur.x+dx},${S.plan.cur.y+dy}`};
            T=S.plan.stepT; p=(srvNow-S.anim.ts)/T; ensurePatchFor(S.plan.cur.x,S.plan.cur.y);
          }
        }
        if(S.anim && S.anim.moving){
          const T2=Math.max(.05, S.anim.t||S.plan.stepT), p2=Math.max(0, Math.min(1,(TimeSync.now()-S.anim.ts)/T2));
          S.pos={ x:S.anim.frm.x+(S.anim.to.x-S.anim.frm.x)*p2, y:S.anim.frm.y+(S.anim.to.y-S.anim.frm.y)*p2 };
          setMoveIndicator(true,false,p2);
        }
      }

      if(!S.plan.active){
        if(S.anim && S.anim.moving){
          const T=Math.max(.05,S.anim.t||.2);
          let p=(TimeSync.now()-S.anim.ts)/T;
          if(p>=1){
            S.pos = { x:S.anim.to.x, y:S.anim.to.y };
            S.anim = null;
            setMoveIndicator(false, S.lastResting, null);
          } else {
            p=Math.max(0, Math.min(1,p));
            S.pos={ x:S.anim.frm.x+(S.anim.to.x-S.anim.frm.x)*p, y:S.anim.frm.y+(S.anim.to.y-S.anim.frm.y)*p };
            setMoveIndicator(true,false,p);
          }
        } else {
          setMoveIndicator(S.lastPathLeft>0 && !S.lastResting, S.lastResting, null);
        }
      }

      const movingNow = !!(S.anim && S.anim.moving);
      if (movingNow) {
        if (!S.wasMoving || S.aimTo.x!=null) { S.aimTo = {x:null,y:null}; renderAim(); }
      } else if (S.wasMoving) {
        S.aimTo = { x: Math.round(S.pos.x), y: Math.round(S.pos.y) };
        renderAim();
      }
      S.wasMoving = movingNow;

      const camAlpha=1-Math.exp(-dt*3.0);
      S.camX = S.camX+(S.pos.x-S.camX)*camAlpha; S.camY = S.camY+(S.pos.y-S.camY)*camAlpha;
      drawMeAt(S.pos.x,S.pos.y); applyCamTransform(); S.raf=requestAnimationFrame(loop);
    };
    S.raf=requestAnimationFrame(loop);
  }

  /* ——— hover/aim ——— */
  function renderHover(){ const gh=S.hov; gh.innerHTML=''; if(S.hover.x==null) return;
    const x=(S.hover.x-S.ox)*S.cell, y=(S.hover.y-S.oy)*S.cell;
    const r=document.createElementNS('http://www.w3.org/2000/svg','rect'); r.setAttribute('x',x); r.setAttribute('y',y); r.setAttribute('width',S.cell); r.setAttribute('height',S.cell); r.setAttribute('class','hover'); gh.appendChild(r) }
  function renderAim(){ const ga=S.aim; ga.innerHTML=''; if(S.aimTo.x==null) return;
    const x=(S.aimTo.x-S.ox)*S.cell, y=(S.aimTo.y-S.oy)*S.cell;
    const r=document.createElementNS('http://www.w3.org/2000/svg','rect'); r.setAttribute('x',x+.5); r.setAttribute('y',y+.5); r.setAttribute('width',S.cell-1); r.setAttribute('height',S.cell-1); r.setAttribute('class','aim'); ga.appendChild(r) }

  /* ——— статы ——— */
  const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v));

function setStats(s){
  // НЕ перетираем S.pos сразу — сначала синхронизируем время и флаги
  if(!TimeSync.inited) TimeSync.init(s.now||Date.now()/1000);
  else TimeSync.blendTo(s.now||Date.now()/1000);

  S.lastResting = !!s.resting;
  S.lastPathLeft = +s.path_left || 0;

  // лагерь
  S.campHere = !!(s.camp && s.camp.here);
  S.campMine = !!(s.camp && s.camp.mine);
  S.hideHero = S.campHere && S.campMine;
  updateCampUI();

  // текстики/баннеры
  const tEl = $('tileRu'); if (tEl) tEl.textContent = prettyTileName(s.tile);
  const wEl = $('wName');  if (wEl) wEl.textContent = prettyWeatherName(s.weather);

  const wxKey = (s.weather && (s.weather.key || s.weather.name || 'clear')) || 'clear';
  const effEl = $('effects');
  if (effEl) effEl.textContent = computeEffects(s.tile, wxKey, s.weather && s.weather.note);

  let climateRaw = (s && s.climate != null) ? s.climate : null;
  if (climateRaw == null && s && s.weather)
    climateRaw = s.weather.climate || s.weather.climate_key || s.weather.climateName || null;
  if (climateRaw == null) climateRaw = climateFromTile(s.tile);
  const clEl = $('climateMain');
  if (clEl) clEl.textContent = 'Климат: ' + prettyClimateName(climateRaw);

  const pxEl = $('px');  if (pxEl)  pxEl.textContent  = s.pos.x;
  const pyEl = $('py');  if (pyEl)  pyEl.textContent  = s.pos.y;
  const fatEl = $('fat'); if (fatEl) fatEl.textContent = s.fatigue;
  const fatFill = $('fatFill'); if (fatFill) fatFill.style.width = Math.min(100, s.fatigue) + '%';

  if (s.screen){
    S.screenW = Number(s.screen.w) || 15;
    S.screenH = Number(s.screen.h) || 9;
  }

  updateWeatherTray(s);
  updateWeatherBanner(s);
  publishWorldState(s);

  // -------- анти-«резинка»: мягкая синхронизация позиции --------
  const nowSrv = TimeSync.now();
  const justArrived =
    (s.path_left === 0) ||
    (s.anim && s.anim.moving && s.pos.x === s.anim.to.x && s.pos.y === s.anim.to.y);

  // Увеличим «замок прибытия», чтобы игнорировать запоздалые кадры
  if (justArrived) S.arriveLockUntil = Math.max(S.arriveLockUntil, nowSrv + 1.0);
  const lockActive = S.arriveLockUntil > nowSrv;

  // Если сервер сообщает анимацию — локальный план гасим
  if (s.anim && s.anim.moving) S.plan.active = false;

  // Мягко подгоняем позицию к серверной:
  const clientMovingLocal = S.plan.active || (S.anim && S.anim.moving);
  const distSrv =
    Math.abs((S.pos?.x ?? s.pos.x) - s.pos.x) +
    Math.abs((S.pos?.y ?? s.pos.y) - s.pos.y);

  // Если не двигаемся локально и нет «лока» — берём серверную позицию.
  // Или если разъехались более чем на 1 клетку — жёстко выравниваем.
  if ((!clientMovingLocal && !lockActive) || distSrv > 1.01) {
    S.pos = { x: s.pos.x, y: s.pos.y };
  }
  // ---------------------------------------------------------------

  // Серверная анимация → локальная
  if (S.campHere) {
    S.plan.active = false;
    S.anim = null;
    // лагерь: если была добыча — стоп
    if (S.gatherActive) stopGather();
  } else if(!lockActive && s.anim && s.anim.moving){
    const key = (s.anim.edge) || `${s.anim.frm.x},${s.anim.frm.y}->${s.anim.to.x},${s.anim.to.y}`;
    const T = Math.max(.05, s.anim.t || .2);

    // серверный ts: если есть p0 — восстановим начало шага
    let srvTs = (typeof s.anim.ts === "number")
      ? s.anim.ts
      : (nowSrv - (s.anim.p0 || 0) * T);

    // если сервер говорит «уже на to» — ставим окончание шага в прошлое
    if (s.pos.x === s.anim.to.x && s.pos.y === s.anim.to.y) srvTs = nowSrv - T;

    // не даём «откатывать» прогресс текущего ключа
    const pSrv = clamp((nowSrv - srvTs) / T, 0, 1);
    if (S.anim && S.anim.moving && S.anim.key === key) {
      const pPrev = clamp((nowSrv - S.anim.ts) / (S.anim.t || T), 0, 1);
      if (pSrv < pPrev - 0.02) srvTs = nowSrv - pPrev * T;
    }

    S.anim = {
      moving: true,
      frm: { ...s.anim.frm },
      to:  { ...s.anim.to  },
      t:   T,
      ts:  srvTs,
      key
    };
  } else {
    S.anim = null;
  }

  // Первичная центровка камеры
  if (S.camX === 0 && S.camY === 0) {
    const cx = (S.pos?.x != null) ? S.pos.x : s.pos.x;
    const cy = (S.pos?.y != null) ? S.pos.y : s.pos.y;
    S.camX = cx; S.camY = cy;
  }

  startRAF();
}

  /* ——— основной тик ——— */
  async function tick(){
    if(S.tickInFlight) return; S.tickInFlight=true; hideDiag();
    if(!ENDPOINTS.state){ showDiag('<b>Нет ENDPOINTS.state</b>'); S.tickInFlight=false; return }
    let s=await apiPOST(ENDPOINTS.state);
    if(!s||!s.ok){ if(ENDPOINTS.stateGet){ const g=await apiGET(ENDPOINTS.stateGet); if(g&&g.ok) s=g } }
    if(!s||!s.ok){ const detail=s?JSON.stringify({http:s.__http,error:s.error||null,detail:s.detail||null}):'no response'; showDiag(`<b>Не удалось получить состояние</b><br><small>${detail}</small>`); S.tickInFlight=false; return }
    try{
      const willChange=(patchSignature(s.patch)!==S.lastPatchSig)||(S.lastVersGen!==VERS_GEN);
      renderPatch(s.patch);
      if(willChange){ addPreloadHints(s.patch); preloadForPatch(s.patch); if(!S.didIdlePrefetch){ S.didIdlePrefetch=true; prefetchAllIdle() } }
      setStats(s);
    }catch(e){ showDiag(`<b>Ошибка рендера:</b> ${String(e)}`) } finally { S.tickInFlight=false }
  }

  /* ——— карта/интеракции ——— */
  function mapPoint(evt){
    const svg=$('map'); const pt=svg.createSVGPoint();
    const e=(evt.touches&&evt.touches[0])?evt.touches[0]:evt; pt.x=e.clientX; pt.y=e.clientY;
    const ctm=svg.getScreenCTM().inverse(); const sp=pt.matrixTransform(ctm);
    const localX = sp.x - S.camOffX, localY = sp.y - S.camOffY;
    const i=Math.floor(localX/S.cell), j=Math.floor(localY/S.cell);
    const tx=S.ox+Math.max(0,Math.min(S.w-1,i)), ty=S.oy+Math.max(0,Math.min(S.h-1,j));
    return {x:tx,y:ty};
  }

  function scheduleTickSoon(ms=120){ clearTimeout(S.tickTimer); S.tickTimer=setTimeout(loop,ms) }

  async function commitDest(t){
    if (S.campHere) { pkToast('Нельзя двигаться, пока развернут лагерь. Нажмите «Лагерь», чтобы свернуть.'); return; }
    const now=performance.now(); if(now-S.lastSetAt<150) return; S.lastSetAt=now;
    const r=await apiPOST(ENDPOINTS.setDest,t);
    if(r&&r.ok){
      pkToast(r.message||'OK');
      if(r.plan && r.plan.dirs){
        S.plan.active=true; S.plan.start={x:r.plan.start.x,y:r.plan.start.y}; S.plan.cur={x:r.plan.start.x,y:r.plan.start.y};
        S.plan.dirs=r.plan.dirs||''; S.plan.idx=0; S.plan.stepT=Math.max(.1, Number(r.plan.step_t)||.6); S.plan.ts=(r.plan.now||Date.now()/1000); S.plan.stopAt=(typeof r.plan.stop_at==='number')?r.plan.stop_at:null;
        if(S.plan.dirs.length){
          try{ window.dispatchEvent(new Event('pk:movement')); }catch(_){}
          const [dx,dy]=([...'RLDU'].includes(S.plan.dirs[0])?((c)=>c==='R'?[1,0]:c==='L'?[-1,0]:c==='D'?[0,1]:[0,-1])(S.plan.dirs[0]):[0,0]);
          S.anim={moving:true, frm:{x:S.plan.cur.x,y:S.plan.cur.y}, to:{x:S.plan.cur.x+dx,y:S.plan.cur.y+dy}, t:S.plan.stepT, ts:S.plan.ts, key:`${S.plan.cur.x},${S.plan.cur.y}->${S.plan.cur.x+dx},${S.plan.cur.y+dy}`};
          S.pos={x:S.plan.cur.x,y:S.plan.cur.y}; ensurePatchFor(S.plan.cur.x,S.plan.cur.y);
        }
      } else { scheduleTickSoon(50) }
    } else { pkToast((r&&r.message)||'Ошибка'); scheduleTickSoon(50) }
  }

  async function onMapDown(e){ e.preventDefault(); S.dragging=true; S.hover=mapPoint(e); S.aimTo={...S.hover}; renderHover(); renderAim();
    clearTimeout(S.longPressTimer); S.longPressTimer=setTimeout(async()=>{ S.dragging=false; clearTimeout(S.longPressTimer); S.plan.active=false; S.anim=null; const r=await apiPOST(ENDPOINTS.stop); pkToast(r.message||'Стоп'); scheduleTickSoon(30) },450) }
  function onMapMove(e){ if(!S.dragging) return; S.hover=mapPoint(e); S.aimTo={...S.hover}; renderHover(); renderAim() }
  async function onMapUp(e){ clearTimeout(S.longPressTimer); if(!S.dragging) return; S.dragging=false; const t=mapPoint(e); S.hover={x:null,y:null}; renderHover(); S.aimTo={...t}; renderAim() }
  async function onGo(){ if(S.aimTo.x==null){ pkToast('Сначала выберите точку на карте'); return } await commitDest(S.aimTo) }

  async function onCampToggle(){
    S.plan.active=false; S.anim=null;
    if (S.gatherActive) await stopGather();
    if (S.campHere) {
      const r=await apiPOST(ENDPOINTS.campLeave);
      pkToast(r.message||(r.ok?'Свернули лагерь':'Ошибка'));
    } else {
      const r=await apiPOST(ENDPOINTS.campStart);
      pkToast(r.message||(r.ok?'Лагерь развернут':'Ошибка'));
    }
    scheduleTickSoon(30);
  }

  async function onStop(){ S.plan.active=false; S.anim=null; if (S.gatherActive) await stopGather(); const r=await apiPOST(ENDPOINTS.stop); pkToast(r.message||'Стоп'); scheduleTickSoon(30) }

  /* ——— цикл обновлений ——— */
  let hidden=document.visibilityState==='hidden';
  document.addEventListener('visibilitychange', ()=>{ hidden=document.visibilityState==='hidden'; if(!hidden && !S.plan.active) scheduleTickSoon(50) });
  async function loop(){ if(!S.plan.active) await tick(); const moving=!!(S.anim && S.anim.moving); const msHidden=3500, msStand=1200, msRest=1800, msMove=650; const next= hidden?msHidden : (moving?msMove : (S.lastResting?msRest:msStand)); S.tickTimer=setTimeout(loop,next) }

  function init(){
    const req=['map','tiles','blds','hover','aim','me','btnGo','btnStop','btnCamp']; const missing=req.filter(id=>!$(id));
    if(missing.length) showDiag(`<b>Ошибка инициализации:</b> отсутствуют элементы: ${missing.join(', ')}`);

    S.camG=$('cam'); S.tiles=$('tiles'); S.blds=$('blds'); S.me=$('me'); S.aim=$('aim'); S.hov=$('hover');

    const svg=$('map'); svg.addEventListener('touchstart', onMapDown, {passive:false});
    svg.addEventListener('touchmove',  onMapMove, {passive:false});
    svg.addEventListener('touchend',   onMapUp,   {passive:false});
    svg.addEventListener('mousedown',  onMapDown);
    svg.addEventListener('mousemove',  onMapMove);
    window.addEventListener('mouseup', onMapUp);

    const btnGo=$('btnGo'), btnStop=$('btnStop'), btnCamp=$('btnCamp'), btnGather=$('btnGather');
    if(btnGo)     btnGo.addEventListener('click', onGo);
    if(btnStop)   btnStop.addEventListener('click', onStop);
    if(btnCamp)   btnCamp.addEventListener('click', onCampToggle);
    if(btnGather) btnGather.addEventListener('click', toggleGather);

    bindToggles();

    try{ if(window.Telegram && Telegram.WebApp && Telegram.WebApp.expand) Telegram.WebApp.expand() }catch(e){}

    scheduleTickSoon(10);
    setInterval(pollTileVersions, 15000);
    startRAF();
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
