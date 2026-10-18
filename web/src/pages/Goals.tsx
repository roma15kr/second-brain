import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import { ScopeTag } from "../shell/ScopeTag";

type Goal = {
  id: number;
  title: string;
  scope: string;
  measure: string;
  deadline: string | null;
  status: "proposed" | "confirmed";
  document: string | null;
  document_id: number | null;
  source_excerpt: string;
};

function GoalRow({ g, onChanged }: { g: Goal; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(g.title);
  const [measure, setMeasure] = useState(g.measure);
  const [deadline, setDeadline] = useState(g.deadline ?? "");
  const act = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/api/goals/${g.id}`, { method: "POST", body }),
    onSuccess: () => {
      setEditing(false);
      onChanged();
    },
  });
  const edits = { title, measure, ...(deadline ? { deadline } : {}) };
  return (
    <li>
      {editing ? (
        <div className="row">
          <input
            aria-label="Goal title"
            className="btn wide-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <input
            aria-label="Measure"
            className="btn"
            placeholder="measure"
            value={measure}
            onChange={(e) => setMeasure(e.target.value)}
          />
          <input
            aria-label="Deadline"
            type="date"
            className="btn"
            value={deadline}
            onChange={(e) => setDeadline(e.target.value)}
          />
        </div>
      ) : (
        <div>
          <b>{g.title}</b> <ScopeTag scope={g.scope} />
          <span className="muted">
            {g.measure && ` · measure: ${g.measure}`}
            {g.deadline && ` · by ${g.deadline}`}
          </span>
        </div>
      )}
      {g.source_excerpt && (
        <blockquote className="match">
          {g.source_excerpt}
          {g.document_id && (
            <>
              {" "}
              — <Link to={`/library/${g.document_id}`}>{g.document}</Link>
            </>
          )}
        </blockquote>
      )}
      <div className="row actions">
        {g.status === "proposed" && (
          <button
            className="btn primary"
            onClick={() => act.mutate({ action: "confirm", ...(editing ? edits : {}) })}
          >
            Confirm
          </button>
        )}
        {editing ? (
          <button className="btn" onClick={() => act.mutate({ action: "edit", ...edits })}>
            Save
          </button>
        ) : (
          <button className="btn" onClick={() => setEditing(true)}>
            Edit
          </button>
        )}
        <button className="btn" onClick={() => act.mutate({ action: "remove" })}>
          Remove
        </button>
      </div>
    </li>
  );
}

// Goals proposed from core documents; only confirmed goals guide priorities and reviews.
export function Goals() {
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: ["goals"],
    queryFn: () => api<{ goals: Goal[] }>("/api/goals"),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["goals"] });
  const goals = list.data?.goals ?? [];
  const proposed = goals.filter((g) => g.status === "proposed");
  const confirmed = goals.filter((g) => g.status === "confirmed");
  if (goals.length === 0) return null;
  return (
    <>
      {proposed.length > 0 && (
        <section className="card group">
          <h3>Goals to confirm ({proposed.length})</h3>
          <ul className="list">
            {proposed.map((g) => (
              <GoalRow key={g.id} g={g} onChanged={refresh} />
            ))}
          </ul>
        </section>
      )}
      {confirmed.length > 0 && (
        <section className="card group">
          <h3>My goals</h3>
          <ul className="list">
            {confirmed.map((g) => (
              <GoalRow key={g.id} g={g} onChanged={refresh} />
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
