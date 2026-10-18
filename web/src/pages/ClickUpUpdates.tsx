import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { api } from "../api/client";
import { kyivTime } from "../briefs/BriefView";

type Update = {
  kind: string;
  direct: boolean;
  text: string;
  title: string | null;
  item_id: number | null;
  link: string | null;
  at: string;
  pushed: boolean;
};

function Row({ u }: { u: Update }) {
  return (
    <li>
      <span className="muted">{kyivTime.format(new Date(u.at))} · </span>
      {u.text}
      {u.title && (
        <>
          {" — "}
          {u.item_id ? <Link to={`/c/${u.item_id}`}>{u.title}</Link> : u.title}
        </>
      )}
      {u.link && (
        <a className="muted" href={u.link} target="_blank" rel="noreferrer">
          {" "}
          ↗ ClickUp
        </a>
      )}
    </li>
  );
}

// ClickUp for you: assigned / mentioned (you or DTC) and activity you follow, last 3 days.
export function ClickUpUpdates() {
  const q = useQuery({
    queryKey: ["clickup-updates"],
    queryFn: () => api<{ updates: Update[] }>("/api/clickup/updates"),
    refetchInterval: 60_000,
  });
  if (q.isPending) return <p className="muted">Loading…</p>;
  if (q.isError) return <p className="error">{q.error.message}</p>;
  const direct = q.data.updates.filter((u) => u.direct);
  const followed = q.data.updates.filter((u) => !u.direct);
  return (
    <>
      <section className="card group">
        <h3>For you (assigned or mentioned)</h3>
        <ul className="list">
          {direct.map((u, i) => (
            <Row key={i} u={u} />
          ))}
          {direct.length === 0 && <li className="muted">Nothing in the last 3 days.</li>}
        </ul>
      </section>
      <section className="card group">
        <h3>Tasks and channels you follow</h3>
        <ul className="list">
          {followed.map((u, i) => (
            <Row key={i} u={u} />
          ))}
          {followed.length === 0 && <li className="muted">Nothing in the last 3 days.</li>}
        </ul>
      </section>
    </>
  );
}
