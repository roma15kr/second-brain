"""Shared request dependencies for API routers."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from kb.db import Conn


def get_conn(request: Request) -> Iterator[Conn]:
    connect = request.app.state.connect
    if connect is None:
        raise RuntimeError("the web OS needs DATABASE_URL")
    with connect() as conn:
        yield conn
