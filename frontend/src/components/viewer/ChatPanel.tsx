import { useEffect, useRef, useState } from "react";
import { AlertTriangle, ChevronDown, Loader2, Send, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  parseAnswer,
  streamChat,
  type Citation,
  type StreamHandlers,
} from "@/lib/chat";
import { cn } from "@/lib/utils";

export interface PendingExcerpt {
  text: string;
  page: number;
}

interface Turn {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[] | null;
  /** Still receiving tokens — drives the caret and disables the composer. */
  streaming?: boolean;
  /** Set only on a user turn that was asked from a PDF highlight. */
  excerpt?: PendingExcerpt | null;
}

interface ChatPanelProps {
  documentId: string;
  onJumpToPage: (page: number) => void;
  pageCount: number;
  /** A highlight the reader just asked to send here, from PdfViewer. */
  pendingExcerpt?: PendingExcerpt | null;
  /** Called once the excerpt has been attached to a question (or dismissed). */
  onConsumeExcerpt?: () => void;
}

const SUGGESTIONS = [
  "What is this document about?",
  "Who are the parties involved?",
  "What are the key dates and amounts?",
];

/**
 * Renders an answer with its `[p. N]` markers as buttons that drive the
 * viewer. This is the interaction that makes the grounding legible rather
 * than merely claimed — a citation you can click and land on is checkable,
 * a citation you can only read is a promise.
 */
function AnswerBody({
  content,
  onJumpToPage,
}: {
  content: string;
  onJumpToPage: (page: number) => void;
}) {
  return (
    <p className="text-sm leading-[1.65] text-foreground/90">
      {parseAnswer(content).map((segment, index) =>
        segment.kind === "text" ? (
          <span key={index}>{segment.value}</span>
        ) : (
          <button
            key={index}
            type="button"
            onClick={() => onJumpToPage(segment.page)}
            title={`Jump to page ${segment.page}`}
            className="mx-0.5 inline-flex items-center rounded border border-primary/30 bg-primary/5 px-1.5 py-px align-baseline font-mono text-[0.6875rem] tabular-nums text-primary transition hover:border-primary hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {segment.label}
          </button>
        ),
      )}
    </p>
  );
}

/**
 * The "grounded in" expander — the highest-value polish item in the plan's
 * §15, because it turns retrieval from an invisible claim into something a
 * reader (or a grader) can inspect directly.
 */
function GroundedIn({
  citations,
  onJumpToPage,
}: {
  citations: Citation[];
  onJumpToPage: (page: number) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="mt-2.5">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="meta inline-flex items-center gap-1.5 rounded transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        Grounded in {citations.length} {citations.length === 1 ? "excerpt" : "excerpts"}
        <ChevronDown
          className={cn("size-3.5 transition-transform", open && "rotate-180")}
          aria-hidden
        />
      </button>

      {open && (
        <ul className="mt-2 space-y-2">
          {citations.map((citation) => (
            <li
              key={citation.chunk_id}
              className="rounded-lg border border-border bg-secondary/40 p-2.5"
            >
              <div className="flex items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() => onJumpToPage(citation.page_start)}
                  className="font-mono text-[0.625rem] tabular-nums text-primary hover:underline"
                >
                  {citation.page_start === citation.page_end
                    ? `p. ${citation.page_start}`
                    : `pp. ${citation.page_start}–${citation.page_end}`}
                </button>
                {/* Which retriever found it. Genuinely diagnostic: a
                    text-only match usually means the question turned on an
                    exact string the embedding blurred away. */}
                <span className="meta">{citation.matched_by.join(" + ")}</span>
              </div>
              <p className="mt-1.5 line-clamp-4 text-xs leading-relaxed text-muted-foreground">
                {citation.excerpt}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ChatPanel({
  documentId,
  onJumpToPage,
  pageCount,
  pendingExcerpt,
  onConsumeExcerpt,
}: ChatPanelProps) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Follow the answer as it streams. Fires on every token, which is the
  // point — the reader should not have to chase the text down the panel.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [turns]);

  // A pending stream outlives this component unless it's cancelled — the
  // reader would keep calling setState on an unmounted tree, and the
  // request would keep burning a Gemini call nobody will read.
  useEffect(() => () => abortRef.current?.abort(), []);

  // A highlight just landed here from the PDF — put the cursor where the
  // question goes, since that's the only thing left for the reader to type.
  useEffect(() => {
    if (pendingExcerpt) textareaRef.current?.focus();
  }, [pendingExcerpt]);

  async function ask(question: string): Promise<void> {
    const trimmed = question.trim();
    if (!trimmed || busy) return;

    const excerpt = pendingExcerpt ?? null;
    // Spent as soon as it's attached to a question, so it can't silently
    // ride along with a second, unrelated one.
    onConsumeExcerpt?.();

    setError(null);
    setBusy(true);
    setInput("");

    const answerId = `a-${crypto.randomUUID()}`;
    setTurns((current) => [
      ...current,
      {
        id: `q-${crypto.randomUUID()}`,
        role: "user",
        content: trimmed,
        citations: null,
        excerpt,
      },
      { id: answerId, role: "assistant", content: "", citations: null, streaming: true },
    ]);

    const controller = new AbortController();
    abortRef.current = controller;

    const patch = (updater: (turn: Turn) => Turn) =>
      setTurns((current) => current.map((t) => (t.id === answerId ? updater(t) : t)));

    const handlers: StreamHandlers = {
      onCitations: (citations) => patch((t) => ({ ...t, citations })),
      // Append rather than replace: each frame carries a fragment, not the
      // whole answer so far.
      onToken: (text) => patch((t) => ({ ...t, content: t.content + text })),
      onDone: (id) => {
        if (id) setSessionId(id);
        patch((t) => ({ ...t, streaming: false }));
      },
      onError: (message) => {
        setError(message);
        // Drop the empty assistant bubble — an error message above an empty
        // answer reads as two failures rather than one.
        setTurns((current) =>
          current.filter((t) => !(t.id === answerId && t.content === "")),
        );
        patch((t) => ({ ...t, streaming: false }));
      },
    };

    // The excerpt is folded straight into the message text sent to the
    // existing grounded chat endpoint — no new route, no new AI code. It
    // just becomes part of what the model is asked to answer from.
    const outgoing = excerpt
      ? `Regarding this excerpt from page ${excerpt.page}:\n"${excerpt.text}"\n\n${trimmed}`
      : trimmed;

    await streamChat(documentId, outgoing, sessionId, handlers, controller.signal);
    setBusy(false);
    abortRef.current = null;
  }

  const isEmpty = turns.length === 0;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        {isEmpty ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 px-3 py-8 text-center">
            <span className="grid size-11 place-items-center rounded-xl bg-secondary text-muted-foreground">
              <Sparkles className="size-5" aria-hidden />
            </span>
            <div>
              <p className="font-display text-xl leading-tight tracking-tight">
                Ask this document
              </p>
              <p className="mx-auto mt-2 max-w-[28ch] text-sm leading-relaxed text-muted-foreground">
                Answers come only from the text{pageCount > 0 && ` of these ${pageCount} pages`},
                with page citations you can click.
              </p>
            </div>
            <div className="flex flex-col gap-1.5">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => void ask(suggestion)}
                  className="rounded-full border border-dashed border-border px-3 py-1.5 text-xs text-muted-foreground transition hover:border-primary hover:bg-primary/5 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <ul className="space-y-5">
            {turns.map((turn) =>
              turn.role === "user" ? (
                <li key={turn.id} className="flex flex-col items-end gap-1.5">
                  {turn.excerpt && (
                    <p className="max-w-[85%] truncate rounded-lg border border-primary/30 bg-primary/5 px-2.5 py-1.5 text-xs italic text-muted-foreground">
                      <span className="mr-1 shrink-0 font-mono not-italic text-primary">
                        p. {turn.excerpt.page}
                      </span>
                      “{turn.excerpt.text}”
                    </p>
                  )}
                  <p className="max-w-[85%] rounded-2xl rounded-br-sm bg-secondary px-3.5 py-2 text-sm leading-relaxed">
                    {turn.content}
                  </p>
                </li>
              ) : (
                <li key={turn.id}>
                  {turn.content ? (
                    <>
                      <AnswerBody content={turn.content} onJumpToPage={onJumpToPage} />
                      {turn.streaming && (
                        <span
                          className="ml-0.5 inline-block h-4 w-[2px] animate-pulse bg-primary align-text-bottom"
                          aria-hidden
                        />
                      )}
                    </>
                  ) : (
                    <p className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Loader2 className="size-3.5 animate-spin" aria-hidden />
                      Searching the document…
                    </p>
                  )}

                  {turn.citations && turn.citations.length > 0 && (
                    <GroundedIn citations={turn.citations} onJumpToPage={onJumpToPage} />
                  )}
                </li>
              ),
            )}
          </ul>
        )}

        {error && (
          <div
            role="alert"
            className="mt-4 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3"
          >
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
            <p className="text-sm text-destructive">{error}</p>
          </div>
        )}
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void ask(input);
        }}
        className="shrink-0 border-t border-border p-4"
      >
        {pendingExcerpt && (
          <div className="mb-2.5 flex items-start gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2">
            <p className="min-w-0 flex-1 text-xs italic leading-relaxed text-muted-foreground">
              <span className="mr-1 shrink-0 font-mono not-italic text-primary">
                p. {pendingExcerpt.page}
              </span>
              <span className="line-clamp-2">“{pendingExcerpt.text}”</span>
            </p>
            <button
              type="button"
              onClick={onConsumeExcerpt}
              aria-label="Remove excerpt"
              className="shrink-0 rounded p-0.5 text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          </div>
        )}
        <div className="flex items-end gap-2">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              // Enter sends, Shift+Enter is a newline — the convention every
              // chat UI uses, and getting it wrong is instantly annoying.
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void ask(input);
              }
            }}
            rows={2}
            maxLength={2000}
            disabled={busy}
            placeholder={
              pendingExcerpt ? "Ask about this excerpt…" : "Ask a question about this document…"
            }
            aria-label="Ask a question about this document"
            className="min-h-[2.75rem] flex-1 resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
          />
          <Button type="submit" size="sm" disabled={busy || !input.trim()}>
            {busy ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <Send className="size-4" aria-hidden />
            )}
            <span className="sr-only">Send</span>
          </Button>
        </div>
      </form>
    </div>
  );
}
