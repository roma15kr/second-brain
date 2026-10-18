import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => vi.unstubAllGlobals());

test("first start asks for the setup code, not a password", async () => {
  mockApi({ "GET /api/auth/me": { signed_in: false, has_passkeys: false, needs_passkey: false } });
  renderApp();
  expect(await screen.findByLabelText("Setup code")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Create passkey" })).toBeDisabled();
  expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
});

test("with a passkey registered, offers passkey sign-in", async () => {
  mockApi({ "GET /api/auth/me": { signed_in: false, has_passkeys: true, needs_passkey: false } });
  renderApp();
  expect(await screen.findByRole("button", { name: "Sign in with passkey" })).toBeInTheDocument();
});

test("a refused setup code shows the server's reason and sends the CSRF header", async () => {
  const calls = mockApi({
    "GET /api/auth/me": { signed_in: false, has_passkeys: false, needs_passkey: false },
  });
  renderApp();
  await userEvent.type(await screen.findByLabelText("Setup code"), "ABCD-EFGH");
  await userEvent.click(screen.getByRole("button", { name: "Create passkey" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("not mocked");
  const begin = calls.find((c) => c.path === "/api/auth/register/begin")!;
  expect(begin.init?.headers).toMatchObject({ "X-KB-Request": "1" });
  expect(JSON.parse(String(begin.init?.body))).toEqual({ setup_code: "ABCD-EFGH" });
});
