// Navigation (web-redesign-v1): five places; every other page opens from one of them.
export type Place = { path: string; label: string; icon: string; also: string[] };

export const PLACES: Place[] = [
  { path: "/", label: "Today", icon: "today", also: ["/inbox", "/loops", "/briefs", "/week"] },
  { path: "/moderate", label: "Moderate", icon: "moderate", also: ["/assistant"] },
  { path: "/meetings", label: "Meetings", icon: "meetings", also: ["/recordings", "/dictate"] },
  {
    path: "/search",
    label: "Search",
    icon: "search",
    also: ["/library", "/people", "/c/", "/scopes", "/clickup"],
  },
  { path: "/settings", label: "Settings", icon: "settings", also: ["/connectors", "/status"] },
];

// The pages reached from Search, Today and Settings (also listed in the ⌘K palette).
export type Page = { path: string; label: string; icon: string; hint: string };

export const PAGES: Page[] = [
  { path: "/inbox", label: "Inbox", icon: "✉", hint: "Mail by priority" },
  { path: "/loops", label: "Loops", icon: "↺", hint: "Promises and replies" },
  { path: "/briefs", label: "Briefs", icon: "🗞", hint: "Morning and evening" },
  { path: "/week", label: "Week", icon: "📅", hint: "Review and plan" },
  { path: "/assistant", label: "Assistant", icon: "✦", hint: "Ask and get drafts" },
  { path: "/dictate", label: "Dictate", icon: "🎙", hint: "Voice to text" },
  { path: "/clickup", label: "ClickUp", icon: "☑", hint: "For you and the team" },
  { path: "/library", label: "Library", icon: "📚", hint: "Documents and goals" },
  { path: "/people", label: "People", icon: "👥", hint: "Who is who" },
  { path: "/connectors", label: "Connectors", icon: "🔌", hint: "Mail, chats, calendars" },
  { path: "/status", label: "Status", icon: "❤", hint: "Health and costs" },
];

// kept for the ⌘K palette: every place and page
const PALETTE_ICON: Record<string, string> = {
  today: "☀",
  moderate: "✓",
  meetings: "🗓",
  search: "🔎",
  settings: "⚙",
};

export const APPS = [
  ...PLACES.map((p) => ({ path: p.path, label: p.label, icon: PALETTE_ICON[p.icon] })),
  ...PAGES.map((p) => ({ path: p.path, label: p.label, icon: p.icon })),
];

export function placeOf(pathname: string): Place | undefined {
  return (
    PLACES.find((p) => p.path !== "/" && pathname.startsWith(p.path)) ??
    PLACES.find((p) => p.also.some((a) => pathname.startsWith(a))) ??
    (pathname === "/" ? PLACES[0] : undefined)
  );
}

export function pageTitle(pathname: string): string {
  const page = PAGES.find((p) => pathname.startsWith(p.path));
  return page?.label ?? placeOf(pathname)?.label ?? "Second brain";
}
