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

test("a proposal is changed by an instruction to the AI before it is created", async () => {
  window.history.pushState({}, "", "/moderate");
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/suggestions": { suggestions },
    "POST /api/suggestions/1/revise": { suggestion: suggestions[0] },
  });
  renderApp();
  const buttons = await screen.findAllByRole("button", { name: "Change with AI" });
  await userEvent.click(buttons[0]);
  expect(screen.getByRole("button", { name: "Dictate" })).toBeInTheDocument(); // or say it
  await userEvent.type(screen.getByLabelText("What to change in 1"), "assign to Kate, due Monday");
  await userEvent.click(screen.getByRole("button", { name: "Apply" }));
  await waitFor(() => expect(calls.some((c) => c.path === "/api/suggestions/1/revise")).toBe(true));
  const post = calls.find((c) => c.path === "/api/suggestions/1/revise");
  expect(JSON.parse(String(post?.init?.body))).toEqual({
    instruction: "assign to Kate, due Monday",
  });
  expect(calls.some((c) => c.path === "/api/suggestions/moderate")).toBe(false); // nothing created
});

test("the owner edits a comment in their own words", async () => {
  window.history.pushState({}, "", "/moderate");
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/suggestions": { suggestions },
    "PATCH /api/suggestions/2": { suggestion: suggestions[1] },
  });
  renderApp();
  const edits = await screen.findAllByRole("button", { name: "Edit" });
  await userEvent.click(edits[1]);
  const text = screen.getByLabelText("Text");
  expect(text).toHaveValue("New buy box approved");
  await userEvent.clear(text);
  await userEvent.type(text, "Approved, go ahead");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
  const patch = calls.find((c) => c.method === "PATCH");
  expect(JSON.parse(String(patch?.init?.body))).toEqual({ fields: { body: "Approved, go ahead" } });
});
