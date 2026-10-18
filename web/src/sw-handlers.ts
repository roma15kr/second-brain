// API reads kept for offline use (last loaded copy).
export const OFFLINE_API = [/^\/api\/auth\/me$/, /^\/api\/today$/, /^\/api\/briefs(\/\d+)?$/];

// Push handling, kept free of service-worker globals so it can be unit-tested.
export type PushPayload = { title: string; body: string; url: string };

export function parsePush(text: string | null | undefined): PushPayload {
  try {
    const data = JSON.parse(text ?? "{}") as Partial<PushPayload>;
    return {
      title: data.title || "Second brain",
      body: data.body || "",
      url: typeof data.url === "string" && data.url.startsWith("/") ? data.url : "/",
    };
  } catch {
    return { title: "Second brain", body: "", url: "/" };
  }
}

export function notificationOptions(p: PushPayload): NotificationOptions {
  return { body: p.body, icon: "/icon-192.png", badge: "/icon-192.png", data: { url: p.url } };
}

type WindowLike = {
  url: string;
  focus(): Promise<unknown>;
  navigate?(url: string): Promise<unknown>;
};

// Focus an open app window (navigating it to the page) or open a new one.
export async function openTarget(
  url: string,
  windows: readonly WindowLike[],
  openWindow: (url: string) => Promise<unknown>,
  origin: string,
): Promise<void> {
  const target = new URL(url, origin).href;
  const existing = windows.find((w) => w.url.startsWith(origin));
  if (existing) {
    await existing.focus();
    if (existing.url !== target && existing.navigate) await existing.navigate(target);
    return;
  }
  await openWindow(target);
}
