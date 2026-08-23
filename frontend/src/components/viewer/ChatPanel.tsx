import { Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";

/**
 * Structural shell. Grounded RAG chat is Phase 9 (§7): hybrid retrieval,
 * streaming tokens, and `[p. N]` citation chips.
 *
 * `onJumpToPage` is already threaded through even though nothing calls it yet
 * — it's the whole point of the viewer exposing jumpToPage, and the citation
 * chip below is a live demonstration that the wiring works end to end.
 */
export function ChatPanel({
  onJumpToPage,
  pageCount,
}: {
  onJumpToPage: (page: number) => void;
  pageCount: number;
}) {
  // Something to prove the viewer link works before the API exists.
  const demoPage = Math.min(2, Math.max(1, pageCount));

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-1 flex-col items-center justify-center gap-4 px-8 py-12 text-center">
        <span className="grid size-11 place-items-center rounded-xl bg-secondary text-muted-foreground">
          <Sparkles className="size-5" aria-hidden />
        </span>
        <div>
          <p className="font-display text-xl leading-tight tracking-tight">
            Ask this document
          </p>
          <p className="mx-auto mt-2 max-w-[26ch] text-sm leading-relaxed text-muted-foreground">
            Grounded answers with page citations arrive in Phase 9. Citations will jump the
            viewer straight to the source.
          </p>
        </div>

        {pageCount > 0 && (
          <button
            type="button"
            onClick={() => onJumpToPage(demoPage)}
            className="group inline-flex items-center gap-2 rounded-full border border-dashed border-border px-3 py-1.5 transition hover:border-primary hover:bg-primary/5 focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Badge variant="match" className="border-0 px-0 group-hover:text-primary">
              preview citation
            </Badge>
            <span className="font-mono text-[0.625rem] tabular-nums text-primary">
              [p. {demoPage}]
            </span>
          </button>
        )}
      </div>

      <div className="border-t border-border p-5">
        <div
          className="rounded-lg border border-dashed border-input px-4 py-3 text-sm text-muted-foreground"
          aria-disabled
        >
          Ask a question about this document…
        </div>
      </div>
    </div>
  );
}
