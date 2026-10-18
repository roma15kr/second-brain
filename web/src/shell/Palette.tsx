import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useNavigate } from "react-router";
import { api } from "../api/client";
import { APPS } from "./apps";

type Entry = { key: string; label: string; hint: string; go: () => void };
type PersonHit = { id: number; name: string };
type SearchHit = { item_id: number; title: string; kind: string };

function useDebounced(value: string, ms = 250) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

// ⌘K command palette: pages, people, conversations and briefs (web-dashboard spec).
export function Palette({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const term = useDebounced(q.trim());
  useEffect(() => input.current?.focus(), []);

  const people = useQuery({
    queryKey: ["palette-people", term],
    enabled: term.length >= 2,
    queryFn: () =>
      api<{ people: PersonHit[] }>(`/api/people?q=${encodeURIComponent(term)}&limit=5`),
  });
  const search = useQuery({
    queryKey: ["palette-search", term],
    enabled: term.length >= 3,
    queryFn: () =>
      api<{ results: SearchHit[] }>(`/api/search?q=${encodeURIComponent(term)}&limit=5`),
  });

  const entries = useMemo<Entry[]>(() => {
    const go = (path: string) => () => {
      navigate(path);
      onClose();
    };
    const lower = q.trim().toLowerCase();
    const pages = APPS.filter((a) => !lower || a.label.toLowerCase().includes(lower)).map((a) => ({
      key: `page-${a.path}`,
      label: `${a.icon} ${a.label}`,
      hint: "page",
      go: go(a.path),
    }));
    const ppl = (people.data?.people ?? []).map((p) => ({
      key: `person-${p.id}`,
      label: `👤 ${p.name}`,
      hint: "person",
      go: go(`/people/${p.id}`),
    }));
    const hits = (search.data?.results ?? []).map((r) => ({
      key: `item-${r.item_id}`,
      label: `${r.kind === "tg_conversation" ? "✈" : "✉"} ${r.title || "(no subject)"}`,
      hint: "conversation",
      go: go(`/c/${r.item_id}`),
    }));
    const searchAll = lower
      ? [
          {
            key: "search",
            label: `🔎 Search for “${q.trim()}”`,
            hint: "search",
            go: go(`/search?q=${encodeURIComponent(q.trim())}`),
          },
        ]
      : [];
    return [...ppl, ...pages, ...hits, ...searchAll];
  }, [q, people.data, search.data, navigate, onClose]);

  function onKey(e: KeyboardEvent) {
    if (e.key === "Escape") onClose();
    else if (e.key === "ArrowDown") setActive((a) => Math.min(a + 1, entries.length - 1));
    else if (e.key === "ArrowUp") setActive((a) => Math.max(a - 1, 0));
    else if (e.key === "Enter") entries[Math.min(active, entries.length - 1)]?.go();
    else return;
    e.preventDefault();
  }

  return (
    <div className="palette-backdrop" onClick={onClose}>
      <div
        className="palette card"
        role="dialog"
        aria-label="Command palette"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={input}
          aria-label="Search or jump to"
          placeholder="Search or jump to… (people, chats, briefs, pages)"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setActive(0);
          }}
          onKeyDown={onKey}
        />
        <ul role="listbox">
          {entries.map((e, i) => (
            <li
              key={e.key}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : ""}
              onMouseEnter={() => setActive(i)}
              onClick={e.go}
            >
              {e.label} <span className="muted">{e.hint}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
