import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";

type Row = { id: number; title: string; headline: string; created_at: string; opened: boolean };

// Notification center: routine outputs not opened yet (web-dashboard spec: OS shell).
export function Bell() {
  const [open, setOpen] = useState(false);
  const briefs = useQuery({
    queryKey: ["bell"],
    queryFn: () => api<{ briefs: Row[] }>("/api/briefs"),
    refetchInterval: 60_000,
  });
  const unread = (briefs.data?.briefs ?? []).filter((b) => !b.opened).slice(0, 10);
  return (
    <div className="bell">
      <button
        className="btn"
        aria-label={`Notifications (${unread.length} unread)`}
        onClick={() => setOpen(!open)}
      >
        🔔 {unread.length > 0 && <span className="badge">{unread.length}</span>}
      </button>
      {open && (
        <div className="bell-panel card" role="menu">
          {unread.length === 0 && <p className="muted">All caught up.</p>}
          <ul className="list">
            {unread.map((b) => (
              <li key={b.id}>
                <Link to={`/briefs/${b.id}`} onClick={() => setOpen(false)}>
                  {b.headline}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
