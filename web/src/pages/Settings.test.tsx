import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

const me = { signed_in: true, has_passkeys: true, needs_passkey: false };
const app = {
  schedule: {
    morning: "08:00:00",
    revision: ["11:00:00", "14:00:00", "17:00:00"],
    evening: "19:00:00",
    weekly_review_day: 4,
    weekly_review_time: "19:00:00",
    weekly_plan_day: 0,
    weekly_plan_time: "08:00:00",
  },
  quiet_hours: { start: "22:00:00", end: "07:30:00" },
  ai_budget_usd: null,
};
const routes = {
  "GET /api/auth/me": me,
  "GET /api/briefs": { briefs: [] },
  "GET /api/settings": { app, budget_default_usd: 30, month_spend_usd: 4.2 },
  "GET /api/settings/push": {
    routines: ["morning", "revision", "evening", "weekly_review", "weekly_plan"],
    devices: [
      {
        id: 3,
        device: "iPhone Safari",
        routines: ["morning", "revision"],
        last_sent_at: null,
        last_error: null,
      },
    ],
  },
  "GET /api/settings/owner": {
    emails: ["me@example.com"],
    added_emails: [],
    telegram_ids: ["111"],
  },
  "GET /api/settings/rules": { rules: [] },
  "GET /api/unsorted": { items: [] },
};

test("moving the morning brief to 07:30 saves the schedule", async () => {
  window.history.pushState({}, "", "/settings");
  const calls = mockApi({ ...routes, "PUT /api/settings": { app } });
  renderApp();
  const morning = await screen.findByLabelText("Morning brief time");
  expect(screen.getByText("spent this month: $4.20")).toBeInTheDocument();
  await userEvent.clear(morning);
  await userEvent.type(morning, "07:30");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(calls.some((c) => c.method === "PUT" && c.path === "/api/settings")).toBe(true),
  );
  const body = JSON.parse(String(calls.find((c) => c.method === "PUT")?.init?.body));
  expect(body.app.schedule.morning).toBe("07:30");
  expect(body.app.schedule.revision).toEqual(["11:00", "14:00", "17:00"]);
  expect(body.app.ai_budget_usd).toBeNull();
});

test("a routine can be switched off for one device", async () => {
  window.history.pushState({}, "", "/settings");
  const calls = mockApi({ ...routes, "PUT /api/settings/push/3": { ok: true } });
  renderApp();
  await userEvent.click(await screen.findByLabelText("Mail revision on device 3"));
  const put = calls.find((c) => c.path === "/api/settings/push/3");
  expect(JSON.parse(String(put?.init?.body))).toEqual({ routines: ["morning"] });
});

test("server validation errors are shown", async () => {
  window.history.pushState({}, "", "/settings");
  mockApi(routes); // PUT not mocked → 404 with a message
  renderApp();
  await userEvent.click(await screen.findByRole("button", { name: "Save" }));
  expect(await screen.findByRole("status")).toHaveTextContent("not mocked");
});
