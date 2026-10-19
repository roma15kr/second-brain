import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { api } from "../api/client";
import { Card, type Suggestion } from "../pages/Assistant";
import { useProjects } from "../shell/useProjects";
import { useState } from "react";
import { AskBox } from "./Ask";

type Created = {
  index: number;
  type: "suggestion" | "loop";
  id: number;
  kind?: string;
  suggestion?: Suggestion | null;
  status?: string;
  action?: "add" | "done" | "dismiss" | "snooze";
  title?: string;
  due?: string | null;
  undone?: boolean;
};
type SearchBlock = {
  query: string;
  kind: string | null;
  scopes: string[];
  person: string | null;
  date_from: string | null;
  date_to: string | null;
  results: { item_id: number; title: string | null; kind: string; date: string | null }[];
};

const LOOP_WORDS = { add: "Added", done: "Closed", dismiss: "Dismissed", snooze: "Snoozed" };

function searchLink(s: SearchBlock): string {
  const p = new URLSearchParams({ q: s.query });
  if (s.kind === "mail" || s.kind === "chats") p.set("kind", s.kind);
  s.scopes.forEach((x) => p.append("scope", x));
  if (s.person) p.set("person", s.person);
  if (s.date_from) p.set("from", s.date_from);
  if (s.date_to) p.set("to", s.date_to);
  return `/search?${p}`;
}

function RunAnyway({ rid, onChanged }: { rid: number; onChanged: () => void }) {
  const run = useMutation({
    mutationFn: () => api(`/api/assistant/requests/${rid}/run-anyway`, { method: "POST" }),
    onSuccess: onChanged,
  });
  return (
    <button className="btn" disabled={run.isPending || run.isSuccess} onClick={() => run.mutate()}>
      Run anyway
    </button>
  );
}

function LoopChange({ rid, c, onChanged }: { rid: number; c: Created; onChanged: () => void }) {
  const undo = useMutation({
    mutationFn: () => api(`/api/assistant/requests/${rid}/undo/${c.index}`, { method: "POST" }),
    onSuccess: onChanged,
  });
  return (
    <li>
      {c.action ? LOOP_WORDS[c.action] : ""} “{c.title}”{c.due && ` · due ${c.due}`}{" "}
      {c.undone ? (
        <span className="muted">· undone</span>
      ) : (
        <button className="btn" onClick={() => undo.mutate()}>
          Undo
        </button>
      )}
    </li>
  );
}

type Request = {
  id: number;
  text: string;
  status: "running" | "done" | "failed";
  steps: { tool: string; summary: string }[];
  answer: string | null;
  refs: { ref: string; item_id: number; title: string | null }[];
  error: string | null;
  cost_usd: number;
  created: Created[];
  search: SearchBlock | null;
  report: {
    title: string;
    sections: {
      heading: string;
      body: string;
      refs: { ref: string; item_id: number; title: string | null }[];
    }[];
  } | null;
  needs_budget: boolean;
  saved_doc_id: number | null;
};
type ThreadData = { id: number; title: string; pinned: boolean; requests: Request[] };

function Report({ r, onChanged }: { r: Request; onChanged: () => void }) {
  const projects = useProjects();
  const [scope, setScope] = useState(projects[0] ?? "personal");
  const save = useMutation({
    mutationFn: () =>
      api(`/api/assistant/requests/${r.id}/report/save`, { method: "POST", body: { scope } }),
    onSuccess: onChanged,
  });
  if (!r.report) return null;
  return (
    <article className="report">
      <h3>{r.report.title}</h3>
      {r.report.sections.map((s, i) => (
        <section key={i}>
          <h4>{s.heading}</h4>
          <div className="answer">{s.body}</div>
          <div className="row">
            {s.refs.map((ref) => (
              <Link key={ref.ref} className="tag" to={`/c/${ref.item_id}`}>
                {ref.title || ref.ref}
              </Link>
            ))}
          </div>
        </section>
      ))}
      {r.saved_doc_id ? (
        <Link to={`/library/${r.saved_doc_id}`}>Saved to the Library</Link>
      ) : (
        <div className="row">
          <select
            aria-label="Project for the note"
            className="btn"
            value={scope}
            onChange={(e) => setScope(e.target.value)}
          >
            {projects.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <button className="btn" onClick={() => save.mutate()}>
            Save to Library
          </button>
        </div>
      )}
    </article>
  );
}

function Turn({ r, onChanged }: { r: Request; onChanged: () => void }) {
  return (
    <li className="turn">
      <div className="question">{r.text}</div>
      {r.steps.length > 0 && (
        <ul className="steps muted">
          {r.steps.map((s, i) => (
            <li key={i}>{s.summary}</li>
          ))}
        </ul>
      )}
      {r.status === "running" && <div className="muted">Working…</div>}
      {r.status === "failed" && <div className="error">{r.error}</div>}
      {r.answer && <div className="answer">{r.answer}</div>}
      {r.needs_budget && <RunAnyway rid={r.id} onChanged={onChanged} />}
      <Report r={r} onChanged={onChanged} />
      {r.search && r.search.results.length > 0 && (
        <div className="search-block">
          <div className="row">
            <span className="tag">“{r.search.query}”</span>
            {r.search.kind && <span className="tag">{r.search.kind}</span>}
            {r.search.scopes.map((x) => (
              <span key={x} className="tag">
                {x}
              </span>
            ))}
            {r.search.person && <span className="tag">person: {r.search.person}</span>}
            {r.search.date_from && <span className="tag">from {r.search.date_from}</span>}
            {r.search.date_to && <span className="tag">to {r.search.date_to}</span>}
            <Link to={searchLink(r.search)}>Open in Search (change filters)</Link>
          </div>
          <ul className="list">
            {r.search.results.map((h) => (
              <li key={h.item_id}>
                <Link to={`/c/${h.item_id}`}>{h.title || "(no subject)"}</Link>
              </li>
            ))}
          </ul>
        </div>
      )}
      {r.created.length > 0 && (
        <ul className="list">
          {r.created.map((c) =>
            c.type === "loop" ? (
              <LoopChange key={c.index} rid={r.id} c={c} onChanged={onChanged} />
            ) : c.suggestion ? (
              c.suggestion.status === "proposed" ? (
                <Card key={c.index} s={c.suggestion} onChanged={onChanged} />
              ) : (
                <li key={c.index} className="muted">
                  Draft {c.suggestion.status}
                </li>
              )
            ) : (
              <li key={c.index} className="muted">
                Draft {c.status}
              </li>
            ),
          )}
        </ul>
      )}
      {r.refs.length > 0 && (
        <div className="row">
          {r.refs.map((ref) => (
            <Link key={ref.ref} className="tag" to={`/c/${ref.item_id}`}>
              {ref.title || ref.ref}
            </Link>
          ))}
        </div>
      )}
      {r.status === "done" && <div className="muted small">${r.cost_usd.toFixed(3)}</div>}
    </li>
  );
}

function PinButton({
  id,
  pinned,
  onChanged,
}: {
  id: number;
  pinned: boolean;
  onChanged: () => void;
}) {
  const pin = useMutation({
    mutationFn: () =>
      api(`/api/assistant/threads/${id}/pin`, { method: "POST", body: { pinned: !pinned } }),
    onSuccess: onChanged,
  });
  return (
    <button className="btn" onClick={() => pin.mutate()} title="Pinned threads are kept">
      {pinned ? "Unpin" : "Pin (keep)"}
    </button>
  );
}

// One request thread: questions, the steps taken, answers with sources, and follow-ups.
export function Thread() {
  const { id } = useParams();
  const queryClient = useQueryClient();
  const key = ["assistant-thread", id];
  const thread = useQuery({
    queryKey: key,
    queryFn: () => api<ThreadData>(`/api/assistant/threads/${id}`),
    refetchInterval: (q) =>
      q.state.data?.requests.some((r) => r.status === "running") ? 1_500 : false,
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: key });
  if (thread.isPending) return <p className="muted">Loading…</p>;
  if (thread.isError) return <p className="error">{thread.error.message}</p>;
  return (
    <section className="card">
      <div className="row">
        <Link to="/assistant">← Assistant</Link>
        <PinButton id={thread.data.id} pinned={thread.data.pinned} onChanged={refresh} />
      </div>
      <ul className="list thread">
        {thread.data.requests.map((r) => (
          <Turn
            key={r.id}
            r={r}
            onChanged={() => void queryClient.invalidateQueries({ queryKey: key })}
          />
        ))}
      </ul>
      <AskBox
        threadId={thread.data.id}
        placeholder="Follow up…"
        onAsked={() => void queryClient.invalidateQueries({ queryKey: key })}
      />
    </section>
  );
}
