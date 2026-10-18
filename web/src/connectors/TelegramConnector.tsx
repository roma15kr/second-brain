import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import { kyivTime } from "../briefs/BriefView";
import { ScopeTag } from "../shell/ScopeTag";
import { useProjects } from "../shell/useProjects";

type Dialog = {
  chat_id: number;
  title: string;
  username: string | null;
  type: string;
  last_message_at: string | null;
  scopes: string[];
  messages_7d: number;
};
type Login = { id: number; status: string; error: string | null; qr_svg: string | null };
type TelegramData = {
  to_mark: Dialog[];
  included: Dialog[];
  ignored: Dialog[];
  self_ids: string[];
  login: Login | null;
};

function LoginPanel({ login }: { login: Login | null }) {
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const active = login && ["pending", "qr", "password_needed"].includes(login.status);
  const status = useQuery({
    queryKey: ["tg-login", login?.id],
    enabled: !!active,
    refetchInterval: 2000,
    queryFn: () => api<Login>(`/api/connectors/telegram/login/${login!.id}`),
  });
  const start = useMutation({
    mutationFn: () => api<Login>("/api/connectors/telegram/login", { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["telegram"] }),
  });
  const send = useMutation({
    mutationFn: () =>
      api(`/api/connectors/telegram/login/${login!.id}/password`, {
        method: "POST",
        body: { password },
      }),
    onSuccess: () => setPassword(""),
  });
  const current = status.data ?? login;
  return (
    <div className="card group">
      <div className="row">
        <span className="muted">
          Read-only: never sends, never marks read. Session stays on the server.
        </span>
        <button className="btn" onClick={() => start.mutate()}>
          Log in again (QR)
        </button>
      </div>
      {current?.status === "pending" && <p className="muted">Waiting for the Telegram service…</p>}
      {current?.status === "qr" && current.qr_svg && (
        <div>
          <p>Scan in Telegram on your phone: Settings → Devices → Link Desktop Device.</p>
          <div className="qr" dangerouslySetInnerHTML={{ __html: current.qr_svg }} />
        </div>
      )}
      {current?.status === "password_needed" && (
        <form
          className="row"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            send.mutate();
          }}
        >
          <input
            aria-label="Two-step verification password"
            type="password"
            className="btn"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button className="btn primary" type="submit" disabled={!password}>
            Continue
          </button>
        </form>
      )}
      {current?.status === "expired" && <p className="muted">The QR code expired — start again.</p>}
      {current?.status === "failed" && <p className="error">{current.error}</p>}
      {current?.status === "done" && <p className="muted">Logged in.</p>}
    </div>
  );
}

// Connectors › Telegram: choose and mark dialogs (connectors spec).
export function TelegramConnector() {
  const queryClient = useQueryClient();
  const projects = useProjects();
  const data = useQuery({
    queryKey: ["telegram"],
    queryFn: () => api<TelegramData>("/api/connectors/telegram"),
  });
  const [message, setMessage] = useState<string | null>(null);
  const set = useMutation({
    mutationFn: ({ id, body }: { id: number; body: { included?: boolean; scopes?: string[] } }) =>
      api<{ rescoped_messages: number }>(`/api/connectors/telegram/dialogs/${id}`, {
        method: "POST",
        body,
      }),
    onSuccess: (r) => {
      if (r.rescoped_messages) setMessage(`${r.rescoped_messages} messages re-labelled.`);
      return queryClient.invalidateQueries({ queryKey: ["telegram"] });
    },
    onError: (e) => setMessage(e.message),
  });
  if (data.isPending) return <p className="muted">Loading…</p>;
  if (data.isError) return <p className="error">{data.error.message}</p>;
  const d = data.data;
  const when = (x: Dialog) =>
    x.last_message_at ? kyivTime.format(new Date(x.last_message_at)) : "—";
  return (
    <>
      <p>
        <Link to="/connectors">← Connectors</Link>
      </p>
      <LoginPanel login={d.login} />
      {message && (
        <p role="status" className="muted">
          {message}
        </p>
      )}
      <section className="card group">
        <h3>To mark ({d.to_mark.length} new dialogs)</h3>
        <p className="muted">
          Including a dialog imports its last 12 months; nothing is stored from ignored dialogs.
        </p>
        <ul className="list">
          {d.to_mark.map((x) => (
            <li key={x.chat_id}>
              <strong>{x.title}</strong>{" "}
              <span className="muted">
                · {x.type} · {when(x)}
              </span>
              <div className="row actions">
                {projects.map((p) => (
                  <button
                    key={p}
                    className="btn"
                    onClick={() =>
                      set.mutate({ id: x.chat_id, body: { included: true, scopes: [p] } })
                    }
                  >
                    Include as {p}
                  </button>
                ))}
                <button
                  className="btn"
                  onClick={() => set.mutate({ id: x.chat_id, body: { included: false } })}
                >
                  Ignore
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>
      <section className="card group">
        <h3>Included ({d.included.length})</h3>
        <table className="table">
          <thead>
            <tr>
              <th>Dialog</th>
              <th>Mark</th>
              <th>Last 7 days</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {d.included.map((x) => (
              <tr key={x.chat_id}>
                <td>
                  {x.title} <span className="muted">· {when(x)}</span>
                </td>
                <td>
                  {x.scopes.map((s) => (
                    <ScopeTag key={s} scope={s} />
                  ))}
                  <select
                    aria-label={`Mark ${x.title}`}
                    className="btn"
                    value=""
                    onChange={(e) =>
                      e.target.value &&
                      set.mutate({ id: x.chat_id, body: { scopes: [e.target.value] } })
                    }
                  >
                    <option value="">Mark…</option>
                    {projects.map((p) => (
                      <option key={p}>{p}</option>
                    ))}
                  </select>
                </td>
                <td>{x.messages_7d} messages</td>
                <td>
                  <button
                    className="btn"
                    onClick={() => set.mutate({ id: x.chat_id, body: { included: false } })}
                  >
                    Ignore
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {d.ignored.length > 0 && (
        <details className="card group">
          <summary>Ignored ({d.ignored.length})</summary>
          <ul className="list">
            {d.ignored.map((x) => (
              <li key={x.chat_id}>
                {x.title}{" "}
                <button
                  className="btn"
                  onClick={() => set.mutate({ id: x.chat_id, body: { included: true } })}
                >
                  Include
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
