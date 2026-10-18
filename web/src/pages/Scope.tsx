import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { api } from "../api/client";
import { kyivTime } from "../briefs/BriefView";

type ScopeData = {
  scope: string;
  archived: boolean;
  activity: { day: string; kind: string; n: number }[];
  open_loops: {
    id: number;
    title: string;
    counterpart: string;
    due_date: string | null;
    overdue: boolean;
  }[];
  key_people: { name: string; conversations: number }[];
  decisions: { item_id: number; title: string | null; outcome: string; at: string | null }[];
};

// A scope's weekly activity, open loops, key people and latest decisions; archive switch.
export function Scope() {
  const { scope } = useParams();
  const queryClient = useQueryClient();
  const data = useQuery({
    queryKey: ["scope", scope],
    queryFn: () => api<ScopeData>(`/api/scopes/${scope}`),
  });
  const archive = useMutation({
    mutationFn: (archived: boolean) =>
      api(`/api/scopes/${scope}/archive`, { method: "POST", body: { archived } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["scope", scope] }),
  });
  if (data.isPending) return <p className="muted">Loading…</p>;
  if (data.isError) return <p className="error">{data.error.message}</p>;
  const d = data.data;
  const byDay = new Map<string, number>();
  d.activity.forEach((a) => byDay.set(a.day, (byDay.get(a.day) ?? 0) + a.n));
  const max = Math.max(1, ...byDay.values());
  return (
    <>
      <div className="row filters">
        <span className={`tag ${d.scope}`}>{d.scope}</span>
        {d.archived && <strong>archived (read-only: sync stopped, still searchable)</strong>}
        <button className="btn" onClick={() => archive.mutate(!d.archived)}>
          {d.archived ? "Unarchive" : "Archive scope…"}
        </button>
      </div>
      <div className="grid">
        <section className="card">
          <h3>Last 7 days</h3>
          <ul className="bars">
            {[...byDay.entries()].map(([day, n]) => (
              <li key={day}>
                <span className="muted">{day.slice(5)}</span>
                <span className="bar" style={{ width: `${(n / max) * 100}%` }} />
                {n}
              </li>
            ))}
          </ul>
        </section>
        <section className="card">
          <h3>Key people (30 days)</h3>
          <ul className="list">
            {d.key_people.map((p) => (
              <li key={p.name}>
                {p.name} <span className="muted">· {p.conversations}</span>
              </li>
            ))}
          </ul>
        </section>
        <section className="card">
          <h3>Open loops</h3>
          <ul className="list">
            {d.open_loops.map((lp) => (
              <li key={lp.id} className={lp.overdue ? "overdue" : ""}>
                {lp.title}{" "}
                <span className="muted">
                  · {lp.counterpart}
                  {lp.due_date && ` · due ${lp.due_date}`}
                </span>
              </li>
            ))}
          </ul>
        </section>
        <section className="card">
          <h3>Latest decisions</h3>
          <ul className="list">
            {d.decisions.map((x) => (
              <li key={x.item_id}>
                <Link to={`/c/${x.item_id}`}>{x.title || "(no subject)"}</Link>
                {x.at && <span className="muted"> · {kyivTime.format(new Date(x.at))}</span>}
                <div>{x.outcome}</div>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </>
  );
}
