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
