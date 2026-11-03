import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "../api/client";
import { ApprovalQueue, type Suggestion } from "./Assistant";

type Group = { key: string; title: string; items: Suggestion[] };

const str = (v: unknown) => (typeof v === "string" ? v : "");
const firstLine = (s: string) => s.split("\n").find((l) => l.trim()) ?? "";

// One line per proposal: what will be created, and the detail that matters.
export function describe(s: Suggestion): { title: string; detail: string; full: string } {
  const p = s.payload;
  switch (s.kind) {
    case "task":
    case "delegate": {
      const who = str(p.assignee_name) || "unassigned";
      const due = str(p.due_date) ? ` · due ${str(p.due_date)}` : "";
      return { title: `Task: ${str(p.name)}`, detail: `${who}${due}`, full: str(p.description) };
    }
    case "clickup_comment":
      return {
        title: `Comment on “${str(p.task_title) || s.item_title || "task"}”`,
        detail: firstLine(str(p.body)),
        full: str(p.body),
      };
    default:
      return {
        title: `${s.kind === "reply_tg" ? "Telegram" : "Message"}: ${s.item_title ?? ""}`.trim(),
        detail: firstLine(str(p.body)),
        full: str(p.body),
      };
  }
}

function groups(list: Suggestion[]): Group[] {
  const out = new Map<string, Group>();
  for (const s of list) {
    if (s.payload.ai_pending) continue; // still being written
    const source = s.payload.source_item_id ?? s.item_id ?? `s${s.id}`;
    const key = String(source);
    if (!out.has(key))
      out.set(key, { key, title: s.reason || s.item_title || "Proposal", items: [] });
    out.get(key)!.items.push(s);
  }
  return [...out.values()];
}

function GroupCard({ group, onDone }: { group: Group; onDone: () => void }) {
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [message, setMessage] = useState<string | null>(null);
  const send = useMutation({
    mutationFn: (create: number[]) =>
      api<{ created: number[]; failed: Record<string, string> }>("/api/suggestions/moderate", {
        method: "POST",
        body: { create, discard: group.items.map((s) => s.id) },
      }),
    onSuccess: (r) => {
      const failed = Object.values(r.failed);
      setMessage(failed.length ? `Not created: ${failed.join("; ")}` : null);
      onDone();
    },
    onError: (e) => setMessage(e.message),
  });
  const toggle = (id: number) =>
    setPicked((old) => {
      const next = new Set(old);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  return (
    <section className="card">
      <h3 className="card-title">{group.title}</h3>
      <ul className="list compact">
        {group.items.map((s) => {
          const d = describe(s);
          return (
            <li key={s.id} className="pick">
              <label>
                <input
                  type="checkbox"
                  checked={picked.has(s.id)}
                  onChange={() => toggle(s.id)}
                  aria-label={d.title}
                />
                <span>
                  <span className="line">{d.title}</span>
                  {d.detail && <span className="sub">{d.detail}</span>}
                </span>
              </label>
              {d.full && d.full !== d.detail && (
                <details>
                  <summary>More</summary>
                  <p className="doc-text">{d.full}</p>
                </details>
              )}
            </li>
          );
        })}
      </ul>
      <div className="actions">
        <button
          className="btn primary"
          disabled={send.isPending || picked.size === 0}
          onClick={() => send.mutate([...picked])}
        >
          {picked.size ? `Create selected (${picked.size})` : "Create selected"}
        </button>
        <button className="btn" disabled={send.isPending} onClick={() => send.mutate([])}>
          Discard all
        </button>
        {message && <span className="error small">{message}</span>}
      </div>
    </section>
  );
}

// Moderate (assistant-moderation-v1): everything the assistant prepared, ticked in one place.
export function Moderate() {
  const [params, setParams] = useSearchParams();
  const editing = params.get("view") === "edit";
  const toggle = (
    <div className="segmented" role="tablist" aria-label="View">
      <button
        role="tab"
        aria-selected={!editing}
        className={!editing ? "on" : ""}
        onClick={() => setParams({})}
      >
        Quick
      </button>
      <button
        role="tab"
        aria-selected={editing}
        className={editing ? "on" : ""}
        onClick={() => setParams({ view: "edit" })}
      >
        Edit before creating
      </button>
    </div>
  );
  if (editing) {
    return (
      <>
        {toggle}
        <ApprovalQueue />
      </>
    );
  }
  return (
    <>
      {toggle}
      <QuickModerate />
    </>
  );
}

function QuickModerate() {
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: ["suggestions", "proposed"],
    queryFn: () => api<{ suggestions: Suggestion[] }>("/api/suggestions"),
  });
  const done = () => {
    void queryClient.invalidateQueries({ queryKey: ["suggestions"] });
    void queryClient.invalidateQueries({ queryKey: ["today"] });
  };
  if (list.isPending) return <p className="muted">Loading…</p>;
  if (list.isError) return <p className="error">{list.error.message}</p>;
  const all = groups(list.data.suggestions);
  return (
    <>
      <p className="muted">
        Tick what to create; the rest of a group is discarded. Mail replies wait in Gmail Drafts.
      </p>
      {all.length ? (
        all.map((g) => <GroupCard key={g.key} group={g} onDone={done} />)
      ) : (
        <div className="empty card">
          <strong>Nothing to moderate</strong>
          <span className="muted">
            New proposals appear after meetings and messages. <Link to="/assistant">Assistant</Link>
          </span>
        </div>
      )}
    </>
  );
}
