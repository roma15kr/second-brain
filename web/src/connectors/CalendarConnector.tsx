import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import { kyivTime } from "../briefs/BriefView";
import { useProjects } from "../shell/useProjects";

type Calendar = {
  id: number;
  account_id: number;
  name: string;
  sync: boolean;
  scopes: string[];
  remind_minutes: number;
  events: number;
  synced_at: string | null;
  error: string | null;
};
type Overview = {
  accounts: { id: number; label: string; type: "ical" | "caldav"; state: string }[];
  calendars: Calendar[];
};

function Row({ c, onChanged }: { c: Calendar; onChanged: () => void }) {
  const projects = useProjects();
  const [error, setError] = useState<string | null>(null);
  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/api/connectors/calendars/${c.id}`, { method: "POST", body }),
    onSuccess: onChanged,
    onError: (e) => setError(e.message),
  });
  return (
    <tr>
      <td>{c.name}</td>
      <td>
        <select
          aria-label={`Mark ${c.name}`}
          className="btn"
          value={c.sync ? (c.scopes[0] ?? "") : ""}
          onChange={(e) =>
            update.mutate(
              e.target.value ? { sync: true, scopes: [e.target.value] } : { sync: false },
            )
          }
        >
          <option value="">Ignore</option>
          {projects.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </td>
      <td>
        <select
          aria-label={`Reminder for ${c.name}`}
          className="btn"
          value={c.remind_minutes}
          onChange={(e) => update.mutate({ remind_minutes: Number(e.target.value) })}
        >
          {[0, 5, 10, 15, 30, 60].map((m) => (
            <option key={m} value={m}>
              {m ? `${m} min before` : "no reminder"}
            </option>
          ))}
        </select>
      </td>
      <td className="muted">
        {c.sync &&
          (c.synced_at
            ? `${c.events} events · ${kyivTime.format(new Date(c.synced_at))}`
            : "syncing…")}
        {(c.error || error) && <div className="error">{c.error ?? error}</div>}
      </td>
    </tr>
  );
}

// Connectors › Calendars: Google by secret address, Apple iCloud / CalDAV; read-only.
export function CalendarConnector() {
  const queryClient = useQueryClient();
  const data = useQuery({
    queryKey: ["calendars"],
    queryFn: () => api<Overview>("/api/connectors/calendars"),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["calendars"] });
  const [url, setUrl] = useState("");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const ical = useMutation({
    mutationFn: () => api("/api/connectors/calendars/ical", { method: "POST", body: { url } }),
    onSuccess: () => {
      setUrl("");
      setMessage("Connected. Mark the calendar below to start syncing.");
      refresh();
    },
    onError: (e) => setMessage(e.message),
  });
  const caldav = useMutation({
    mutationFn: () =>
      api("/api/connectors/calendars/caldav", {
        method: "POST",
        body: { username: user, password },
      }),
    onSuccess: () => {
      setPassword("");
      setMessage("Connected. Mark the calendars you want below.");
      refresh();
    },
    onError: (e) => setMessage(e.message),
  });
  const submit = (fn: () => void) => (e: FormEvent) => {
    e.preventDefault();
    fn();
  };
  return (
    <>
      <p>
        <Link to="/connectors">← Connectors</Link>
      </p>
      <section className="card group">
        <h3>Calendars</h3>
        <p className="muted">
          Read-only: the second brain never changes your calendars. Marked calendars sync every 10
          minutes; reminders arrive before meetings you have not declined.
        </p>
        <table className="table">
          <tbody>
            {data.data?.calendars.map((c) => (
              <Row key={c.id} c={c} onChanged={refresh} />
            ))}
          </tbody>
        </table>
        {data.data && data.data.calendars.length === 0 && (
          <p className="muted">No calendars connected yet.</p>
        )}
      </section>
      <section className="card group">
        <h3>Google calendar</h3>
        <p className="muted">
          Google Calendar → Settings → your calendar → “Secret address in iCal format”.
        </p>
        <form className="row" onSubmit={submit(() => ical.mutate())}>
          <input
            aria-label="Secret iCal address"
            className="btn wide-input"
            placeholder="https://calendar.google.com/calendar/ical/…/private-…/basic.ics"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <button className="btn primary" disabled={!url || ical.isPending}>
            Connect
          </button>
        </form>
      </section>
      <section className="card group">
        <h3>Apple iCloud (or another CalDAV server)</h3>
        <p className="muted">
          Use an app-specific password: appleid.apple.com → Sign-In and Security → App-Specific
          Passwords.
        </p>
        <form className="row" onSubmit={submit(() => caldav.mutate())}>
          <input
            aria-label="Apple Account email"
            className="btn"
            placeholder="you@icloud.com"
            value={user}
            onChange={(e) => setUser(e.target.value)}
          />
          <input
            aria-label="App-specific password"
            className="btn"
            type="password"
            placeholder="xxxx-xxxx-xxxx-xxxx"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button className="btn primary" disabled={!user || !password || caldav.isPending}>
            Connect
          </button>
        </form>
      </section>
      {message && <p role="status">{message}</p>}
    </>
  );
}
