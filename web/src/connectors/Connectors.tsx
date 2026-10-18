import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import { kyivTime } from "../briefs/BriefView";
import { ScopeTag } from "../shell/ScopeTag";
import type { Project } from "../shell/useProjects";

type Mail = {
  source_id: string;
  account_id: number | null;
  label: string;
  address: string;
  from_config: boolean;
  scopes: string[];
  healthy: boolean;
  last_ok: string | null;
  last_error: string | null;
  items: number;
};
type Tg = {
  source_id: string;
  healthy: boolean;
  last_ok: string | null;
  last_error: string | null;
  included: number;
  to_mark: number;
  items: number;
};
type Hub = {
  mail: Mail[];
  telegram: Tg[];
  catalog: { key: string; name: string; state: string; adds: string }[];
};

function State({ healthy, error }: { healthy: boolean; error: string | null }) {
  return healthy ? (
    <span className="state ok">healthy</span>
  ) : (
    <span className="state warn" title={error ?? ""}>
      needs attention
    </span>
  );
}

function Projects() {
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: ["projects"],
    queryFn: () => api<{ projects: Project[] }>("/api/projects"),
  });
  const [name, setName] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const add = useMutation({
    mutationFn: () => api("/api/projects", { method: "POST", body: { name, label: name } }),
    onSuccess: () => {
      setName("");
      setMessage(null);
      return queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: (e) => setMessage(e.message),
  });
  return (
    <section className="card group">
      <h3>Personal and projects</h3>
      <div className="row">
        {list.data?.projects.map((p) => (
          <ScopeTag key={p.name} scope={p.name} />
        ))}
      </div>
      <form
        className="row actions"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          if (name.trim()) add.mutate();
        }}
      >
        <input
          aria-label="New project"
          className="btn"
          placeholder="New project, e.g. acme"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button className="btn" type="submit">
          Add project
        </button>
        {message && <span className="error">{message}</span>}
      </form>
    </section>
  );
}

// Connectors hub (connectors spec): what is connected, its health and marks, and what is planned.
export function Connectors() {
  const hub = useQuery({ queryKey: ["connectors"], queryFn: () => api<Hub>("/api/connectors") });
  if (hub.isPending) return <p className="muted">Loading…</p>;
  if (hub.isError) return <p className="error">{hub.error.message}</p>;
  const h = hub.data;
  const since = (x: string | null) => (x ? kyivTime.format(new Date(x)) : "never");
  return (
    <>
      <p className="note">
        Everything the second brain knows comes from here. Each source is marked <b>Personal</b> or
        a <b>project</b>; new dialogs wait under “to mark”.
      </p>
      <section className="card group">
        <h3>Connected</h3>
        <table className="table">
          <thead>
            <tr>
              <th>Connector</th>
              <th>State</th>
              <th>Last sync</th>
              <th>Marks</th>
              <th>Items</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {h.mail.map((m) => (
              <tr key={m.source_id}>
                <td>
                  ✉ <b>{m.label}</b>{" "}
                  <span className="muted">
                    {m.address}
                    {m.from_config && " · from config"}
                  </span>
                </td>
                <td>
                  <State healthy={m.healthy} error={m.last_error} />
                  {m.last_error && <div className="error small">{m.last_error.slice(0, 120)}</div>}
                </td>
                <td className="muted">{since(m.last_ok)}</td>
                <td>
                  {m.scopes.map((s) => (
                    <ScopeTag key={s} scope={s} />
                  ))}
                </td>
                <td>{m.items}</td>
                <td>
                  <Link className="btn" to="/connectors/mail">
                    Settings
                  </Link>
                </td>
              </tr>
            ))}
            {h.telegram.map((t) => (
              <tr key={t.source_id}>
                <td>
                  ✈ <b>Telegram</b>
                </td>
                <td>
                  <State healthy={t.healthy} error={t.last_error} />
                  {t.last_error && <div className="error small">{t.last_error.slice(0, 120)}</div>}
                </td>
                <td className="muted">{since(t.last_ok)}</td>
                <td>
                  {t.included} dialogs{t.to_mark > 0 && <b> · {t.to_mark} to mark</b>}
                </td>
                <td>{t.items}</td>
                <td>
                  <Link className="btn" to="/connectors/telegram">
                    Settings
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="row actions">
          <Link className="btn primary" to="/connectors/mail">
            + Add a mailbox (Gmail or IMAP/SMTP)
          </Link>
        </p>
      </section>
      <Projects />
      <section className="card group">
        <h3>Planned</h3>
        <ul className="list">
          {h.catalog.map((c) => (
            <li key={c.key}>
              <span className={`state ${c.state === "planned" ? "plan" : "no"}`}>
                {c.state === "planned" ? "planned" : "not possible live"}
              </span>{" "}
              <b>{c.name}</b> — <span className="muted">{c.adds}</span>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
