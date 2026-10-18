# 0015. Web OS: React + TypeScript SPA/PWA over a Python JSON API
Date: 2026-10-18
Status: accepted

## Context
The second brain gets a web interface ("second brain OS"): dashboards, daily/weekly assistant
routines, inbox revision, open loops, search, people, scopes. Requirements: installable PWA with
offline caching, web push, widget-style live dashboards, command palette, mobile layout. The
backend is Python. Server-rendered Python + HTMX was considered (one language, no JS build) and
rejected by the owner: the requirements are client-side capabilities that an SPA handles natively.

## Decision
- Frontend: React + TypeScript + Vite, PWA (service worker, manifest, Web Push), in `web/`.
- Backend: the existing Python package exposes a JSON API (`/api/*`, Starlette) and serves the
  built SPA from the same origin, so authentication uses an HttpOnly session cookie.
- Login: passkeys (WebAuthn) for the single owner + one-time recovery codes; the MCP bearer token
  stays separate for Claude clients.
- Push: Web Push with VAPID keys (iOS requires the PWA to be added to the Home Screen).
- `make check` covers both stacks (`STACKS := python ts`).

## Consequences
A JS toolchain and a second build stage in the Docker image. API contract must be typed on both
sides (OpenAPI → generated TS types). React vs Svelte was benchmarked on 2026-10-18 (`docs/research/react-vs-svelte.md`): React kept —
Svelte is faster and lighter, but agent-UI libraries and AI-written code reliability decide here.
