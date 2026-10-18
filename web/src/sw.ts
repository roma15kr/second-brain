/// <reference lib="webworker" />
import { precacheAndRoute } from "workbox-precaching";
import { notificationOptions, openTarget, parsePush } from "./sw-handlers";

declare const self: ServiceWorkerGlobalScope;

precacheAndRoute(self.__WB_MANIFEST);
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
