import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

const me = { signed_in: true, has_passkeys: true, needs_passkey: false };
const brief = (id: number, routine: string, headline: string) => ({
  id,
  routine,
  title: routine,
  headline,
  window_start: "2026-10-19T00:00:00Z",
  window_end: "2026-10-26T00:00:00Z",
  mode: "ai",
  sections: [],
  created_at: "2026-10-26T05:00:00Z",
});
const proposed = [
  { title: "Close the Epicentr deal", reason: "due this week", refs: ["item:1"] },
  { title: "Chase customs documents", reason: "overdue", refs: ["loop:2"] },
];

test("last week's review and plan are shown and the plan can be accepted", async () => {
  window.history.pushState({}, "", "/week");
  let accepted: unknown = null;
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/week": () => ({
      week_start: "2026-10-26",
      review: null,
      plan: {
        brief: brief(9, "weekly_plan", "Weekly plan: 14 conversations"),
        proposed,
        accepted,
        accepted_at: null,
      },
      weeks: ["2026-10-26", "2026-10-19"],
    }),
    "GET /api/week?start=2026-10-19": {
      week_start: "2026-10-19",
      review: brief(5, "weekly_review", "Weekly review: 40 conversations across 3 scopes"),
      plan: null,
      weeks: ["2026-10-26", "2026-10-19"],
    },
    "POST /api/week/plan/9/accept": () => {
      accepted = proposed;
      return { ok: true };
    },
  });
  renderApp();
  expect(await screen.findByDisplayValue("Close the Epicentr deal")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Accept plan" }));
  await waitFor(() => expect(screen.getByText("accepted")).toBeInTheDocument());
  const post = calls.find((c) => c.path === "/api/week/plan/9/accept");
  expect(JSON.parse(String(post?.init?.body))).toEqual({});
  await userEvent.click(screen.getByRole("button", { name: "← Previous week" }));
  expect(
    await screen.findByText("Weekly review: 40 conversations across 3 scopes"),
  ).toBeInTheDocument();
});

test("editing a priority saves the edited list", async () => {
  window.history.pushState({}, "", "/week");
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/week": {
      week_start: "2026-10-26",
      review: null,
      plan: {
        brief: brief(9, "weekly_plan", "Weekly plan"),
        proposed,
        accepted: null,
        accepted_at: null,
      },
      weeks: [],
    },
    "POST /api/week/plan/9/accept": { ok: true },
  });
  renderApp();
  const first = await screen.findByLabelText("Priority 1");
  await userEvent.clear(first);
  await userEvent.type(first, "Sign Epicentr");
  await userEvent.click(screen.getByRole("button", { name: "Save and accept" }));
  const post = calls.find((c) => c.path === "/api/week/plan/9/accept");
  expect(JSON.parse(String(post?.init?.body)).priorities[0].title).toBe("Sign Epicentr");
});
