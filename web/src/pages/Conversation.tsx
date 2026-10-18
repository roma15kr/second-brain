import { useProjects } from "../shell/useProjects";
import { ScopeTag } from "../shell/ScopeTag";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { api } from "../api/client";
import { kyivTime } from "../briefs/BriefView";

type Message = {
  key: string;
  author: string;
  sent_at: string;
  text: string;
  locator: string | null;
};
type Item = {
  item_id: number;
  kind: string;
  title: string | null;
  scopes: string[];
  participants: string[];
  summary: string | null;
  question: string | null;
  outcome: string | null;
  locator: string | null;
  total: number;
  offset: number;
  next_offset: number | null;
  messages: Message[];
  loops: { id: number; kind: string; title: string; status: string; due_date: string | null }[];
};

const PAGE = 50;

// One conversation: summary, outcome, people, scope, loops and messages (web-dashboard spec).
export function Conversation() {
  const SCOPES = useProjects();
  const { id } = useParams();
  const [params] = useSearchParams();
  const matched = params.get("m");
  const [offset, setOffset] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const url =
    offset === null && matched
      ? `/api/items/${id}?around=${encodeURIComponent(matched)}`
      : `/api/items/${id}?offset=${offset ?? 0}`;
  const item = useQuery({ queryKey: ["item", id, url], queryFn: () => api<Item>(url) });
  const scope = useMutation({
    mutationFn: (body: { scope: string; apply_to: string }) =>
      api<{ result: string }>(`/api/items/${id}/scope`, { method: "POST", body }),
    onSuccess: (r) => {
      setMessage(r.result);
      return queryClient.invalidateQueries({ queryKey: ["item", id] });
    },
    onError: (e) => setMessage(e.message),
  });
  const highlighted = useRef<HTMLLIElement>(null);
  useEffect(() => highlighted.current?.scrollIntoView?.({ block: "center" }), [item.data]);

  if (item.isPending) return <p className="muted">Loading…</p>;
  if (item.isError) return <p className="error">{item.error.message}</p>;
  const it = item.data;
  const applyTo = it.kind === "tg_conversation" ? "chat" : "sender";
  return (
    <>
      <article className="card">
        <h2>{it.title || "(no subject)"}</h2>
        <div className="row">
          {it.scopes.map((s) => (
            <ScopeTag key={s} scope={s} />
          ))}
          <select
            aria-label="Change scope"
            className="btn"
            value=""
            onChange={(e) =>
              e.target.value && scope.mutate({ scope: e.target.value, apply_to: "item" })
            }
          >
            <option value="">Change scope…</option>
            {SCOPES.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <select
            aria-label={`Scope for the whole ${applyTo}`}
            className="btn"
            value=""
            onChange={(e) =>
              e.target.value && scope.mutate({ scope: e.target.value, apply_to: applyTo })
            }
          >
            <option value="">…for the whole {applyTo}</option>
            {SCOPES.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          {it.locator && (
            <a className="btn" href={it.locator} target="_blank" rel="noreferrer">
              Open original ↗
            </a>
          )}
        </div>
        {message && (
          <p role="status" className="muted">
            {message}
          </p>
        )}
        {it.question && <p className="muted">Q: {it.question}</p>}
        {it.summary && <p>{it.summary}</p>}
        {it.outcome && (
          <p>
            <strong>Outcome:</strong> {it.outcome}
          </p>
        )}
        {it.participants.length > 0 && (
          <p className="muted">People: {it.participants.join(", ")}</p>
        )}
        {it.loops.length > 0 && (
          <div>
            <strong>Loops:</strong>{" "}
            {it.loops.map((lp) => (
              <Link key={lp.id} to="/loops" className="tag">
                ↺ {lp.title} ({lp.status})
              </Link>
            ))}
          </div>
        )}
      </article>
      <ul className="list card messages">
        {it.messages.map((m) => {
          const isMatch = !!matched && m.locator === matched;
          return (
            <li
              key={m.key}
              ref={isMatch ? highlighted : undefined}
              className={isMatch ? "matched" : ""}
            >
              <div className="muted">
                <strong>{m.author}</strong> · {kyivTime.format(new Date(m.sent_at))}
                {m.locator?.startsWith("https://") && (
                  <>
                    {" "}
                    ·{" "}
                    <a href={m.locator} target="_blank" rel="noreferrer">
                      open ↗
                    </a>
                  </>
                )}
              </div>
              <div className="body">{m.text}</div>
            </li>
          );
        })}
      </ul>
      <div className="row">
        {it.offset > 0 && (
          <button className="btn" onClick={() => setOffset(Math.max(0, it.offset - PAGE))}>
            ← Earlier
          </button>
        )}
        <span className="muted">
          {it.offset + 1}–{it.offset + it.messages.length} of {it.total}
        </span>
        {it.next_offset !== null && (
          <button className="btn" onClick={() => setOffset(it.next_offset)}>
            Later →
          </button>
        )}
      </div>
    </>
  );
}
