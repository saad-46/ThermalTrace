/* ThermalTrace service worker: app-shell cache, network-first API reads with an offline
   fallback to the last response, and Web Push display. Mutations are never cached. */
const SHELL = "tt-shell-v1";
const API = "tt-api-v1";

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(["/", "/manifest.webmanifest", "/icon.svg"])).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => ![SHELL, API].includes(k)).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  );
});

const CACHEABLE_API = [/\/api\/v1\/events(\?|$|\/)/, /\/api\/v1\/alerts(\?|$)/, /\/api\/v1\/watchlists/, /\/api\/v1\/status$/];

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.pathname.startsWith("/api/")) {
    if (!CACHEABLE_API.some((r) => r.test(url.pathname + url.search))) return;
    e.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(API).then((c) => c.put(req, copy));
          }
          return res;
        })
        .catch(() =>
          caches.match(req).then((hit) => {
            if (!hit) return new Response(JSON.stringify({ error: { code: "offline", message: "Offline and no cached copy" } }), { status: 503, headers: { "content-type": "application/json" } });
            const headers = new Headers(hit.headers);
            headers.set("x-tt-offline-cache", "1");
            return hit.blob().then((b) => new Response(b, { status: 200, headers }));
          }),
        ),
    );
    return;
  }
  if (req.mode === "navigate") {
    e.respondWith(fetch(req).catch(() => caches.match("/")));
    return;
  }
  if (url.origin === self.location.origin && /\.(js|css|svg|woff2?)$/.test(url.pathname)) {
    e.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => { const copy = res.clone(); caches.open(SHELL).then((c) => c.put(req, copy)); return res; })),
    );
  }
});

self.addEventListener("push", (e) => {
  let data = { title: "ThermalTrace", body: "New alert", event_id: null };
  try { data = { ...data, ...e.data.json() }; } catch { /* plain text payload */ }
  e.waitUntil(self.registration.showNotification(data.title, { body: data.body, icon: "/icon.svg", data: { event_id: data.event_id }, tag: data.event_id || undefined }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const id = e.notification.data && e.notification.data.event_id;
  e.waitUntil(self.clients.openWindow(id ? `/events/${id}` : "/alerts"));
});
