import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "../api/client";
import { transcript } from "../assistant/Ask";
import { Recorder } from "../assistant/Recorder";
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

const isTask = (s: Suggestion) => s.kind === "task" || s.kind === "delegate";

// Voice into a text field: the dictation's transcript is appended.
function VoiceInto({ onText }: { onText: (t: string) => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <>
      <Recorder
        compact
        onUploaded={(id) => {
          setBusy(true);
          void transcript(id)
            .then(onText)
            .finally(() => setBusy(false));
        }}
      />
      {busy && <span className="muted small">Transcribing…</span>}
    </>
  );
}

// Per proposal: read it in full, ask the AI to change it, or edit it yourself (typed or spoken).
function Change({ s, full, onDone }: { s: Suggestion; full: string; onDone: () => void }) {
  const [mode, setMode] = useState<"" | "more" | "ai" | "edit">("");
  const [instruction, setInstruction] = useState("");
  const p = s.payload;
  const [fields, setFields] = useState<Record<string, string>>((): Record<string, string> =>
    isTask(s)
      ? {
          name: str(p.name),
          assignee_name: str(p.assignee_name),
          due_date: str(p.due_date),
          description: str(p.description),
        }
      : { body: str(p.body) },
  );
  const [error, setError] = useState<string | null>(null);
  const done = () => {
    setMode("");
    setInstruction("");
    setError(null);
    onDone();
  };
  const revise = useMutation({
    mutationFn: () =>
      api(`/api/suggestions/${s.id}/revise`, { method: "POST", body: { instruction } }),
    onSuccess: done,
    onError: (e) => setError(e.message),
  });
  const save = useMutation({
    mutationFn: () => api(`/api/suggestions/${s.id}`, { method: "PATCH", body: { fields } }),
    onSuccess: done,
    onError: (e) => setError(e.message),
  });
  const set = (k: string, v: string) => setFields((f) => ({ ...f, [k]: v }));
  const append = (k: string) => (t: string) =>
    setFields((f) => ({ ...f, [k]: f[k] ? `${f[k]} ${t}` : t }));
  const revisions = Array.isArray(p.revisions) ? p.revisions.length : 0;
  return (
    <div className="change">
      <div className="change-links">
        {full && (
          <button
            type="button"
            className="link"
            onClick={() => setMode(mode === "more" ? "" : "more")}
          >
            More
          </button>
        )}
        <button type="button" className="link" onClick={() => setMode(mode === "ai" ? "" : "ai")}>
          Change with AI
        </button>
        <button
          type="button"
          className="link"
          onClick={() => setMode(mode === "edit" ? "" : "edit")}
        >
          Edit
        </button>
        {revisions > 0 && <span className="muted small">changed {revisions}×</span>}
      </div>
      {mode === "more" && <p className="doc-text">{full}</p>}
      {mode === "ai" && (
        <div className="change-panel">
          <textarea
            aria-label={`What to change in ${s.id}`}
            rows={2}
            placeholder="e.g. shorter, assign to Kate, due Monday"
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
          />
          <div className="row">
            <VoiceInto onText={(t) => setInstruction((old) => (old ? `${old} ${t}` : t))} />
            <button
              className="btn primary"
              disabled={!instruction.trim() || revise.isPending}
              onClick={() => revise.mutate()}
            >
              {revise.isPending ? "Changing…" : "Apply"}
            </button>
          </div>
        </div>
      )}
      {mode === "edit" && (
        <div className="change-panel">
          {isTask(s) ? (
            <>
              <input
                aria-label="Title"
                value={fields.name}
                onChange={(e) => set("name", e.target.value)}
              />
              <div className="row">
                <input
                  aria-label="Assignee"
                  placeholder="Assignee"
                  value={fields.assignee_name}
                  onChange={(e) => set("assignee_name", e.target.value)}
                />
                <input
                  aria-label="Due date"
                  type="date"
                  value={fields.due_date}
                  onChange={(e) => set("due_date", e.target.value)}
                />
              </div>
              <textarea
                aria-label="Description"
                rows={3}
                value={fields.description}
                onChange={(e) => set("description", e.target.value)}
              />
              <div className="row">
                <VoiceInto onText={append("description")} />
              </div>
            </>
          ) : (
            <>
              <textarea
                aria-label="Text"
                rows={5}
                value={fields.body}
                onChange={(e) => set("body", e.target.value)}
              />
              <div className="row">
                <VoiceInto onText={append("body")} />
              </div>
            </>
          )}
          <div className="row">
            <button className="btn primary" disabled={save.isPending} onClick={() => save.mutate()}>
              Save
            </button>
            <button className="btn" onClick={() => setMode("")}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {error && <p className="error small">{error}</p>}
    </div>
  );
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
              <Change s={s} full={d.full !== d.detail ? d.full : ""} onDone={onDone} />
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
