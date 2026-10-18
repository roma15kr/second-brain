import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router";
import { APPS } from "./apps";
import { Bell } from "./Bell";
import { Palette } from "./Palette";
import { useOnline } from "./useOnline";

const clock = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Kyiv",
  weekday: "short",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

function title(pathname: string): string {
  const app = [...APPS]
    .reverse()
    .find((a) => (a.path === "/" ? pathname === "/" : pathname.startsWith(a.path)));
  return app?.label ?? "Second brain";
}

// OS shell: dock (bottom bar on phones), ⌘K palette, notification center (web-dashboard spec).
export function Shell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const online = useOnline();
  const [palette, setPalette] = useState(false);
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => !p);
      }
    };
    window.addEventListener("keydown", onKey);
    const t = setInterval(() => setNow(new Date()), 30_000);
    return () => {
      window.removeEventListener("keydown", onKey);
      clearInterval(t);
    };
  }, []);
  return (
    <div className="shell">
      <nav className="dock" aria-label="Apps">
        {APPS.map((a) => (
          <NavLink
            key={a.path}
            to={a.path}
            end={a.path === "/"}
            className={a.phone ? "" : "desktop-only"}
          >
            <span className="i" aria-hidden>
              {a.icon}
            </span>
            {a.label}
          </NavLink>
        ))}
        <button className="more phone-only" onClick={() => setPalette(true)}>
          <span className="i" aria-hidden>
            ⋯
          </span>
          More
        </button>
      </nav>
      <div className="workspace">
        <header className="top">
          <strong>{title(pathname)}</strong>
          <button className="cmd" onClick={() => setPalette(true)}>
            <span className="desktop-only">⌘K </span>Search or jump to…
          </button>
          <Bell />
          <span className="muted desktop-only">{clock.format(now)}</span>
        </header>
        <main className="page">
          {!online && (
            <p className="note banner" role="status">
              Offline — showing the last loaded pages; actions are disabled until you are back
              online.
            </p>
          )}
          <fieldset className="plain" disabled={!online}>
            {children}
          </fieldset>
        </main>
      </div>
      {palette && <Palette onClose={() => setPalette(false)} />}
    </div>
  );
}
