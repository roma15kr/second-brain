import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

const me = { signed_in: true, has_passkeys: true, needs_passkey: false };

test("sign out everywhere else, and new recovery codes are shown once", async () => {
  window.history.pushState({}, "", "/settings");
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/briefs": { briefs: [] },
    "GET /api/settings": {
      app: {
        schedule: {
          morning: "08:00:00",
          revision: ["11:00:00"],
          evening: "19:00:00",
          weekly_review_day: 4,
          weekly_review_time: "19:00:00",
          weekly_plan_day: 0,
          weekly_plan_time: "08:00:00",
        },
        quiet_hours: { start: "22:00:00", end: "07:30:00" },
        ai_budget_usd: null,
      },
      budget_default_usd: 30,
      month_spend_usd: 0,
    },
    "GET /api/settings/push": { routines: [], devices: [] },
    "GET /api/settings/owner": { emails: [], added_emails: [], telegram_ids: [] },
    "GET /api/settings/rules": { rules: [] },
    "GET /api/unsorted": { items: [] },
    "GET /api/auth/sessions": {
      sessions: [
        {
          id: "aaaaaaaaaaaaaaaa",
          device: "Mac Safari",
          last_seen_at: "2026-10-20T08:00:00Z",
          current: true,
          recovery: false,
        },
        {
          id: "bbbbbbbbbbbbbbbb",
          device: "iPhone",
          last_seen_at: "2026-10-19T08:00:00Z",
          current: false,
          recovery: false,
        },
      ],
      passkeys: [
        { id: "p1", device: "Mac Safari", created_at: "2026-10-18T08:00:00Z", last_used_at: null },
      ],
      recovery_codes_left: 9,
    },
    "POST /api/auth/sessions/revoke-others": { revoked: 1 },
    "POST /api/auth/recovery-codes": {
      recovery_codes: Array.from({ length: 10 }, (_, i) => `code-${i}`),
    },
  });
  renderApp();
  expect(await screen.findByText("· this device")).toBeInTheDocument();
  expect(screen.getByText(/9 of 10 left/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Sign out everywhere else" }));
  expect(await screen.findByText("Signed out 1 other device(s).")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Generate new codes" }));
  expect(await screen.findByText("code-9")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "I've saved them" }));
  await waitFor(() => expect(screen.queryByText("code-9")).not.toBeInTheDocument());
  expect(calls.some((c) => c.path === "/api/auth/sessions/revoke-others")).toBe(true);
});
