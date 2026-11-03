import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router";
import { api } from "../api/client";
import { ASSISTANT, GROUPS, pageTitle, SECTIONS, sectionOf, TABS, type Section } from "./apps";
import { Bell } from "./Bell";
import { ICONS } from "./icons";
import { Palette } from "./Palette";
import { useOnline } from "./useOnline";

// the number of proposals waiting, shown next to Moderate
function useModerateCount(): number {
  const today = useQuery({
    queryKey: ["today"],
    queryFn: () => api<{ moderate?: number }>("/api/today"),
    refetchInterval: 120_000,
  });
  return today.data?.moderate ?? 0;
}

function Item({ s, current, count }: { s: Section; current?: string; count?: number }) {
  return (
    <NavLink
      to={s.path}
      end={s.path === "/"}
      className={() => (current === s.path ? "active" : "")}
      aria-current={current === s.path ? "page" : undefined}
    >
      {ICONS[s.icon]}
      <span>{s.label}</span>
      {count ? <span className="count">{count}</span> : null}
    </NavLink>
  );
}

function Sidebar({ current, moderate }: { current?: string; moderate: number }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="logo" aria-hidden />
        Second brain
      </div>
      <Link to={ASSISTANT.path} className="ask-btn">
        {ICONS.assistant}
        <span>Ask or dictate</span>
        {ICONS.mic}
      </Link>
      <nav className="side-nav" aria-label="Main">
        {GROUPS.map((g) => (
          <div key={g.title} className="nav-group">
            <span className="nav-title">{g.title}</span>
            {g.items.map((s) => (
              <Item
                key={s.path}
                s={s}
                current={current}
                count={s.path === "/moderate" ? moderate : undefined}
              />
            ))}
          </div>
        ))}
      </nav>
    </aside>
  );
}

function TabBar({ current, moderate }: { current?: string; moderate: number }) {
  const find = (p: string) => SECTIONS.find((s) => s.path === p)!;
  const { pathname } = useLocation();
  return (
    <nav className="tabbar" aria-label="Tabs">
      {TABS.left.map((p) => (
        <Item
          key={p}
          s={find(p)}
          current={current}
          count={p === "/moderate" ? moderate : undefined}
        />
      ))}
      <NavLink
        to={ASSISTANT.path}
        className={() => `tab-ask${current === ASSISTANT.path ? " active" : ""}`}
        aria-label="Assistant"
      >
        <span className="tab-ask-circle">{ICONS.assistant}</span>
        <span>Assistant</span>
      </NavLink>
      {TABS.right.map((p) => (
        <Item key={p} s={find(p)} current={current} />
      ))}
      <NavLink to="/menu" className={() => (pathname === "/menu" ? "active" : "")}>
        {ICONS.menu}
        <span>Menu</span>
      </NavLink>
    </nav>
  );
}

// The phone's Menu: every section, one tap away (web-redesign-v1).
export function Menu() {
  return (
    <>
      {GROUPS.map((g) => (
        <section key={g.title} className="card menu-group">
          <h3 className="card-title">{g.title}</h3>
          <ul className="list">
            {g.items.map((s) => (
              <li key={s.path}>
                <Link to={s.path} className="menu-row">
                  <span className="menu-icon">{ICONS[s.icon]}</span>
                  <span>
                    <span className="line">{s.label}</span>
                    <span className="sub">{s.hint}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}

// App shell (web-redesign-v1): sidebar on wide screens, tab bar on phones, ⌘K palette.
export function Shell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const online = useOnline();
  const moderate = useModerateCount();
  const current = sectionOf(pathname)?.path;
  const [palette, setPalette] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => !p);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div className="shell">
      <Sidebar current={current} moderate={moderate} />
      <div className="workspace">
        <header className="top">
          <h1>{pageTitle(pathname)}</h1>
          <button className="cmd" onClick={() => setPalette(true)} aria-label="Search or jump to…">
            {ICONS.search}
            <span className="desktop-only">Search or jump to…</span>
            <kbd className="desktop-only">⌘K</kbd>
          </button>
          <Bell />
        </header>
        <main className="page">
          {!online && (
            <p className="note banner" role="status">
              Offline — showing the last loaded pages; actions wait until you are back online.
            </p>
          )}
          <fieldset className="plain" disabled={!online}>
            {children}
          </fieldset>
        </main>
      </div>
      <TabBar current={current} moderate={moderate} />
      {palette && <Palette onClose={() => setPalette(false)} />}
    </div>
  );
}
