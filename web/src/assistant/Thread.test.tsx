import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

const me = { signed_in: true, has_passkeys: true, needs_passkey: false };
const req = (status: string, extra = {}) => ({
  id: 1,
  thread_id: 4,
  text: "what did we agree with Rozetka about delivery?",
  status,
  steps: [{ tool: "search", summary: "searched for “Rozetka delivery”" }],
  answer: null,
  refs: [],
  error: null,
  created: [],
  search: null,
  report: null,
  needs_budget: false,
  saved_doc_id: null,
  cost_usd: 0,
  started_at: "2026-10-20T08:00:00Z",
  finished_at: null,
  ...extra,
});

test("a palette request opens its thread, shows steps, then the cited answer", async () => {
  let polls = 0;
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/today": { brief: null },
    "GET /api/briefs": { briefs: [] },
    "GET /api/people?q=Rozetka%20delivery%3F&limit=5": { people: [] },
    "GET /api/search?q=Rozetka%20delivery%3F&limit=5": { results: [] },
    "POST /api/assistant/requests": { id: 1, thread_id: 4 },
    "GET /api/assistant/threads/4": () => {
      polls += 1;
      return {
        id: 4,
        title: "t",
        requests: [
          polls < 2
            ? req("running")
            : req("done", {
                answer: "Delivery in 5 days, prepaid.",
                refs: [{ ref: "item:9", item_id: 9, title: "Rozetka delivery" }],
                cost_usd: 0.012,
              }),
        ],
      };
    },
  });
  renderApp();
  await screen.findByRole("navigation", { name: "Apps" });
  await userEvent.keyboard("{Meta>}k{/Meta}");
  await userEvent.type(await screen.findByLabelText("Search or jump to"), "Rozetka delivery?");
  await userEvent.click(await screen.findByRole("option", { name: /Ask the assistant/ }));
  await waitFor(() => expect(window.location.pathname).toBe("/assistant/t/4"));
  expect(await screen.findByText("searched for “Rozetka delivery”")).toBeInTheDocument();
  expect(
    await screen.findByText("Delivery in 5 days, prepaid.", {}, { timeout: 4000 }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Rozetka delivery" })).toHaveAttribute("href", "/c/9");
  const post = calls.find((c) => c.method === "POST");
  expect(JSON.parse(String(post?.init?.body))).toEqual({ text: "Rozetka delivery?" });
});

test("drafts appear inline and a loop change can be undone", async () => {
  window.history.pushState({}, "", "/assistant/t/4");
  let undone = false;
  const draft = {
    id: 7,
    kind: "task",
    payload: { name: "Update the banners", due_date: "2026-10-23", assignee_name: "Max" },
    reason: "From your request",
    scopes: [],
    item_id: null,
    item_title: null,
    status: "proposed",
    applied_ref: null,
    error: null,
    created_at: "2026-10-20T08:00:00Z",
  };
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/assistant/threads/4": () => ({
      id: 4,
      title: "t",
      requests: [
        req("done", {
          answer: "Prepared a task and closed the reminder.",
          created: [
            { index: 0, type: "suggestion", id: 7, kind: "draft_task", suggestion: draft },
            { index: 1, type: "loop", id: 3, action: "done", title: "Call Olena", undone },
          ],
        }),
      ],
    }),
    "POST /api/assistant/requests/1/undo/1": () => {
      undone = true;
      return { undone: true };
    },
  });
  renderApp();
  expect(await screen.findByDisplayValue("Update the banners")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Create task" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Undo" }));
  expect(await screen.findByText("· undone")).toBeInTheDocument();
});

test("a report can be saved to the Library and over-budget requests offer Run anyway", async () => {
  window.history.pushState({}, "", "/assistant/t/4");
  let saved: unknown = null;
  let ranAnyway = false;
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/projects": { projects: [{ name: "quokka" }, { name: "personal" }] },
    "GET /api/assistant/threads/4": () => ({
      id: 4,
      title: "t",
      pinned: false,
      requests: [
        req("done", {
          answer: "The report is ready.",
          report: {
            title: "Quokka week",
            sections: [
              {
                heading: "Decisions",
                body: "New listing photos.",
                refs: [{ ref: "item:9", item_id: 9, title: "Photos" }],
              },
            ],
          },
          saved_doc_id: saved ? 12 : null,
        }),
        req("done", { id: 2, answer: "AI budget is used up.", needs_budget: true }),
      ],
    }),
    "POST /api/assistant/requests/1/report/save": (init?: RequestInit) => {
      saved = JSON.parse(String(init?.body));
      return { document_id: 12 };
    },
    "POST /api/assistant/requests/2/run-anyway": () => {
      ranAnyway = true;
      return { id: 3, thread_id: 4 };
    },
  });
  renderApp();
  expect(await screen.findByRole("heading", { name: "Quokka week" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Photos" })).toHaveAttribute("href", "/c/9");
  await userEvent.click(screen.getByRole("button", { name: "Save to Library" }));
  expect(await screen.findByRole("link", { name: "Saved to the Library" })).toBeInTheDocument();
  expect(saved).toHaveProperty("scope");
  await userEvent.click(screen.getByRole("button", { name: "Run anyway" }));
  await waitFor(() => expect(ranAnyway).toBe(true));
});
