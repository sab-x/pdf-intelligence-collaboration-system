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
 */
export function SummaryAbstract({ document }: { document: DocumentSummary }) {
  const [expanded, setExpanded] = useState(false);
  const accent = spineColor(document);
  const keyPoints = document.key_points ?? [];

  return (
    <section
      className="relative overflow-hidden rounded-xl border border-border bg-card"
      aria-labelledby="summary-heading"
    >
      <span
        className="absolute inset-x-0 top-0 h-[3px]"
        style={{ backgroundColor: accent }}
        aria-hidden
      />

      <div className="px-7 py-6 2xl:px-8 2xl:py-7">
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
              "mt-4 font-display text-[1.375rem] leading-[1.45] tracking-[-0.005em] text-foreground",
              !expanded && "line-clamp-4",
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
              <li key={point} className="flex gap-3 text-sm leading-relaxed">
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

        {(document.summary || keyPoints.length > 0) && (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="meta mt-5 inline-flex items-center gap-1.5 rounded transition hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
            aria-expanded={expanded}
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
        )}
      </div>
    </section>
  );
}
