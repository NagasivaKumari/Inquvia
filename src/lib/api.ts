/**
 * Thin wrapper around fetch that automatically attaches the JWT from
 * localStorage as an Authorization: Bearer header.
 *
 * Drop-in replacement for fetch() throughout the app.
 */
export function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;

  const headers = new Headers(init.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  return fetch(url, {
    ...init,
    headers,
    credentials: "include",
    cache: (init.cache as RequestCache) ?? "no-store",
  });
}

/** Convenience: POST with a JSON body */
export function apiPost(url: string, body: unknown, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  return apiFetch(url, { ...init, method: "POST", headers, body: JSON.stringify(body) });
}

/** Convenience: DELETE */
export function apiDelete(url: string, init: RequestInit = {}): Promise<Response> {
  return apiFetch(url, { ...init, method: "DELETE" });
}
