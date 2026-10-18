import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { api } from "../api/client";
import { kyivTime } from "../briefs/BriefView";
import { ScopeTag } from "../shell/ScopeTag";
import { AiSwitch, fileToB64 } from "./Library";

type DocDetail = {
  id: number;
  title: string;
  kind: string;
  core: boolean;
  scopes: string[];
  ai_allowed: boolean;
  text: string;
  versions: { id: number; filename: string; size: number; created_at: string }[];
};

// One document: latest text, versions (kept), new version or note edit (personal-base spec).
export function LibraryDoc() {
  const { id } = useParams();
  const queryClient = useQueryClient();
  const doc = useQuery({
    queryKey: ["doc", id],
    queryFn: () => api<DocDetail>(`/api/library/${id}`),
  });
  const [viewing, setViewing] = useState<number | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const old = useQuery({
    queryKey: ["doc-version", id, viewing],
    enabled: viewing !== null,
    queryFn: () => api<{ text: string }>(`/api/library/${id}/versions/${viewing}`),
  });
  const refresh = () => {
    setDraft(null);
    return queryClient.invalidateQueries({ queryKey: ["doc", id] });
  };
  const upload = useMutation({
    mutationFn: async (body: Record<string, unknown>) =>
      api(`/api/library/${id}/versions`, { method: "POST", body }),
    onSuccess: refresh,
  });
  if (doc.isPending) return <p className="muted">Loading…</p>;
  if (doc.isError) return <p className="error">{doc.error.message}</p>;
  const d = doc.data;
  const isNote = d.versions[0]?.filename === "note.md";
  return (
    <>
      <p>
        <Link to="/library">← Library</Link>
      </p>
      <article className="card">
        <h2>{d.title}</h2>
        <div className="row">
          {d.scopes.map((s) => (
            <ScopeTag key={s} scope={s} />
          ))}
          <span className="muted">{d.kind}</span>
          <AiSwitch doc={d} onChanged={refresh} />
        </div>
        {draft !== null ? (
          <>
            <textarea
              aria-label="Note text"
              className="btn wide"
              rows={16}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
            <div className="row">
              <button className="btn primary" onClick={() => upload.mutate({ text: draft })}>
                Save as new version
              </button>
              <button className="btn" onClick={() => setDraft(null)}>
                Cancel
              </button>
            </div>
          </>
        ) : (
          <pre className="doc-text">{d.text}</pre>
        )}
        <div className="row actions">
          {isNote && draft === null && (
            <button className="btn" onClick={() => setDraft(d.text)}>
              Edit note
            </button>
          )}
          <label className="btn">
            Upload new version
            <input
              type="file"
              aria-label="New version file"
              hidden
              accept=".md,.markdown,.txt,.pdf,.docx"
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f)
                  upload.mutate({ file: { filename: f.name, content_b64: await fileToB64(f) } });
              }}
            />
          </label>
        </div>
        {upload.isError && <p className="error">{upload.error.message}</p>}
      </article>
      <section className="card group">
        <h3>Versions</h3>
        <ul className="list">
          {d.versions.map((v, i) => (
            <li key={v.id}>
              {v.filename}{" "}
              <span className="muted">
                · {kyivTime.format(new Date(v.created_at))} · {Math.ceil(v.size / 1024)} KB
              </span>
              {i === 0 ? (
                <strong> · current</strong>
              ) : (
                <button className="btn" onClick={() => setViewing(viewing === v.id ? null : v.id)}>
                  {viewing === v.id ? "Hide" : "View"}
                </button>
              )}
              {viewing === v.id && old.data && <pre className="doc-text">{old.data.text}</pre>}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
