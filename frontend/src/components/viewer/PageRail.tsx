import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { cn } from "@/lib/utils";

interface PageRailProps {
  page: number;
  pageCount: number;
  onJump: (page: number) => void;
}

/**
 * A slim numeric rail rather than a pager: the editable page number is the
 * control, the arrows are secondary, and a hairline fill underneath shows
 * position through the document at a glance.
 */
export function PageRail({ page, pageCount, onJump }: PageRailProps) {
  const [draft, setDraft] = useState(String(page));

  // Scrolling moves the page too, so the field has to follow the document —
  // but only while the user isn't mid-edit, which is why this syncs on `page`
  // rather than being a pure controlled value.
  useEffect(() => setDraft(String(page)), [page]);

  function commit(event: FormEvent) {
    event.preventDefault();
    const parsed = Number.parseInt(draft, 10);
    if (Number.isNaN(parsed)) {
      setDraft(String(page));
      return;
    }
    onJump(Math.min(Math.max(parsed, 1), pageCount));
  }

  const progress = pageCount > 0 ? (page / pageCount) * 100 : 0;

  return (
    <div className="relative flex items-center gap-1 rounded-lg border border-reader-edge/60 bg-reader/80 px-1.5 py-1.5 backdrop-blur">
      <button
        type="button"
        onClick={() => onJump(page - 1)}
        disabled={page <= 1}
        aria-label="Previous page"
        className={cn(
          "rounded-md p-1.5 text-white/70 transition",
          "hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-white/40",
          "disabled:pointer-events-none disabled:opacity-30",
        )}
      >
        <ChevronLeft className="size-4" aria-hidden />
      </button>

      <form onSubmit={commit} className="flex items-center gap-1.5 px-1">
        <label className="sr-only" htmlFor="page-rail-input">
          Page number
        </label>
        <input
          id="page-rail-input"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          inputMode="numeric"
          className={cn(
            "w-9 rounded border border-transparent bg-white/10 py-0.5 text-center",
            "font-mono text-xs tabular-nums text-white",
            "focus:border-white/30 focus:outline-none",
          )}
        />
        <span className="font-mono text-[0.625rem] uppercase tracking-[0.11em] text-white/45">
          / {pageCount || "—"}
        </span>
      </form>

      <button
        type="button"
        onClick={() => onJump(page + 1)}
        disabled={page >= pageCount}
        aria-label="Next page"
        className={cn(
          "rounded-md p-1.5 text-white/70 transition",
          "hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-white/40",
          "disabled:pointer-events-none disabled:opacity-30",
        )}
      >
        <ChevronRight className="size-4" aria-hidden />
      </button>

      {/* Position indicator — a hairline, not a chunky progress bar. */}
      <span
        className="pointer-events-none absolute inset-x-1.5 bottom-0 h-px overflow-hidden rounded-full bg-white/10"
        aria-hidden
      >
        <span
          className="block h-full rounded-full bg-white/60 transition-[width] duration-300 ease-out"
          style={{ width: `${progress}%` }}
        />
      </span>
    </div>
  );
}
