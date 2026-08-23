// Document data layer: types, query keys, and fetchers.
//
// Query keys live here rather than being spelled inline at each call site,
// because the optimistic delete in Dashboard has to cancel/snapshot/restore
// the exact same key the list query uses — a typo there fails silently by
// simply not rolling anything back.

import { api, apiUpload } from "@/lib/api";

export type DocumentStatus = "processing" | "ready" | "failed";

export interface DocumentSummary {
  id: string;
  filename: string;
  size_bytes: number;
  page_count: number | null;
  status: DocumentStatus;
  error_message: string | null;
  summary: string | null;
  doc_type: string | null;
  key_points: string[] | null;
  extracted_chars: number | null;
  created_at: string;
}

/** GET /search adds these two to every document (PROJECT_PLAN.md §3, §8). */
export interface SearchResult extends DocumentSummary {
  match_reason: "filename" | "semantic";
  snippet: string;
}

export interface DocumentStatusPayload {
  status: DocumentStatus;
  error_message: string | null;
}

export const documentKeys = {
  all: ["documents"] as const,
  list: () => [...documentKeys.all, "list"] as const,
  status: (id: string) => [...documentKeys.all, "status", id] as const,
  search: (q: string) => [...documentKeys.all, "search", q] as const,
};

export const listDocuments = () => api.get<DocumentSummary[]>("/documents");

export const getDocument = (id: string) => api.get<DocumentSummary>(`/documents/${id}`);

export interface SignedUrl {
  url: string;
  expires_at: string;
}

/**
 * Signed URL for the raw PDF. Deliberately NOT cached long: the backend mints
 * these with a 15-minute TTL (SIGNED_URL_TTL_SECONDS), so a stale one would
 * fail mid-read.
 */
export const getDocumentFileUrl = (id: string) =>
  api.get<SignedUrl>(`/documents/${id}/file`);

export const getDocumentStatus = (id: string) =>
  api.get<DocumentStatusPayload>(`/documents/${id}/status`);

export const searchDocuments = (q: string) =>
  api.get<SearchResult[]>(`/search?q=${encodeURIComponent(q)}`);

export const deleteDocument = (id: string) => api.delete<void>(`/documents/${id}`);

export const uploadDocument = (
  file: File,
  onProgress?: (percent: number) => void,
  signal?: AbortSignal,
) => apiUpload<DocumentSummary>("/documents", file, onProgress, signal);

// ---------------------------------------------------------------------------
// Presentation helpers
// ---------------------------------------------------------------------------

/** Mirrors the backend cap in app/core/config.py (MAX_UPLOAD_MB). */
export const MAX_UPLOAD_MB = 20;

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Deterministic spine colour per doc_type, so "Employment Agreement" is the
 * same hue on every card and across reloads — the grid becomes scannable by
 * kind. Hashing (rather than a lookup table) means an unseen doc_type from
 * the model still gets a stable colour instead of a fallback grey.
 */
const SPINE_HUES = [268, 200, 155, 24, 320, 96, 240, 8];

export function spineColor(doc: { status: DocumentStatus; doc_type: string | null }): string {
  if (doc.status === "failed") return "oklch(0.553 0.201 25.5)";
  if (doc.status === "processing") return "oklch(0.7 0.135 68)";
  const label = doc.doc_type?.trim();
  if (!label) return "oklch(0.75 0.02 265)";
  let hash = 0;
  for (let i = 0; i < label.length; i += 1) {
    hash = (hash * 31 + label.charCodeAt(i)) >>> 0;
  }
  return `oklch(0.62 0.13 ${SPINE_HUES[hash % SPINE_HUES.length]})`;
}

// ---------------------------------------------------------------------------
// Library statistics
// ---------------------------------------------------------------------------

export interface LibraryStats {
  total: number;
  storageBytes: number;
  uploadsThisWeek: number;
  processing: number;
}

/**
 * Derived entirely from the list the dashboard already holds — no extra
 * endpoint, no second round trip, and it can never disagree with the grid
 * rendered beside it.
 */
export function computeLibraryStats(documents: DocumentSummary[]): LibraryStats {
  const weekAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
  let storageBytes = 0;
  let uploadsThisWeek = 0;
  let processing = 0;

  for (const doc of documents) {
    storageBytes += doc.size_bytes;
    if (new Date(doc.created_at).getTime() >= weekAgo) uploadsThisWeek += 1;
    if (doc.status === "processing") processing += 1;
  }

  return { total: documents.length, storageBytes, uploadsThisWeek, processing };
}
