import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

const me = { signed_in: true, has_passkeys: true, needs_passkey: false };
const row = (id: number, routine: string, title: string, opened = false) => ({
  id,
  routine,
  title,
  headline: `${title}: 2 conversations across 1 scope`,
  mode: "ai",
  created_at: "2026-10-20T05:00:00Z",
  opened,
  useful: null,
});
const brief = {
  id: 7,
  routine: "morning",
  title: "Morning brief",
  headline: "Morning brief: 2 conversations across 1 scope",
  window_start: "2026-10-19T16:00:00Z",
  window_end: "2026-10-20T05:00:00Z",
  mode: "ai",
  sections: [],
  created_at: "2026-10-20T05:00:00Z",
  opened: false,
  useful: null,
};

test("briefs list shows every routine output and filters by type", async () => {
  window.history.pushState({}, "", "/briefs");
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/briefs": {
      briefs: [row(2, "evening", "Evening wrap"), row(1, "morning", "Morning brief", true)],
      next_before: null,
    },
    "GET /api/briefs?routine=evening": {
      briefs: [row(2, "evening", "Evening wrap")],
      next_before: null,
    },
  });
  renderApp();
  expect(await screen.findByText("Evening wrap")).toBeInTheDocument();
  expect(screen.getByText("Morning brief")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Evening" }));
  await waitFor(() => expect(screen.queryByText("Morning brief")).not.toBeInTheDocument());
  expect(calls.some((c) => c.path === "/api/briefs?routine=evening")).toBe(true);
});

test("opening a brief from a push records it, and rating is sent", async () => {
  window.history.pushState({}, "", "/briefs/7?via=push");
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/briefs/7": brief,
    "POST /api/briefs/7/opened": { ok: true },
    "POST /api/briefs/7/rating": { ok: true },
  });
  renderApp();
  expect(
    await screen.findByText("Morning brief: 2 conversations across 1 scope"),
  ).toBeInTheDocument();
  await waitFor(() => expect(calls.some((c) => c.path === "/api/briefs/7/opened")).toBe(true));
  const opened = calls.filter((c) => c.path === "/api/briefs/7/opened");
  expect(opened).toHaveLength(1);
  expect(JSON.parse(String(opened[0].init?.body))).toEqual({ via: "push" });
  await userEvent.click(screen.getByRole("button", { name: "👍 Useful" }));
  const rating = calls.find((c) => c.path === "/api/briefs/7/rating");
  expect(JSON.parse(String(rating?.init?.body))).toEqual({ useful: true });
});
