import { ScopeTag } from "../shell/ScopeTag";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { kyivTime } from "../briefs/BriefView";

type InboxItem = {
  item_id: number;
  title: string;
  summary: string;
  action: string;
  reason: string;
  sender: string | null;
  scopes: string[];
  link: string | null;
  last_activity_at: string;
};
type InboxData = {
  pass: { id: number; headline: string; created_at: string } | null;
  groups: Record<"needs_reply" | "important" | "fyi" | "noise", InboxItem[]>;
};

const GROUPS: [keyof InboxData["groups"], string][] = [
  ["needs_reply", "Needs reply"],
  ["important", "Important"],
  ["fyi", "FYI"],
  ["noise", "Noise"],
];
const SCOPES = ["personal", "digisoft", "quokka", "rdim"];

function at(daysAhead: number, weekdayMonday = false): string {
  const d = new Date();
  if (weekdayMonday) d.setDate(d.getDate() + ((8 - d.getDay()) % 7 || 7));
  else d.setDate(d.getDate() + daysAhead);
  d.setHours(9, 0, 0, 0);
  return d.toISOString();
}

function Row({ item, onChanged }: { item: InboxItem; onChanged: () => void }) {
  const [message, setMessage] = useState<string | null>(null);
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) =>
      api<{ result?: string }>(path, { method: "POST", body }),
    onSuccess: (r) => {
      if (r?.result) setMessage(r.result);
      onChanged();
    },
    onError: (e) => setMessage(e.message),
  });
  const post = (path: string, body?: unknown) => act.mutate({ path, body });
  const base = `/api/inbox/${item.item_id}`;
  return (
    <li>
      <div>
        {item.link ? (
          <a href={item.link} target="_blank" rel="noreferrer">
            {item.title}
          </a>
        ) : (
          <strong>{item.title}</strong>
        )}{" "}
        {item.scopes.map((s) => (
          <ScopeTag key={s} scope={s} />
        ))}
        <span className="muted">
          {" "}
          · {item.sender} · {kyivTime.format(new Date(item.last_activity_at))}
        </span>
      </div>
      {item.action && <div>→ {item.action}</div>}
      {item.summary && <div className="muted">{item.summary}</div>}
      <div className="row actions">
        {item.link && (
          <a className="btn" href={item.link} target="_blank" rel="noreferrer">
            Open in Gmail
          </a>
        )}
        <button className="btn" onClick={() => post(`${base}/done`)}>
          Done
        </button>
        <button className="btn" onClick={() => post(`${base}/snooze`, { until: at(1) })}>
          Snooze to tomorrow
        </button>
        <button className="btn" onClick={() => post(`${base}/snooze`, { until: at(0, true) })}>
          Snooze to Monday
        </button>
        <select
          aria-label="Change scope"
          className="btn"
          value=""
          onChange={(e) => e.target.value && post(`${base}/scope`, { scope: e.target.value })}
        >
          <option value="">Scope…</option>
          {SCOPES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        {item.sender && (
          <>
            <button
              className="btn"
              onClick={() => post("/api/senders/pref", { address: item.sender, pref: "noise" })}
            >
              Sender is noise
            </button>
            <button
              className="btn"
              onClick={() => post("/api/senders/pref", { address: item.sender, pref: "important" })}
            >
              Sender is important
            </button>
          </>
        )}
      </div>
      {message && (
        <div role="status" className="muted">
          {message}
        </div>
      )}
    </li>
  );
}

// The latest mail revision pass, grouped, with one-tap actions (web-dashboard spec: Inbox).
export function Inbox() {
  const queryClient = useQueryClient();
  const inbox = useQuery({ queryKey: ["inbox"], queryFn: () => api<InboxData>("/api/inbox") });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["inbox"] });
  if (inbox.isPending) return <p className="muted">Loading…</p>;
  if (inbox.isError) return <p className="error">{inbox.error.message}</p>;
  const { pass, groups } = inbox.data;
  if (!pass) return <p className="muted">No mail revision yet — the first pass runs at 11:00.</p>;
  return (
    <>
      <p className="muted">
        {pass.headline} · {kyivTime.format(new Date(pass.created_at))}
      </p>
      {GROUPS.map(([key, title]) => {
        const items = groups[key];
        if (!items.length) return null;
        const list = (
          <ul className="list">
            {items.map((item) => (
              <Row key={item.item_id} item={item} onChanged={refresh} />
            ))}
          </ul>
        );
        return (
          <section key={key} className="card group">
            {key === "noise" ? (
              <details>
                <summary>
                  {title} ({items.length})
                </summary>
                {list}
              </details>
            ) : (
              <>
                <h3>
                  {title} ({items.length})
                </h3>
                {list}
              </>
            )}
          </section>
        );
      })}
    </>
  );
}
