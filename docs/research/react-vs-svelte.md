# React vs Svelte for the web OS (2026-10-18)

Question: which frontend framework for the second brain OS (single owner, laptop + phone PWA,
dashboards fed by a Python JSON API, AI routines today and possibly multi-agent views later)?

## 1. Raw speed — js-framework-benchmark (Chrome 154, results published 2026-10-04)

Source: `krausest/js-framework-benchmark`, file `webdriver-ts-results/src/results.ts` (commit
"Chrome 154 results"). Medians of the published runs, keyed implementations; computed with
a local script. Durations in ms (lower is better), memory in MB, size in kB.

| Benchmark | vanilla JS | React 19.2 (hooks) | React 19 + Compiler | Svelte 5.42 | Solid 1.9 |
|---|---:|---:|---:|---:|---:|
| create 1,000 rows | 20.6 | 23.6 | 24.0 | 22.1 | 21.7 |
| replace 1,000 rows | 22.1 | 30.2 | 29.8 | 24.9 | 23.9 |
| partial update (every 10th row) | 9.7 | 14.7 | 14.9 | 10.9 | 10.4 |
| select row | 2.5 | 5.4 | 7.0 | 5.0 | 3.2 |
| swap 2 rows | 11.0 | **89.7** | 90.9 | 13.0 | 12.5 |
| remove row | 10.1 | 11.3 | 12.0 | 10.5 | 10.2 |
| create 10,000 rows | 213 | 401 | 433 | 232 | 229 |
| append 1,000 rows | 23.6 | 29.3 | 29.5 | 25.1 | 24.7 |
| clear 1,000 rows | 8.7 | 17.6 | 17.6 | 10.4 | 10.6 |
| memory after load | 0.5 | 1.2 | 1.1 | 0.7 | 0.6 |
| memory with 1,000 rows | 1.9 | 4.4 | 4.6 | 2.9 | 2.7 |
| compressed bundle (brotli) | 2.5 | **51.4** | 50.0 | **9.7** | 4.5 |
| first paint | 54 | **227** | 220 | **71** | 52 |
| **geometric mean slowdown vs fastest** (9 CPU tests, unweighted) | 1.00 | **1.82** | 1.91 | **1.19** | 1.10 |

Third-party 2026 articles report the same pattern (Svelte ≈ 1.1–1.2×, React ≈ 1.7–1.8× of vanilla),
with inconsistent exact figures; the table above is computed from the benchmark's own data.

**What it means for this app:** Svelte is ~1.5× faster on DOM work, uses ~35% less memory and ships
~5× less JavaScript. In absolute terms for our pages (lists of tens to a few hundred rows, not
10,000), interactions are 1–10 ms in either framework — below the 16 ms frame budget, i.e.
not perceptible. The visible difference is **cold start on the phone**: ~150 ms first paint and
~40 kB more JS for React on the first visit; afterwards the service worker serves the app from cache.

## 2. Server load

Identical. Both compile to static files served once and cached by the service worker; there is no
server-side rendering in our design. Server load is the Python API (queries, search, AI calls,
SSE streams) and does not depend on the frontend framework. (SvelteKit or Next.js SSR would add
server load; we use neither.)

## 3. Parallel execution

- The browser runs each tab's UI on **one main thread** in both frameworks. Real parallelism comes
  from **Web Workers** (e.g. a client-side search index or markdown rendering), which both use the
  same way.
- **React 19** has a concurrent renderer: `useTransition` / `useDeferredValue` let a large re-render
  be interrupted so typing and taps stay responsive. Useful when many panels update at once.
- **Svelte 5** has no scheduler but updates only the exact DOM nodes whose signals changed
  ("runes"), so there is usually less work to schedule.
- The heavy parallel work in this system — routines, agents, AI calls — runs **on the server**
  (Python job queue, asyncio), not in the browser.

## 4. Future multi-agent UI

A multi-agent view means several agents streaming progress, tool calls and drafts at the same time
(SSE/WebSocket), plus human-in-the-loop approvals.

| Need | React | Svelte |
|---|---|---|
| Many concurrent token streams updating small parts of the screen | Fine with an external store (`useSyncExternalStore`) or signals; naive state causes re-renders | **Native strength** (fine-grained reactivity) |
| Ready-made agent/chat UI components | **assistant-ui, CopilotKit, AG-UI clients**, Vercel AI SDK — React-first | Vercel AI SDK (official Svelte bindings); AG-UI via own client; fewer kits |
| Generative UI (agent returns components) | Most examples and libraries | Possible, few examples |
| Code written by AI coding agents (how this project is built) | **Largest training base; most reliable output** | Svelte 5 runes are newer; agents sometimes emit Svelte 4 syntax (mitigated by Svelte's llms.txt/MCP docs) |

## 5. Ecosystem and team

React: used by ~84% of State of JS 2025 respondents; largest library and hiring pool. Svelte:
consistently top-rated satisfaction, much smaller ecosystem (job listings ~1% of React's).

## 6. Scorecard (weights for this project)

| Criterion | Weight | React | Svelte |
|---|---:|---:|---:|
| Runtime speed / memory | 15% | 3 | 5 |
| Phone cold start / bundle | 10% | 3 | 5 |
| Server load | 5% | 5 | 5 |
| Parallel / concurrent UI | 10% | 4 | 4 |
| Agent UI ecosystem (future multi-agent) | 20% | 5 | 3 |
| Reliability of AI-written code | 25% | 5 | 3 |
| Libraries (PWA, passkeys, charts, tests) | 10% | 5 | 4 |
| Simplicity for a single-user app | 5% | 3 | 5 |
| **Weighted total** | | **4.30** | **3.90** |

## Verdict

**Keep React** (ADR 0015). Svelte wins every performance metric, but at this app's data sizes the
gap is invisible except ~150 ms on a first, uncached phone load. The deciding factors are the
future agent UI (React-first component kits) and that the code is written mostly by AI coding
agents, which produce React most reliably. Mitigations for React's weak spots: route-level code
splitting, keep the shell small, use an external store for streams.

**When Svelte would be the better choice:** if phone cold-start and minimal code matter more than
agent UI kits, or if a human Svelte developer maintains the frontend.

## Sources
- js-framework-benchmark, Chrome 154 results: https://github.com/krausest/js-framework-benchmark
  (raw data `webdriver-ts-results/src/results.ts`; interactive table https://krausest.github.io/js-framework-benchmark/current.html)
- State of JS 2025, front-end frameworks: https://2025.stateofjs.com/en-US/libraries/front-end-frameworks/
- Usage figure (React 83.6%): https://blog.codercops.com/blog/state-of-javascript-2025-survey-2026
- Agent UI libraries and framework support: https://cadenya.com/other-content/copilotkit-vs-assistant-ui-vs-ag-ui ,
  https://alexander-lukashov.medium.com/the-overview-of-ui-libraries-for-ai-chat-interfaces-in-2026-146a1492114a ,
  https://dev.to/aierastack/choosing-a-frontend-framework-in-2026-when-ai-becomes-your-invisible-teammate-5b8g
- Svelte job market and ecosystem size: https://tech-insider.org/svelte-vs-react-2026/
