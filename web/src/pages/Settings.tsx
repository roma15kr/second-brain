import { useProjects } from "../shell/useProjects";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { api } from "../api/client";
import { Notifications } from "../push/Notifications";

type AppSettings = {
  schedule: {
    morning: string;
    revision: string[];
    evening: string;
    weekly_review_day: number;
    weekly_review_time: string;
    weekly_plan_day: number;
    weekly_plan_time: string;
  };
  quiet_hours: { start: string; end: string };
  ai_budget_usd: number | null;
};
type SettingsData = { app: AppSettings; budget_default_usd: number; month_spend_usd: number };
type Device = {
  id: number;
  device: string;
  routines: string[];
  last_sent_at: string | null;
  last_error: string | null;
};
type Rule = { id: number; kind: string; value: string; scopes: string[] };
type Unsorted = { item_id: number; kind: string; title: string | null; participants: string[] };

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const ROUTINE_LABELS: Record<string, string> = {
  morning: "Morning brief",
  revision: "Mail revision",
  evening: "Evening wrap",
  weekly_review: "Weekly review",
  weekly_plan: "Weekly plan",
};
const hm = (t: string) => t.slice(0, 5);

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="card group">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function Schedule({ data }: { data: SettingsData }) {
  const queryClient = useQueryClient();
  const s = data.app;
  const [form, setForm] = useState({
    morning: hm(s.schedule.morning),
    revision: s.schedule.revision.map(hm).join(", "),
    evening: hm(s.schedule.evening),
    review_day: s.schedule.weekly_review_day,
    review_time: hm(s.schedule.weekly_review_time),
    plan_day: s.schedule.weekly_plan_day,
    plan_time: hm(s.schedule.weekly_plan_time),
    quiet_start: hm(s.quiet_hours.start),
    quiet_end: hm(s.quiet_hours.end),
    budget: s.ai_budget_usd === null ? "" : String(s.ai_budget_usd),
  });
  const [message, setMessage] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () =>
      api("/api/settings", {
        method: "PUT",
        body: {
          app: {
            schedule: {
              morning: form.morning,
              revision: form.revision
                .split(",")
                .map((x) => x.trim())
                .filter(Boolean),
              evening: form.evening,
              weekly_review_day: Number(form.review_day),
              weekly_review_time: form.review_time,
              weekly_plan_day: Number(form.plan_day),
              weekly_plan_time: form.plan_time,
            },
            quiet_hours: { start: form.quiet_start, end: form.quiet_end },
            ai_budget_usd: form.budget === "" ? null : Number(form.budget),
          },
        },
      }),
    onSuccess: () => {
      setMessage("Saved. Applies from the next scheduler cycle.");
      return queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (e) => setMessage(e.message),
  });
  const field = (key: keyof typeof form) => ({
    value: String(form[key]),
    onChange: (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value }),
  });
  const day = (key: "review_day" | "plan_day", label: string) => (
    <select aria-label={label} className="btn" {...field(key)}>
      {DAYS.map((d, i) => (
        <option key={d} value={i}>
          {d}
        </option>
      ))}
    </select>
  );
  return (
    <form
      className="settings-form"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <label>
        Morning brief{" "}
        <input aria-label="Morning brief time" type="time" className="btn" {...field("morning")} />
      </label>
      <label>
        Mail revision passes{" "}
        <input aria-label="Mail revision times" className="btn" {...field("revision")} />
      </label>
      <label>
        Evening wrap{" "}
        <input aria-label="Evening wrap time" type="time" className="btn" {...field("evening")} />
      </label>
      <label>
        Weekly review {day("review_day", "Weekly review day")}
        <input
          aria-label="Weekly review time"
          type="time"
          className="btn"
          {...field("review_time")}
        />
      </label>
      <label>
        Weekly plan {day("plan_day", "Weekly plan day")}
        <input aria-label="Weekly plan time" type="time" className="btn" {...field("plan_time")} />
      </label>
      <label>
        Quiet hours (no push){" "}
        <input
          aria-label="Quiet hours start"
          type="time"
          className="btn"
          {...field("quiet_start")}
        />
        to{" "}
        <input aria-label="Quiet hours end" type="time" className="btn" {...field("quiet_end")} />
      </label>
      <label>
        Monthly AI budget, $
        <input
          aria-label="Monthly AI budget"
          type="number"
          min={0}
          step={1}
          className="btn"
          placeholder={String(data.budget_default_usd)}
          {...field("budget")}
        />
        <span className="muted">spent this month: ${data.month_spend_usd.toFixed(2)}</span>
      </label>
      <div className="row">
        <button className="btn primary" type="submit">
          Save
        </button>
        {message && (
          <span role="status" className="muted">
            {message}
          </span>
        )}
      </div>
    </form>
  );
}

function Devices() {
  const queryClient = useQueryClient();
  const devices = useQuery({
    queryKey: ["push-devices"],
    queryFn: () => api<{ routines: string[]; devices: Device[] }>("/api/settings/push"),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["push-devices"] });
  const update = useMutation({
    mutationFn: ({ id, routines }: { id: number; routines: string[] }) =>
      api(`/api/settings/push/${id}`, { method: "PUT", body: { routines } }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api(`/api/settings/push/${id}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
  return (
    <>
      <Notifications />
      <ul className="list">
        {devices.data?.devices.map((d) => (
          <li key={d.id}>
            <strong>{d.device.slice(0, 60) || `Device ${d.id}`}</strong>
            {d.last_error && <span className="error"> · {d.last_error.slice(0, 80)}</span>}
            <div className="row">
              {devices.data.routines.map((r) => (
                <label key={r} className="muted">
                  <input
                    type="checkbox"
                    aria-label={`${ROUTINE_LABELS[r]} on device ${d.id}`}
                    checked={d.routines.includes(r)}
                    onChange={(e) =>
                      update.mutate({
                        id: d.id,
                        routines: e.target.checked
                          ? [...d.routines, r]
                          : d.routines.filter((x) => x !== r),
                      })
                    }
                  />{" "}
                  {ROUTINE_LABELS[r]}
                </label>
              ))}
              <button className="btn" onClick={() => remove.mutate(d.id)}>
                Remove device
              </button>
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

function Identities() {
  const queryClient = useQueryClient();
  const owner = useQuery({
    queryKey: ["owner"],
    queryFn: () =>
      api<{ emails: string[]; added_emails: string[]; telegram_ids: string[] }>(
        "/api/settings/owner",
      ),
  });
  const [emails, setEmails] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () =>
      api("/api/settings/owner", {
        method: "PUT",
        body: {
          emails: (emails ?? "")
            .split(",")
            .map((e) => e.trim())
            .filter(Boolean),
          telegram_ids: owner.data?.telegram_ids ?? [],
        },
      }),
    onSuccess: () => {
      setMessage("Saved.");
      return queryClient.invalidateQueries({ queryKey: ["owner"] });
    },
    onError: (e) => setMessage(e.message),
  });
  if (!owner.data) return null;
  return (
    <>
      <p className="muted">
        Your addresses decide who wrote last and which promises are yours:{" "}
        {owner.data.emails.join(", ") || "—"}
        {owner.data.telegram_ids.length > 0 && ` · Telegram ${owner.data.telegram_ids.join(", ")}`}
      </p>
      <div className="row">
        <input
          aria-label="Other email addresses of mine"
          className="btn wide-input"
          placeholder="Other addresses of mine, comma-separated"
          value={emails ?? owner.data.added_emails.join(", ")}
          onChange={(e) => setEmails(e.target.value)}
        />
        <button className="btn" onClick={() => save.mutate()}>
          Save addresses
        </button>
        {message && <span className="muted">{message}</span>}
      </div>
    </>
  );
}

function Rules() {
  const SCOPES = useProjects();
  const queryClient = useQueryClient();
  const rules = useQuery({
    queryKey: ["rules"],
    queryFn: () => api<{ rules: Rule[] }>("/api/settings/rules"),
  });
  const [form, setForm] = useState({ kind: "domain", value: "", scope: "quokka" });
  const [message, setMessage] = useState<string | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["rules"] });
  const add = useMutation({
    mutationFn: () =>
      api<{ rescoped_messages: number }>("/api/settings/rules", {
        method: "POST",
        body: { kind: form.kind, value: form.value, scopes: [form.scope] },
      }),
    onSuccess: (r) => {
      setMessage(`Rule added; ${r.rescoped_messages} messages re-labelled.`);
      setForm({ ...form, value: "" });
      return refresh();
    },
    onError: (e) => setMessage(e.message),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api(`/api/settings/rules/${id}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
  return (
    <>
      <ul className="list">
        {rules.data?.rules.map((r) => (
          <li key={r.id}>
            {r.kind} <code>{r.value}</code> → {r.scopes.join(", ")}{" "}
            <button className="btn" onClick={() => remove.mutate(r.id)}>
              Delete
            </button>
          </li>
        ))}
      </ul>
      <form
        className="row"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          if (form.value.trim()) add.mutate();
        }}
      >
        <select
          aria-label="Rule kind"
          className="btn"
          value={form.kind}
          onChange={(e) => setForm({ ...form, kind: e.target.value })}
        >
          <option value="domain">sender domain</option>
          <option value="address">sender address</option>
          <option value="chat">Telegram chat id</option>
          <option value="folder">mail folder/label</option>
        </select>
        <input
          aria-label="Rule value"
          className="btn"
          placeholder="quokka.ua"
          value={form.value}
          onChange={(e) => setForm({ ...form, value: e.target.value })}
        />
        <select
          aria-label="Rule scope"
          className="btn"
          value={form.scope}
          onChange={(e) => setForm({ ...form, scope: e.target.value })}
        >
          {SCOPES.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <button className="btn" type="submit">
          Add rule
        </button>
      </form>
      {message && <p className="muted">{message}</p>}
    </>
  );
}

function UnsortedReview() {
  const SCOPES = useProjects();
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: ["unsorted"],
    queryFn: () => api<{ items: Unsorted[] }>("/api/unsorted"),
  });
  const assign = useMutation({
    mutationFn: ({ id, scope, applyTo }: { id: number; scope: string; applyTo: string }) =>
      api(`/api/items/${id}/scope`, { method: "POST", body: { scope, apply_to: applyTo } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["unsorted"] }),
  });
  const items = list.data?.items ?? [];
  if (items.length === 0) return <p className="muted">Nothing unsorted.</p>;
  return (
    <ul className="list">
      {items.slice(0, 30).map((u) => {
        const applyTo = u.kind === "tg_conversation" ? "chat" : "sender";
        return (
          <li key={u.item_id}>
            {u.title || "(no subject)"}{" "}
            <span className="muted">· {u.participants.slice(0, 3).join(", ")}</span>
            <div className="row actions">
              {SCOPES.map((s) => (
                <button
                  key={s}
                  className="btn"
                  onClick={() => assign.mutate({ id: u.item_id, scope: s, applyTo: "item" })}
                >
                  {s}
                </button>
              ))}
              <select
                aria-label={`Scope for the whole ${applyTo} of ${u.item_id}`}
                className="btn"
                value=""
                onChange={(e) =>
                  e.target.value && assign.mutate({ id: u.item_id, scope: e.target.value, applyTo })
                }
              >
                <option value="">…whole {applyTo}</option>
                {SCOPES.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

// Settings (web-dashboard spec): routines, quiet hours, push per device, identities, AI budget,
// scope rules and unsorted review. Passkeys and recovery codes are in the Security section.
export function Settings({ security }: { security?: ReactNode }) {
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => api<SettingsData>("/api/settings"),
  });
  return (
    <>
      <Section title="Routines and AI budget">
        {settings.data ? <Schedule data={settings.data} /> : <p className="muted">Loading…</p>}
      </Section>
      <Section title="Notifications">
        <Devices />
      </Section>
      {security}
      <Section title="Me">
        <Identities />
      </Section>
      <Section title="Scope rules">
        <Rules />
      </Section>
      <Section title="Unsorted conversations">
        <UnsortedReview />
      </Section>
    </>
  );
}
