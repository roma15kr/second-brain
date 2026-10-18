import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { api } from "../api/client";
import type { Brief } from "../api/types";
import { BriefView } from "../briefs/BriefView";

type BriefDetail = Brief & { opened: boolean; useful: boolean | null };

// One brief with a usefulness rating; opening it is recorded (push or in-app).
export function BriefPage() {
  const { id } = useParams();
  const [search] = useSearchParams();
  const queryClient = useQueryClient();
  const brief = useQuery({
    queryKey: ["brief", id],
    queryFn: () => api<BriefDetail>(`/api/briefs/${id}`),
  });
  const recorded = useRef<string | null>(null);
  useEffect(() => {
    if (!id || recorded.current === id) return;
    recorded.current = id;
    const via = search.get("via") === "push" ? "push" : "app";
    void api(`/api/briefs/${id}/opened`, { method: "POST", body: { via } }).catch(() => {});
  }, [id, search]);
  const rate = useMutation({
    mutationFn: (useful: boolean) =>
      api(`/api/briefs/${id}/rating`, { method: "POST", body: { useful } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["brief", id] }),
  });

  if (brief.isPending) return <p className="muted">Loading…</p>;
  if (brief.isError) return <p className="error">{brief.error.message}</p>;
  const b = brief.data;
  return (
    <>
      <p>
        <Link to="/briefs">← All briefs</Link>
      </p>
      <BriefView brief={b} />
      <div className="row rating">
        <span className="muted">Was this useful?</span>
        <button
          className={`btn ${b.useful === true ? "primary" : ""}`}
          onClick={() => rate.mutate(true)}
        >
          👍 Useful
        </button>
        <button
          className={`btn ${b.useful === false ? "primary" : ""}`}
          onClick={() => rate.mutate(false)}
        >
          👎 Not useful
        </button>
      </div>
    </>
  );
}
