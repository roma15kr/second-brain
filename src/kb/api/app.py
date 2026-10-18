"""The web OS app: `/api/*` JSON routes plus the built SPA from the same origin.

Any non-API path that is not a built file returns `index.html`, so client-side routes
(`/briefs/12`) survive a reload. Unknown `/api/*` paths stay JSON 404s.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse


def build_app(dist: Path | None) -> FastAPI:
    app = FastAPI(title="second-brain web OS", docs_url=None, redoc_url=None)

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

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
            return FileResponse(candidate)
        # index.html must never be cached: it names the current hashed assets.
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

    return app
