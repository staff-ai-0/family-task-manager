// Family Task Manager — service worker: offline shell + web push.

const CACHE_NAME = 'ftm-shell-v1';

const PRECACHE_ASSETS = [
    '/icon-192.png',
    '/icon-512.png',
    '/icon-maskable-192.png',
    '/icon-maskable-512.png',
    '/favicon.svg',
    '/manifest.webmanifest',
    '/offline.html',
];

// ── Lifecycle ────────────────────────────────────────────────────────────────

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_ASSETS))
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(
                keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
            ))
            .then(() => self.clients.claim())
    );
});

// ── Fetch strategies ─────────────────────────────────────────────────────────

self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // Only intercept same-origin GET requests
    if (request.method !== 'GET' || url.origin !== self.location.origin) return;

    // API calls: always network, never cache
    if (url.pathname.startsWith('/api/')) return;

    // Astro-fingerprinted bundles + precached icons: cache-first, populate on miss
    if (url.pathname.startsWith('/_astro/') || PRECACHE_ASSETS.includes(url.pathname)) {
        event.respondWith(
            caches.match(request).then((cached) => {
                if (cached) return cached;
                return fetch(request).then((resp) => {
                    const clone = resp.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
                    return resp;
                });
            })
        );
        return;
    }

    // Navigation (HTML pages): network-first, offline fallback
    if (request.mode === 'navigate') {
        event.respondWith(
            fetch(request).catch(() => caches.match('/offline.html'))
        );
        return;
    }
});

// ── Push notification handlers ───────────────────────────────────────────────

self.addEventListener('push', (event) => {
    let payload = { title: 'Family Task Manager', body: '', url: '/dashboard' };
    try {
        if (event.data) payload = { ...payload, ...event.data.json() };
    } catch (e) {
        // Non-JSON payload — fall back to defaults.
    }

    const opts = {
        body: payload.body,
        icon: '/icon-192.png',
        badge: '/icon-192.png',
        tag: payload.tag || 'ftm-push',
        data: { url: payload.url },
        renotify: true,
    };
    event.waitUntil(self.registration.showNotification(payload.title, opts));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const url = (event.notification.data && event.notification.data.url) || '/dashboard';
    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
            for (const client of clients) {
                if ('focus' in client) {
                    client.navigate(url);
                    return client.focus();
                }
            }
            if (self.clients.openWindow) return self.clients.openWindow(url);
        })
    );
});
