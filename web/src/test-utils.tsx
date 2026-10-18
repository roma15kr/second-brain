import { QueryClient } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { App } from "./App";

type Route = Record<string, unknown | ((init?: RequestInit) => unknown)>;

// Stubs fetch with a map of "METHOD /path" → JSON body (or a function returning it).
export function mockApi(routes: Route) {
  const calls: { method: string; path: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", async (input: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const path = String(input);
    calls.push({ method, path, init });
    const key = `${method} ${path}`;
    if (!(key in routes))
      return new Response(JSON.stringify({ detail: "not mocked" }), { status: 404 });
    const value = routes[key];
    const body = typeof value === "function" ? value(init) : value;
    return new Response(JSON.stringify(body), { status: 200 });
  });
  return calls;
}

export function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<App client={client} />);
}
