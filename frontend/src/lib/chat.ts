// RAG chat client — PROJECT_PLAN.md §7.
//
// ## Why this doesn't go through apiFetch
//
// Two reasons, both structural rather than stylistic:
//
// 1. It's a STREAM. apiFetch awaits response.json(); this has to read the
//    body incrementally as tokens arrive, which is the entire feature.
//
// 2. It bypasses the Vercel rewrite and talks to the Render origin
//    DIRECTLY. Edge proxies buffer streamed responses — the request still
//    succeeds and the answer still arrives, but all at once at the end,
//    which silently deletes token-by-token streaming while looking like it
//    works. That is the exact failure you'd only notice while recording a
//    demo.
//
// Going cross-origin is safe here specifically because this route
// authenticates with a bearer token and needs no cookie: no third-party
// cookie problem, and CORS on the backend already allows FRONTEND_URL.
//
// EventSource is not an option — it can't send a POST body or an
// Authorization header. fetch + a ReadableStream reader is the only way.

import { getAccessToken, getGuestCredentials } from "@/lib/api";

/**
 * Where the streaming request goes.
 *
 * Empty in development, so the call falls through to the relative path and
 * Vite's dev proxy. On Vercel, VITE_STREAM_BASE_URL is set to the Render
 * origin so the stream skips the edge proxy entirely.
 */
const STREAM_BASE = import.meta.env.VITE_STREAM_BASE_URL ?? "";

export interface Citation {
  chunk_id: string;
  page_start: number;
  page_end: number;
  excerpt: string;
  matched_by: string[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[] | null;
  created_at: string;
}

export interface StreamHandlers {
  onCitations: (citations: Citation[], query: string) => void;
  onToken: (text: string) => void;
  onDone: (sessionId: string) => void;
  onError: (message: string) => void;
}

function authHeader(): Record<string, string> {
  // Same precedence as api.ts. A guest can chat — must-have 7 says the
  // feature is available to invited users too.
  const bearer = getGuestCredentials()?.token ?? getAccessToken();
  return bearer ? { Authorization: `Bearer ${bearer}` } : {};
}

/**
 * Parse a buffer of SSE text into complete frames.
 *
 * Returns the frames plus whatever trailing partial text is left over. That
 * remainder matters: network chunks split wherever TCP feels like it, very
 * often mid-frame, and discarding the tail would drop tokens at random
 * under exactly the conditions that are hardest to reproduce.
 */
function parseFrames(buffer: string): { frames: string[]; rest: string } {
  const parts = buffer.split("\n\n");
  const rest = parts.pop() ?? "";
  return { frames: parts, rest };
}

function readFrame(frame: string): { event: string; data: unknown } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
}

export async function streamChat(
  documentId: string,
  message: string,
  sessionId: string | null,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${STREAM_BASE}/api/v1/documents/${documentId}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeader() },
      body: JSON.stringify({ message, session_id: sessionId }),
      signal,
    });
  } catch {
    handlers.onError("Can't reach the server right now. Please try again.");
    return;
  }

  if (!response.ok) {
    // Authorization and rate-limit failures are real status codes, not
    // `error` frames — the backend validates everything it can before the
    // response starts streaming precisely so they arrive this way.
    let detail = "Something went wrong.";
    if (response.status === 429) {
      detail = "Too many questions just now. Give it a minute and try again.";
    } else if (response.status === 404) {
      detail = "This document is no longer available.";
    } else {
      try {
        const body = (await response.json()) as { detail?: string };
        if (body?.detail) detail = body.detail;
      } catch {
        // non-JSON error body — keep the generic message
      }
    }
    handlers.onError(detail);
    return;
  }

  if (!response.body) {
    handlers.onError("Streaming isn't supported in this browser.");
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      // stream: true so a multi-byte character split across two network
      // chunks is held back rather than decoded into a replacement char.
      buffer += decoder.decode(value, { stream: true });

      const { frames, rest } = parseFrames(buffer);
      buffer = rest;

      for (const frame of frames) {
        const parsed = readFrame(frame);
        if (!parsed) continue;
        const data = parsed.data as Record<string, unknown>;
        switch (parsed.event) {
          case "citations":
            handlers.onCitations(
              (data.citations as Citation[]) ?? [],
              (data.query as string) ?? "",
            );
            break;
          case "token":
            handlers.onToken((data.text as string) ?? "");
            break;
          case "done":
            handlers.onDone((data.session_id as string) ?? "");
            break;
          case "error":
            handlers.onError((data.message as string) ?? "Something went wrong.");
            break;
        }
      }
    }
  } catch (err) {
    // An abort is the user navigating away or asking something else — not
    // a failure worth showing them.
    if ((err as Error)?.name !== "AbortError") {
      handlers.onError("The connection dropped mid-answer. Please try again.");
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Split an answer into text and `[p. N]` / `[pp. N-M]` citation markers, so
 * the markers can be rendered as buttons that drive the viewer.
 *
 * Done here rather than with markdown because the answer is plain prose by
 * prompt design, and because MarkdownBody's sanitiser would strip any
 * interactive element injected into it — correctly so.
 */
export type AnswerSegment =
  | { kind: "text"; value: string }
  | { kind: "citation"; label: string; page: number };

const CITATION_RE = /\[pp?\.\s*(\d+)(?:\s*[-–]\s*(\d+))?\]/g;

export function parseAnswer(answer: string): AnswerSegment[] {
  const segments: AnswerSegment[] = [];
  let lastIndex = 0;

  for (const match of answer.matchAll(CITATION_RE)) {
    const start = match.index ?? 0;
    if (start > lastIndex) {
      segments.push({ kind: "text", value: answer.slice(lastIndex, start) });
    }
    segments.push({
      kind: "citation",
      label: match[0],
      // Jump to the FIRST page of a range: it's where the cited passage
      // begins, and landing mid-quote is disorienting.
      page: Number(match[1]),
    });
    lastIndex = start + match[0].length;
  }

  if (lastIndex < answer.length) {
    segments.push({ kind: "text", value: answer.slice(lastIndex) });
  }
  return segments;
}
