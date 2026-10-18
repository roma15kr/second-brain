import { notificationOptions, openTarget, parsePush } from "./sw-handlers";

test("push event shows the headline and keeps the page to open", () => {
  const p = parsePush(
    JSON.stringify({
      title: "Second brain",
      body: "Morning brief: 3 need your reply",
      url: "/briefs/7",
    }),
  );
  expect(p.body).toBe("Morning brief: 3 need your reply");
  expect(notificationOptions(p).data).toEqual({ url: "/briefs/7" });
});

test("malformed or foreign URLs fall back to the app root", () => {
  expect(parsePush("not json").url).toBe("/");
  expect(parsePush(JSON.stringify({ url: "https://evil.example" })).url).toBe("/");
});

test("click opens the brief in a new window when the app is closed", async () => {
  const opened: string[] = [];
  await openTarget("/briefs/7", [], async (u) => opened.push(u), "https://os.example");
  expect(opened).toEqual(["https://os.example/briefs/7"]);
});

test("click focuses and navigates an open app window", async () => {
  const win = {
    url: "https://os.example/",
    focus: vi.fn(async () => {}),
    navigate: vi.fn(async () => {}),
  };
  const openWindow = vi.fn(async () => {});
  await openTarget("/briefs/7", [win], openWindow, "https://os.example");
  expect(win.focus).toHaveBeenCalled();
  expect(win.navigate).toHaveBeenCalledWith("https://os.example/briefs/7");
  expect(openWindow).not.toHaveBeenCalled();
});
