import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

test("proposed goals show their source paragraph and can be confirmed", async () => {
  window.history.pushState({}, "", "/library");
  let status = "proposed";
  const calls = mockApi({
    "GET /api/auth/me": { signed_in: true, has_passkeys: true, needs_passkey: false },
    "GET /api/briefs": { briefs: [] },
    "GET /api/projects": { projects: [] },
    "GET /api/library": { documents: [] },
    "GET /api/goals": () => ({
      goals: [
        {
          id: 4,
          title: "Launch on 2 new marketplaces",
          scope: "quokka",
          measure: "listings live",
          deadline: "2026-12-31",
          status,
          document: "Quokka plan 2026",
          document_id: 1,
          source_excerpt:
            "We will launch on 2 new marketplaces by the end of 2026, starting with Epicentr.",
        },
      ],
    }),
    "POST /api/goals/4": () => {
      status = "confirmed";
      return { ok: true };
    },
  });
  renderApp();
  expect(await screen.findByText("Goals to confirm (1)")).toBeInTheDocument();
  expect(screen.getByText(/starting with Epicentr/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(screen.getByText("My goals")).toBeInTheDocument());
  expect(JSON.parse(String(calls.find((c) => c.method === "POST")?.init?.body))).toEqual({
    action: "confirm",
  });
});
