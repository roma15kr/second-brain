"""Requests to the assistant, in threads (assistant-requests spec; design D3).

A request is stored, then runs in a small background pool so it finishes even if the page is
closed; the SPA polls it for steps and the answer.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from kb.api.deps import get_conn
from kb.assistant import agent
from kb.db import Conn
from kb.redact import redact_text

router = APIRouter()
Db = Annotated[Conn, Depends(get_conn)]
WORKERS = 2
MAX_CHARS = 4000
KEEP_DAYS = 90

_pool: ThreadPoolExecutor | None = None


def background(request: Request, job: Callable[[], None]) -> None:
    """Runs a job in the small background pool (tests replace `app.state.assistant_submit`)."""
    submit = getattr(request.app.state, "assistant_submit", None)
    if submit is not None:
        submit(job)
        return
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="assistant")
    _pool.submit(job)


def _submit(request: Request, rid: int) -> None:
    state = request.app.state
    connect, config, searcher = state.connect, state.config, state.searcher
    llm = state.assistant_llm

    def job() -> None:
        with connect() as conn:
            agent.run_request(conn, config, llm, searcher, rid, datetime.now(UTC))

    background(request, job)


def _request(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "thread_id": r["thread_id"],
        "text": r["text"],
        "status": r["status"],
        "steps": r["steps"],
        "answer": r["answer_md"],
        "refs": _refs(r),
        "error": r["error"],
        "created": r.get("created_view", r.get("created", [])),
        "report": _report_view(r),
        "needs_budget": r["needs_budget"],
        "saved_doc_id": r["saved_doc_id"],
        "search": r.get("search"),
        "cost_usd": float(r["cost_usd"]),
        "started_at": r["started_at"].isoformat(),
        "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
    }


def _report_view(r: dict[str, Any]) -> dict[str, Any] | None:
    rep = r.get("report")
    if not rep:
        return None
    titles = r.get("titles", {})
    return {
        "title": rep["title"],
        "sections": [
            {
                **s,
                "refs": [
                    {
                        "ref": ref,
                        "item_id": int(ref.removeprefix("item:")),
                        "title": titles.get(ref),
                    }
                    for ref in s["refs"]
                ],
            }
            for s in rep["sections"]
        ],
    }


def _refs(r: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "ref": ref,
            "item_id": int(ref.removeprefix("item:")),
            "title": r.get("titles", {}).get(ref),
        }
        for ref in r["refs"]
        if ref.startswith("item:")
    ]


def _with_created(conn: Conn, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drafts a request made, with their live status (approved or discarded in the queue)."""
    from kb.assistant import suggestions

    ids = [c["id"] for r in rows for c in r.get("created") or [] if c.get("type") == "suggestion"]
    live = {
        s["id"]: s
        for s in (
            suggestions.listing(conn, "proposed", 500) + suggestions.listing(conn, "recent", 500)
        )
        if s["id"] in ids
    }
    out = []
    for r in rows:
        view = []
        for n, c in enumerate(r.get("created") or []):
            entry = {**c, "index": n}
            if c.get("type") == "suggestion":
                s = live.get(c["id"])
                entry["suggestion"] = s
                if s is None:
                    st = conn.execute(
                        "SELECT status FROM suggestions WHERE id = %s", (c["id"],)
                    ).fetchone()
                    entry["status"] = st["status"] if st else "gone"
            view.append(entry)
        out.append({**r, "created_view": view})
    return out


def _with_titles(conn: Conn, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs = [ref for r in rows for ref in r["refs"]] + [
        ref for r in rows for s in (r.get("report") or {}).get("sections", []) for ref in s["refs"]
    ]
    ids = {int(ref.removeprefix("item:")) for ref in refs if ref.startswith("item:")}
    titles = {
        f"item:{t['id']}": t["title"] or t["kind"]
        for t in conn.execute(
            "SELECT id, title, kind FROM items WHERE id = ANY(%s)", (list(ids),)
        ).fetchall()
    }
    return [{**r, "titles": titles} for r in rows]


@router.post("/api/assistant/requests")
def create(
    request: Request,
    conn: Db,
    text: Annotated[str, Body(embed=True)],
    thread_id: Annotated[int | None, Body(embed=True)] = None,
) -> dict[str, int]:
    text = text.strip()
    if not text:
        raise HTTPException(400, "the request is empty")
    if len(text) > MAX_CHARS:
        raise HTTPException(400, f"the request is too long (max {MAX_CHARS} characters)")
    text = redact_text(text)
    if thread_id is None:
        row = conn.execute(
            "INSERT INTO assistant_threads (title) VALUES (%s) RETURNING id", (text[:80],)
        ).fetchone()
        assert row is not None
        thread_id = int(row["id"])
    elif not conn.execute("SELECT 1 FROM assistant_threads WHERE id = %s", (thread_id,)).fetchone():
        raise HTTPException(404, f"no thread {thread_id}")
    row = conn.execute(
        "INSERT INTO assistant_requests (thread_id, text) VALUES (%s, %s) RETURNING id",
        (thread_id, text),
    ).fetchone()
    assert row is not None
    conn.execute("UPDATE assistant_threads SET updated_at = now() WHERE id = %s", (thread_id,))
    _submit(request, int(row["id"]))
    return {"id": int(row["id"]), "thread_id": thread_id}


@router.get("/api/assistant/requests/{rid}")
def get(conn: Db, rid: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM assistant_requests WHERE id = %s", (rid,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no request {rid}")
    return _request(_with_created(conn, _with_titles(conn, [dict(row)]))[0])


@router.get("/api/assistant/threads")
def threads(conn: Db) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT t.*, (SELECT count(*) FROM assistant_requests r WHERE r.thread_id = t.id) AS n"
        " FROM assistant_threads t ORDER BY t.pinned DESC, t.updated_at DESC LIMIT 50"
    ).fetchall()
    return {
        "threads": [
            {
                "id": r["id"],
                "title": r["title"],
                "pinned": r["pinned"],
                "requests": r["n"],
                "updated_at": r["updated_at"].isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/api/assistant/threads/{tid}")
def thread(conn: Db, tid: int) -> dict[str, Any]:
    t = conn.execute("SELECT * FROM assistant_threads WHERE id = %s", (tid,)).fetchone()
    if t is None:
        raise HTTPException(404, f"no thread {tid}")
    rows = conn.execute(
        "SELECT * FROM assistant_requests WHERE thread_id = %s ORDER BY id", (tid,)
    ).fetchall()
    return {
        "id": t["id"],
        "title": t["title"],
        "pinned": t["pinned"],
        "requests": [
            _request(r) for r in _with_created(conn, _with_titles(conn, [dict(r) for r in rows]))
        ],
    }


@router.post("/api/assistant/requests/{rid}/run-anyway")
def run_anyway(request: Request, conn: Db, rid: int) -> dict[str, int]:
    """Over budget: the owner chose to use AI for this one request (asked again)."""
    old = conn.execute("SELECT * FROM assistant_requests WHERE id = %s", (rid,)).fetchone()
    if old is None or not old["needs_budget"]:
        raise HTTPException(400, "this request did not wait for budget")
    row = conn.execute(
        "INSERT INTO assistant_requests (thread_id, text, allow_over_budget) VALUES (%s, %s, true)"
        " RETURNING id",
        (old["thread_id"], old["text"]),
    ).fetchone()
    assert row is not None
    _submit(request, int(row["id"]))
    return {"id": int(row["id"]), "thread_id": int(old["thread_id"])}


@router.post("/api/assistant/requests/{rid}/report/save")
def save_report(conn: Db, rid: int, scope: Annotated[str, Body(embed=True)]) -> dict[str, int]:
    """Saves a request's report to the Library as a note (indexed, so it is searchable)."""
    import os

    from kb import library, scopes
    from kb.assistant import actions

    row = conn.execute("SELECT * FROM assistant_requests WHERE id = %s", (rid,)).fetchone()
    if row is None or not row["report"]:
        raise HTTPException(404, f"request {rid} has no report")
    titles = _with_titles(conn, [dict(row)])[0]["titles"]
    text = actions.report_markdown(row["report"], titles, os.environ.get("KB_WEB_ORIGIN", ""))
    try:
        doc = library.add_document(
            conn,
            row["report"]["title"],
            "note",
            [scope],
            "report.md",
            text.encode(),
            scopes.known(conn),
            datetime.now(UTC),
        )
    except library.LibraryError as e:
        raise HTTPException(400, str(e)) from e
    conn.execute("UPDATE assistant_requests SET saved_doc_id = %s WHERE id = %s", (doc, rid))
    return {"document_id": doc}


@router.post("/api/assistant/threads/{tid}/pin")
def pin(conn: Db, tid: int, pinned: Annotated[bool, Body(embed=True)]) -> dict[str, bool]:
    if not conn.execute(
        "UPDATE assistant_threads SET pinned = %s WHERE id = %s RETURNING id", (pinned, tid)
    ).fetchone():
        raise HTTPException(404, f"no thread {tid}")
    return {"pinned": pinned}


def delete_old_threads(conn: Conn, now: datetime) -> int:
    """Threads are kept 90 days after their last request unless pinned."""
    return len(
        conn.execute(
            "DELETE FROM assistant_threads WHERE NOT pinned AND updated_at < %s RETURNING id",
            (now - timedelta(days=KEEP_DAYS),),
        ).fetchall()
    )


@router.post("/api/assistant/requests/{rid}/undo/{index}")
def undo(conn: Db, rid: int, index: int) -> dict[str, Any]:
    from kb.assistant import actions

    try:
        return actions.undo(conn, rid, index, datetime.now(UTC))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


def fail_interrupted(conn: Conn) -> int:
    """At startup: requests cut off by a restart are failed (the owner can ask again)."""
    return len(
        conn.execute(
            "UPDATE assistant_requests SET status = 'failed', finished_at = now(),"
            " error = 'interrupted by an update — please ask again' WHERE status = 'running'"
            " RETURNING id"
        ).fetchall()
    )
