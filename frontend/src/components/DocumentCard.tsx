import { formatDistanceToNow } from "date-fns";
import { AlertTriangle, FileText, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import {
  formatBytes,
  spineColor,
  type DocumentSummary,
  type SearchResult,
} from "@/lib/documents";
import { cn } from "@/lib/utils";

interface DocumentCardProps {
  document: DocumentSummary | SearchResult;
  onDelete: (document: DocumentSummary) => void;
  /** Dimmed + non-interactive while its optimistic delete is in flight. */
  isDeleting?: boolean;
}

function isSearchResult(doc: DocumentSummary | SearchResult): doc is SearchResult {
  return "match_reason" in doc;
}

export function DocumentCard({ document, onDelete, isDeleting }: DocumentCardProps) {
  const failed = document.status === "failed";

  return (
    <article
      className={cn(
        "lift group relative flex flex-col overflow-hidden rounded-xl border border-border bg-card",
        "hover:-translate-y-[3px] hover:border-foreground/20",
        "focus-within:-translate-y-[3px] focus-within:border-foreground/20",
        isDeleting && "pointer-events-none opacity-40",
      )}
    >
      {/* The spine: doc_type-derived colour, so the grid is scannable by kind. */}
      <span className="spine" style={{ backgroundColor: spineColor(document) }} aria-hidden />

      <div className="flex flex-1 flex-col gap-3.5 py-6 pl-7 pr-6 2xl:py-7 2xl:pl-8 2xl:pr-7">
        <div className="flex items-start justify-between gap-3">
          {failed ? (
            <Badge variant="failed">
              <AlertTriangle className="size-3" aria-hidden />
              Failed
            </Badge>
          ) : (
            <Badge variant="type">{document.doc_type ?? "Document"}</Badge>
          )}

          <button
            type="button"
            onClick={() => onDelete(document)}
            aria-label={`Delete ${document.filename}`}
            // z-10 is load-bearing: the filename link below spreads an
            // ::after over the whole card to make it one big hit target, and
            // that overlay paints above this button without it.
            //
            // Hidden until hover on pointer devices, but always reachable by
            // keyboard — opacity-0 alone would leave an invisible tab stop,
            // so focus-visible brings it back. On touch there is no hover at
            // all, so below sm it simply stays visible.
            className={cn(
              "relative z-10 -mr-1 -mt-1 rounded-md p-1.5 text-muted-foreground transition",
              "opacity-0 max-sm:opacity-100",
              "hover:bg-destructive/10 hover:text-destructive",
              "focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring",
              "group-hover:opacity-100",
            )}
          >
            <Trash2 className="size-4" aria-hidden />
          </button>
        </div>

        <h3 className="text-base font-medium leading-[1.35] tracking-[-0.011em] 2xl:text-[1.0625rem]">
          {/* The whole card is a link target via ::after, so the hit area is
              the card while the accessible name stays just the filename. */}
          <Link
            to={`/documents/${document.id}`}
            className="after:absolute after:inset-0 after:content-[''] hover:underline focus-visible:outline-none"
          >
            <span className="line-clamp-2 break-words">{document.filename}</span>
          </Link>
        </h3>

        {failed ? (
          <p className="line-clamp-3 text-sm leading-relaxed text-muted-foreground">
            {document.error_message ?? "This document could not be processed."}
          </p>
        ) : (
          <p className="line-clamp-3 text-sm leading-relaxed text-muted-foreground">
            {document.summary ?? "No summary available for this document."}
          </p>
        )}

        {isSearchResult(document) && (
          <div className="flex items-center gap-2 pt-0.5">
            <Badge variant="match">
              matched: {document.match_reason}
            </Badge>
            {/* Phase 11 fills this with the matching passage for semantic
                hits; today it echoes the filename. */}
            <span className="truncate text-xs italic text-muted-foreground">
              {document.snippet}
            </span>
          </div>
        )}

        <div className="meta mt-auto flex items-center gap-2 pt-2">
          <FileText className="size-3.5 shrink-0" aria-hidden />
          <time dateTime={document.created_at}>
            {formatDistanceToNow(new Date(document.created_at), { addSuffix: true })}
          </time>
          <span aria-hidden>·</span>
          <span>{formatBytes(document.size_bytes)}</span>
          {document.page_count !== null && (
            <>
              <span aria-hidden>·</span>
              <span>
                {document.page_count} {document.page_count === 1 ? "page" : "pages"}
              </span>
            </>
          )}
        </div>
      </div>
    </article>
  );
}
