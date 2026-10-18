import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import { Rules } from "../pages/Settings";
import { ScopeTag } from "../shell/ScopeTag";
import { useProjects } from "../shell/useProjects";

type Mailbox = {
  id: number;
  label: string;
  address: string;
  preset: string;
  scopes: string[];
  state: string;
  password_set: boolean;
};
type Sender = { address: string; threads: number };

function AddMailbox({ onDone }: { onDone: () => void }) {
  const projects = useProjects();
  const [f, setF] = useState({
    preset: "gmail",
    label: "",
    address: "",
    password: "",
    imap_host: "",
    imap_port: "993",
    smtp_host: "",
    smtp_port: "465",
    smtp_security: "ssl",
    scope: "personal",
  });
  const [error, setError] = useState<string | null>(null);
  const add = useMutation({
    mutationFn: () =>
      api("/api/connectors/mail", {
        method: "POST",
        body: {
          mailbox: {
            preset: f.preset,
            label: f.label,
            address: f.address,
            password: f.password,
            imap_host: f.imap_host,
            imap_port: Number(f.imap_port),
            smtp_host: f.smtp_host,
            smtp_port: Number(f.smtp_port),
            smtp_security: f.smtp_security,
            scopes: [f.scope],
          },
        },
      }),
    onSuccess: () => {
      setError(null);
      setF({ ...f, password: "", address: "", label: "" });
      onDone();
    },
    onError: (e) => setError(e.message),
  });
  const field = (k: keyof typeof f, label: string, type = "text") => (
    <input
      aria-label={label}
      placeholder={label}
      type={type}
      className="btn"
      value={f[k]}
      onChange={(e) => setF({ ...f, [k]: e.target.value })}
    />
  );
  return (
    <form
      className="settings-form"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        add.mutate();
      }}
    >
      <div className="row">
        <select
          aria-label="Provider"
          className="btn"
          value={f.preset}
          onChange={(e) => setF({ ...f, preset: e.target.value })}
        >
          <option value="gmail">Gmail / Google Workspace</option>
          <option value="imap">Other (IMAP + SMTP)</option>
        </select>
        {field("label", "Name, e.g. Personal Gmail")}
      </div>
      <div className="row">
        {field("address", "Email address")}
        {field("password", "App password", "password")}
      </div>
      {f.preset === "imap" && (
        <div className="row">
          {field("imap_host", "IMAP server")}
          {field("imap_port", "IMAP port")}
          {field("smtp_host", "SMTP server")}
          {field("smtp_port", "SMTP port")}
          <select
            aria-label="SMTP security"
            className="btn"
            value={f.smtp_security}
            onChange={(e) => setF({ ...f, smtp_security: e.target.value })}
          >
            <option value="ssl">SSL</option>
            <option value="starttls">STARTTLS</option>
          </select>
        </div>
      )}
      <div className="row">
        <label>
          Default mark{" "}
          <select
            aria-label="Default mark"
            className="btn"
            value={f.scope}
            onChange={(e) => setF({ ...f, scope: e.target.value })}
          >
            {projects.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </label>
        <button
          className="btn primary"
          type="submit"
          disabled={!f.address || !f.password || add.isPending}
        >
          {add.isPending ? "Checking IMAP and SMTP…" : "Connect"}
        </button>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </form>
  );
}

function MailboxRow({ m, onChanged }: { m: Mailbox; onChanged: () => void }) {
  const projects = useProjects();
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/api/connectors/mail/${m.id}`, { method: "PATCH", body }),
    onSuccess: () => {
      setPassword("");
      setMessage("Saved.");
      onChanged();
    },
    onError: (e) => setMessage(e.message),
  });
  const disconnect = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/api/connectors/mail/${m.id}/disconnect`, { method: "POST", body }),
    onSuccess: onChanged,
    onError: (e) => setMessage(e.message),
  });
  return (
    <li>
      <b>{m.label}</b>{" "}
      <span className="muted">
        {m.address} · {m.preset}
      </span>{" "}
      {m.scopes.map((s) => (
        <ScopeTag key={s} scope={s} />
      ))}
      {m.state === "disconnected" && <span className="state no"> disconnected</span>}
      {m.state === "active" && (
        <div className="row actions">
          <select
            aria-label={`Default mark for ${m.address}`}
            className="btn"
            value=""
            onChange={(e) => e.target.value && update.mutate({ scopes: [e.target.value] })}
          >
            <option value="">Mark…</option>
            {projects.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
          <input
            aria-label={`New app password for ${m.address}`}
            type="password"
            className="btn"
            placeholder={m.password_set ? "•••••• set — replace" : "App password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button className="btn" disabled={!password} onClick={() => update.mutate({ password })}>
            Replace password
          </button>
          <button className="btn" onClick={() => disconnect.mutate({})}>
            Disconnect (keep searchable)
          </button>
          <button className="btn" onClick={() => disconnect.mutate({ remove_from_search: true })}>
            Disconnect and remove from search
          </button>
          <button
            className="btn"
            onClick={() => {
              if (window.prompt("Type DELETE to also delete the archived originals") === "DELETE") {
                disconnect.mutate({ delete_archive: true, confirm: "DELETE" });
              }
            }}
          >
            Delete everything…
          </button>
        </div>
      )}
      {message && <div className="muted">{message}</div>}
    </li>
  );
}

function SendersToMark() {
  const queryClient = useQueryClient();
  const projects = useProjects();
  const senders = useQuery({
    queryKey: ["senders"],
    queryFn: () => api<{ senders: Sender[] }>("/api/connectors/mail/senders"),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["senders"] });
  const rule = useMutation({
    mutationFn: ({ kind, value, scope }: { kind: string; value: string; scope: string }) =>
      api("/api/settings/rules", { method: "POST", body: { kind, value, scopes: [scope] } }),
    onSuccess: refresh,
  });
  const noise = useMutation({
    mutationFn: (address: string) =>
      api("/api/senders/pref", { method: "POST", body: { address, pref: "noise" } }),
    onSuccess: refresh,
  });
  const list = senders.data?.senders ?? [];
  if (list.length === 0) return <p className="muted">No unsorted senders in the last 30 days.</p>;
  return (
    <ul className="list">
      {list.map((s) => {
        const domain = s.address.split("@")[1];
        return (
          <li key={s.address}>
            {s.address} <span className="muted">· {s.threads} threads</span>
            <div className="row actions">
              {projects.map((p) => (
                <button
                  key={p}
                  className="btn"
                  onClick={() => rule.mutate({ kind: "address", value: s.address, scope: p })}
                >
                  {p}
                </button>
              ))}
              <select
                aria-label={`Mark domain ${domain}`}
                className="btn"
                value=""
                onChange={(e) =>
                  e.target.value &&
                  rule.mutate({ kind: "domain", value: domain, scope: e.target.value })
                }
              >
                <option value="">all of @{domain}…</option>
                {projects.map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </select>
              <button className="btn" onClick={() => noise.mutate(s.address)}>
                noise
              </button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

// Connectors › Mail: mailboxes, marks, rules and senders to mark (connectors spec).
export function MailConnector() {
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: ["mailboxes"],
    queryFn: () => api<{ mailboxes: Mailbox[] }>("/api/connectors/mail"),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["mailboxes"] });
    void queryClient.invalidateQueries({ queryKey: ["connectors"] });
  };
  return (
    <>
      <p>
        <Link to="/connectors">← Connectors</Link>
      </p>
      <section className="card group">
        <h3>Connect a mailbox</h3>
        <p className="muted">
          Use an app password (Google Account → Security → App passwords). Nothing is ever sent
          without your tap.
        </p>
        <AddMailbox onDone={refresh} />
      </section>
      <section className="card group">
        <h3>Connected here</h3>
        <ul className="list">
          {list.data?.mailboxes.map((m) => (
            <MailboxRow key={m.id} m={m} onChanged={refresh} />
          ))}
          {list.data?.mailboxes.length === 0 && (
            <li className="muted">
              None yet (the main Gmail comes from the server configuration).
            </li>
          )}
        </ul>
      </section>
      <section className="card group">
        <h3>Senders to mark (unsorted, last 30 days)</h3>
        <SendersToMark />
      </section>
      <section className="card group">
        <h3>Rules (first match wins)</h3>
        <Rules />
      </section>
    </>
  );
}
