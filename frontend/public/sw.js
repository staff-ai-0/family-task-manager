// Family Task Manager — service worker for Web Push.
// Receives a payload from PushService.fan_out_pending_gig and shows a
// notification. Clicking the notification focuses (or opens) the
// approvals queue.

self.addEventListener("install", (event) => {
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
    let payload = { title: "Family Task Manager", body: "", url: "/parent/approvals" };
    try {
        if (event.data) payload = { ...payload, ...event.data.json() };
    } catch (e) {
        // Non-JSON payload; fall back to defaults.
    }

    const opts = {
        body: payload.body,
        icon: "/icon-192.png",
        badge: "/icon-192.png",
        tag: payload.tag || "ftm-push",
        data: { url: payload.url },
        // Re-notify even if a notification with the same tag exists.
        renotify: true,
    };
    event.waitUntil(self.registration.showNotification(payload.title, opts));
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const url = (event.notification.data && event.notification.data.url) || "/parent/approvals";
    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
            for (const client of clients) {
                if ("focus" in client) {
                    client.navigate(url);
                    return client.focus();
                }
            }
            if (self.clients.openWindow) return self.clients.openWindow(url);
        })
    );
});
