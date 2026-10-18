import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Brief, BriefItem } from "../api/types";

const KIND_ICON: Record<string, string> = { email_thread: "✉", tg_conversation: "✈" };
const time = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Kyiv",
  weekday: "short",
  hour: "2-digit",
  minute: "2-digit",
});

function Item({ item }: { item: BriefItem }) {
  const title = item.title || "(no subject)";
  return (
    <li>
      <span aria-hidden>{KIND_ICON[item.kind] ?? "•"} </span>
      {item.link ? (
        <a href={item.link} target="_blank" rel="noreferrer">
          {title}
        </a>
      ) : (
        <strong>{title}</strong>
      )}
      <span className="muted"> · {time.format(new Date(item.last_activity_at))}</span>
      {item.summary && <div className="muted">{item.summary}</div>}
    </li>
  );
}

export function Today() {
  const today = useQuery({
    queryKey: ["today"],
    queryFn: () => api<{ brief: Brief | null }>("/api/today"),
  });
  if (today.isPending) return <p className="muted">Loading…</p>;
  if (today.isError) return <p className="error">{today.error.message}</p>;
  const brief = today.data.brief;
  if (!brief) return <p className="muted">No brief yet — the first one arrives at 08:00.</p>;
  return (
    <article className="card brief">
      <h2>{brief.headline}</h2>
      <p className="muted">
        {time.format(new Date(brief.window_start))} → {time.format(new Date(brief.window_end))}
        {brief.mode === "data" && " · data only"}
      </p>
      {brief.sections.map((s) => (
        <section key={s.title}>
          <h3>
            <span className={`tag ${s.title}`}>{s.title}</span>{" "}
            <span className="muted">{s.text}</span>
          </h3>
          <ul className="list">
            {s.items.map((item) => (
              <Item key={item.ref} item={item} />
            ))}
          </ul>
        </section>
      ))}
    </article>
  );
}
