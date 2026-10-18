"""Personal base (personal-base spec, design D16): the owner's documents and notes.

Every document is marked personal or a project and has a kind; constitution, plan and goals
are core documents the assistant plans with. Versions are kept; the latest one is indexed for
search (redacted, like mail) as a `document` item plus `doc_section` items per heading, which
search reports as their document.
"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime
from pathlib import PurePath
from typing import Any

from psycopg.types.json import Jsonb

from kb.db import Conn
from kb.redact import redact_text

SOURCE_ID = "library"
MAX_BYTES = 20 * 1024 * 1024
KINDS = ("constitution", "plan", "goals", "note", "reference")
CORE_KINDS = ("constitution", "plan", "goals")
TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
SECTION_MIN_CHARS = 1500  # shorter documents are covered by the document item itself


class LibraryError(ValueError):
    pass


def extract_text(filename: str, data: bytes) -> str:
    suffix = PurePath(filename).suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return data.decode("utf-8", errors="replace")
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
    if suffix == ".docx":
        import docx

        doc = docx.Document(io.BytesIO(data))
        lines = []
        for p in doc.paragraphs:
            style = (p.style.name if p.style is not None else "") or ""
            if style.lower().startswith("heading") and p.text.strip():
                level = re.sub(r"\D", "", style) or "1"
                lines.append("#" * min(int(level), 6) + " " + p.text.strip())
            else:
                lines.append(p.text)
        return "\n".join(lines).strip()
    raise LibraryError(f"unsupported file type {suffix or '(none)'}; use .md, .txt, .pdf or .docx")


def _validate(kind: str, scopes: list[str], valid: tuple[str, ...]) -> None:
    if kind not in KINDS:
        raise LibraryError(f"kind must be one of {', '.join(KINDS)}")
    if not scopes:
        raise LibraryError("choose personal or a project for this document")
    bad = [s for s in scopes if s not in valid]
    if bad:
        raise LibraryError(f"unknown scope(s) {bad}; valid: {', '.join(valid)}")


def add_document(
    conn: Conn,
    title: str,
    kind: str,
    scopes: list[str],
    filename: str,
    data: bytes,
    valid_scopes: tuple[str, ...],
    now: datetime,
    ai_allowed: bool | None = None,
) -> int:
    _validate(kind, scopes, valid_scopes)
    if not title.strip():
        title = PurePath(filename).stem
    row = conn.execute(
        "INSERT INTO documents (title, kind, scopes, ai_allowed, created_at, updated_at)"
        " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (
            title.strip()[:200],
            kind,
            scopes,
            kind in CORE_KINDS if ai_allowed is None else ai_allowed,
            now,
            now,
        ),
    ).fetchone()
    assert row is not None
    add_version(conn, int(row["id"]), filename, data, now)
    return int(row["id"])


def add_version(conn: Conn, doc_id: int, filename: str, data: bytes, now: datetime) -> int:
    if len(data) > MAX_BYTES:
        raise LibraryError("files are limited to 20 MB")
    if not data:
        raise LibraryError("the file is empty")
    text = extract_text(filename, data)
    row = conn.execute(
        "INSERT INTO document_versions (document_id, filename, size, sha256, data, text,"
        " created_at) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (doc_id, filename, len(data), hashlib.sha256(data).hexdigest(), data, text, now),
    ).fetchone()
    assert row is not None
    conn.execute("UPDATE documents SET updated_at = %s WHERE id = %s", (now, doc_id))
    index_document(conn, doc_id)
    return int(row["id"])


def update(
    conn: Conn,
    doc_id: int,
    valid_scopes: tuple[str, ...],
    title: str | None = None,
    kind: str | None = None,
    scopes: list[str] | None = None,
    ai_allowed: bool | None = None,
) -> None:
    doc = get(conn, doc_id)
    _validate(kind or doc["kind"], scopes if scopes is not None else doc["scopes"], valid_scopes)
    conn.execute(
        "UPDATE documents SET title = coalesce(%s, title), kind = coalesce(%s, kind),"
        " scopes = coalesce(%s, scopes), ai_allowed = coalesce(%s, ai_allowed),"
        " updated_at = now() WHERE id = %s",
        (title, kind, scopes, ai_allowed, doc_id),
    )
    index_document(conn, doc_id)


def get(conn: Conn, doc_id: int) -> dict[str, Any]:
    doc = conn.execute("SELECT * FROM documents WHERE id = %s", (doc_id,)).fetchone()
    if doc is None:
        raise LibraryError(f"no document {doc_id}")
    return dict(doc)


def latest_version(conn: Conn, doc_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, filename, size, sha256, text, created_at FROM document_versions"
        " WHERE document_id = %s ORDER BY id DESC LIMIT 1",
        (doc_id,),
    ).fetchone()
    return dict(row) if row else None


def sections(text: str) -> list[tuple[str, str]]:
    """(heading, body) per Markdown heading; text before the first heading is the intro."""
    parts: list[tuple[str, str]] = []
    heading, buf = "", list[str]()
    for line in text.splitlines():
        m = re.match(r"^#{1,6}\s+(.*)", line)
        if m:
            if "".join(buf).strip():
                parts.append((heading, "\n".join(buf).strip()))
            heading, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    if "".join(buf).strip():
        parts.append((heading, "\n".join(buf).strip()))
    return parts


def index_document(conn: Conn, doc_id: int) -> int:
    """(Re)builds the search items of a document from its latest version. Returns item id."""
    doc = get(conn, doc_id)
    version = latest_version(conn, doc_id)
    text = redact_text(version["text"] if version else "")
    meta = {
        "document_id": doc_id,
        "doc_kind": doc["kind"],
        "private": not doc["ai_allowed"],
        "version_id": version["id"] if version else None,
    }
    row = conn.execute(
        """
        INSERT INTO items (source_id, source_item_key, kind, scopes, title, raw_text,
                           occurred_at, last_activity_at, locator, metadata, updated_at)
        VALUES (%s, %s, 'document', %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (source_id, source_item_key) DO UPDATE SET scopes = EXCLUDED.scopes,
            title = EXCLUDED.title, raw_text = EXCLUDED.raw_text,
            last_activity_at = EXCLUDED.last_activity_at, metadata = EXCLUDED.metadata,
            hidden = false, updated_at = now()
        RETURNING id
        """,
        (
            SOURCE_ID,
            f"doc-{doc_id}",
            doc["scopes"],
            doc["title"],
            text,
            doc["created_at"],
            version["created_at"] if version else doc["updated_at"],
            f"/library/{doc_id}",
            Jsonb(meta),
        ),
    ).fetchone()
    assert row is not None
    item_id = int(row["id"])
    conn.execute(
        "DELETE FROM items WHERE source_id = %s AND source_item_key LIKE %s",
        (SOURCE_ID, f"doc-{doc_id}-s%"),
    )
    if len(text) >= SECTION_MIN_CHARS:
        for n, (heading, body) in enumerate(sections(text)):
            conn.execute(
                "INSERT INTO items (source_id, source_item_key, kind, scopes, title, raw_text,"
                " last_activity_at, locator, metadata) VALUES (%s, %s, 'doc_section', %s, %s,"
                " %s, %s, %s, %s)",
                (
                    SOURCE_ID,
                    f"doc-{doc_id}-s{n}",
                    doc["scopes"],
                    f"{doc['title']} - {heading}" if heading else doc["title"],
                    body,
                    version["created_at"] if version else doc["updated_at"],
                    f"/library/{doc_id}",
                    Jsonb({**meta, "parent_item_id": item_id, "section": heading}),
                ),
            )
    return item_id


def delete(conn: Conn, doc_id: int) -> None:
    conn.execute(
        "DELETE FROM items WHERE source_id = %s AND (source_item_key = %s"
        " OR source_item_key LIKE %s)",
        (SOURCE_ID, f"doc-{doc_id}", f"doc-{doc_id}-s%"),
    )
    conn.execute("DELETE FROM documents WHERE id = %s", (doc_id,))


def listing(conn: Conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT d.*, count(v.id) AS versions, max(v.created_at) AS version_at,
               (array_agg(v.size ORDER BY v.id DESC))[1] AS size,
               (array_agg(v.filename ORDER BY v.id DESC))[1] AS filename
        FROM documents d LEFT JOIN document_versions v ON v.document_id = d.id
        GROUP BY d.id ORDER BY d.kind IN ('constitution', 'plan', 'goals') DESC, d.updated_at DESC
        """
    ).fetchall()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "kind": r["kind"],
            "core": r["kind"] in CORE_KINDS,
            "scopes": list(r["scopes"]),
            "ai_allowed": r["ai_allowed"],
            "versions": r["versions"],
            "filename": r["filename"],
            "size": r["size"],
            "updated_at": r["updated_at"].isoformat(),
        }
        for r in rows
    ]
