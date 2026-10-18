import { screen } from "@testing-library/react";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => vi.unstubAllGlobals());

const me = { signed_in: true, has_passkeys: true, needs_passkey: false };

test("today shows the morning brief per scope with links to the original", async () => {
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/today": {
      brief: {
        id: 1,
        routine: "morning",
        title: "Morning brief",
        headline: "Morning brief: 2 conversations across 2 scopes",
        window_start: "2026-10-19T16:00:00Z",
        window_end: "2026-10-20T05:00:00Z",
        mode: "data",
        created_at: "2026-10-20T05:00:00Z",
        sections: [
          {
            title: "quokka",
            text: "1 email thread",
            refs: ["item:7"],
            items: [
              {
                ref: "item:7",
                id: 7,
                kind: "email_thread",
                title: "Listing price",
                summary: "Dealer asks about the listing price.",
                outcome: null,
                link: "https://mail.google.com/mail/#search/x",
                last_activity_at: "2026-10-19T20:00:00Z",
                scopes: ["quokka"],
                participants: [],
              },
            ],
          },
          { title: "rdim", text: "1 chat", refs: ["item:8"], items: [] },
        ],
      },
    },
  });
  renderApp();
  expect(
    await screen.findByText("Morning brief: 2 conversations across 2 scopes"),
  ).toBeInTheDocument();
  const link = screen.getByRole("link", { name: "Listing price" });
  expect(link).toHaveAttribute("href", "https://mail.google.com/mail/#search/x");
  expect(link).toHaveAttribute("target", "_blank");
  expect(screen.getByText("Dealer asks about the listing price.")).toBeInTheDocument();
  expect(screen.getByText("rdim")).toBeInTheDocument();
});

test("before the first brief, today says when it arrives", async () => {
  mockApi({ "GET /api/auth/me": me, "GET /api/today": { brief: null } });
  renderApp();
  expect(await screen.findByText(/first one arrives at 08:00/)).toBeInTheDocument();
});
