// Fetch wrapper for /api/v1/*. Handles bearer-token attachment and a single
// silent refresh-and-retry on 401 via the httpOnly refresh cookie.
//
// The in-memory access token lives here (not in React state) so it survives
// being read/written from outside components (e.g. immediately after
// login/signup resolve, before the next render). AuthProvider is the only
// thing that calls setAccessToken/setOnAuthExpired.

const API_BASE = "/api/v1";

let accessToken: string | null = null;

// ---------------------------------------------------------------------------
// Guest credentials (share links) — PROJECT_PLAN.md §4.
//
// A guest JWT is a completely different credential from a user access token:
// 24 hours, scoped to one document, and NO refresh cookie behind it. That
// last point is what makes this more than a second variable. apiFetch's
// silent-refresh-on-401 assumes a refresh cookie exists; for a guest it
// would POST /auth/refresh, get 401 because there's no cookie, and bounce
// them to /login — from a page they were never logged into and have no
// account for. So when a guest token is present the refresh path is skipped
// entirely and the 401 surfaces as "this link is no longer valid", which is
// both true and actionable.
//
// sessionStorage, deliberately not a cookie: it dies with the tab and is
// never sent automatically, so it can't be replayed cross-tab as a user
// session. It's also per-tab, which means opening a second share link in a
// new tab gets its own identity rather than overwriting the first.
// ---------------------------------------------------------------------------

const GUEST_STORAGE_KEY = "pdfintel.guest";

export interface GuestCredentials {
  token: string;
  documentId: string;
  displayName: string;
  permission: "view" | "comment";
  /**
   * The share token this session was created from. Stored so a reload can
   * tell whether the credential in this tab belongs to the link currently
   * in the address bar — following a second, different share link must ask
   * for a name again rather than silently reusing the first identity.
   */
  shareToken: string;
}

let guestCredentials: GuestCredentials | null = null;

function readStoredGuest(): GuestCredentials | null {
  // Wrapped because sessionStorage throws outright in some privacy modes
  // rather than returning null, and a share page that white-screens is
  // worse than one that just asks for a name again.
  try {
    const raw = sessionStorage.getItem(GUEST_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as GuestCredentials;
    if (!parsed?.token || !parsed?.documentId) return null;
    return parsed;
  } catch {
    return null;
  }
}

guestCredentials = readStoredGuest();

export function setGuestCredentials(credentials: GuestCredentials | null): void {
  guestCredentials = credentials;
  try {
    if (credentials) {
      sessionStorage.setItem(GUEST_STORAGE_KEY, JSON.stringify(credentials));
    } else {
      sessionStorage.removeItem(GUEST_STORAGE_KEY);
    }
  } catch {
    // Storage unavailable — the in-memory copy still carries this tab's
    // session, it just won't survive a reload.
  }
}

export function getGuestCredentials(): GuestCredentials | null {
  return guestCredentials;
}

/**
 * Guest credentials for a specific document, or null.
 *
 * The document check matters: a stale entry from a previous share link must
 * not be sent as the credential for a different document. The backend would
 * reject it (require_document_access compares share_links.document_id), but
 * failing here means the UI can ask for a name again instead of rendering a
 * confusing 404.
 */
export function getGuestCredentialsFor(documentId: string): GuestCredentials | null {
  const current = guestCredentials;
  return current && current.documentId === documentId ? current : null;
}

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

  // Guest tokens are scoped to one document and are rejected by /auth/*,
  // which requires an "access"-kind token. Sending one there produces a 401
  // that has nothing to do with the share link — and AuthProvider probes
  // /auth/me on mount for EVERY route, share page included. Attaching the
  // guest token to that probe made a plain page refresh look like a revoked
  // link, clear the credential, and bounce an account-less visitor to
  // /login. Auth routes therefore never carry it.
  const isAuthRoute = path.startsWith("/auth/");
  const guestToken = isAuthRoute ? null : (guestCredentials?.token ?? null);

  const doFetch = async (): Promise<Response> => {
    const requestHeaders = new Headers(headers);
    if (body !== undefined && !requestHeaders.has("Content-Type")) {
      requestHeaders.set("Content-Type", "application/json");
    }
    // A guest token wins when present (and permitted on this path). Making
    // the precedence explicit means a leftover access token in memory can't
    // shadow the guest's credential.
    const bearer = guestToken ?? accessToken;
    if (bearer) {
      requestHeaders.set("Authorization", `Bearer ${bearer}`);
    }
    return fetch(`${API_BASE}${path}`, {
      ...rest,
      headers: requestHeaders,
      credentials: "include",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  };

  let response = await doFetch();

  // A guest has no refresh cookie, so there is nothing to silently refresh.
  // Attempting it would 401 again and fire onAuthExpired, redirecting an
  // account-less visitor to /login. Their 401 means one thing — the link was
  // revoked, expired, or the 24h token ran out — so say that instead.
  //
  // Gated on guestToken, not guestCredentials: this must only fire when the
  // guest token was actually the credential sent. A 401 from a route that
  // never carried it says nothing about the share link's validity.
  if (response.status === 401 && guestToken) {
    setGuestCredentials(null);
    throw new ApiError(
      401,
      "This share link is no longer valid. Ask the owner for a new one.",
      null,
    );
  }

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
    // Same precedence as apiFetch. Guests can't upload — the route depends
    // on require_user — but the header logic stays consistent rather than
    // quietly diverging between the two clients.
    const bearer = guestCredentials?.token ?? accessToken;
    if (bearer) {
      xhr.setRequestHeader("Authorization", `Bearer ${bearer}`);
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
