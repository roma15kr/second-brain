import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

const me = { signed_in: true, has_passkeys: true, needs_passkey: false };
const dictation = (forms = {}) => ({
  id: 41,
  status: "done",
  seconds: 42,
  first_line: "Отже, значить",
  transcript: "Отже, значить, банери оновимо до пʼятниці",
  forms,
  error: null,
  cost_usd: 0.004,
  saved_doc_id: null,
  created_at: "2026-10-20T08:00:00Z",
});

test("a dictation can be read verbatim, structured, saved and sent as a request", async () => {
  window.history.pushState({}, "", "/dictate/41");
  let rendered = false;
  let saved: unknown = null;
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/dictations": { dictations: [] },
    "GET /api/dictations/41": () =>
      dictation(
        rendered
          ? { structured: { text: "Банери до пʼятниці.\n\n## Actions\n- Оновити банери" } }
          : {},
      ),
    "POST /api/dictations/41/render": () => {
      rendered = true;
      return { text: "x" };
    },
    "POST /api/dictations/41/save": (init?: RequestInit) => {
      saved = JSON.parse(String(init?.body));
      return { document_id: 5 };
    },
    "POST /api/assistant/requests": { id: 2, thread_id: 9 },
    "GET /api/assistant/threads/9": { id: 9, title: "t", pinned: false, requests: [] },
  });
  renderApp();
  expect(await screen.findByDisplayValue(/банери оновимо до пʼятниці/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: "Structured" }));
  expect(await screen.findByDisplayValue(/## Actions/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Save to Library" }));
  await waitFor(() => expect(saved).toMatchObject({ form: "structured" }));
  await userEvent.click(screen.getByRole("button", { name: "As a request" }));
  await waitFor(() => expect(window.location.pathname).toBe("/assistant/t/9"));
  const ask = calls.find((c) => c.path === "/api/assistant/requests");
  expect(JSON.parse(String(ask?.init?.body)).text).toContain("## Actions");
});
