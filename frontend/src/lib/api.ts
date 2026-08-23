// Fetch wrapper for /api/v1/*. Handles bearer-token attachment and a single
// silent refresh-and-retry on 401 via the httpOnly refresh cookie.
//
// The in-memory access token lives here (not in React state) so it survives
// being read/written from outside components (e.g. immediately after
// login/signup resolve, before the next render). AuthProvider is the only
// thing that calls setAccessToken/setOnAuthExpired.

const API_BASE = "/api/v1";

let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

// AuthProvider registers this so the wrapper can clear auth state and
// redirect to /login when a 401 survives the refresh attempt — without this
// module importing React or the router.
let onAuthExpired: (() => void) | null = null;

export function setOnAuthExpired(callback: (() => void) | null): void {
  onAuthExpired = callback;
}

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Skip the silent-refresh-on-401 dance entirely (use for /auth/login, /auth/signup). */
  skipAuthRetry?: boolean;
  /**
   * Still attempt the silent refresh, but never fire onAuthExpired if it
   * fails — used for the initial "am I logged in" check on app mount, where
   * "not authenticated" is an expected outcome, not a session expiring.
   */
  silentAuthCheck?: boolean;
}

function extractErrorMessage(data: unknown): string | null {
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: unknown } | undefined;
      if (first && typeof first === "object" && typeof first.msg === "string") {
        return first.msg;
      }
    }
  }
  return null;
}

/**
 * Why three outcomes and not a boolean:
 *
 * "expired" means the server actively rejected the refresh token — the
 * session is genuinely over and the user must log in again.
 *
 * "unavailable" means we never got an answer: the backend was restarting
 * (uvicorn --reload does this constantly in development), the network
 * blipped, or a 5xx came back. The session may be perfectly valid.
 *
 * Collapsing those two into `false` is what made a momentarily unreachable
 * backend destroy a live session and bounce the user to /login.
 */
type RefreshOutcome = "refreshed" | "expired" | "unavailable";

let refreshPromise: Promise<RefreshOutcome> | null = null;

async function refreshAccessToken(): Promise<RefreshOutcome> {
  // De-dupe concurrent 401s into a single /refresh call instead of a stampede.
  // This matters more than it looks: refresh tokens ROTATE server-side and the
  // old one is revoked on use, so a second concurrent call presenting the same
  // cookie would be treated as reuse and kill the session.
  if (!refreshPromise) {
    refreshPromise = (async (): Promise<RefreshOutcome> => {
      let res: Response;
      try {
        res = await fetch(`${API_BASE}/auth/refresh`, {
          method: "POST",
          credentials: "include",
        });
      } catch {
        // Never reached the server — say nothing about the session's validity.
        return "unavailable";
      }
      if (res.status === 401 || res.status === 403) return "expired";
      if (!res.ok) return "unavailable";
      try {
        const data = (await res.json()) as { access_token: string };
        setAccessToken(data.access_token);
        return "refreshed";
      } catch {
        return "unavailable";
      }
    })();
  }
  try {
    return await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { body, skipAuthRetry, silentAuthCheck, headers, ...rest } = options;

  const doFetch = async (): Promise<Response> => {
    const requestHeaders = new Headers(headers);
    if (body !== undefined && !requestHeaders.has("Content-Type")) {
      requestHeaders.set("Content-Type", "application/json");
    }
    if (accessToken) {
      requestHeaders.set("Authorization", `Bearer ${accessToken}`);
    }
    return fetch(`${API_BASE}${path}`, {
      ...rest,
      headers: requestHeaders,
      credentials: "include",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  };

  let response = await doFetch();

  if (response.status === 401 && !skipAuthRetry && path !== "/auth/refresh") {
    const outcome = await refreshAccessToken();

    if (outcome === "refreshed") {
      response = await doFetch();
    } else if (outcome === "expired") {
      setAccessToken(null);
      if (!silentAuthCheck) {
        onAuthExpired?.();
      }
      throw new ApiError(401, "Your session has expired. Please log in again.", null);
    } else {
      // "unavailable" — the refresh never got an answer. Keep the session
      // intact and report a transport problem, so a restarting backend or a
      // dropped connection surfaces as a retryable error instead of silently
      // logging the user out.
      throw new ApiError(
        503,
        "Can't reach the server right now. Please try again in a moment.",
        null,
      );
    }
  }

  if (!response.ok) {
    let data: unknown = null;
    try {
      data = await response.clone().json();
    } catch {
      // non-JSON error body — fall through to the generic message below
    }
    const message = extractErrorMessage(data) ?? response.statusText ?? "Something went wrong.";
    throw new ApiError(response.status, message, data);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  get: <T = unknown>(path: string, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "GET" }),
  post: <T = unknown>(path: string, body?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "POST", body }),
  delete: <T = unknown>(path: string, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "DELETE" }),
};

// ---------------------------------------------------------------------------
// Multipart upload with progress.
//
// This deliberately does NOT go through apiFetch. Two reasons: apiFetch
// JSON.stringifies its body and sets Content-Type: application/json, which is
// wrong for multipart (the browser must set its own boundary); and fetch()
// cannot report UPLOAD progress at all — only download. XHR is still the only
// way to drive a real progress bar, so a 20 MB PDF on a slow line shows
// movement instead of a frozen spinner.
// ---------------------------------------------------------------------------

function sendMultipart<T>(
  path: string,
  formData: FormData,
  onProgress?: (percent: number) => void,
  signal?: AbortSignal,
): Promise<{ status: number; parse: () => T; errorMessage: () => string }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}${path}`);
    xhr.withCredentials = true;
    if (accessToken) {
      xhr.setRequestHeader("Authorization", `Bearer ${accessToken}`);
    }

    if (onProgress) {
      xhr.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      });
    }

    xhr.addEventListener("load", () => {
      let parsed: unknown = null;
      try {
        parsed = JSON.parse(xhr.responseText);
      } catch {
        // non-JSON body — handled by the callers below
      }
      resolve({
        status: xhr.status,
        parse: () => parsed as T,
        errorMessage: () =>
          extractErrorMessage(parsed) ?? xhr.statusText ?? "Upload failed.",
      });
    });
    xhr.addEventListener("error", () =>
      reject(new ApiError(0, "Network error during upload.", null)),
    );
    xhr.addEventListener("abort", () =>
      reject(new ApiError(0, "Upload cancelled.", null)),
    );

    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(formData);
  });
}

export async function apiUpload<T = unknown>(
  path: string,
  file: File,
  onProgress?: (percent: number) => void,
  signal?: AbortSignal,
): Promise<T> {
  const build = () => {
    const fd = new FormData();
    fd.append("file", file);
    return fd;
  };

  let result = await sendMultipart<T>(path, build(), onProgress, signal);

  // Same silent-refresh-and-retry contract as apiFetch. The progress bar is
  // reset to 0 first, because a retry genuinely re-sends the whole file.
  if (result.status === 401) {
    const outcome = await refreshAccessToken();
    if (outcome === "expired") {
      setAccessToken(null);
      onAuthExpired?.();
      throw new ApiError(401, "Your session has expired. Please log in again.", null);
    }
    if (outcome === "unavailable") {
      throw new ApiError(
        503,
        "Can't reach the server right now. Please try again in a moment.",
        null,
      );
    }
    onProgress?.(0);
    result = await sendMultipart<T>(path, build(), onProgress, signal);
  }

  if (result.status < 200 || result.status >= 300) {
    throw new ApiError(result.status, result.errorMessage(), null);
  }
  return result.parse();
}
