// Sharing data layer — types, query keys, fetchers.
//
// Note which of these carry credentials and which don't: previewShare and
// createGuestSession are called from the public share page by someone with
// no account at all. They still go through apiFetch, because at that point
// there is no token in memory and no guest credential stored yet, so the
// Authorization header is simply absent — which is exactly what the public
// routes expect.

import { api } from "@/lib/api";

export type SharePermission = "view" | "comment";

export interface ShareLink {
  id: string;
  token: string;
  /** Fully-qualified link, built server-side from FRONTEND_URL. */
  url: string;
  permission: SharePermission;
  invited_email: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  last_accessed_at: string | null;
  view_count: number;
  created_at: string;
  /** Server-computed: not revoked and not past expiry. Never re-derive this. */
  is_active: boolean;
}

export interface ShareLinkCreate {
  permission: SharePermission;
  invited_email?: string | null;
  expires_in_hours?: number | null;
}

/** Public preview — deliberately thin. No document id, no summary. */
export interface SharePreview {
  filename: string;
  page_count: number | null;
  permission: SharePermission;
  shared_by: string;
}

export interface GuestSession {
  guest_token: string;
  token_type: string;
  expires_in_seconds: number;
  document_id: string;
  permission: SharePermission;
  display_name: string;
}

export const shareKeys = {
  all: ["shares"] as const,
  forDocument: (documentId: string) => [...shareKeys.all, documentId] as const,
  preview: (token: string) => [...shareKeys.all, "preview", token] as const,
};

export const listShareLinks = (documentId: string) =>
  api.get<ShareLink[]>(`/documents/${documentId}/shares`);

export const createShareLink = (documentId: string, body: ShareLinkCreate) =>
  api.post<ShareLink>(`/documents/${documentId}/shares`, body);

export const revokeShareLink = (shareId: string) =>
  api.delete<void>(`/shares/${shareId}`);

export const previewShare = (token: string) =>
  api.get<SharePreview>(`/share/${encodeURIComponent(token)}`, {
    // No credential exists yet and none is expected. Without this, a stale
    // access token from a previous session in the same browser would trigger
    // the refresh dance on a route that never returns 401 for auth reasons.
    skipAuthRetry: true,
  });

export const createGuestSession = (token: string, displayName: string) =>
  api.post<GuestSession>(
    `/share/${encodeURIComponent(token)}/session`,
    { display_name: displayName },
    { skipAuthRetry: true },
  );

// ---------------------------------------------------------------------------
// Presentation helpers
// ---------------------------------------------------------------------------

export const PERMISSION_LABEL: Record<SharePermission, string> = {
  view: "Can view",
  comment: "Can view and comment",
};

/**
 * Copy text to the clipboard, with a fallback.
 *
 * navigator.clipboard is unavailable on insecure origins and in some
 * embedded webviews. The share link is the one thing on that dialog the
 * owner actually needs to walk away with, so silently failing to copy it is
 * not an acceptable outcome — the execCommand path is ugly but it works
 * where the modern API doesn't.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through
  }

  try {
    const el = document.createElement("textarea");
    el.value = text;
    el.setAttribute("readonly", "");
    el.style.position = "fixed";
    el.style.opacity = "0";
    document.body.appendChild(el);
    el.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(el);
    return ok;
  } catch {
    return false;
  }
}
