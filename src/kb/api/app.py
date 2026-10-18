"""The web OS app: `/api/*` JSON routes plus the built SPA from the same origin.

Every `/api/*` route needs a signed-in session except the few in PUBLIC_API (health and the
sign-in ceremonies); the check is a middleware, so new routes are protected by default.
State-changing requests must also carry `X-KB-Request: 1` (CSRF defence together with
SameSite cookies). Any non-API path that is not a built file returns `index.html`, so
client-side routes (`/briefs/12`) survive a reload.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from kb.api import (
    auth,
    routes_briefs,
    routes_inbox,
    routes_loops,
    routes_people,
    routes_push,
    routes_search,
    routes_settings,
    routes_today,
    routes_week,
)
from kb.config import Config
from kb.db import Conn

PUBLIC_API = {
    "/api/health",
    "/api/auth/me",
    "/api/auth/register/begin",
    "/api/auth/register/finish",
    "/api/auth/login/begin",
    "/api/auth/login/finish",
}
CSRF_HEADER = "x-kb-request"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
NO_CACHE = {"sw.js", "registerSW.js"}  # the service worker must update promptly

Connect = Callable[[], Conn]
Credential = Annotated[dict[str, Any], Body(embed=True)]
SetupCode = Annotated[str | None, Body(embed=True)]
Clock = Callable[[], datetime]


def _now() -> datetime:
    return datetime.now(UTC)


def _device(request: Request) -> str:
    return request.headers.get("user-agent", "")[:200]


def build_app(
    dist: Path | None,
    connect: Connect | None = None,
    rp: auth.RelyingParty | None = None,
    clock: Clock = _now,
    config: Config | None = None,
    searcher: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None,
) -> FastAPI:
    app = FastAPI(title="second-brain web OS", docs_url=None, redoc_url=None)
    app.state.connect = connect
    app.state.config = config or Config()
    app.state.searcher = searcher or (
        routes_search.local_searcher(connect, app.state.config) if connect else None
    )

    @contextmanager
    def db() -> Iterator[Conn]:
        if connect is None:
            raise RuntimeError("the web OS needs DATABASE_URL")
        with connect() as conn:
            yield conn

    def relying_party() -> auth.RelyingParty:
        if rp is None or not rp.rp_id:
            raise auth.AuthError(503, "KB_WEB_ORIGIN is not configured on the server.")
        return rp

    @app.exception_handler(auth.AuthError)
    async def auth_error(_: Request, exc: auth.AuthError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        if request.method in UNSAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
            return JSONResponse({"detail": "missing X-KB-Request header"}, status_code=403)
        token = request.cookies.get(auth.SESSION_COOKIE)
        session = None
        if token and connect is not None:

            def lookup() -> dict[str, Any] | None:
                with db() as conn:
                    return auth.session_for(conn, token, clock())

            session = await run_in_threadpool(lookup)
        request.state.session = session
        if session is None and path not in PUBLIC_API:
            return JSONResponse({"detail": "sign in required"}, status_code=401)
        return await call_next(request)

    def set_session_cookie(response: Response, token: str) -> None:
        response.set_cookie(
            auth.SESSION_COOKIE,
            token,
            max_age=auth.SESSION_DAYS * 86400,
            httponly=True,
            secure=rp.secure_cookies if rp else True,
            samesite="lax",
            path="/",
        )

    def set_challenge_cookie(response: Response, cid: str) -> None:
        response.set_cookie(
            auth.CHALLENGE_COOKIE,
            cid,
            max_age=int(auth.CHALLENGE_TTL.total_seconds()),
            httponly=True,
            secure=rp.secure_cookies if rp else True,
            samesite="strict",
            path="/api/auth",
        )

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(request: Request) -> dict[str, Any]:
        session = request.state.session
        with db() as conn:
            passkeys = auth.has_passkeys(conn, rp.rp_id if rp else "")
        return {
            "signed_in": session is not None,
            "has_passkeys": passkeys,
            "needs_passkey": bool(session and session["needs_passkey"]),
        }

    @app.post("/api/auth/register/begin")
    def register_begin(request: Request, setup_code: SetupCode = None) -> Response:
        with db() as conn:
            cid, options = auth.begin_registration(
                conn, relying_party(), setup_code, request.state.session is not None, clock()
            )
        out = Response(options, media_type="application/json")
        set_challenge_cookie(out, cid)
        return out

    @app.post("/api/auth/register/finish")
    def register_finish(request: Request, credential: Credential) -> JSONResponse:
        with db() as conn:
            token = auth.finish_registration(
                conn,
                relying_party(),
                request.cookies.get(auth.CHALLENGE_COOKIE),
                credential,
                _device(request),
                request.state.session is not None,
                clock(),
            )
        out = JSONResponse({"ok": True})
        out.delete_cookie(auth.CHALLENGE_COOKIE, path="/api/auth")
        if token:
            set_session_cookie(out, token)
        return out

    @app.post("/api/auth/login/begin")
    def login_begin() -> Response:
        with db() as conn:
            cid, options = auth.begin_login(conn, relying_party(), clock())
        out = Response(options, media_type="application/json")
        set_challenge_cookie(out, cid)
        return out

    @app.post("/api/auth/login/finish")
    def login_finish(request: Request, credential: Credential) -> JSONResponse:
        with db() as conn:
            token = auth.finish_login(
                conn,
                relying_party(),
                request.cookies.get(auth.CHALLENGE_COOKIE),
                credential,
                _device(request),
                clock(),
            )
        out = JSONResponse({"ok": True})
        out.delete_cookie(auth.CHALLENGE_COOKIE, path="/api/auth")
        set_session_cookie(out, token)
        return out

    @app.post("/api/auth/logout")
    def logout(request: Request) -> JSONResponse:
        with db() as conn:
            auth.end_session(conn, request.cookies.get(auth.SESSION_COOKIE, ""))
        out = JSONResponse({"ok": True})
        out.delete_cookie(auth.SESSION_COOKIE, path="/")
        return out

    app.include_router(routes_today.router)
    app.include_router(routes_push.router)
    app.include_router(routes_briefs.router)
    app.include_router(routes_inbox.router)
    app.include_router(routes_settings.router)
    app.include_router(routes_loops.router)
    app.include_router(routes_week.router)
    app.include_router(routes_search.router)
    app.include_router(routes_people.router)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def api_not_found(rest: str) -> JSONResponse:
        return JSONResponse({"detail": f"unknown API path /api/{rest}"}, status_code=404)

    @app.get("/{path:path}", include_in_schema=False, response_model=None)
    def spa(path: str) -> FileResponse | JSONResponse:
        if dist is None or not (dist / "index.html").is_file():
            return JSONResponse({"detail": "web app not built"}, status_code=503)
        root = dist.resolve()
        candidate = (root / path).resolve()
        if path and candidate.is_relative_to(root) and candidate.is_file():
            if candidate.suffix == ".webmanifest":
                return FileResponse(candidate, media_type="application/manifest+json")
            if candidate.name in NO_CACHE:
                return FileResponse(candidate, headers={"Cache-Control": "no-cache"})
            return FileResponse(candidate)
        # index.html must never be cached: it names the current hashed assets.
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

    return app
