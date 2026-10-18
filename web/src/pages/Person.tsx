import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { api } from "../api/client";
import { kyivTime } from "../briefs/BriefView";

type Profile = {
  person_id: number;
  display_name: string;
  names: string[];
  identities: string[];
  scopes: string[];
  first_interaction: string | null;
  last_interaction: string | null;
  conversations: number;
  recent: {
    item_id: number;
    kind: string;
    title: string | null;
    last_activity_at: string | null;
    summary: string | null;
  }[];
  merges: { id: number; merged_id: number; reason: string }[];
  open_loops: { id: number; kind: string; title: string; due_date: string | null }[];
};

// One person: identities, scopes, interactions, loops, conversations; link/merge/undo.
export function Person() {
  const { id } = useParams();
  const queryClient = useQueryClient();
  const [key, setKey] = useState("");
  const [find, setFind] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const profile = useQuery({
    queryKey: ["person", id],
    queryFn: () => api<Profile>(`/api/people/${id}`),
  });
  const candidates = useQuery({
    queryKey: ["people", find],
    enabled: find.trim().length >= 2,
    queryFn: () =>
      api<{ people: { id: number; name: string }[] }>(
        `/api/people?q=${encodeURIComponent(find.trim())}&limit=8`,
      ),
  });
  const done = (text: string) => {
    setMessage(text);
    return queryClient.invalidateQueries({ queryKey: ["person"] });
  };
  const fail = (e: Error) => setMessage(e.message);
  const link = useMutation({
    mutationFn: () => api(`/api/people/${id}/link`, { method: "POST", body: { key } }),
    onSuccess: () => {
      setKey("");
      return done("Identity linked.");
    },
    onError: fail,
  });
  const merge = useMutation({
    mutationFn: (other: number) =>
      api(`/api/people/${id}/merge`, { method: "POST", body: { other_id: other } }),
    onSuccess: () => {
      setFind("");
      return done("Merged. You can undo it below.");
    },
    onError: fail,
  });
  const undo = useMutation({
    mutationFn: (mergeId: number) => api(`/api/people/merges/${mergeId}/undo`, { method: "POST" }),
    onSuccess: () => done("Merge undone."),
    onError: fail,
  });

  if (profile.isPending) return <p className="muted">Loading…</p>;
  if (profile.isError) return <p className="error">{profile.error.message}</p>;
  const p = profile.data;
  return (
    <>
      <article className="card">
        <h2>{p.display_name}</h2>
        {p.names.length > 1 && (
          <p className="muted">Also: {p.names.filter((n) => n !== p.display_name).join(", ")}</p>
        )}
        <p>
          {p.scopes.map((s) => (
            <Link key={s} to={`/scopes/${s}`} className={`tag ${s}`}>
              {s}
            </Link>
          ))}
        </p>
        <p className="muted">
          {p.conversations} conversations
          {p.first_interaction && ` · first ${kyivTime.format(new Date(p.first_interaction))}`}
          {p.last_interaction && ` · last ${kyivTime.format(new Date(p.last_interaction))}`}
        </p>
        <ul className="identities">
          {p.identities.map((k) => (
            <li key={k}>
              <code>{k}</code>
            </li>
          ))}
        </ul>
        {message && (
          <p role="status" className="muted">
            {message}
          </p>
        )}
      </article>
      {p.open_loops.length > 0 && (
        <section className="card group">
          <h3>Open loops</h3>
          <ul className="list">
            {p.open_loops.map((lp) => (
              <li key={lp.id}>
                <Link to="/loops">↺ {lp.title}</Link>
                {lp.due_date && <span className="muted"> · due {lp.due_date}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className="card group">
        <h3>Recent conversations</h3>
        <ul className="list">
          {p.recent.map((c) => (
            <li key={c.item_id}>
              <Link to={`/c/${c.item_id}`}>{c.title || "(no subject)"}</Link>
              {c.last_activity_at && (
                <span className="muted"> · {kyivTime.format(new Date(c.last_activity_at))}</span>
              )}
              {c.summary && <div className="muted">{c.summary}</div>}
            </li>
          ))}
        </ul>
      </section>
      <section className="card group">
        <h3>Link and merge</h3>
        <form
          className="row"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            if (key.trim()) link.mutate();
          }}
        >
          <input
            aria-label="Identity to link"
            className="btn wide-input"
            placeholder="email:a@b.c, phone:+380…, tg:123, tgu:username"
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
          <button className="btn" type="submit">
            Link
          </button>
        </form>
        <div className="row actions">
          <input
            aria-label="Find a person to merge"
            className="btn wide-input"
            placeholder="Merge with… (type a name)"
            value={find}
            onChange={(e) => setFind(e.target.value)}
          />
        </div>
        <ul className="list">
          {(candidates.data?.people ?? [])
            .filter((c) => c.id !== p.person_id)
            .map((c) => (
              <li key={c.id}>
                {c.name}{" "}
                <button className="btn" onClick={() => merge.mutate(c.id)}>
                  Merge into {p.display_name}
                </button>
              </li>
            ))}
        </ul>
        {p.merges.length > 0 && (
          <ul className="list">
            {p.merges.map((m) => (
              <li key={m.id}>
                Merged person #{m.merged_id} <span className="muted">({m.reason})</span>{" "}
                <button className="btn" onClick={() => undo.mutate(m.id)}>
                  Undo merge
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
