import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import { ScopeTag } from "../shell/ScopeTag";
import { useProjects } from "../shell/useProjects";

type ListRow = {
  list_id: string;
  space: string;
  folder: string;
  list: string;
  sync: boolean;
  scopes: string[];
  default_for_drafts: boolean;
  tasks: number;
};
type Overview = {
  accounts: { id: number; label: string; team: string | null; state: string }[];
  lists: ListRow[];
  members: {
    email: string;
    areas: string;
    tasks: number;
    person_id: number | null;
    person: string | null;
  }[];
};

function Connect({ onDone }: { onDone: () => void }) {
  const [token, setToken] = useState("");
  const [teams, setTeams] = useState<{ id: string; name: string }[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const connect = useMutation({
    mutationFn: (team_id?: string) =>
      api<{ id?: number; choose_team?: { id: string; name: string }[] }>(
        "/api/connectors/clickup",
        {
          method: "POST",
          body: team_id ? { token, team_id } : { token },
        },
      ),
    onSuccess: (r) => {
      if (r.choose_team) return setTeams(r.choose_team);
      setToken("");
      setTeams(null);
      setError(null);
      onDone();
    },
    onError: (e) => setError(e.message),
  });
  return (
    <form
      className="row"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        connect.mutate(undefined);
      }}
    >
      <input
        aria-label="ClickUp personal API token"
        type="password"
        className="btn wide-input"
        placeholder="Personal API token (ClickUp → Settings → Apps), starts with pk_"
        value={token}
        onChange={(e) => setToken(e.target.value)}
      />
      <button className="btn primary" type="submit" disabled={!token}>
        Connect
      </button>
      {teams && (
        <span>
          Workspace:{" "}
          {teams.map((t) => (
            <button key={t.id} type="button" className="btn" onClick={() => connect.mutate(t.id)}>
              {t.name}
            </button>
          ))}
        </span>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </form>
  );
}

// Connectors › ClickUp: choose and mark lists, default list for task drafts, team ↔ people.
export function ClickUpConnector() {
  const queryClient = useQueryClient();
  const projects = useProjects();
  const data = useQuery({
    queryKey: ["clickup"],
    queryFn: () => api<Overview>("/api/connectors/clickup"),
  });
  const [message, setMessage] = useState<string | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["clickup"] });
  const set = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api<{ relabelled_tasks: number }>(`/api/connectors/clickup/lists/${id}`, {
        method: "POST",
        body,
      }),
    onSuccess: (r) => {
      setMessage(r.relabelled_tasks ? `${r.relabelled_tasks} tasks re-labelled.` : null);
      return refresh();
    },
    onError: (e) => setMessage(e.message),
  });
  const d = data.data;
  return (
    <>
      <p>
        <Link to="/connectors">← Connectors</Link>
      </p>
      <section className="card group">
        <h3>ClickUp</h3>
        <p className="muted">
          Reads tasks and comments of the lists you choose · creates tasks only from drafts you
          approve · never edits or deletes.
        </p>
        {d?.accounts.map((a) => (
          <p key={a.id}>
            <span className="state ok">connected</span> {a.team ?? a.label}
          </p>
        ))}
        <Connect onDone={refresh} />
      </section>
      {message && (
        <p role="status" className="muted">
          {message}
        </p>
      )}
      {d && d.lists.length > 0 && (
        <section className="card group">
          <h3>Spaces and lists</h3>
          <table className="table">
            <thead>
              <tr>
                <th>List</th>
                <th>Mark</th>
                <th>Sync</th>
                <th>Default for task drafts</th>
                <th>Tasks</th>
              </tr>
            </thead>
            <tbody>
              {d.lists.map((l) => (
                <tr key={l.list_id}>
                  <td>
                    <span className="muted">
                      {l.space}
                      {l.folder && ` › ${l.folder}`} ›{" "}
                    </span>
                    {l.list}
                  </td>
                  <td>
                    {l.scopes.map((s) => (
                      <ScopeTag key={s} scope={s} />
                    ))}
                    <select
                      aria-label={`Mark ${l.list}`}
                      className="btn"
                      value=""
                      onChange={(e) =>
                        e.target.value &&
                        set.mutate({ id: l.list_id, body: { scopes: [e.target.value] } })
                      }
                    >
                      <option value="">Mark…</option>
                      {projects.map((p) => (
                        <option key={p}>{p}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Sync ${l.list}`}
                      checked={l.sync}
                      onChange={(e) =>
                        set.mutate({ id: l.list_id, body: { sync: e.target.checked } })
                      }
                    />
                  </td>
                  <td>
                    <input
                      type="radio"
                      name="default-drafts"
                      aria-label={`Default for drafts: ${l.list}`}
                      checked={l.default_for_drafts}
                      onChange={() =>
                        set.mutate({ id: l.list_id, body: { default_for_drafts: true } })
                      }
                    />
                  </td>
                  <td>{l.tasks}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {d && d.members.length > 0 && (
        <section className="card group">
          <h3>Team ↔ people</h3>
          <table className="table">
            <tbody>
              {d.members.map((m) => (
                <tr key={m.email}>
                  <td>{m.email}</td>
                  <td>
                    {m.person_id ? <Link to={`/people/${m.person_id}`}>{m.person}</Link> : "—"}
                  </td>
                  <td className="muted">{m.areas}</td>
                  <td>{m.tasks} tasks</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">
            Areas come from the lists of each member's tasks; they are used to suggest whom to
            delegate a request to.
          </p>
        </section>
      )}
    </>
  );
}
