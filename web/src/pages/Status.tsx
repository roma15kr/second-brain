import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { kyivTime } from "../briefs/BriefView";

type Source = {
  source: string;
  healthy: boolean;
  last_ok: string | null;
  last_error: string | null;
};
type StatusData = {
  system: {
    healthy: boolean;
    sources: Source[];
    clickup?: {
      source: string;
      label: string;
      lists_syncing: number;
      tasks: number;
      last_ok: string | null;
      last_error: string | null;
      healthy: boolean;
      note: string | null;
    }[];
    index_queue: { pending: number; failed: number };
    items: Record<string, number>;
    database_mb: number | null;
    backup: {
      last_status: string | null;
      last_at: string | null;
      detail: string | null;
      stale: boolean;
    };
  };
  routine_runs: {
    routine: string;
    slot: string;
    status: string;
    delayed: boolean;
    error: string | null;
  }[];
  ai: {
    month_spend_usd: number;
    budget_usd: number;
    by_purpose: { purpose: string; model: string; usd: number }[];
  };
  usefulness: {
    days: number;
    briefs: { total: number; used: number; share: number | null; target: number };
    loops: { total: number; resolved: number; share: number | null; target: number };
  };
  audio?: {
    bytes: number;
    files: number;
    growth_bytes_per_month: number;
    deletions_next_30_days: number;
    last_backup: { status: string; detail: string; at: string } | null;
  };
  assistant?: {
    requests_7d: number;
    requests_target: number;
    approved_from_requests: number | null;
    approved_target: number;
  };
  suggestions?: {
    kind: string;
    accepted: number;
    edited: number;
    discarded: number;
    rate: number | null;
    cooling: boolean;
  }[];
};

const SUGGESTION_KINDS: Record<string, string> = {
  reply_email: "email replies",
  reply_tg: "Telegram replies",
  task: "task drafts",
  delegate: "delegations",
  nudge: "nudges",
  decline: "declines",
};

const gb = (b: number) => `${(b / 1024 ** 3).toFixed(1)} GB`;
const pct = (x: number | null) => (x === null ? "—" : `${Math.round(x * 100)}%`);

function Metric({
  label,
  share,
  target,
  detail,
}: {
  label: string;
  share: number | null;
  target: number;
  detail: string;
}) {
  const ok = share !== null && share >= target;
  return (
    <div className="metric">
      <div className={`kpi ${share === null ? "" : ok ? "good" : "bad"}`}>{pct(share)}</div>
      <div>{label}</div>
      <div className="muted">
        {detail} · target {pct(target)}
      </div>
    </div>
  );
}

// Status (web-dashboard spec): source health, routine runs, queue, backups, AI spend, usefulness.
export function Status() {
  const status = useQuery({
    queryKey: ["status"],
    queryFn: () => api<StatusData>("/api/status"),
    refetchInterval: 60_000,
  });
  if (status.isPending) return <p className="muted">Loading…</p>;
  if (status.isError) return <p className="error">{status.error.message}</p>;
  const { system, routine_runs, ai, usefulness } = status.data;
  const kinds = status.data.suggestions ?? [];
  const accepted = kinds.reduce((n, k) => n + k.accepted, 0);
  const decided = accepted + kinds.reduce((n, k) => n + k.discarded, 0);
  return (
    <div className="grid">
      <section className="card">
        <h3>Usefulness (last {usefulness.days} days)</h3>
        <div className="row">
          <Metric
            label="briefs opened or rated"
            share={usefulness.briefs.share}
            target={usefulness.briefs.target}
            detail={`${usefulness.briefs.used} of ${usefulness.briefs.total}`}
          />
          <Metric
            label="loops resolved"
            share={usefulness.loops.share}
            target={usefulness.loops.target}
            detail={`${usefulness.loops.resolved} of ${usefulness.loops.total}`}
          />
          <Metric
            label="assistant suggestions approved"
            share={decided ? accepted / decided : null}
            target={0.6}
            detail={`${accepted} of ${decided}`}
          />
        </div>
        {status.data.assistant && (
          <p>
            Assistant: {status.data.assistant.requests_7d} requests this week (target{" "}
            {status.data.assistant.requests_target}) ·{" "}
            {pct(status.data.assistant.approved_from_requests)} of drafts from requests approved
            (target {pct(status.data.assistant.approved_target)})
          </p>
        )}
        {status.data.audio && status.data.audio.files > 0 && (
          <p>
            Meeting audio: {gb(status.data.audio.bytes)} in {status.data.audio.files} files, +
            {gb(status.data.audio.growth_bytes_per_month)}/month
            {status.data.audio.deletions_next_30_days > 0 &&
              ` · ${status.data.audio.deletions_next_30_days} due for deletion in 30 days`}
            {status.data.audio.last_backup && (
              <span className="muted">
                {" "}
                · backup {status.data.audio.last_backup.status}:{" "}
                {status.data.audio.last_backup.detail}
              </span>
            )}
          </p>
        )}
        {kinds.length > 0 && (
          <ul className="list">
            {kinds.map((k) => (
              <li key={k.kind}>
                {SUGGESTION_KINDS[k.kind] ?? k.kind}: {pct(k.rate)} approved
                <span className="muted">
                  {" "}
                  · {k.accepted} approved ({k.edited} edited) · {k.discarded} discarded
                  {k.cooling && " · fewer for now: the last 5 were discarded"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="card">
        <h3>{system.healthy ? "✅ Sources healthy" : "⚠ Needs attention"}</h3>
        <ul className="list">
          {system.sources.map((s) => (
            <li key={s.source}>
              {s.healthy ? "✅" : "⚠"} {s.source}
              {s.last_ok && (
                <span className="muted"> · synced {kyivTime.format(new Date(s.last_ok))}</span>
              )}
              {s.last_error && <div className="error">{s.last_error}</div>}
            </li>
          ))}
          {(system.clickup ?? []).map((c) => (
            <li key={c.source}>
              {c.healthy ? "✅" : "⚠"} ClickUp {c.label}
              <span className="muted">
                {" "}
                · {c.lists_syncing} lists · {c.tasks} tasks
                {c.last_ok && ` · synced ${kyivTime.format(new Date(c.last_ok))}`}
              </span>
              {c.note && <div className="muted">{c.note}</div>}
              {c.last_error && <div className="error">{c.last_error}</div>}
            </li>
          ))}
        </ul>
        <p className="muted">
          Index queue: {system.index_queue.pending} pending, {system.index_queue.failed} failed ·{" "}
          {Object.entries(system.items)
            .map(([k, n]) => `${n} ${k}`)
            .join(", ")}
          {system.database_mb !== null && ` · DB ${system.database_mb} MB`}
        </p>
      </section>
      <section className="card">
        <h3>Backups</h3>
        <p className={system.backup.stale ? "error" : ""}>
          {system.backup.last_status ?? "none yet"}
          {system.backup.last_at && ` · ${kyivTime.format(new Date(system.backup.last_at))}`}
          {system.backup.stale && " · stale (older than 2 days)"}
        </p>
        {system.backup.detail && <p className="muted">{system.backup.detail}</p>}
      </section>
      <section className="card">
        <h3>AI spend this month</h3>
        <p>
          <span className="kpi">${ai.month_spend_usd.toFixed(2)}</span> of $
          {ai.budget_usd.toFixed(0)}
          {ai.month_spend_usd >= ai.budget_usd && (
            <strong className="error"> · cap reached: briefs are data-only</strong>
          )}
        </p>
        <ul className="list">
          {ai.by_purpose.map((p) => (
            <li key={`${p.purpose}-${p.model}`} className="muted">
              {p.purpose} ({p.model}): ${p.usd.toFixed(2)}
            </li>
          ))}
        </ul>
      </section>
      <section className="card">
        <h3>Routine runs</h3>
        <ul className="list">
          {routine_runs.map((r) => (
            <li key={`${r.routine}-${r.slot}`}>
              {r.status === "done" ? "✅" : r.status === "failed" ? "⚠" : "…"} {r.routine}{" "}
              <span className="muted">
                {kyivTime.format(new Date(r.slot))}
                {r.delayed && " · delayed"}
              </span>
              {r.error && <div className="error">{r.error}</div>}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
