import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import { kyivTime } from "../briefs/BriefView";
import { ScopeTag } from "../shell/ScopeTag";
import { useProjects } from "../shell/useProjects";

type Doc = {
  id: number;
  title: string;
  kind: string;
  core: boolean;
  scopes: string[];
  ai_allowed: boolean;
  versions: number;
  filename: string | null;
  size: number | null;
  updated_at: string;
};
const KINDS = ["constitution", "plan", "goals", "note", "reference"];
const KIND_ICON: Record<string, string> = {
  constitution: "📜",
  plan: "📈",
  goals: "🎯",
  note: "🗒",
  reference: "📄",
};

export async function fileToB64(file: File): Promise<string> {
  const buf = new Uint8Array(await file.arrayBuffer());
  let bin = "";
  for (let i = 0; i < buf.length; i += 0x8000)
    bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  return btoa(bin);
}

export function AiSwitch({
  doc,
  onChanged,
}: {
  doc: { id: number; ai_allowed: boolean };
  onChanged: () => void;
}) {
  const toggle = useMutation({
    mutationFn: () =>
      api(`/api/library/${doc.id}`, { method: "PATCH", body: { ai_allowed: !doc.ai_allowed } }),
    onSuccess: onChanged,
  });
  return (
    <label className="muted">
      <input
        type="checkbox"
        aria-label="AI may read"
        checked={doc.ai_allowed}
        onChange={() => toggle.mutate()}
      />{" "}
      AI may read
      {!doc.ai_allowed && " · 🔒 local only"}
    </label>
  );
}

function AddForm({ onDone }: { onDone: () => void }) {
  const projects = useProjects();
  const [mode, setMode] = useState<"file" | "note">("file");
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [kind, setKind] = useState("plan");
  const [scope, setScope] = useState("");
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: async () => {
      const body: Record<string, unknown> = { kind, scopes: scope ? [scope] : [], title };
      if (mode === "file" && file)
        body.file = { filename: file.name, content_b64: await fileToB64(file) };
      else body.text = text;
      return api("/api/library", { method: "POST", body });
    },
    onSuccess: () => {
      setFile(null);
      setTitle("");
      setText("");
      setError(null);
      onDone();
    },
    onError: (e) => setError(e.message),
  });
  const pick = (f: File | undefined) => {
    if (!f) return;
    setFile(f);
    if (!title) setTitle(f.name.replace(/\.[^.]+$/, ""));
  };
  let input: ReactNode;
  if (mode === "file") {
    input = (
      <label
        className="drop"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          pick(e.dataTransfer.files[0]);
        }}
      >
        {file
          ? `📎 ${file.name}`
          : "Drop a file here (Markdown, text, PDF, Word ≤ 20 MB) or click to choose"}
        <input
          type="file"
          aria-label="File"
          accept=".md,.markdown,.txt,.pdf,.docx"
          hidden
          onChange={(e) => pick(e.target.files?.[0])}
        />
      </label>
    );
  } else {
    input = (
      <textarea
        aria-label="Note text"
        className="btn wide"
        rows={6}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
    );
  }
  return (
    <form
      className="settings-form"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <div className="row">
        <button
          type="button"
          className={`btn ${mode === "file" ? "primary" : ""}`}
          onClick={() => setMode("file")}
        >
          Upload a file
        </button>
        <button
          type="button"
          className={`btn ${mode === "note" ? "primary" : ""}`}
          onClick={() => setMode("note")}
        >
          New note
        </button>
      </div>
      {input}
      <div className="row">
        <input
          aria-label="Title"
          className="btn wide-input"
          placeholder="Title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <select
          aria-label="Kind"
          className="btn"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
        >
          {KINDS.map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
        <select
          aria-label="Mark"
          className="btn"
          value={scope}
          onChange={(e) => setScope(e.target.value)}
        >
          <option value="">Personal or project…</option>
          {projects.map((p) => (
            <option key={p}>{p}</option>
          ))}
        </select>
        <button
          className="btn primary"
          type="submit"
          disabled={!scope || (mode === "file" ? !file : !text.trim())}
        >
          Save
        </button>
      </div>
      {!scope && (
        <p className="muted">Every document must be marked Personal or a project before saving.</p>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </form>
  );
}

// Library: the owner's constitution, plans, notes and files (personal-base spec).
export function Library({ goals }: { goals?: ReactNode }) {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState("");
  const list = useQuery({
    queryKey: ["library"],
    queryFn: () => api<{ documents: Doc[] }>("/api/library"),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["library"] });
  const docs = (list.data?.documents ?? []).filter((d) => !filter || d.scopes.includes(filter));
  const projects = useProjects();
  const row = (d: Doc) => (
    <li key={d.id}>
      <span aria-hidden>{KIND_ICON[d.kind]} </span>
      <Link to={`/library/${d.id}`}>{d.title}</Link>{" "}
      {d.scopes.map((s) => (
        <ScopeTag key={s} scope={s} />
      ))}
      <span className="muted">
        {" "}
        · {d.kind} · v{d.versions} · {kyivTime.format(new Date(d.updated_at))}
      </span>
      <div>
        <AiSwitch doc={d} onChanged={refresh} />
      </div>
    </li>
  );
  return (
    <>
      <section className="card group">
        <AddForm onDone={refresh} />
      </section>
      {goals}
      <div className="row filters">
        <button className={`btn ${filter === "" ? "primary" : ""}`} onClick={() => setFilter("")}>
          All
        </button>
        {projects.map((p) => (
          <button
            key={p}
            className={`btn ${filter === p ? "primary" : ""}`}
            onClick={() => setFilter(p)}
          >
            {p}
          </button>
        ))}
      </div>
      <section className="card group">
        <h3>Core documents — the assistant plans with these</h3>
        <ul className="list">{docs.filter((d) => d.core).map(row)}</ul>
      </section>
      <section className="card group">
        <h3>Notes and references</h3>
        <ul className="list">{docs.filter((d) => !d.core).map(row)}</ul>
      </section>
    </>
  );
}
