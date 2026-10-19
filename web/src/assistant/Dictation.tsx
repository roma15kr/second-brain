import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "../api/client";
import { kyivTime } from "../briefs/BriefView";
import { useProjects } from "../shell/useProjects";
import { ask } from "./Ask";
import { Recorder } from "./Recorder";

type Form = "verbatim" | "clean" | "structured";
export type DictationData = {
  id: number;
  status: "uploaded" | "transcribing" | "done" | "failed";
  seconds: number;
  first_line: string;
  transcript: string | null;
  forms: Partial<Record<"clean" | "structured", { text: string; note?: string }>>;
  error: string | null;
  cost_usd: number;
  saved_doc_id: number | null;
  created_at: string;
};

const TABS: [Form, string][] = [
  ["verbatim", "Verbatim"],
  ["clean", "Clean"],
  ["structured", "Structured"],
];

export function useDictation(id: number | null) {
  return useQuery({
    queryKey: ["dictation", id],
    enabled: id !== null,
    queryFn: () => api<DictationData>(`/api/dictations/${id}`),
    refetchInterval: (q) =>
      q.state.data && ["uploaded", "transcribing"].includes(q.state.data.status) ? 1_500 : false,
  });
}

function Result({ d }: { d: DictationData }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const projects = useProjects();
  const [form, setForm] = useState<Form>("verbatim");
  const [edited, setEdited] = useState<Record<string, string>>({});
  const [scope, setScope] = useState(projects[0] ?? "personal");
  const [message, setMessage] = useState<string | null>(null);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["dictation", d.id] });
  const render = useMutation({
    mutationFn: (f: "clean" | "structured") =>
      api(`/api/dictations/${d.id}/render`, { method: "POST", body: { form: f } }),
    onSuccess: refresh,
    onError: (e) => setMessage(e.message),
  });
  const original = form === "verbatim" ? (d.transcript ?? "") : (d.forms[form]?.text ?? "");
  const text = edited[form] ?? original;
  const save = useMutation({
    mutationFn: () =>
      api<{ document_id: number }>(`/api/dictations/${d.id}/save`, {
        method: "POST",
        body: { form, scope, text },
      }),
    onSuccess: () => {
      setMessage("Saved to the Library.");
      refresh();
    },
    onError: (e) => setMessage(e.message),
  });
  const choose = (f: Form) => {
    setForm(f);
    if (f !== "verbatim" && !d.forms[f] && !render.isPending) render.mutate(f);
  };
  return (
    <div>
      <div className="row" role="tablist">
        {TABS.map(([f, label]) => (
          <button
            key={f}
            role="tab"
            aria-selected={form === f}
            className={`btn ${form === f ? "primary" : ""}`}
            onClick={() => choose(f)}
          >
            {label}
          </button>
        ))}
      </div>
      {render.isPending && form !== "verbatim" && !d.forms[form] ? (
        <p className="muted">Working on it…</p>
      ) : (
        <>
          {form !== "verbatim" && d.forms[form]?.note && (
            <p className="muted">{d.forms[form]?.note}</p>
          )}
          <textarea
            aria-label="Dictation text"
            className="btn wide"
            rows={12}
            value={text}
            onChange={(e) => setEdited({ ...edited, [form]: e.target.value })}
          />
        </>
      )}
      <div className="row actions">
        <button className="btn" onClick={() => void navigator.clipboard?.writeText(text)}>
          Copy
        </button>
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
        <button className="btn" disabled={!text || save.isPending} onClick={() => save.mutate()}>
          Save to Library
        </button>
        <button
          className="btn primary"
          disabled={!text}
          onClick={() => void ask(text).then((c) => navigate(`/assistant/t/${c.thread_id}`))}
        >
          As a request
        </button>
      </div>
      {d.saved_doc_id && <Link to={`/library/${d.saved_doc_id}`}>Open the note</Link>}
      {message && <p className="muted">{message}</p>}
      <p className="muted small">
        {Math.round(d.seconds)} s · ${d.cost_usd.toFixed(3)}
      </p>
    </div>
  );
}

function Current({ id }: { id: number }) {
  const d = useDictation(id);
  if (d.isPending) return <p className="muted">Uploading…</p>;
  if (d.isError) return <p className="error">{d.error.message}</p>;
  if (d.data.status === "failed")
    return <p className="error">Not transcribed yet: {d.data.error} (retried automatically)</p>;
  if (d.data.status !== "done") return <p className="muted">Transcribing…</p>;
  return <Result d={d.data} />;
}

// Dictate: speak, then take it verbatim, cleaned, structured, or as a request (voice-dictation).
export function Dictation() {
  const params = useParams();
  const navigate = useNavigate();
  const current = params.id ? Number(params.id) : null;
  const history = useQuery({
    queryKey: ["dictations"],
    queryFn: () => api<{ dictations: DictationData[] }>("/api/dictations"),
  });
  return (
    <>
      <section className="card">
        <Recorder onUploaded={(id) => void navigate(`/dictate/${id}`)} />
        {current !== null && <Current key={current} id={current} />}
      </section>
      {history.data && history.data.dictations.length > 0 && (
        <section className="card">
          <h3>Recent dictations</h3>
          <ul className="list">
            {history.data.dictations.map((h) => (
              <li key={h.id}>
                <Link to={`/dictate/${h.id}`}>{h.first_line || `(${h.status})`}</Link>
                <span className="muted">
                  {" "}
                  · {kyivTime.format(new Date(h.created_at))} · {Math.round(h.seconds)} s · $
                  {h.cost_usd.toFixed(3)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
