import type { Brief, BriefItem, BriefSection } from "../api/types";

const KIND_ICON: Record<string, string> = { email_thread: "✉", tg_conversation: "✈", loop: "↺" };
export const kyivTime = new Intl.DateTimeFormat("en-GB", {
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
      <span className="muted"> · {kyivTime.format(new Date(item.last_activity_at))}</span>
      {item.reason ? (
        <div>{item.reason}</div>
      ) : (
        item.summary && <div className="muted">{item.summary}</div>
      )}
    </li>
  );
}

function SectionView({ section: s }: { section: BriefSection }) {
  if (s.kind === "note") {
    return (
      <p className="note">
        <strong>{s.title}:</strong> {s.text}
      </p>
    );
  }
  const heading =
    s.kind === "ai" || s.kind === "focus" || s.kind === "group" ? (
      <h3>{s.kind === "focus" ? "★ Focus" : s.title}</h3>
    ) : (
      <h3>
        <span className={`tag ${s.title}`}>{s.title}</span> <span className="muted">{s.text}</span>
      </h3>
    );
  return (
    <section className={`section-${s.kind ?? "data"}`}>
      {heading}
      {s.kind === "ai" && <p>{s.text}</p>}
      <ul className="list">
        {s.items.map((item) => (
          <Item key={item.ref} item={item} />
        ))}
      </ul>
    </section>
  );
}

// A brief page body: AI sections and focus (each line linked to its source), notes, then all
// activity per scope.
export function BriefView({ brief }: { brief: Brief }) {
  return (
    <article className="card brief">
      <h2>{brief.headline}</h2>
      <p className="muted">
        {kyivTime.format(new Date(brief.window_start))} →{" "}
        {kyivTime.format(new Date(brief.window_end))}
        {brief.mode === "data" && " · data only"}
      </p>
      {brief.sections.map((s, i) => (
        <SectionView key={`${s.title}-${i}`} section={s} />
      ))}
    </article>
  );
}
