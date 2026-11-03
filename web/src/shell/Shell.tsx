import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router";
import { pageTitle, PLACES, placeOf } from "./apps";
import { Bell } from "./Bell";
import { ICONS } from "./icons";
import { Palette } from "./Palette";
import { useOnline } from "./useOnline";

function Nav({ className, label }: { className: string; label: string }) {
  const { pathname } = useLocation();
  const current = placeOf(pathname);
  return (
    <nav className={className} aria-label={label}>
      {PLACES.map((p) => (
        <NavLink
          key={p.path}
          to={p.path}
          end={p.path === "/"}
          className={() => (current?.path === p.path ? "active" : "")}
          aria-current={current?.path === p.path ? "page" : undefined}
        >
          {ICONS[p.icon]}
          <span>{p.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}

// App shell (web-redesign-v1): sidebar on wide screens, tab bar on phones, ⌘K palette.
export function Shell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const online = useOnline();
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
      <aside className="sidebar">
        <div className="brand">
          <span className="logo" aria-hidden />
          Second brain
        </div>
        <Nav className="side-nav" label="Main" />
      </aside>
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
      <Nav className="tabbar" label="Tabs" />
      {palette && <Palette onClose={() => setPalette(false)} />}
    </div>
  );
}
