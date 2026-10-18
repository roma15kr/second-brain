"""Brute-force protection shared by the MCP server and the web OS sign-in (per client IP)."""

from __future__ import annotations

from collections import defaultdict, deque

from starlette.types import Scope


class RateLimiter:
    """Sliding-window counters per client: failed logins and requests."""

    def __init__(
        self, max_failures: int, failure_window: float, max_requests: int, request_window: float
    ) -> None:
        self.max_failures, self.failure_window = max_failures, failure_window
        self.max_requests, self.request_window = max_requests, request_window
        self.failures: dict[str, deque[float]] = defaultdict(deque)
        self.requests: dict[str, deque[float]] = defaultdict(deque)

    @staticmethod
    def _trim(q: deque[float], now: float, window: float) -> int:
        while q and now - q[0] > window:
            q.popleft()
        return len(q)

    def locked(self, client: str, now: float) -> bool:
        return self._trim(self.failures[client], now, self.failure_window) >= self.max_failures

    def failed(self, client: str, now: float) -> None:
        self.failures[client].append(now)

    def allow_request(self, client: str, now: float) -> bool:
        q = self.requests[client]
        if self._trim(q, now, self.request_window) >= self.max_requests:
            return False
        q.append(now)
        return True


def client_ip(scope: Scope) -> str:
    """The real client: Cloudflare's CF-Connecting-IP (set by Cloudflare, not by the client),
    else the first X-Forwarded-For address added by Coolify's proxy."""
    headers = dict(scope.get("headers") or [])
    cf = headers.get(b"cf-connecting-ip", b"").decode(errors="ignore").strip()
    if cf:
        return cf
    forwarded = headers.get(b"x-forwarded-for", b"").decode(errors="ignore")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = scope.get("client")
    return str(client[0]) if client else "unknown"
