import { useState } from "react";
import { ChevronDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { spineColor, type DocumentSummary } from "@/lib/documents";
import { cn } from "@/lib/utils";

/**
 * The pinned summary, set as an editorial abstract: a serif lede at reading
 * size, a rule in the document's own spine colour, and the key points as a
 * numbered list beneath. The spine hue is the same hash used on the dashboard
 * card, so a document keeps its identity colour from the grid into the reader.
 *
 * ## Why the expanded state is a scroll container
 *
 * The toggle button used to live at the end of the flowing content. That
 * worked collapsed and broke expanded: this section sits in a fixed-height
 * flex column above the viewer, and `overflow-hidden` (needed so the accent
 * bar respects the rounded corners) clipped whatever ran past the bottom.
 * On a document with four key points the button was rendered, present in the
 * accessibility tree, and completely invisible — so the abstract could be
 * expanded and never collapsed again.
 *
 * The fix is structural rather than cosmetic: the body scrolls, the toggle
 * lives outside the scroll area, and the whole section is capped so it can
 * never crowd the PDF out of the layout no matter how long the summary is.
 */
export function SummaryAbstract({ document }: { document: DocumentSummary }) {
  const [expanded, setExpanded] = useState(false);
  const accent = spineColor(document);
  const keyPoints = document.key_points ?? [];
  const hasToggle = Boolean(document.summary) || keyPoints.length > 0;

  return (
    <section
      className={cn(
        "relative flex shrink-0 flex-col overflow-hidden rounded-xl border border-border bg-card",
        // Only capped when expanded — collapsed content is line-clamped to
        // four lines and already fits, and an unconditional cap would add a
        // pointless scrollbar to short summaries.
        expanded && "max-h-[min(60vh,30rem)]",
      )}
      aria-labelledby="summary-heading"
    >
      <span
        className="absolute inset-x-0 top-0 z-10 h-[3px]"
        style={{ backgroundColor: accent }}
        aria-hidden
      />

      <div
        className={cn(
          // Tighter than it was. Collapsed, this block is a glance-at
          // orientation aid sitting above the actual document — it was
          // taking ~220px of a ~900px viewport and squeezing the PDF into a
          // third of a page. Expanded it can breathe, because then reading
          // it IS the task.
          "min-h-0 px-6 pt-5 2xl:px-7 2xl:pt-6",
          expanded ? "flex-1 overflow-y-auto" : "overflow-hidden",
          hasToggle ? "pb-2" : "pb-5 2xl:pb-6",
        )}
      >
        <div className="flex flex-wrap items-center gap-3">
          <h2 id="summary-heading" className="meta">
            Abstract
          </h2>
          {document.doc_type && (
            <Badge variant="type" style={{ borderColor: accent, color: accent }}>
              {document.doc_type}
            </Badge>
          )}
        </div>

        {document.summary ? (
          <p
            className={cn(
              "mt-3 font-display tracking-[-0.005em] text-foreground",
              // Editorial size only once you've chosen to read it. Collapsed
              // it's a 3-line lede at a size that doesn't dominate the page.
              expanded
                ? "text-[1.4375rem] leading-[1.55]"
                : "line-clamp-3 text-[1.1875rem] leading-[1.55]",
            )}
          >
            {document.summary}
          </p>
        ) : (
          <p className="mt-4 text-sm text-muted-foreground">
            No summary is available for this document.
          </p>
        )}

        {keyPoints.length > 0 && expanded && (
          <ol className="mt-6 space-y-2.5 border-t border-border pt-5">
            {keyPoints.map((point, index) => (
              // Index in the key, not the text: the model can legitimately
              // return two identical points, and a duplicate React key
              // silently drops one of them from the list.
              <li key={`${index}-${point}`} className="flex gap-3 text-sm leading-relaxed">
                <span
                  className="mt-0.5 font-mono text-[0.625rem] tabular-nums"
                  style={{ color: accent }}
                  aria-hidden
                >
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="text-muted-foreground">{point}</span>
              </li>
            ))}
          </ol>
        )}
      </div>

      {/* Outside the scroll container, so it is reachable at any content
          length. This is the whole point of the restructure. */}
      {hasToggle && (
        <div
          className={cn(
            "shrink-0 px-6 pb-4 pt-2.5 2xl:px-7",
            // A hairline only when there's scrollable content above it, so
            // the collapsed card keeps its clean single-block look.
            expanded && "border-t border-border bg-card",
          )}
        >
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="meta inline-flex items-center gap-1.5 rounded transition hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
            aria-expanded={expanded}
            aria-controls="summary-heading"
          >
            {expanded
              ? "Collapse"
              : keyPoints.length > 0
                ? `Read full abstract · ${keyPoints.length} key points`
                : "Read full abstract"}
            <ChevronDown
              className={cn("size-3.5 transition-transform", expanded && "rotate-180")}
              aria-hidden
            />
          </button>
        </div>
      )}
    </section>
  );
}
