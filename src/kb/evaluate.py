"""Acceptance evaluation: real questions with their expected answers, run against search.

Question file (YAML list):
  - q: "who asked to fix email forwarding via SMTP"
    expect:                       # any one match counts as found
      title_contains: "Вячеслав"  # and/or text_contains / locator_contains / item_id
    note: "Telegram, Вячеслав Никонов, Mirohost SMTP"

`text_contains` is matched against title, summary, excerpt and context messages.
Reported: recall@k (answer in the top k), MRR, latency p50/p95, and every miss.
"""

from __future__ import annotations

import json
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

Search = Callable[[str, int], list[dict[str, Any]]]


@dataclass
class Case:
    q: str
    expect: dict[str, Any]
    note: str = ""


@dataclass
class Outcome:
    case: Case
    rank: int | None  # 1-based position of the first matching result
    seconds: float
    top: list[str] = field(default_factory=list)


def load(path: str | Path) -> list[Case]:
    data = yaml.safe_load(Path(path).read_text()) or []
    cases = []
    for i, row in enumerate(data, 1):
        if not isinstance(row, dict) or "q" not in row or not row.get("expect"):
            raise ValueError(f"case {i}: needs 'q' and a non-empty 'expect'")
        cases.append(Case(str(row["q"]), dict(row["expect"]), str(row.get("note", ""))))
    return cases


def _haystack(r: dict[str, Any]) -> str:
    parts = [r.get("title") or "", r.get("summary") or "", r.get("excerpt") or ""]
    for c in (r.get("extra") or {}).get("context") or []:
        parts.append(c.get("text") or "")
    return "\n".join(parts).lower()


def matches(r: dict[str, Any], expect: dict[str, Any]) -> bool:
    if "item_id" in expect and r.get("item_id") == expect["item_id"]:
        return True
    if (
        "title_contains" in expect
        and expect["title_contains"].lower() in (r.get("title") or "").lower()
    ):
        return True
    if "text_contains" in expect and expect["text_contains"].lower() in _haystack(r):
        return True
    return bool(
        "locator_contains" in expect and expect["locator_contains"] in (r.get("locator") or "")
    )


def run(cases: list[Case], search: Search, k: int = 10) -> list[Outcome]:
    out = []
    for c in cases:
        t = time.perf_counter()
        results = search(c.q, k)
        dt = time.perf_counter() - t
        rank = next((i for i, r in enumerate(results, 1) if matches(r, c.expect)), None)
        out.append(Outcome(c, rank, dt, [str(r.get("title") or "")[:60] for r in results[:3]]))
    return out


def report(outcomes: list[Outcome], k: int = 10) -> dict[str, Any]:
    n = len(outcomes)
    found = [o for o in outcomes if o.rank is not None and o.rank <= k]
    times = sorted(o.seconds for o in outcomes)
    return {
        "questions": n,
        f"recall@{k}": round(len(found) / n, 3) if n else None,
        "recall@1": round(sum(1 for o in outcomes if o.rank == 1) / n, 3) if n else None,
        "mrr": round(sum(1 / o.rank for o in outcomes if o.rank) / n, 3) if n else None,
        "latency_p50_s": round(statistics.median(times), 3) if times else None,
        "latency_p95_s": round(times[min(n - 1, int(n * 0.95))], 3) if times else None,
        "misses": [
            {"q": o.case.q, "note": o.case.note, "top3": o.top}
            for o in outcomes
            if o.rank is None or o.rank > k
        ],
        "ranks": {o.case.q: o.rank for o in outcomes},
    }


def mcp_search(url: str, token: str) -> Search:
    """Search through a running MCP server (the full production pipeline)."""
    import httpx

    def call(q: str, k: int) -> list[dict[str, Any]]:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "search", "arguments": {"query": q, "limit": k}},
        }
        r = httpx.post(
            url,
            json=body,
            timeout=120,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
            },
        )
        r.raise_for_status()
        payload = r.json()
        if "error" in payload or payload.get("result", {}).get("isError"):
            raise RuntimeError(json.dumps(payload)[:500])
        return list(payload["result"]["structuredContent"]["result"])

    return call
