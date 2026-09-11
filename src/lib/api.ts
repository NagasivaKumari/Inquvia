/**
 * Thin wrapper around fetch that automatically attaches the JWT from
 * localStorage as an Authorization: Bearer header.
 *
 * Drop-in replacement for fetch() throughout the app.
 */
// In-flight promise and short TTL cache for GET /api/auth/me to prevent multi-component request flooding
let _authMeInFlight: Promise<Response> | null = null;
let _authMeCache: { response: Response; timestamp: number } | null = null;
const AUTH_ME_TTL_MS = 3000;

export function invalidateAuthCache(): void {
  _authMeCache = null;
  _authMeInFlight = null;
}

export function apiFetch(url: string | URL | Request, init: RequestInit = {}): Promise<Response> {
  const method = (init.method || (typeof url === "object" && "method" in url ? (url as Request).method : "GET")).toUpperCase();
  const urlString = typeof url === "string" ? url : typeof url === "object" && "url" in url ? (url as Request).url : String(url);
  const isAuthMe = method === "GET" && urlString.includes("/api/auth/me");

  if (isAuthMe && !init.body) {
    const now = Date.now();
    if (_authMeCache && (now - _authMeCache.timestamp) < AUTH_ME_TTL_MS) {
      return Promise.resolve(_authMeCache.response.clone());
    }
    if (_authMeInFlight) {
      return _authMeInFlight.then((res) => res.clone());
    }
  }

  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;

  const headers = new Headers(
    typeof url === "object" && url !== null && "headers" in url && (url as Request).headers
      ? (url as Request).headers
      : init.headers
  );
  if (init.headers && typeof url === "object" && url !== null && "headers" in url) {
    new Headers(init.headers).forEach((value, key) => {
      headers.set(key, value);
    });
  }
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const nextInit: RequestInit = {
    ...init,
    headers,
    credentials: "include",
    cache: (init.cache as RequestCache) ?? "no-store",
  };
  // wrapFetchWithPayment retries with a cloned Request whose body is a stream.
  // Chromium requires duplex when that Request is passed with a new init.
  if (typeof url === "object" && url !== null && "body" in url && (url as Request).body) {
    (nextInit as RequestInit & { duplex: "half" }).duplex = "half";
  }

  const fetchPromise = fetch(url, nextInit);

  if (isAuthMe && !init.body) {
    _authMeInFlight = fetchPromise
      .then((res) => {
        if (res.ok) {
          _authMeCache = { response: res.clone(), timestamp: Date.now() };
        }
        return res;
      })
      .finally(() => {
        _authMeInFlight = null;
      });
    return _authMeInFlight.then((res) => res.clone());
  }

  return fetchPromise;
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
