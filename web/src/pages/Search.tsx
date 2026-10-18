import { ScopeTag } from "../shell/ScopeTag";
import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "../api/client";
import { kyivTime } from "../briefs/BriefView";

type Ctx = {
  author: string;
  sent_at: string;
  text: string;
  matched: boolean;
  locator: string | null;
};
type Result = {
  item_id: number;
  kind: string;
  scopes: string[];
  title: string | null;
  participants: string[];
  last_activity_at: string | null;
  excerpt: string;
  locator: string | null;
  summary: string | null;
  extra: { context?: Ctx[] };
};
type SearchData = {
  results: Result[];
  briefs: { id: number; routine: string; headline: string; created_at: string }[];
};

const SCOPES = ["personal", "digisoft", "quokka", "rdim", "unsorted"];

// Knowledge-base search with filters, matched context and deep links (web-dashboard spec).
export function Search() {
  const [params, setParams] = useSearchParams();
  const [draft, setDraft] = useState(params.get("q") ?? "");
  const q = params.get("q") ?? "";
  const query = params.toString();
  const search = useQuery({
    queryKey: ["search", query],
    enabled: q.trim().length > 0,
    queryFn: () => api<SearchData>(`/api/search?${query}`),
  });
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    set("q", draft.trim());
  };
  return (
    <>
      <form className="row filters" onSubmit={submit}>
        <input
          aria-label="Search query"
          className="btn wide-input"
          placeholder="Words or meaning, in any language"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button className="btn primary" type="submit">
          Search
        </button>
      </form>
      <div className="row filters">
        <select
          aria-label="Scope"
          className="btn"
          value={params.get("scope") ?? ""}
          onChange={(e) => set("scope", e.target.value)}
        >
          <option value="">All scopes</option>
          {SCOPES.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select
          aria-label="Source"
          className="btn"
          value={params.get("kind") ?? ""}
          onChange={(e) => set("kind", e.target.value)}
        >
          <option value="">Mail and chats</option>
          <option value="mail">Mail</option>
          <option value="chats">Telegram</option>
        </select>
        <input
          aria-label="Person"
          className="btn"
          placeholder="Person…"
          defaultValue={params.get("person") ?? ""}
          onBlur={(e) => set("person", e.target.value.trim())}
        />
        <input
          aria-label="From"
          type="date"
          className="btn"
          value={params.get("from") ?? ""}
          onChange={(e) => set("from", e.target.value)}
        />
        <input
          aria-label="To"
          type="date"
          className="btn"
          value={params.get("to") ?? ""}
          onChange={(e) => set("to", e.target.value)}
        />
      </div>
      {search.isFetching && <p className="muted">Searching…</p>}
      {search.isError && <p className="error">{search.error.message}</p>}
      {search.data && search.data.briefs.length > 0 && (
        <section className="card group">
          <h3>Briefs</h3>
          <ul className="list">
            {search.data.briefs.map((b) => (
              <li key={b.id}>
                <Link to={`/briefs/${b.id}`}>{b.headline}</Link>{" "}
                <span className="muted">{kyivTime.format(new Date(b.created_at))}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {search.data && (
        <ul className="list card">
          {search.data.results.map((r) => {
            const matched = r.extra.context?.find((c) => c.matched);
            const to = `/c/${r.item_id}${matched?.locator ? `?m=${encodeURIComponent(matched.locator)}` : ""}`;
            return (
              <li key={r.item_id}>
                <div>
                  <span aria-hidden>{r.kind === "tg_conversation" ? "✈" : "✉"} </span>
                  <Link to={to}>{r.title || "(no subject)"}</Link>{" "}
                  {r.scopes.map((s) => (
                    <ScopeTag key={s} scope={s} />
                  ))}
                  {r.last_activity_at && (
                    <span className="muted">
                      {" "}
                      · {kyivTime.format(new Date(r.last_activity_at))}
                    </span>
                  )}
                </div>
                {r.summary && <div className="muted">{r.summary}</div>}
                {matched ? (
                  <blockquote className="match">
                    <strong>{matched.author}:</strong> {matched.text}
                  </blockquote>
                ) : (
                  r.excerpt && <blockquote className="match">{r.excerpt}</blockquote>
                )}
                {r.locator?.startsWith("https://") && (
                  <a className="muted" href={r.locator} target="_blank" rel="noreferrer">
                    Open original ↗
                  </a>
                )}
              </li>
            );
          })}
          {search.data.results.length === 0 && <li className="muted">Nothing found.</li>}
        </ul>
      )}
    </>
  );
}
