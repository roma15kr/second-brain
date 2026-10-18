import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Brief } from "../api/types";
import { BriefView } from "../briefs/BriefView";

export function Today() {
  const today = useQuery({
    queryKey: ["today"],
    queryFn: () => api<{ brief: Brief | null }>("/api/today"),
  });
  if (today.isPending) return <p className="muted">Loading…</p>;
  if (today.isError) return <p className="error">{today.error.message}</p>;
  const brief = today.data.brief;
  if (!brief) return <p className="muted">No brief yet — the first one arrives at 08:00.</p>;
  return <BriefView brief={brief} />;
}
