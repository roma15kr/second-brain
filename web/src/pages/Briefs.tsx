import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import { kyivTime } from "../briefs/BriefView";

type BriefRow = {
  id: number;
  routine: string;
  title: string;
  headline: string;
  mode: string;
  created_at: string;
  opened: boolean;
  useful: boolean | null;
};

const FILTERS: [string, string | null][] = [
  ["All", null],
  ["Morning", "morning"],
  ["Mail revision", "revision"],
  ["Evening", "evening"],
  ["Weekly review", "weekly_review"],
  ["Weekly plan", "weekly_plan"],
];

const day = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Kyiv",
  day: "numeric",
  month: "short",
});

// Every routine output by date, with type filters and opened state (web-dashboard spec).
export function Briefs() {
  const [routine, setRoutine] = useState<string | null>(null);
  const list = useInfiniteQuery({
    queryKey: ["briefs", routine],
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams();
      if (routine) params.set("routine", routine);
      if (pageParam) params.set("before", String(pageParam));
      const qs = params.toString();
      return api<{ briefs: BriefRow[]; next_before: number | null }>(
        `/api/briefs${qs ? `?${qs}` : ""}`,
      );
    },
    getNextPageParam: (last) => last.next_before,
  });
  const rows = list.data?.pages.flatMap((p) => p.briefs) ?? [];
  return (
    <>
      <div className="row filters">
        {FILTERS.map(([label, value]) => (
          <button
            key={label}
            className={`btn ${routine === value ? "primary" : ""}`}
            onClick={() => setRoutine(value)}
          >
            {label}
          </button>
        ))}
      </div>
      {list.isPending && <p className="muted">Loading…</p>}
      {list.isError && <p className="error">{list.error.message}</p>}
      <ul className="list card">
        {rows.map((b) => (
          <li key={b.id} className={b.opened ? "" : "unread"}>
            <Link to={`/briefs/${b.id}`}>
              <span className="muted">
                {day.format(new Date(b.created_at))} {kyivTime.format(new Date(b.created_at))}
              </span>{" "}
              <strong>{b.title}</strong> — {b.headline.replace(`${b.title}: `, "")}
            </Link>
            {b.useful !== null && <span aria-label="rating"> {b.useful ? "👍" : "👎"}</span>}
          </li>
        ))}
        {list.isSuccess && rows.length === 0 && <li className="muted">No briefs yet.</li>}
      </ul>
      {list.hasNextPage && (
        <button className="btn" onClick={() => list.fetchNextPage()}>
          Load more
        </button>
      )}
    </>
  );
}
