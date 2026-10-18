import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

const me = { signed_in: true, has_passkeys: true, needs_passkey: false };
const base = {
  "GET /api/auth/me": me,
  "GET /api/briefs": { briefs: [] },
  "GET /api/projects": {
    projects: ["personal", "quokka"].map((name) => ({ name, label: name, archived: false })),
  },
};

test("a document cannot be saved without a mark; upload sends kind, mark and file", async () => {
  window.history.pushState({}, "", "/library");
  let saved = false;
  const calls = mockApi({
    ...base,
    "GET /api/library": () => ({
      documents: saved
        ? [
            {
              id: 1,
              title: "Quokka plan 2026",
              kind: "plan",
              core: true,
              scopes: ["quokka"],
              ai_allowed: true,
              versions: 1,
              filename: "q.md",
              size: 10,
              updated_at: "2026-10-20T08:00:00Z",
            },
          ]
        : [],
    }),
    "POST /api/library": () => {
      saved = true;
      return { id: 1 };
    },
  });
  renderApp();
  const file = new File(["Launch Epicentr"], "Quokka plan 2026.md", { type: "text/markdown" });
  await userEvent.upload(await screen.findByLabelText("File"), file);
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  expect(screen.getByText(/must be marked Personal or a project/)).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("Mark"), "quokka");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("link", { name: "Quokka plan 2026" })).toBeInTheDocument();
  const body = JSON.parse(String(calls.find((c) => c.method === "POST")?.init?.body));
  expect(body).toMatchObject({ kind: "plan", scopes: ["quokka"], title: "Quokka plan 2026" });
  expect(atob(body.file.content_b64)).toBe("Launch Epicentr");
});

test("the AI may read switch updates the document", async () => {
  window.history.pushState({}, "", "/library");
  const calls = mockApi({
    ...base,
    "GET /api/library": {
      documents: [
        {
          id: 2,
          title: "Health",
          kind: "note",
          core: false,
          scopes: ["personal"],
          ai_allowed: false,
          versions: 1,
          filename: "note.md",
          size: 5,
          updated_at: "2026-10-20T08:00:00Z",
        },
      ],
    },
    "PATCH /api/library/2": { ok: true },
  });
  renderApp();
  expect(await screen.findByText(/local only/)).toBeInTheDocument();
  await userEvent.click(screen.getByLabelText("AI may read"));
  await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
  expect(JSON.parse(String(calls.find((c) => c.method === "PATCH")?.init?.body))).toEqual({
    ai_allowed: true,
  });
});
