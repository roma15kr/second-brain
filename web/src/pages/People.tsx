import { ScopeTag } from "../shell/ScopeTag";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { api } from "../api/client";
import { kyivTime } from "../briefs/BriefView";

type PersonRow = {
  id: number;
  name: string;
  channels: string[];
  scopes: string[];
  last_interaction: string;
  conversations: number;
  open_loops: number;
};
const CHANNEL_ICON: Record<string, string> = { email: "✉", telegram: "✈", phone: "☎" };

// People by recent activity with channels, scopes and open loops (web-dashboard spec).
export function People() {
  const list = useQuery({
    queryKey: ["people"],
    queryFn: () => api<{ people: PersonRow[] }>("/api/people"),
  });
  if (list.isPending) return <p className="muted">Loading…</p>;
  if (list.isError) return <p className="error">{list.error.message}</p>;
  return (
    <table className="card table">
      <thead>
        <tr>
          <th>Person</th>
          <th>Channels</th>
          <th>Scopes</th>
          <th>Last</th>
          <th>Loops</th>
        </tr>
      </thead>
      <tbody>
        {list.data.people.map((p) => (
          <tr key={p.id}>
            <td>
              <Link to={`/people/${p.id}`}>{p.name}</Link>
            </td>
            <td>{p.channels.map((c) => CHANNEL_ICON[c] ?? c).join(" ")}</td>
            <td>
              {p.scopes.map((s) => (
                <ScopeTag key={s} scope={s} />
              ))}
            </td>
            <td className="muted">{kyivTime.format(new Date(p.last_interaction))}</td>
            <td>{p.open_loops > 0 ? `↺ ${p.open_loops}` : ""}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
