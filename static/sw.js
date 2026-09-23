/* Paddock Legacy service worker: makes the site installable and shows phone/desktop alerts. */
self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (event) { event.waitUntil(self.clients.claim()); });

self.addEventListener("push", function (event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data && event.data.text() }; }
  event.waitUntil(self.registration.showNotification(data.title || "Paddock Legacy", {
    body: data.body || "",
    icon: "/static/icons/icon-192.png",
    badge: "/static/icons/icon-192.png",
    data: { url: data.url || "/" }
  }));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (list) {
    for (var i = 0; i < list.length; i++) {
      if ("focus" in list[i]) { list[i].navigate(url); return list[i].focus(); }
    }
    return self.clients.openWindow(url);
  }));
});

/* Network first; if you're offline, show a simple message instead of the browser's error page. */
self.addEventListener("fetch", function (event) {
  if (event.request.mode !== "navigate") return;
  event.respondWith(fetch(event.request).catch(function () {
    return new Response("<meta name=viewport content='width=device-width'><body style='font-family:sans-serif;background:#07090f;color:#e8ecf3;padding:2rem'>" +
      "<h1>You're offline</h1><p>Reconnect and pull to refresh.</p>", { headers: { "Content-Type": "text/html" } });
  }));
});
