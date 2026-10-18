// Same-origin JSON client. State-changing requests carry X-KB-Request (CSRF defence, design D2).
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T>(
  path: string,
  init: { method?: string; body?: unknown } = {},
): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = {};
  if (method !== "GET") headers["X-KB-Request"] = "1";
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  const r = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, (data as { detail?: string }).detail ?? r.statusText);
  return data as T;
}
