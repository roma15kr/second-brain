import { useEffect, useState } from "react";
import { api } from "../api/client";

type State = "checking" | "unsupported" | "install" | "denied" | "off" | "on";

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4))
    .replace(/-/g, "+")
    .replace(/_/g, "/");
  const raw = atob(padded);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function isIos() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent);
}

function isStandalone() {
  return window.matchMedia?.("(display-mode: standalone)").matches ?? false;
}

// Per-device push switch (web-access spec). iOS only allows push in the installed app.
export function Notifications() {
  const [state, setState] = useState<State>("checking");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
        setState(isIos() && !isStandalone() ? "install" : "unsupported");
        return;
      }
      if (Notification.permission === "denied") return setState("denied");
      const reg = await navigator.serviceWorker.ready;
      setState((await reg.pushManager.getSubscription()) ? "on" : "off");
    })().catch(() => setState("unsupported"));
  }, []);

  async function enable() {
    setMessage(null);
    try {
      if ((await Notification.requestPermission()) !== "granted") return setState("denied");
      const { public_key } = await api<{ public_key: string }>("/api/push/key");
      if (!public_key) throw new Error("Push is not configured on the server yet.");
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(public_key),
      });
      await api("/api/push/subscribe", { method: "POST", body: { subscription: sub.toJSON() } });
      setState("on");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    }
  }

  async function test() {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (!sub) return setState("off");
    const { sent } = await api<{ sent: number }>("/api/push/test", {
      method: "POST",
      body: { endpoint: sub.endpoint },
    });
    setMessage(sent ? "Test notification sent." : "The push service did not accept it.");
  }

  return (
    <div className="notifications muted">
      {state === "install" &&
        "To get notifications on iPhone: Share → Add to Home Screen, then open the app."}
      {state === "unsupported" && "This browser cannot receive notifications."}
      {state === "denied" && "Notifications are blocked for this site in the browser settings."}
      {state === "off" && (
        <button className="btn" onClick={enable}>
          🔔 Enable notifications on this device
        </button>
      )}
      {state === "on" && (
        <>
          🔔 Notifications on ·{" "}
          <button className="btn" onClick={test}>
            Send test
          </button>
        </>
      )}
      {message && <div role="status">{message}</div>}
    </div>
  );
}
