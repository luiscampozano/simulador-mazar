// Permite instalar el simulador como app. Siempre busca primero la versión nueva en internet;
// solo si no hay conexión muestra la última copia guardada. No toca datos de otros sitios.
const CACHE = "app-v1";
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(
  caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())
));
self.addEventListener("fetch", e => {
  const r = e.request;
  if (r.method !== "GET" || new URL(r.url).origin !== location.origin) return;
  e.respondWith(
    fetch(r).then(res => {
      if (res.ok) { const c = res.clone(); caches.open(CACHE).then(k => k.put(r, c)); }
      return res;
    }).catch(() => caches.match(r, { ignoreSearch: true }))
  );
});
