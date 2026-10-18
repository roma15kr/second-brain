// Dock apps (web-dashboard spec: OS shell). Apps join the dock as their pages are built.
export type App = { path: string; label: string; icon: string; phone?: boolean };

export const APPS: App[] = [
  { path: "/", label: "Today", icon: "☀", phone: true },
  { path: "/inbox", label: "Inbox", icon: "✉", phone: true },
  { path: "/loops", label: "Loops", icon: "↺", phone: true },
  { path: "/briefs", label: "Briefs", icon: "🗞", phone: true },
  { path: "/week", label: "Week", icon: "📅" },
  { path: "/search", label: "Search", icon: "🔎" },
  { path: "/people", label: "People", icon: "👥" },
  { path: "/library", label: "Library", icon: "📚" },
  { path: "/connectors", label: "Connectors", icon: "🔌" },
  { path: "/status", label: "Status", icon: "❤" },
  { path: "/settings", label: "Settings", icon: "⚙" },
];
