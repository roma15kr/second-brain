# Design: web-os-v1

## Context

Builds on `v1-mail-telegram-search` (branch `kb-design-v1-plan`), which is deployed and provides:
items (email threads, Telegram conversations, passages) with AI summaries (`question`, `summary`,
`outcome`, `entities`), `messages` with authors and identity keys, people/identities, scopes, hybrid
search (`kb.search.search`), health (`kb.health.status`), an OpenAI client with batch support and
usage ledger (`kb.distill`, `llm_usage`, `PRICES`), a Postgres job queue (`kb.jobs`) and a
Starlette-based MCP server with bearer auth and a `RateLimiter` (`kb.mcp_server`). Services in
`docker-compose.yml`: postgres, backup, ingest, telegram, index, mcp. The `make` TypeScript targets
(`make/ts.mk`) expect `package.json` at the repo root. Motivation: see proposal.md.

## Goals / Non-Goals

**Goals:** a typed JSON API over existing data plus new routines/loops data; a React SPA/PWA with
passkeys and Web Push; a scheduler that produces briefs reliably (catch-up, idempotent, budgeted);
loop detection that is cheap, auditable and correctable.

**Non-Goals:** voice (ADR 0014), in-app chat, sending anything automatically, writing to Telegram
or calendars, offline editing (offline is read-only), multi-user, the planned connectors.

## Decisions

### D1. API: FastAPI app in `src/kb/api/`, served with the SPA from one origin
FastAPI (Starlette-based, like the MCP server) gives Pydantic request/response models and an
OpenAPI document; `openapi-typescript` generates `web/src/api/schema.ts`, so both sides share one
contract. A new compose service `web` runs `kb web` (uvicorn) on its own domain
`os.141-94-30-173.sslip.io`; it serves `/api/*` and the built SPA (`/` + history fallback).
*Alternative:* plain Starlette routes (no new dependency, hand-written TS types — drift risk).

### D2. Auth: passkeys + session cookie
`webauthn` (py_webauthn) on the server, `@simplewebauthn/browser` in the SPA. First registration
requires a one-time setup code from `kb web setup-code` (stored hashed, 1 h expiry). Ten recovery
codes (scrypt-hashed, single use). Sessions: random token in an HttpOnly, Secure, SameSite=Lax cookie,
stored hashed with device label and expiry (30 days, sliding). State-changing requests also require
the `X-KB-Request: 1` header (CSRF defence with SameSite). Lockout reuses `RateLimiter` (moved to
`kb/ratelimit.py`) for sign-in and recovery attempts.

### D3. Push: Web Push with VAPID
`pywebpush` on the server; the SPA's service worker (vite-plugin-pwa, `injectManifest` strategy)
handles `push` → `showNotification(headline, {data: {url}})` and `notificationclick` → open URL.
Subscriptions per device with per-routine toggles; 404/410 from the push service deletes the
subscription. Payload: headline + URL only (no content). Quiet hours enforced server-side.

### D4. Scheduler: a `routines` service with idempotent runs
`kb routines` loops every 30 s: for each routine, compute the latest due slot in Europe/Kyiv
(`zoneinfo`) from settings; if no `routine_runs` row exists for (routine, slot) and the slot is
within its catch-up window (same day for daily routines, 24 h for weekly), insert the row (unique
constraint = idempotent across restarts/duplicates), generate, store the brief, push. A delayed run
is marked `delayed`. One routine at a time; failures are recorded and retried once after 5 minutes.

### D5. Brief generation: data first, AI second, sources enforced
Each routine first builds a **fact pack** with SQL (no AI): items in the window per scope with their
summaries/outcomes/people, open loops (due, overdue, opened/closed in window), triage results,
counts. The AI step (`gpt-6.1-sol`, structured output) only writes prose sections and picks focus
items **by item/loop id** from the fact pack. Output is validated: every referenced id must exist in
the fact pack; unknown ids are dropped; a section with no valid references is replaced by the
data-only rendering. If the monthly cap is reached, the data-only brief is stored (spec: budget).
Brief = `briefs` row with `sections` JSON (title, text, refs[]) + headline for push.

### D6. Mail revision triage: cheap model, sender memory
Each pass takes email items with activity since the previous pass, applies sender rules first
(`sender_prefs`: noise/important per address), then classifies the rest with `gpt-6-luna`
(needs_reply / important / fyi / noise + one-line suggested action) from the item summary and last
message; results stored in `triage` (item, pass, class, action). Push only if needs_reply or
important > 0.

### D7. Open loops: detection job after distillation, owner-aware
Owner identities come from Settings (seeded from config `owner.identities`). After a unit is
summarized (or changes), a `loops.detect` job sends `gpt-6-luna` the last ~40 messages with authors
marked `ME`/`OTHER(name)` plus the unit's open loops; it returns new loops (kind, title, counterpart
message key, due phrase → resolved to a date in Kyiv time) and loops it considers fulfilled (with
the closing message key). Needs-reply for email is also checked deterministically: the latest
message is not from the owner and is newer than the owner's last message. Dismissed loops store
their source message key so the same message never recreates them. Every change writes a
`loop_events` row (who: system/owner, action, at).

### D8. Frontend
`web/` — Vite + React + TypeScript, react-router, TanStack Query (cache, background refresh),
vite-plugin-pwa (manifest, offline read-only cache of GET /api for Today/briefs), a small own CSS
(design tokens, light/dark) — no UI framework. Pages per mockups. Command palette searches people,
briefs, pages and runs `/api/search` for conversations. Root `package.json` (npm workspaces:
`web`) exposes `typecheck`, `lint` (ESLint), `test` (Vitest + Testing Library), `format` (Prettier),
so `STACKS := python ts` works with the existing `make` targets.

### D9. Settings in the database
`app_settings` (key → JSON) holds schedule, passes, quiet hours, push toggles, owner identities and
AI budget cap, with defaults from config; edited via `/api/settings` (validated by Pydantic).

### D10. Usage events
`app_events` (kind, ref, at): brief_opened, item_opened, loop_done/snoozed/dismissed, rating. The
Status page computes the success metric over 28 days.

### D11. Connector accounts and encrypted credentials
Sources move from config-only to the database: `connector_accounts` (kind imap|telegram|clickup|
calendar, label, default_scopes, settings JSON, secret ciphertext, state). Config sources stay
supported and are shown read-only on the hub. Secrets are encrypted with AES-GCM (`cryptography`,
already installed as a transitive dependency — becomes a direct one) using `KB_SECRET_KEY`;
the API never returns them. Credentials are tested before saving (IMAP LOGIN, ClickUp `GET /user`,
calendar fetch). The `ingest` service reloads accounts every minute, so connecting needs no restart.
*Alternative:* keep secrets in Coolify env only (no web connect; rejected by the owner's request).

### D12. Telegram dialogs and QR login from the web
The `telegram` service writes dialog metadata (id, title, type, last activity — via read-only
`get_dialogs`) into `tg_dialogs` every 10 minutes; `included` and `scopes` columns replace the
config allowlist (config entries are imported once). Including a dialog enqueues its 12-month
backfill. QR login: the API inserts a `telegram_login` request; the telegram service produces the
QR token and polls for confirmation; the SPA renders the token as a QR code. The read-only wrapper
(no send/read-ack methods) is unchanged and still tested.

### D13. Marks are rules
Marks set on the hub become rows in the existing review-rules layer (highest priority):
`mailbox default`, `sender/domain/label`, `tg chat`, `clickup list`, `calendar`, `document`.
Changing a mark calls `scopes.rescope` for the affected items. Projects live in a `scopes` table
(name, label, color, archived) seeded with personal/digisoft/quokka/rdim; validation uses it.

### D14. ClickUp connector
`kb/connectors/clickup.py`: REST API v2 with the personal token; polls chosen lists every 5 min
with `date_updated_gt` (cursor per list), fetches task comments; respects 429 + `X-RateLimit-Reset`
(100 req/min on the owner's plan). A task with its comments is one unit (`clickup_task`) built
through `messages` like other sources; members link to people by `email:` identity. Writes: only
`POST /list/{id}/task` from an approved suggestion; the created task id is stored on the
suggestion (idempotent retry). Webhooks are a later optimisation (needs a public callback).

### D15. Calendars: secret iCal address, read-only
Google Calendar's "secret address in iCal format" needs no OAuth (consistent with the owner's
choice of IMAP over Google OAuth). Polled every 10 min; parsed with `icalendar` +
`recurring-ical-events` (new dependencies, need approval) into `events` (uid, calendar,
start/end, title, attendees, my response status, location/meet link). Attendee emails link to
people. CalDAV for other providers is a later option.

### D16. Personal base storage and extraction
`documents` (title, kind, scopes, ai_allowed, core) + `document_versions` (bytes in Postgres
`bytea` ≤ 20 MB, sha256, extracted text, created_at). Extraction: md/txt direct; PDF `pypdf`; DOCX
`python-docx` (new dependencies, need approval). Latest version is indexed as `document` units
split by headings (passages), so search and MCP find them. `ai_allowed = false` documents are
excluded from every AI prompt by a single filter in the fact-pack/prompt builders (tested).
Goals: one `gpt-6.1-sol` structured call per core-document version proposes goals with the source
paragraph; `goals` rows start `proposed`, become `confirmed` by the owner.

### D17. Suggestions and the approval queue
`suggestions` (kind reply_email|reply_tg|nudge|task|delegate|decline, scope, payload JSON, refs,
goal_id, reason, status proposed|approved|applied|discarded|failed, applied_ref, edited bool,
discard_reason). Executors run in the `routines` service after approval:
- **Gmail draft:** IMAP `APPEND` to the `\Drafts` folder with the `\Draft` flag and
  `In-Reply-To`/`References` of the last message so Gmail threads it; the ingest connector skips
  `\Draft` messages, and loop closing ignores drafts (spec scenario).
- **ClickUp task:** D14.
- **Telegram:** no executor; the SPA copies the text and opens the `t.me` link.

### D18. Priority (Eisenhower) — deterministic score, AI only explains
`priority = importance × urgency`. Importance features: person tier (interaction frequency,
owner marks "important"), match to a confirmed goal (embedding similarity between the item
summary and goal text ≥ threshold), money/contract/deadline entities from distillation.
Urgency: explicit deadline proximity, waiting time. Quadrant from thresholds; the reason string is
built from the features (no AI), so it is cheap and testable.

### D19. Reply drafts and tone
For the top N needs-reply email per day (default 10, budget-checked), `gpt-6.1-sol` receives: the
redacted thread, KB context (top 5 search results for the thread's question, excluding
`ai_allowed=false` documents), 5–10 of the owner's previous sent replies to the same person or
scope as tone examples, and the language of the thread; returns draft + cited refs (validated
like briefs). Telegram drafts are produced for needs-reply chat loops the same way.

### D20. Meetings: reminders, prep, notes
The routines loop also schedules per-event jobs: prep at T-30 min (or in the morning brief when
the meeting is before 10:00), reminder push at T-10 min. Prep uses a fact pack (attendee people,
last items, loops, ClickUp tasks, goal match) + one AI call for the agenda (refs validated).
Notes import: `POST /api/meetings/:id/notes` (text or file; .vtt/.srt cues joined; .docx via
python-docx) or an email forwarded to the owner's mailbox with a `[meeting]` subject tag matched
to the nearest event. Processing: one structured AI call → summary, decisions, actions (owner,
due) → owner's actions become loops (`i_owe`), others become `task` suggestions with the
teammate's default list.

### D21. Focus blocks and attention audit
Free blocks = working hours (settings, default 09:00–18:00) minus events, ≥ 90 min. Meeting load
= event minutes / working minutes. Attention audit = counts of messages, meetings and tasks per
scope for the week vs. confirmed goals' scopes; "no progress" = goal without matching items for 14
days. All SQL; the AI only words the weekly sections.

### D22. Frontend framework decision: React (confirmed by benchmark)
`docs/research/react-vs-svelte.md`: Svelte 5 is ~1.5× faster on DOM work, ~5× smaller bundle,
~150 ms faster first paint (js-framework-benchmark, Chrome 154); server load is identical; at our
data sizes interactions are under one frame in both. React wins on agent-UI libraries and on the
reliability of AI-written code, which decide this project (weighted score 4.3 vs 3.9). Mitigations:
route-level code splitting, small shell, external store for streams.

## Files

| File | Why |
|---|---|
| `src/kb/migrations/0011_web_os.sql` | webauthn_credentials, sessions, recovery_codes, setup_codes, push_subscriptions, app_settings, routine_runs, briefs, triage, sender_prefs, loops, loop_events, loop_dismissed_sources, app_events |
| `src/kb/ratelimit.py` | `RateLimiter` moved from mcp_server (shared) |
| `src/kb/api/__init__.py`, `app.py` | FastAPI app, SPA static serving, error handling, CSRF header check |
| `src/kb/api/auth.py` | passkey registration/sign-in, setup & recovery codes, sessions, devices |
| `src/kb/api/routes_*.py` | today, briefs, inbox, loops, search, items, people, scopes, settings, status, push, events |
| `src/kb/settings_store.py` | typed settings with defaults (D9) |
| `src/kb/routines/scheduler.py` | due-slot computation, catch-up, idempotent runs (D4) |
| `src/kb/routines/factpack.py` | SQL fact packs per routine (D5) |
| `src/kb/routines/briefs.py` | AI sections, id validation, data-only fallback, headline (D5) |
| `src/kb/routines/triage.py` | mail revision passes (D6) |
| `src/kb/loops.py` | detection prompt/schema, apply results, manual actions, overdue/aging (D7) |
| `src/kb/push.py` | Web Push sending, quiet hours, subscription cleanup (D3) |
| `src/kb/cli.py` (edit) | `kb web`, `kb web setup-code`, `kb routines`, `kb routines run <name>` |
| `src/kb/indexer.py` (edit) | enqueue `loops.detect` after unit changes/summaries |
| `src/kb/config.py` (edit) | `owner`, `web`, `routines` sections |
| `docker/Dockerfile` (edit) | node build stage for `web/` → copy `dist` into the Python image |
| `docker-compose.yml` (edit) | `web` and `routines` services |
| `package.json`, `package-lock.json` | npm workspaces root delegating scripts to `web/` |
| `web/` | Vite React app: `src/pages/*` per mockup, `src/shell/*` (dock, palette, notifications), `src/api/*` (generated schema + client), `src/sw.ts` (service worker), tests |
| `Makefile` (edit) | `STACKS := python ts` |
| `docs/external/README.md` (edit) | new env vars and services |
| `src/kb/migrations/0012_connectors_assistant.sql` | connector_accounts, tg_dialogs, telegram_login, scopes, clickup cursors, events, documents, document_versions, goals, suggestions |
| `src/kb/secrets.py` | AES-GCM encrypt/decrypt with `KB_SECRET_KEY` (D11) |
| `src/kb/connectors/accounts.py` | load DB + config sources; test credentials (D11) |
| `src/kb/connectors/clickup.py` | ClickUp sync and task creation (D14) |
| `src/kb/connectors/calendar.py` | iCal fetch, recurrence expansion, events (D15) |
| `src/kb/connectors/telegram.py` (edit) | dialogs listing, DB allowlist, QR login requests (D12) |
| `src/kb/connectors/imap.py` (edit) | skip `\Draft`; `append_draft()` (D17) |
| `src/kb/library.py` | documents, versions, extraction, goals (D16) |
| `src/kb/assistant/priority.py` | Eisenhower score and reasons (D18) |
| `src/kb/assistant/suggestions.py` | queue, approve/edit/discard, executors (D17) |
| `src/kb/assistant/drafts.py` | reply and nudge drafts with tone examples (D19) |
| `src/kb/assistant/meetings.py` | prep, reminders, notes processing (D20) |
| `src/kb/assistant/focus.py` | focus blocks, meeting load, attention audit (D21) |
| `src/kb/api/routes_{connectors,library,meetings,assistant}.py` | API for the new pages |
| `web/src/pages/{Connectors,Library,Meetings,Assistant}/*` | new pages per mockups |

## Types and signatures

```python
# kb/routines/scheduler.py
RoutineName = Literal["morning", "revision", "evening", "weekly_review", "weekly_plan"]
@dataclass(frozen=True)
class Slot: routine: RoutineName; at: datetime  # aware, Kyiv
def due_slots(settings: RoutineSettings, now: datetime) -> list[Slot]: ...
def claim(conn: Conn, slot: Slot) -> int | None: ...  # routine_runs id, None if already run
def run_due(conn: Conn, config: Config, llm: LlmClient | None, now: datetime) -> list[int]: ...

# kb/routines/factpack.py
@dataclass
class FactPack: window: tuple[datetime, datetime]; by_scope: dict[str, list[ItemFact]]
    loops: list[LoopFact]; triage: list[TriageFact]; counts: dict[str, int]
def build(conn: Conn, routine: RoutineName, window: tuple[datetime, datetime]) -> FactPack: ...

# kb/routines/briefs.py
@dataclass
class Section: title: str; text: str; refs: list[str]  # "item:123" | "loop:45"
def generate(pack: FactPack, routine: RoutineName, llm: LlmClient | None, budget_left: float) -> list[Section]: ...
def validate_refs(sections: list[Section], pack: FactPack) -> list[Section]: ...
def data_only(pack: FactPack, routine: RoutineName) -> list[Section]: ...
def headline(routine: RoutineName, pack: FactPack) -> str: ...

# kb/routines/triage.py
TriageClass = Literal["needs_reply", "important", "fyi", "noise"]
def run_pass(conn: Conn, config: Config, llm: LlmClient | None, since: datetime, now: datetime) -> PassResult: ...

# kb/loops.py
LoopKind = Literal["needs_reply", "i_owe", "owed_to_me", "manual"]
LoopStatus = Literal["open", "done", "snoozed", "dismissed"]
def detect(conn: Conn, config: Config, llm: LlmClient, item_id: int) -> DetectResult: ...
def needs_reply_check(conn: Conn, item_id: int, owner_keys: list[str]) -> bool: ...
def act(conn: Conn, loop_id: int, action: str, by: str, until: date | None = None) -> None: ...
def resolve_due(phrase: str | None, said_at: datetime, tz: ZoneInfo) -> date | None: ...

# kb/push.py
def send(conn: Conn, routine: RoutineName, headline: str, url: str, now: datetime) -> int: ...

# kb/assistant/suggestions.py
SuggestionKind = Literal["reply_email", "reply_tg", "nudge", "task", "delegate", "decline"]
def propose(conn: Conn, kind: SuggestionKind, payload: dict, refs: list[str], reason: str, goal_id: int | None) -> int: ...
def approve(conn: Conn, sid: int, edited_payload: dict | None = None) -> None: ...  # queues the executor
def execute(conn: Conn, config: Config, sid: int) -> str: ...  # applied_ref: draft Message-ID / task id

# kb/assistant/priority.py
@dataclass(frozen=True)
class Priority: score: float; quadrant: Literal["do", "schedule", "delegate", "drop"]; reason: str
def score(conn: Conn, item_id: int, goals: list[Goal], now: datetime) -> Priority: ...

# kb/connectors/imap.py
def append_draft(account: ImapAccount, thread_last: Message, body: str, subject: str) -> str: ...

# kb/connectors/clickup.py
def sync_list(conn: Conn, client: ClickUpClient, list_id: str, scopes: list[str]) -> int: ...
def create_task(client: ClickUpClient, list_id: str, task: TaskDraft) -> str: ...

# kb/connectors/calendar.py
def sync_calendar(conn: Conn, url: str, calendar_id: int, now: datetime) -> int: ...

# kb/library.py
def add_version(conn: Conn, doc_id: int, filename: str, data: bytes) -> int: ...
def extract_text(filename: str, data: bytes) -> str: ...
def propose_goals(conn: Conn, llm: LlmClient, version_id: int) -> list[int]: ...

# kb/assistant/meetings.py
def prep(conn: Conn, llm: LlmClient | None, event_id: int) -> list[Section]: ...
def process_notes(conn: Conn, llm: LlmClient, event_id: int, text: str) -> NotesResult: ...

# kb/secrets.py
def seal(plaintext: str) -> bytes: ...
def unseal(blob: bytes) -> str: ...

# kb/api/auth.py
def begin_registration(conn, setup_code: str | None, session: Session | None) -> dict: ...
def finish_registration(conn, response: dict, device: str) -> RecoveryCodes | None: ...
def begin_login(conn) -> dict: ...
def finish_login(conn, response: dict, device: str) -> Session: ...
```

## Call stacks

**Morning brief:** `kb routines` → `run_due(now)` → `due_slots` → `claim(slot)` → `factpack.build`
→ `briefs.generate` (LLM structured output) → `validate_refs` → insert `briefs` → `push.send`
(quiet hours, per-device toggles) → device service worker → notification → tap → SPA `/briefs/:id`
→ `GET /api/briefs/:id` → `app_events(brief_opened)`.

**Mail revision:** `run_due` (revision slot) → `triage.run_pass(since=previous pass)` → sender_prefs
→ LLM for the rest → `triage` rows → brief (revision) → push only if needs_reply/important.

**Loop lifecycle:** indexer rebuilds a unit → enqueue `loops.detect(item)` (after summary settles)
→ `needs_reply_check` + LLM detect → insert/close loops + `loop_events` → morning brief fact pack
includes due/overdue → owner taps Done in SPA → `POST /api/loops/:id/act` → `loops.act`.

**Reply draft:** revision pass → `priority.score` → top N needs-reply → `drafts.reply` (LLM, refs
validated) → `suggestions.propose` → Assistant page → owner approves → `execute` →
`imap.append_draft` → draft in the Gmail thread → owner sends from Gmail → next ingest sees the
sent reply → needs-reply loop closes.

**Meeting:** `calendar.sync_calendar` → events → routines tick: T-30 `meetings.prep` → T-10
`push.send` → after the meeting the owner attaches notes → `process_notes` → loops (mine) +
`task` suggestions → approve → `clickup.create_task` → ClickUp sync sees the task closed → loop done.

**Including a dialog:** Connectors › Telegram → `POST /api/connectors/telegram/dialogs/:id`
(included, scopes) → review rule + backfill job → the telegram service picks it up within a minute.

**Sign-in:** SPA `/login` → `POST /api/auth/login/begin` → browser WebAuthn → `/login/finish` →
session cookie → `GET /api/today`.

## Test plan

Python (pytest, embedded Postgres, stubbed LLM/push):
- `test_due_slots_kyiv_dst` — slots computed in Europe/Kyiv across a DST change.
- `test_claim_is_idempotent` — two schedulers claiming one slot → one run.
- `test_catch_up_once_after_downtime` — 07:00–09:30 outage → one delayed morning brief.
- `test_factpack_morning_window_and_scopes` — items since last evening wrap grouped by scope.
- `test_brief_refs_validated_unknown_ids_dropped` / `test_data_only_brief_when_budget_reached`.
- `test_revision_quiet_pass_no_push` / `test_revision_needs_reply_pushes` / `test_sender_noise_pref`.
- `test_weekly_plan_accept_feeds_morning_brief`.
- `test_quiet_hours_no_push_but_brief_stored`.
- `test_loop_detect_promise_by_owner_with_due` / `test_promise_to_owner` / `test_chitchat_no_loop` (stub LLM fixtures).
- `test_needs_reply_closes_when_owner_replies` / `test_dismissed_source_not_recreated` / `test_snooze_returns_on_date` / `test_overdue_marked`.
- `test_resolve_due_phrases_uk_ru_en` — "завтра", "до понеділка", "by Friday" → dates.
- API: `test_all_routes_require_session`, `test_setup_code_required_for_first_passkey`, `test_recovery_code_single_use`, `test_sign_out_everywhere`, `test_login_lockout_after_10_failures`, `test_csrf_header_required_on_post`, `test_settings_validation`.
- `test_push_payload_has_no_content` / `test_gone_subscription_deleted`.
- `test_usefulness_metric_28_days`.
- Connectors: `test_secret_roundtrip_and_never_returned_by_api`, `test_wrong_imap_password_not_saved`,
  `test_new_account_ingested_without_restart`, `test_new_dialog_not_ingested_until_included`,
  `test_mark_change_rescopes_items`, `test_disconnect_keep_vs_remove`, `test_add_project_scope`;
  `test_telegram_wrapper_has_no_write_methods` keeps passing.
- ClickUp (recorded HTTP fixtures): `test_sync_list_incremental_cursor`, `test_429_backoff_resumes`,
  `test_task_created_only_from_approved`, `test_create_task_idempotent_retry`, `test_closed_task_closes_loop`.
- Calendar: `test_ics_recurring_expanded_kyiv`, `test_declined_and_all_day_not_reminded`,
  `test_prep_and_reminder_times`.
- Library: `test_extract_md_pdf_docx`, `test_document_requires_mark`, `test_versions_latest_indexed`,
  `test_ai_disallowed_document_never_in_prompt`, `test_goals_proposed_need_confirmation`.
- Assistant: `test_priority_goal_linked_first_with_reason`, `test_draft_saved_to_drafts_not_sent`
  (fake IMAP server: APPEND to Drafts; no send path exists), `test_draft_not_ingested_and_loop_stays_open`,
  `test_nudge_for_overdue_owed_to_me`, `test_delegate_matches_teammate_area`,
  `test_focus_blocks_and_meeting_load_warning`, `test_neglected_goal_in_weekly_review`,
  `test_notes_to_loops_and_task_drafts`, `test_discard_rate_lowers_frequency`.
- TS: `connectors.test.tsx`, `library.test.tsx` (mark required), `assistant.test.tsx`
  (approve/edit/discard), `meeting.test.tsx`.

TypeScript (Vitest + Testing Library, MSW for API):
- `shell.test.tsx` — dock, bottom bar on narrow width, ⌘K palette jumps to a person.
- `today.test.tsx` — brief, needs-reply and due promises render from API data.
- `inbox.test.tsx`, `loops.test.tsx` — actions call the API and update the list.
- `sw.test.ts` — push event shows headline and opens URL on click.
- `offline.test.tsx` — offline banner and disabled actions.

## Migration Plan
Branch `change/web-os-v1` from `kb-design-v1-plan`; PR to `main` after v1 is merged. Deploy:
migration 0011 → `web` and `routines` services → `kb web setup-code` in the Coolify terminal →
register the first passkey → install the app on phone/laptop → enable push. Rollback: stop the two
services; no existing behaviour changes.

## Risks / Trade-offs
- [Loop detection precision] → cheap model + owner corrections (dismiss/done) recorded; dismissed
  sources never recreated; precision measured on Status via the resolved/dismissed ratio.
- [iOS push needs Home-Screen install] → onboarding step in Settings; push also works on desktop.
- [Public web endpoint] → passkeys only, lockout, CSRF header, no data before sign-in.
- [AI cost of briefs] → fact packs use summaries (not raw text); monthly cap; data-only fallback.
- [Second toolchain] → workspaces keep `make check` single-command; CI already sets up Node.
- [First writes outside the server] → only two executors, both behind approval, idempotent and
  logged; no Telegram writer exists; no code path sends email.
- [Credentials in the database] → AES-GCM with a key only in Coolify env; backups hold only
  ciphertext; losing the key means re-entering credentials (documented).
- [Personal documents sent to OpenAI] → per-document "AI may read" switch, redaction, only core
  documents on by default.
- [Draft quality and tone] → acceptance and edit rates on Status; tone from the owner's own replies.

## Open Questions
- Exact default revision pass times (11:00/14:00/17:00 assumed) — editable in Settings.

## Least confident decisions
1. **React vs Svelte** — benchmarked (D22): React kept; Svelte is faster and lighter, but the gap
   is invisible at our data sizes except on a cold phone start.
2. **Loop detection by LLM per conversation** — may produce false positives in busy group chats
   (РД ТОП); limiting detection to DMs and small groups first may be better.
3. **Separate `routines` service vs running inside `index`** — separate isolates failures but adds a
   container; the index loop already has idle cycles.
4. **Briefs written by `gpt-6.1-sol`** — `gpt-6-luna` may be good enough at a fraction of the cost.
5. **FastAPI as a new dependency** — gives OpenAPI types; plain Starlette would avoid it.
6. **Separate web domain (`os.…`) vs a path on the MCP domain** — separate keeps cookies and CSP
   clean but needs another Coolify domain.
7. **Gmail drafts via IMAP APPEND** — avoids OAuth, but threading of appended drafts depends on
   correct `References`; verified on the real mailbox in the drafts tracer task.
8. **New dependencies** (`pypdf`, `python-docx`, `icalendar`, `recurring-ical-events`) — need the
   owner's approval (AGENTS.md); alternatives: text-only uploads and a minimal ICS parser.
9. **Polling ClickUp every 5 minutes instead of webhooks** — simpler, no public callback; fits 100 req/min.
10. **Meeting notes source** — the owner's meeting-notes app is unknown; import accepts paste,
    files and forwarded email until the native recorder exists.
