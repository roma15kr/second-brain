import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api } from "../api/client";

type Loop = {
  id: number;
  kind: "needs_reply" | "i_owe" | "owed_to_me" | "manual";
  title: string;
  counterpart: string;
  scopes: string[];
  status: string;
  due_date: string | null;
  overdue: boolean;
  due_today: boolean;
  age_days: number | null;
  link: string | null;
};
type LoopsData = { loops: Loop[]; open_counts: Partial<Record<Loop["kind"], number>> };

const DIRECTIONS: [string, Loop["kind"] | null][] = [
  ["All", null],
  ["I owe", "i_owe"],
  ["Owed to me", "owed_to_me"],
  ["Needs reply", "needs_reply"],
  ["Mine", "manual"],
];
const STATUSES = ["open", "snoozed", "done", "dismissed"] as const;
const SCOPES = ["personal", "digisoft", "quokka", "rdim"];
const WHO: Record<Loop["kind"], string> = {
  needs_reply: "Reply to",
  i_owe: "You → ",
  owed_to_me: "→ You from",
  manual: "",
};

function isoDay(daysAhead: number): string {
  const d = new Date();
  d.setDate(d.getDate() + daysAhead);
  return d.toLocaleDateString("en-CA"); // YYYY-MM-DD in local (Kyiv) time
}

function nextMonday(): string {
  const d = new Date();
  return isoDay((8 - d.getDay()) % 7 || 7);
}

// Loops with direction, counterpart, due date or age, scope and source (open-loops spec).
export function Loops() {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("open");
  const [kind, setKind] = useState<Loop["kind"] | null>(null);
  const [scope, setScope] = useState("");
  const [person, setPerson] = useState("");
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const params = new URLSearchParams({ status });
  if (kind) params.set("kind", kind);
  if (scope) params.set("scope", scope);
  if (person.trim()) params.set("person", person.trim());
  const loops = useQuery({
    queryKey: ["loops", params.toString()],
    queryFn: () => api<LoopsData>(`/api/loops?${params}`),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["loops"] });
  const act = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, string> }) =>
      api(`/api/loops/${id}/act`, { method: "POST", body }),
    onSuccess: refresh,
    onError: (e) => setError(e.message),
  });
  const add = useMutation({
    mutationFn: () => api("/api/loops", { method: "POST", body: { title } }),
    onSuccess: () => {
      setTitle("");
      return refresh();
    },
    onError: (e) => setError(e.message),
  });
  const counts = loops.data?.open_counts ?? {};

  return (
    <>
      <div className="row filters">
        {DIRECTIONS.map(([label, value]) => (
          <button
            key={label}
            className={`btn ${kind === value ? "primary" : ""}`}
            onClick={() => setKind(value)}
          >
            {label}
            {value && counts[value] ? ` ${counts[value]}` : ""}
          </button>
        ))}
        <select
          aria-label="Status"
          className="btn"
          value={status}
          onChange={(e) => setStatus(e.target.value as (typeof STATUSES)[number])}
        >
          {STATUSES.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select
          aria-label="Scope"
          className="btn"
          value={scope}
          onChange={(e) => setScope(e.target.value)}
        >
          <option value="">All scopes</option>
          {SCOPES.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <input
          aria-label="Person"
          className="btn"
          placeholder="Person…"
          value={person}
          onChange={(e) => setPerson(e.target.value)}
        />
      </div>
      <form
        className="row add-loop"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          if (title.trim()) add.mutate();
        }}
      >
        <input
          aria-label="New loop"
          className="btn"
          placeholder="Add a loop, e.g. Renew the domain"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <button className="btn" type="submit" disabled={!title.trim()}>
          Add
        </button>
      </form>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {loops.isPending && <p className="muted">Loading…</p>}
      {loops.isError && <p className="error">{loops.error.message}</p>}
      <ul className="list card">
        {loops.data?.loops.map((lp) => (
          <li key={lp.id} className={lp.overdue ? "overdue" : ""}>
            <div>
              {lp.link ? (
                <a href={lp.link} target="_blank" rel="noreferrer">
                  {lp.title}
                </a>
              ) : (
                <strong>{lp.title}</strong>
              )}{" "}
              {lp.scopes.map((s) => (
                <span key={s} className={`tag ${s}`}>
                  {s}
                </span>
              ))}
            </div>
            <div className="muted">
              {WHO[lp.kind]} {lp.counterpart}
              {lp.overdue && <strong className="error"> · overdue since {lp.due_date}</strong>}
              {!lp.overdue && lp.due_date && ` · due ${lp.due_date}`}
              {!lp.due_date && lp.age_days !== null && ` · ${lp.age_days} days open`}
            </div>
            {status === "open" && (
              <div className="row actions">
                <button
                  className="btn"
                  onClick={() => act.mutate({ id: lp.id, body: { action: "done" } })}
                >
                  Done
                </button>
                <button
                  className="btn"
                  onClick={() =>
                    act.mutate({ id: lp.id, body: { action: "snooze", until: isoDay(1) } })
                  }
                >
                  Snooze to tomorrow
                </button>
                <button
                  className="btn"
                  onClick={() =>
                    act.mutate({ id: lp.id, body: { action: "snooze", until: nextMonday() } })
                  }
                >
                  Snooze to Monday
                </button>
                <button
                  className="btn"
                  onClick={() => act.mutate({ id: lp.id, body: { action: "dismiss" } })}
                  title="Not a real promise — never detected again from this message"
                >
                  Dismiss
                </button>
                <input
                  type="date"
                  aria-label="Due date"
                  className="btn"
                  value={lp.due_date ?? ""}
                  onChange={(e) =>
                    e.target.value &&
                    act.mutate({ id: lp.id, body: { action: "due", due: e.target.value } })
                  }
                />
              </div>
            )}
            {status !== "open" && (
              <div className="row actions">
                <button
                  className="btn"
                  onClick={() => act.mutate({ id: lp.id, body: { action: "reopen" } })}
                >
                  Reopen
                </button>
              </div>
            )}
          </li>
        ))}
        {loops.isSuccess && loops.data.loops.length === 0 && (
          <li className="muted">Nothing here.</li>
        )}
      </ul>
    </>
  );
}
