const STATIC = 'pk-static-v2'; // было v1
const MATCH = /\/static\/tiles\//;

self.addEventListener('install', e=>{
  self.skipWaiting();
  e.waitUntil(caches.open(STATIC));
});

self.addEventListener('activate', e=>{
  e.waitUntil((async()=>{
    const keys = await caches.keys();
    await Promise.all(keys.filter(k=>k!==STATIC).map(k=>caches.delete(k)));
    self.clients.claim();
  })());
});

self.addEventListener('fetch', e=>{
  const url = new URL(e.request.url);
  if (MATCH.test(url.pathname)) {
    e.respondWith((async()=>{
      const cache = await caches.open(STATIC);
      const hit = await cache.match(e.request);
      const fetchP = fetch(e.request).then(r=>{
        cache.put(e.request, r.clone()); return r;
      }).catch(()=>hit);
      return hit || fetchP;
    })());
  }
});
