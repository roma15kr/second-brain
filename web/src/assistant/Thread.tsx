import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { api } from "../api/client";
import { AskBox } from "./Ask";

type Request = {
  id: number;
  text: string;
  status: "running" | "done" | "failed";
  steps: { tool: string; summary: string }[];
  answer: string | null;
  refs: { ref: string; item_id: number; title: string | null }[];
  error: string | null;
  cost_usd: number;
};
type ThreadData = { id: number; title: string; requests: Request[] };

function Turn({ r }: { r: Request }) {
  return (
    <li className="turn">
      <div className="question">{r.text}</div>
      {r.steps.length > 0 && (
        <ul className="steps muted">
          {r.steps.map((s, i) => (
            <li key={i}>{s.summary}</li>
          ))}
        </ul>
      )}
      {r.status === "running" && <div className="muted">Working…</div>}
      {r.status === "failed" && <div className="error">{r.error}</div>}
      {r.answer && <div className="answer">{r.answer}</div>}
      {r.refs.length > 0 && (
        <div className="row">
          {r.refs.map((ref) => (
            <Link key={ref.ref} className="tag" to={`/c/${ref.item_id}`}>
              {ref.title || ref.ref}
            </Link>
          ))}
        </div>
      )}
      {r.status === "done" && <div className="muted small">${r.cost_usd.toFixed(3)}</div>}
    </li>
  );
}

// One request thread: questions, the steps taken, answers with sources, and follow-ups.
export function Thread() {
  const { id } = useParams();
  const queryClient = useQueryClient();
  const key = ["assistant-thread", id];
  const thread = useQuery({
    queryKey: key,
    queryFn: () => api<ThreadData>(`/api/assistant/threads/${id}`),
    refetchInterval: (q) =>
      q.state.data?.requests.some((r) => r.status === "running") ? 1_500 : false,
  });
  if (thread.isPending) return <p className="muted">Loading…</p>;
  if (thread.isError) return <p className="error">{thread.error.message}</p>;
  return (
    <section className="card">
      <p>
        <Link to="/assistant">← Assistant</Link>
      </p>
      <ul className="list thread">
        {thread.data.requests.map((r) => (
          <Turn key={r.id} r={r} />
        ))}
      </ul>
      <AskBox
        threadId={thread.data.id}
        placeholder="Follow up…"
        onAsked={() => void queryClient.invalidateQueries({ queryKey: key })}
      />
    </section>
  );
}
