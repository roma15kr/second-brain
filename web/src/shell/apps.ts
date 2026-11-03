// Navigation (web-redesign-v1): the assistant first; every section visible in groups (sidebar)
// or in Menu (phone).
export type Section = { path: string; label: string; icon: string; hint: string };
export type Group = { title: string; items: Section[] };

export const ASSISTANT: Section = {
  path: "/assistant",
  label: "Assistant",
  icon: "assistant",
  hint: "Ask or dictate",
};

export const GROUPS: Group[] = [
  {
    title: "Work",
    items: [
      { path: "/", label: "Today", icon: "today", hint: "What needs you now" },
      { path: "/moderate", label: "Moderate", icon: "moderate", hint: "Tasks, comments, messages" },
      { path: "/inbox", label: "Inbox", icon: "inbox", hint: "Mail by priority" },
      { path: "/loops", label: "Loops", icon: "loops", hint: "Promises and replies" },
      { path: "/meetings", label: "Meetings", icon: "meetings", hint: "Calendar and recordings" },
    ],
  },
  {
    title: "Knowledge",
    items: [
      { path: "/search", label: "Search", icon: "search", hint: "Mail, chats, tasks" },
      { path: "/library", label: "Library", icon: "library", hint: "Documents and goals" },
      { path: "/people", label: "People", icon: "people", hint: "Who is who" },
    ],
  },
  {
    title: "Reports",
    items: [
      { path: "/briefs", label: "Briefs", icon: "briefs", hint: "Morning and evening" },
      { path: "/week", label: "Week", icon: "week", hint: "Review and plan" },
      { path: "/clickup", label: "ClickUp", icon: "clickup", hint: "For you and the team" },
    ],
  },
  {
    title: "System",
    items: [
      {
        path: "/connectors",
        label: "Connectors",
        icon: "connectors",
        hint: "Mail, chats, calendars",
      },
      { path: "/status", label: "Status", icon: "status", hint: "Health and costs" },
      { path: "/settings", label: "Settings", icon: "settings", hint: "Team, routines, devices" },
    ],
  },
];

export const SECTIONS: Section[] = [ASSISTANT, ...GROUPS.flatMap((g) => g.items)];

// phone tab bar: the assistant in the centre
export const TABS = {
  left: ["/", "/moderate"],
  right: ["/meetings"],
};

// pages that belong to a section (for the title and the active mark)
const ALSO: Record<string, string[]> = {
  "/assistant": ["/dictate"],
  "/meetings": ["/recordings"],
  "/search": ["/c/", "/scopes"],
  "/people": [],
};

export function sectionOf(pathname: string): Section | undefined {
  if (pathname === "/") return SECTIONS.find((s) => s.path === "/");
  if (pathname === "/menu") return undefined;
  return (
    SECTIONS.find((s) => s.path !== "/" && pathname.startsWith(s.path)) ??
    SECTIONS.find((s) => (ALSO[s.path] ?? []).some((a) => pathname.startsWith(a)))
  );
}

export function pageTitle(pathname: string): string {
  if (pathname === "/menu") return "Menu";
  return sectionOf(pathname)?.label ?? "Second brain";
}

const PALETTE_ICON: Record<string, string> = {
  assistant: "✦",
  today: "☀",
  moderate: "✓",
  inbox: "✉",
  loops: "↺",
  meetings: "🗓",
  search: "🔎",
  library: "📚",
  people: "👥",
  briefs: "🗞",
  week: "📅",
  clickup: "☑",
  connectors: "🔌",
  status: "❤",
  settings: "⚙",
}; // fmt: skip

// the ⌘K palette lists every section
export const APPS = SECTIONS.map((s) => ({
  path: s.path,
  label: s.label,
  icon: PALETTE_ICON[s.icon],
}));
