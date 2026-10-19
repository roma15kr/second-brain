import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import { kyivTime } from "../briefs/BriefView";
import { ScopeTag } from "../shell/ScopeTag";

type Suggestion = {
  id: number;
  kind: string;
  payload: Record<string, unknown>;
  reason: string;
  scopes: string[];
  item_id: number | null;
  item_title: string | null;
  status: string;
  applied_ref: string | null;
  error: string | null;
  created_at: string;
};

const KIND: Record<string, string> = {
  reply_email: "Email reply",
  reply_tg: "Telegram reply",
  task: "ClickUp task",
  delegate: "Delegate",
  nudge: "Nudge",
  decline: "Decline",
};

const DONE: Record<string, string> = {
  approved: "Saving…",
  applying: "Saving…",
  applied: "Done",
  failed: "Failed",
};

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function Card({ s, onChanged }: { s: Suggestion; onChanged: () => void }) {
  const [body, setBody] = useState(str(s.payload.body));
  const [name, setName] = useState(str(s.payload.name));
  const [due, setDue] = useState(str(s.payload.due_date));
  const [error, setError] = useState<string | null>(null);
  const edited =
    s.kind === "reply_email" ? { body } : s.kind === "task" ? { name, due_date: due || null } : {};
  const approve = useMutation({
    mutationFn: () =>
      api(`/api/suggestions/${s.id}/approve`, { method: "POST", body: { payload: edited } }),
    onSuccess: onChanged,
    onError: (e) => setError(e.message),
  });
  const [sendAt, setSendAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (sendAt === null) return;
    const t = setInterval(() => {
      setNow(Date.now());
      if (Date.now() >= sendAt) {
        clearInterval(t);
        onChanged();
      }
    }, 250);
    return () => clearInterval(t);
  }, [sendAt, onChanged]);
  const send = useMutation({
    mutationFn: () =>
      api<{ send_after: string }>(`/api/suggestions/${s.id}/send`, {
        method: "POST",
        body: { payload: { body } },
      }),
    onSuccess: (r) => {
      setNow(Date.now());
      setSendAt(Date.parse(r.send_after));
    },
    onError: (e) => setError(e.message),
  });
  const undo = useMutation({
    mutationFn: () => api(`/api/suggestions/${s.id}/undo`, { method: "POST" }),
    onSuccess: () => setSendAt(null),
    onError: (e) => setError(e.message),
  });
  const discard = useMutation({
    mutationFn: () => api(`/api/suggestions/${s.id}/discard`, { method: "POST", body: {} }),
    onSuccess: onChanged,
    onError: (e) => setError(e.message),
  });
  return (
    <li>
      <div>
        <strong>{KIND[s.kind] ?? s.kind}</strong>{" "}
        {s.item_id && <Link to={`/c/${s.item_id}`}>{s.item_title || "(no subject)"}</Link>}{" "}
        {s.scopes.map((x) => (
          <ScopeTag key={x} scope={x} />
        ))}
      </div>
      {s.reason && <div className="muted">{s.reason}</div>}
      {s.kind === "reply_email" && (
        <textarea
          aria-label="Reply"
          className="btn wide"
          rows={6}
          value={body}
          placeholder="Write the reply…"
          onChange={(e) => setBody(e.target.value)}
        />
      )}
      {s.kind === "task" && (
        <div className="row">
          <input
            aria-label="Task name"
            className="btn"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <input
            aria-label="Due date"
            className="btn"
            type="date"
            value={due}
            onChange={(e) => setDue(e.target.value)}
          />
          {str(s.payload.assignee_name) && (
            <span className="muted">for {str(s.payload.assignee_name)}</span>
          )}
        </div>
      )}
      {sendAt !== null ? (
        <div className="row actions" role="status">
          <span>Sending in {Math.max(0, Math.ceil((sendAt - now) / 1000))} s…</span>
          <button className="btn" onClick={() => undo.mutate()}>
            Undo
          </button>
        </div>
      ) : (
        <div className="row actions">
          {s.kind === "reply_email" && (
            <button className="btn primary" disabled={send.isPending} onClick={() => send.mutate()}>
              Send
            </button>
          )}
          <button className="btn" disabled={approve.isPending} onClick={() => approve.mutate()}>
            {s.kind === "reply_email"
              ? "Save to Drafts"
              : s.kind === "task"
                ? "Create task"
                : "Approve"}
          </button>
          <button className="btn" onClick={() => discard.mutate()}>
            Discard
          </button>
        </div>
      )}
      {error && (
        <div role="alert" className="error">
          {error}
        </div>
      )}
    </li>
  );
}

function Recent({ s, onChanged }: { s: Suggestion; onChanged: () => void }) {
  const retry = useMutation({
    mutationFn: () => api(`/api/suggestions/${s.id}/approve`, { method: "POST", body: {} }),
    onSuccess: onChanged,
  });
  const sent = s.payload.action === "send";
  const what =
    s.kind === "reply_email" && s.status === "applied"
      ? sent
        ? "Sent"
        : "Saved to Drafts"
      : sent && s.status !== "failed"
        ? "Sending…"
        : (DONE[s.status] ?? s.status);
  return (
    <li>
      <span className={s.status === "failed" ? "state error" : "state ok"}>{what}</span>{" "}
      {KIND[s.kind] ?? s.kind} · {s.item_title || str(s.payload.name)}
      <span className="muted"> · {kyivTime.format(new Date(s.created_at))}</span>
      {s.error && <div className="error">{s.error}</div>}
      {s.status === "failed" && (
        <button className="btn" onClick={() => retry.mutate()}>
          Retry
        </button>
      )}
    </li>
  );
}

// Assistant: the approval queue (assistant-actions spec). Nothing leaves without a tap here.
export function Assistant() {
  const queryClient = useQueryClient();
  const pending = useQuery({
    queryKey: ["suggestions", "proposed"],
    queryFn: () => api<{ suggestions: Suggestion[] }>("/api/suggestions"),
  });
  const recent = useQuery({
    queryKey: ["suggestions", "recent"],
    queryFn: () => api<{ suggestions: Suggestion[] }>("/api/suggestions?status=recent"),
    refetchInterval: (q) =>
      q.state.data?.suggestions.some((s) => s.status === "approved" || s.status === "applying")
        ? 5_000
        : false,
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["suggestions"] });
  if (pending.isPending) return <p className="muted">Loading…</p>;
  if (pending.isError) return <p className="error">{pending.error.message}</p>;
  return (
    <>
      <section className="card group">
        <h3>Waiting for you</h3>
        <ul className="list">
          {pending.data.suggestions.map((s) => (
            <Card key={s.id} s={s} onChanged={refresh} />
          ))}
          {pending.data.suggestions.length === 0 && <li className="muted">Nothing to approve.</li>}
        </ul>
      </section>
      {recent.data && recent.data.suggestions.length > 0 && (
        <section className="card group">
          <h3>Recently approved</h3>
          <ul className="list">
            {recent.data.suggestions.map((s) => (
              <Recent key={s.id} s={s} onChanged={refresh} />
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
