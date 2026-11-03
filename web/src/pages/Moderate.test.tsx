import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

const me = { signed_in: true, has_passkeys: true, needs_passkey: false };
const base = {
  scopes: ["quokka"],
  item_id: 40,
  item_title: "Weekly Nastya",
  status: "proposed",
  applied_ref: null,
  error: null,
  created_at: "2026-11-02T12:00:00Z",
  reason: "From the meeting “Weekly Nastya”",
};
const suggestions = [
  {
    ...base,
    id: 1,
    kind: "task",
    payload: {
      name: "Update the bundle page",
      assignee_name: "Anastasiya Tarasova",
      due_date: "2026-11-06",
      source_item_id: 40,
    },
  },
  {
    ...base,
    id: 2,
    kind: "clickup_comment",
    payload: { task_title: "Bundles redesign", body: "New buy box approved", source_item_id: 40 },
  },
  {
    ...base,
    id: 3,
    kind: "task",
    payload: { name: "Order samples", assignee_name: "Kate Oleksyuk", source_item_id: 40 },
  },
];

test("the owner ticks two proposals of a meeting and creates them; the rest is discarded", async () => {
  window.history.pushState({}, "", "/moderate");
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/suggestions": { suggestions },
    "POST /api/suggestions/moderate": { created: [1, 2], failed: {} },
  });
  renderApp();
  expect(await screen.findByText("From the meeting “Weekly Nastya”")).toBeInTheDocument();
  expect(screen.getByText("Anastasiya Tarasova · due 2026-11-06")).toBeInTheDocument();
  expect(screen.getByText("Comment on “Bundles redesign”")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Discard all" })).toBeInTheDocument();
  await userEvent.click(screen.getByLabelText("Task: Update the bundle page"));
  await userEvent.click(screen.getByLabelText("Comment on “Bundles redesign”"));
  await userEvent.click(screen.getByRole("button", { name: "Create selected (2)" }));
  await waitFor(() => expect(calls.some((c) => c.path === "/api/suggestions/moderate")).toBe(true));
  const post = calls.find((c) => c.path === "/api/suggestions/moderate");
  expect(JSON.parse(String(post?.init?.body))).toEqual({ create: [1, 2], discard: [1, 2, 3] });
});

test("nothing to moderate", async () => {
  window.history.pushState({}, "", "/moderate");
  mockApi({ "GET /api/auth/me": me, "GET /api/suggestions": { suggestions: [] } });
  renderApp();
  expect(await screen.findByText("Nothing to moderate")).toBeInTheDocument();
});
