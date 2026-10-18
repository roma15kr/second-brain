import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import type { Brief } from "../api/types";
import { BriefView } from "../briefs/BriefView";

type Priority = { title: string; reason: string; refs: string[] };
type WeekData = {
  week_start: string;
  review: Brief | null;
  plan: {
    brief: Brief;
    proposed: Priority[];
    accepted: Priority[] | null;
    accepted_at: string | null;
  } | null;
  weeks: string[];
};

function shift(iso: string, days: number): string {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + days);
  return d.toLocaleDateString("en-CA");
}

function PlanEditor({ plan, onDone }: { plan: NonNullable<WeekData["plan"]>; onDone: () => void }) {
  // Reset by remounting (see the `key` where PlanEditor is used), not by an effect.
  const [items, setItems] = useState<Priority[]>(plan.accepted ?? plan.proposed);
  const accept = useMutation({
    mutationFn: (edited: Priority[] | null) =>
      api(`/api/week/plan/${plan.brief.id}/accept`, {
        method: "POST",
        body: edited ? { priorities: edited } : {},
      }),
    onSuccess: onDone,
  });
  const changed = JSON.stringify(items) !== JSON.stringify(plan.accepted ?? plan.proposed);
  return (
    <section className="card priorities">
      <h3>
        Priorities for this week{" "}
        {plan.accepted ? (
          <span className="tag personal">accepted</span>
        ) : (
          <span className="tag">proposed</span>
        )}
      </h3>
      <ol>
        {items.map((p, i) => (
          <li key={i}>
            <input
              aria-label={`Priority ${i + 1}`}
              className="btn wide"
              value={p.title}
              onChange={(e) =>
                setItems(items.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))
              }
            />
            {p.reason && <div className="muted">{p.reason}</div>}
          </li>
        ))}
      </ol>
      <div className="row">
        {!plan.accepted && !changed && (
          <button className="btn primary" onClick={() => accept.mutate(null)}>
            Accept plan
          </button>
        )}
        {changed && (
          <button className="btn primary" onClick={() => accept.mutate(items)}>
            Save and accept
          </button>
        )}
        <button
          className="btn"
          onClick={() => setItems([...items, { title: "", reason: "", refs: [] }])}
          disabled={items.length >= 5}
        >
          Add priority
        </button>
      </div>
    </section>
  );
}

// The Friday review and the Monday plan of a week (web-dashboard spec: Week page).
export function Week() {
  const queryClient = useQueryClient();
  const [start, setStart] = useState<string | null>(null);
  const week = useQuery({
    queryKey: ["week", start],
    queryFn: () => api<WeekData>(`/api/week${start ? `?start=${start}` : ""}`),
  });
  if (week.isPending) return <p className="muted">Loading…</p>;
  if (week.isError) return <p className="error">{week.error.message}</p>;
  const w = week.data;
  return (
    <>
      <div className="row filters">
        <button className="btn" onClick={() => setStart(shift(w.week_start, -7))}>
          ← Previous week
        </button>
        <strong>Week of {w.week_start}</strong>
        <button className="btn" onClick={() => setStart(shift(w.week_start, 7))}>
          Next week →
        </button>
        {w.weeks.length > 0 && (
          <select
            aria-label="Week"
            className="btn"
            value={w.week_start}
            onChange={(e) => setStart(e.target.value)}
          >
            {!w.weeks.includes(w.week_start) && (
              <option value={w.week_start}>{w.week_start}</option>
            )}
            {w.weeks.map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
          </select>
        )}
      </div>
      {w.plan && (
        <PlanEditor
          key={`${w.plan.brief.id}-${w.plan.accepted_at ?? "proposed"}`}
          plan={w.plan}
          onDone={() => queryClient.invalidateQueries({ queryKey: ["week"] })}
        />
      )}
      {w.plan && <BriefView brief={w.plan.brief} />}
      {w.review && <BriefView brief={w.review} />}
      {!w.plan && !w.review && (
        <p className="muted">
          No weekly review or plan for this week yet (Friday 19:00, Monday 08:00).
        </p>
      )}
    </>
  );
}
