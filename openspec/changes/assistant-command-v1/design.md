# Design: assistant-command-v1

## Context

See proposal.md (Why). Relevant current state on `main`:
- The SPA (React, ADR 0015) talks to the FastAPI app in the `web` container; search runs in the MCP
  container through `POST /internal/search` (models loaded once), with `SearchFilters.include_private=False`
  keeping "AI may not read" documents out.
- `kb.distill.OpenAIClient` wraps the OpenAI Responses API (structured output, batch); briefs use
  `gpt-6.1-sol`, triage `gpt-6-luna`. Spend is checked against a **monthly** budget
  (`settings_store.budget_usd`).
- `suggestions` (web-os-v1 D17) holds drafts with approve/edit/discard; the ClickUp task executor
  exists; email executors (IMAP APPEND, SMTP send with undo) are web-os-v1 task group 12.
- Loops: `loops.add_manual`, `loops.act` (snooze/done/dismiss) with `loop_events`.
- Library: `library.add_document` + `index_document` (notes are a document kind).
- Web Push: `push.notify_*` with per-device routine opt-in.

## Goals / Non-Goals

**Goals:** one agent loop shared by text and voice requests; every outward action through the
existing suggestions queue; dictation that works on iPhone Safari/PWA and desktop browsers.

**Non-Goals:**
- Live (streaming) captions while speaking; transcription starts after stop.
- Voice replies (text-to-speech).
- The assistant acting on a schedule from a request ("every Monday send me…") — later change.
- Requests from Telegram or MCP; the box is in the web OS only.
- System-wide dictation, background or call recording (native apps, ADR 0014).

## Decisions

### D1. Agent: OpenAI Responses API with function tools, bounded loop
`src/kb/assistant/agent.py` runs `gpt-6.1-sol` with function tools and `store=False`, feeding tool
results back until the model returns a final message, at most **8 tool calls** and **90 s** per
request. Final output is a structured JSON (`answer_md`, `refs`, `created` (suggestion/loop ids),
`report` or null); refs are validated like briefs (`item:`/`loop:`/`suggestion:` ids that exist and
were returned by a tool in this request), unknown refs are dropped and the statement marked
unsourced.
*Alternatives:* a fixed intent classifier + one handler per intent (cheaper, but each new action
means new code, and follow-ups like "assign it to Olena instead" are awkward); Claude via MCP
(already exists, but not in the web OS and not on the phone with approvals).

### D2. Tools (server-side, owner-scoped, read-mostly)
| Tool | Effect |
|---|---|
| `search(query, scopes?, kinds?, person?, since?, until?)` | internal search, `include_private=False` |
| `get_item(id)` | redacted text + metadata; refuses private documents |
| `person(name)` | people profile |
| `loops(status?, scope?)`, `clickup_updates()`, `today()` | read state |
| `draft_reply(item_id, text)`, `draft_email(to, subject, text, mailbox?)` | `suggestions` kind `reply_email` / new kind `email` |
| `draft_task(list?, name, description, assignee?, due?)` | `suggestions` kind `task` (list via `default_list` / name match) |
| `draft_tg_reply(item_id, text)` | `suggestions` kind `reply_tg` |
| `update_suggestion(id, changes)` | only `proposed` suggestions from this thread |
| `add_loop(title, due?, person?)`, `loop_action(id, snooze/done/dismiss, until?)` | direct, recorded for undo |
| `report(title, period, scope?, sections)` | stores a report (D5) |
No tool sends mail, writes to ClickUp or Telegram: approval and executors stay in web-os-v1 D17.
Suggestions get `origin` (`routine` | `command`) and `thread_id` for the metric and for follow-ups.

### D3. Requests run in the API process, persisted step by step
`POST /api/assistant/requests {thread_id?, text, voice_dictation_id?}` inserts `assistant_requests`
(status `running`) and starts the agent on a small thread pool (2 workers) in the `web` container;
each tool call appends a step (`{tool, summary}`) so `GET /api/assistant/requests/{id}` (polled every
1.5 s by the SPA) shows progress. On finish: status `done|failed`, answer, refs, cost; a push
(`routine = assistant`) when it took > 30 s. On startup, requests left `running` are marked
`failed` with "interrupted by an update — Retry".
*Alternatives:* the `routines` loop (30 s tick: too slow for interactive use); SSE streaming
(Cloudflare and iOS PWA reconnection make polling simpler; can be added later).

### D4. Threads and context
`assistant_threads` (title from the first request, pinned, updated_at); a follow-up sends the last
6 turns (request, answer, created ids) as context; older turns are summarised once into the
thread. Threads not pinned are deleted after 90 days (maintenance task). Requests and answers are
redacted (`redact_text`) before storage and are **not** indexed into search (no self-citation).

### D5. Reports
The `report` tool stores `{title, sections:[{heading, body_md, refs}]}` on the request; the SPA
renders it as a page with links. "Save to Library" calls `library.add_document(kind='note')` with
the markdown and the chosen scope, then `index_document`, so saved reports become searchable.
Facts for reports come from tools (search, loops, ClickUp updates, fact-pack helpers from
`routines/factpack.py` for a period/scope), so the model writes, but data is fetched.

### D6. Budget
Before each model call the agent checks the month's spend + an estimate (input tokens × price);
over budget → no model call: the request text is searched as is and the answer explains
(loop changes need the model to understand the request, so they wait for budget); "Run anyway" sets `allow_over_budget` on that one request. Costs are
recorded per request and per dictation and summed into the monthly spend with briefs.

### D7. Dictation recording in the browser
`Recorder` component: `getUserMedia({audio})` + `MediaRecorder`, mime picked by
`isTypeSupported` (`audio/webm;codecs=opus` on Chrome, `audio/mp4` on Safari/iOS), 10 s timeslices
appended to an IndexedDB record so a stop, lock (`visibilitychange` → stop) or crash keeps what was
recorded. Upload `POST /api/dictations` (multipart, ≤ 25 MB, ≈ 15 min at 64 kbps AAC) with retry
from IndexedDB until the server returns an id; then the local blob is deleted.
*Alternative:* streaming to `gpt-live-transcribe` over WebRTC — live text is nice but iOS
background suspension and reconnection make it fragile; deferred.

### D8. Transcription and forms
Server stores the upload under `/data/dictations/<id>` and transcribes with OpenAI
`gpt-transcribe` (ADR 0014), language auto-detected (no forced language, so mixed speech stays as
spoken), then deletes the audio; on failure keeps it 7 days with retry (maintenance task).
Forms are produced on demand and cached on the row:
- **Verbatim** = the transcript;
- **Clean** = `gpt-6-luna`, instruction "remove fillers/repetitions/false starts, fix punctuation,
  do not reword, add or drop sentences"; checked: if the clean text loses more than 15% of the
  transcript's content words, Verbatim is shown with a note;
- **Structured** = `gpt-6.1-sol`, structured output `{summary, sections:[{heading, bullets}],
  decisions[], actions:[{text, owner?, due?}]}`; dates only when present in the transcript (the
  prompt forbids inventing; a check drops `due` values whose day/month words are not in the text);
- **As a request** = D3 with the transcript as text.

### D9. API and storage
Tables: `assistant_threads`, `assistant_requests` (thread_id, text, status, steps jsonb, answer_md,
refs, report jsonb, created jsonb, cost_usd, allow_over_budget, started_at, finished_at),
`dictations` (status, audio_path, mime, seconds, transcript, forms jsonb, cost_usd, saved_doc_id,
created_at); `suggestions.origin`, `suggestions.thread_id`, kind `email` added to the check.
All endpoints are session-protected with the CSRF header (existing middleware).

### D10. UI
- Palette: typing `?` or choosing "Ask the assistant" turns the input into a request field.
- Dock app **Assistant** (`/assistant`): thread list, thread view (request, steps, answer with
  ref chips, inline suggestion cards with approve/edit/discard, loop changes with undo, report
  view with "Save to Library").
- Microphone button in the request field and a **Dictate** button in the dock: a sheet with timer,
  pause/stop, then the four form tabs, Copy / Save to Library / Ask.

## Risks / Trade-offs

- [The model creates wrong drafts or tasks] → all go through the approval queue; discard reasons
  feed the existing learning; metric tracked per origin.
- [Prompt injection from mail/chat content read by tools] → tool results are passed as data with a
  system rule; the agent has no tool that acts outward; `update_suggestion` is limited to the
  thread's own drafts; loop changes are undoable.
- [Long requests hold a worker in the web container] → 2 workers, 90 s cap, queue beyond that with
  "waiting" status.
- [Structured form drops or invents content] → faithfulness checks in D8; Verbatim is always one
  tap away; spec scenarios become tests with recorded transcripts.
- [iOS MediaRecorder quirks (mp4 only, stops on lock)] → mime detection, timeslices in IndexedDB,
  tests on the owner's iPhone in acceptance.
- [Cost of agent loops] → 8-call cap, cheap model for Clean, budget gate, cost shown per request.

## Migration Plan

Additive migrations only (new tables, a nullable column, a widened check). Deploy as usual
(PR → main → Coolify). Rollback: redeploy the previous image; new tables are ignored.
ADR 0014 gets an amendment note; the web-os-v1 proposal non-goal gets a pointer to this change.

## Open Questions

- Whether the default mailbox for new emails should be per project (e.g. quokka mailbox for
  quokka recipients) once more than one mailbox is connected; v1 uses "last used with this
  address, else the default".
