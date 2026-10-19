import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Brief } from "../api/types";
import { BriefView } from "../briefs/BriefView";
import { MeetingLine, type Meeting } from "./Meetings";

function TodayMeetings({ meetings }: { meetings: Meeting[] }) {
  if (!meetings.length) return null;
  return (
    <section className="card group">
      <h3>Today's meetings</h3>
      <ul className="list">
        {meetings.map((m) => (
          <MeetingLine key={m.id} m={m} />
        ))}
      </ul>
    </section>
  );
}

export function Today() {
  const today = useQuery({
    queryKey: ["today"],
    queryFn: () => api<{ brief: Brief | null; meetings?: Meeting[] }>("/api/today"),
  });
  if (today.isPending) return <p className="muted">Loading…</p>;
  if (today.isError) return <p className="error">{today.error.message}</p>;
  const brief = today.data.brief;
  return (
    <>
      <TodayMeetings meetings={today.data.meetings ?? []} />
      {brief ? (
        <BriefView brief={brief} />
      ) : (
        <p className="muted">No brief yet — the first one arrives at 08:00.</p>
      )}
    </>
  );
}
