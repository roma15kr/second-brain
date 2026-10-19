# Proposal: assistant-command-v1 — ask the assistant by text or voice, and dictate structured notes

Branch: `change/assistant-command-v1`, created from `main` (web-os-v1 slices 1–11 are merged there).
Depends on web-os-v1 task group 12 for the email draft executor (Save to Drafts / Send on tap);
until that lands, email drafts from this change wait in the approval queue like any other suggestion.

## Why

**Problem (in the owner's words):** "Add a possibility to ask, make draft emails or tasks, search,
or make some additional action (like prepare a report) for my assistant via a text field and voice
dictation. I also need to be able to dictate and not only transcribe my text, but summarize and
structure my speech."

Today the web OS only *pushes* (briefs, revisions, loops, suggestions). To ask something or get a
draft, the owner has to switch to Claude via MCP, and nothing spoken can be captured at all.

**Evidence:**
- Owner request 2026-10-18 (chat, quoted above).
- Roadmap "Next": `chat-v1` (KB chat via OpenAI tools) and `voice-v1` (dictation) —
  `docs/product/roadmap.md`.
- `docs/research/web-os-pwa-voice.md`: microphone + `MediaRecorder` work in the installed PWA on
  iPhone, macOS Safari and Chrome **while the app is open**; what the web cannot do is system-wide
  dictation, background recording and capturing call audio — those stay in the native apps.
- web-os-v1 already has the pieces this builds on: internal search, open loops, ClickUp updates,
  the suggestions table with the approval queue and the ClickUp task executor.

**Success metric:** over 4 consecutive weeks the owner makes **≥ 15 assistant requests per week**
(text or voice), and **≥ 60% of drafts and tasks** created from requests are approved (as is or
edited) rather than discarded. Measured from the app's event log (`assistant_request`,
suggestion approve/discard with `origin = command`) and shown on the Status page.

## What Changes

- **Assistant box** in the web OS: a text field (with a microphone button) available from every
  page — the ⌘K palette gets an "Ask the assistant" mode, and on the phone a button in the dock.
  The owner types or says what they want; the assistant answers with sources, or prepares an action.
- **What the assistant can do from a request:**
  - answer questions from the knowledge base (mail, Telegram, ClickUp, Library), with cited sources;
  - search and show results (same search as the Search page);
  - draft an email (a reply in an existing thread, or a new email) → approval queue;
  - draft a ClickUp task (list, assignee, due date) → approval queue;
  - draft a Telegram reply (for copying, as in web-os-v1);
  - create, snooze or close an open loop ("remind me to call Olena on Thursday");
  - prepare a report (e.g. "Quokka week: what was decided, what is late") → a page that can be
    saved to the Library.
- **Outward actions never happen from the box directly**: drafts and tasks go to the approval queue
  (web-os-v1 rule "Propose, never act alone" applies unchanged). Loops are the owner's own list and
  are changed directly, with undo.
- **Requests run on the server** and continue if the phone locks; the page shows the steps taken
  ("searched mail for …", "read thread …") and the result when it is ready. Request history is kept
  as threads so the owner can follow up ("make it shorter", "assign it to Max instead").
- **Dictation in the app** (microphone button): the owner speaks, the recording is transcribed, and
  the owner picks what to get:
  - **Verbatim** — the transcript as spoken;
  - **Clean** — filler words, repetitions and false starts removed, punctuation fixed, same wording;
  - **Structured** — a short summary, then the content organised under headings with bullet points,
    with decisions and action items listed separately;
  - **As a request** — the transcript is sent to the assistant as a command.
  The result can be copied, saved to the Library as a note (with a project mark), or turned into a
  request. Dictation keeps the language spoken (uk/ru/en, mixed).
- **Privacy and cost**: audio is deleted after a successful transcription; transcripts and requests
  are redacted before storage like other sources; private Library documents are never read by the
  assistant; every request counts against the monthly AI budget and shows its cost.
- **Decision changes (need owner confirmation):**
  - ADR 0014 is amended: the web OS **does** record dictation while the app is open (in-app only);
    system-wide dictation, background and call/meeting recording remain in the native apps.
  - The web-os-v1 non-goal "Chat with the knowledge base inside the web app" is lifted by this change.

## Capabilities

### New Capabilities
- `assistant-requests`: the owner asks the assistant in natural language (text or a transcribed
  voice request); it answers with sources or prepares actions (drafts, tasks, loops, reports) within
  the approval rules, keeps request threads, and respects privacy and budget limits.
- `voice-dictation`: recording speech in the web OS and turning it into a verbatim, clean or
  structured text (or a request), with saving to the Library and audio deletion after transcription.

### Modified Capabilities
None in `openspec/specs/`. The approval-queue rules this change relies on live in the unarchived
web-os-v1 `assistant-actions` delta and are used, not changed; the knowledge-search exclusions for
private documents apply as they are.

## Impact

- **API:** `POST /api/assistant/requests`, `GET /api/assistant/requests/{id}`,
  `GET /api/assistant/threads`, `POST /api/dictations` (audio upload), `POST /api/dictations/{id}/render`,
  `POST /api/dictations/{id}/save`.
- **Backend:** `src/kb/assistant/agent.py` (tool loop over the OpenAI Responses API with function
  tools), `src/kb/assistant/tools.py`, `src/kb/assistant/reports.py`, `src/kb/dictation.py`;
  suggestions gain `origin` and a new kind `email` (a new email, not a reply).
- **DB:** migrations for `assistant_threads`, `assistant_requests` (steps, refs, cost),
  `dictations` (transcript, renders, audio path until deleted); `suggestions.origin`.
- **Frontend:** Assistant page and thread view, palette "Ask" mode, dock button, `Recorder` component
  (MediaRecorder; webm/opus or mp4 on iOS), Dictation sheet.
- **Dependencies:** none new (OpenAI SDK already in use for transcription and tool calls).
- **Docs:** ADR 0014 amendment, web-os-v1 proposal non-goal note, architecture, STATUS.
