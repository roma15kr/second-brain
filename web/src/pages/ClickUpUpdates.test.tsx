import { screen } from "@testing-library/react";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

test("ClickUp for you separates direct items from followed activity", async () => {
  window.history.pushState({}, "", "/clickup");
  mockApi({
    "GET /api/auth/me": { signed_in: true, has_passkeys: true, needs_passkey: false },
    "GET /api/briefs": { briefs: [] },
    "GET /api/clickup/updates": {
      updates: [
        {
          kind: "mentioned",
          direct: true,
          text: "Олена mentioned you",
          title: "Banners",
          item_id: 5,
          link: "https://app.clickup.com/t/a",
          at: "2026-10-20T08:00:00Z",
          pushed: true,
        },
        {
          kind: "followed_chat",
          direct: false,
          text: "Макс wrote in a channel you follow",
          title: "#marketing · 2026-10-20",
          item_id: 6,
          link: null,
          at: "2026-10-20T07:00:00Z",
          pushed: true,
        },
      ],
    },
  });
  renderApp();
  expect(await screen.findByText("Олена mentioned you", { exact: false })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Banners" })).toHaveAttribute("href", "/c/5");
  expect(screen.getByText(/Макс wrote in a channel you follow/)).toBeInTheDocument();
});
