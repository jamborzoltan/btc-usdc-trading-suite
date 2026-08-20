const CACHE_NAME = "btc-usdc-robot-shell-v21";
const APP_SHELL = [
  "./",
  "./index.html",
  "./styles.css",
  "./auth.js",
  "./app.js",
  "./manifest.webmanifest",
  "./icons/btc-usdc-robot.svg",
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys
        .filter(key => key !== CACHE_NAME)
        .map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // A MySQL vezérlés és a Binance-runtime mindig hálózatról jön, így nem mutatunk
  // gyorsítótárból régi egyenleget, pozíciót vagy robot-szívverést.
  if (url.pathname.includes("/api/")) {
    event.respondWith(fetch(request));
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then(response => {
          if (response && response.ok) {
            caches.open(CACHE_NAME).then(cache => cache.put("./index.html", response.clone()));
          }
          return response;
        })
        .catch(() => caches.match("./index.html"))
    );
    return;
  }

  event.respondWith(
    fetch(request)
      .then(response => {
        if (!response || !response.ok) return response;
        const responseCopy = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(request, responseCopy));
        return response;
      })
      .catch(() => caches.match(request).then(cached => cached || Response.error()))
  );
});
