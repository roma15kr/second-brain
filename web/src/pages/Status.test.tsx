import { screen } from "@testing-library/react";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

test("status shows usefulness against targets, health, backups and AI spend", async () => {
  window.history.pushState({}, "", "/status");
  mockApi({
    "GET /api/auth/me": { signed_in: true, has_passkeys: true, needs_passkey: false },
    "GET /api/briefs": { briefs: [] },
    "GET /api/status": {
      system: {
        healthy: false,
        sources: [
          {
            source: "gmail-digisoft",
            healthy: false,
            last_ok: null,
            last_error: "AUTHENTICATIONFAILED",
          },
        ],
        index_queue: { pending: 0, failed: 0 },
        items: { email_thread: 625 },
        database_mb: 266,
        backup: {
          last_status: "ok",
          last_at: "2026-10-20T03:00:00Z",
          detail: "restored counts match",
          stale: false,
        },
      },
      routine_runs: [
        {
          routine: "morning",
          slot: "2026-10-20T05:00:00Z",
          status: "done",
          delayed: true,
          error: null,
        },
      ],
      ai: {
        month_spend_usd: 6.4,
        budget_usd: 30,
        by_purpose: [{ purpose: "morning", model: "gpt-6.1-sol", usd: 2.1 }],
      },
      usefulness: {
        days: 28,
        briefs: { total: 20, used: 17, share: 0.85, target: 0.8 },
        loops: { total: 10, resolved: 5, share: 0.5, target: 0.7 },
      },
    },
  });
  renderApp();
  expect(await screen.findByText("85%")).toHaveClass("good");
  expect(screen.getByText("50%")).toHaveClass("bad");
  expect(screen.getByText("AUTHENTICATIONFAILED")).toBeInTheDocument();
  expect(screen.getByText("$6.40")).toBeInTheDocument();
  expect(screen.getByText(/delayed/)).toBeInTheDocument();
});
