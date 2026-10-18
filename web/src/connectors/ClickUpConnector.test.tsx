import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

test("marking and syncing a ClickUp list", async () => {
  window.history.pushState({}, "", "/connectors/clickup");
  const calls = mockApi({
    "GET /api/auth/me": { signed_in: true, has_passkeys: true, needs_passkey: false },
    "GET /api/briefs": { briefs: [] },
    "GET /api/projects": {
      projects: ["personal", "quokka"].map((name) => ({ name, label: name, archived: false })),
    },
    "GET /api/connectors/clickup": {
      accounts: [{ id: 1, label: "Quokka", team: "Quokka", state: "active" }],
      lists: [
        {
          list_id: "L1",
          space: "Quokka",
          folder: "Sales",
          list: "Marketplaces",
          sync: false,
          scopes: [],
          default_for_drafts: false,
          tasks: 0,
        },
      ],
      members: [
        {
          email: "olena@quokka.example",
          areas: "Marketplaces",
          tasks: 3,
          person_id: 5,
          person: "Олена",
        },
      ],
    },
    "POST /api/connectors/clickup/lists/L1": { relabelled_tasks: 0 },
  });
  renderApp();
  await userEvent.selectOptions(await screen.findByLabelText("Mark Marketplaces"), "quokka");
  await userEvent.click(screen.getByLabelText("Sync Marketplaces"));
  await waitFor(() =>
    expect(calls.filter((c) => c.path === "/api/connectors/clickup/lists/L1")).toHaveLength(2),
  );
  const bodies = calls
    .filter((c) => c.path === "/api/connectors/clickup/lists/L1")
    .map((c) => JSON.parse(String(c.init?.body)));
  expect(bodies).toEqual([{ scopes: ["quokka"] }, { sync: true }]);
  expect(screen.getByRole("link", { name: "Олена" })).toHaveAttribute("href", "/people/5");
});
