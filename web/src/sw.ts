/// <reference lib="webworker" />
import { ExpirationPlugin } from "workbox-expiration";
import { createHandlerBoundToURL, precacheAndRoute } from "workbox-precaching";
import { NavigationRoute, registerRoute } from "workbox-routing";
import { NetworkFirst } from "workbox-strategies";
import { OFFLINE_API } from "./sw-handlers";
import { notificationOptions, openTarget, parsePush } from "./sw-handlers";

declare const self: ServiceWorkerGlobalScope;

precacheAndRoute(self.__WB_MANIFEST);
// Offline (web-access spec): the app shell for every page, and the last loaded Today, briefs and
// sign-in state; everything else needs the network.
registerRoute(new NavigationRoute(createHandlerBoundToURL("/index.html")));
registerRoute(
  ({ url, request }) => request.method === "GET" && OFFLINE_API.some((re) => re.test(url.pathname)),
  new NetworkFirst({
    cacheName: "api-read",
    networkTimeoutSeconds: 4,
    plugins: [new ExpirationPlugin({ maxEntries: 60, maxAgeSeconds: 14 * 86400 })],
  }),
);
self.addEventListener("install", () => void self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  const p = parsePush(event.data?.text());
  event.waitUntil(self.registration.showNotification(p.title, notificationOptions(p)));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data as { url?: string } | null)?.url ?? "/";
  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((windows) =>
        openTarget(url, windows, (u) => self.clients.openWindow(u), self.location.origin),
      ),
  );
});
