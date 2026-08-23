import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Clock, RotateCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  documentKeys,
  getDocumentStatus,
  spineColor,
  type DocumentSummary,
} from "@/lib/documents";

const POLL_INTERVAL_MS = 2_000;
// PROJECT_PLAN.md §5 is explicit that this is 5 minutes, not 90 seconds: a
// 60-page PDF on a cold free instance needs download + extraction +
// map-reduce summary before it can flip to ready.
const GIVE_UP_MS = 5 * 60 * 1000;

/**
 * Honest staged progress text (§5 asks for this rather than a bare spinner).
 *
 * The backend reports a single 'processing' status with no sub-stage, so
 * these thresholds are derived from elapsed time, not read from the server —
 * they describe what ingest() is doing at that point, they don't measure it.
 * Measured on a real 1-page upload: download + PyMuPDF extraction finish in
 * a few seconds, and summarisation is the long pole at 20-90s.
 */
function stageLabel(elapsedMs: number): string {
  if (elapsedMs < 6_000) return "Extracting text…";
  if (elapsedMs < 20_000) return "Summarising…";
  return "Summarising… (large document)";
}

interface ProcessingCardProps {
  document: DocumentSummary;
}

export function ProcessingCard({ document }: ProcessingCardProps) {
  const queryClient = useQueryClient();
  const [elapsed, setElapsed] = useState(0);

  // Anchored to mount rather than to created_at: a document already
  // mid-ingestion when the dashboard loads should still get a full patience
  // budget from the moment this card starts watching it.
  const startedAt = useRef(Date.now());
  const gaveUp = elapsed >= GIVE_UP_MS;

  useEffect(() => {
    if (gaveUp) return;
    const id = window.setInterval(() => setElapsed(Date.now() - startedAt.current), 1_000);
    return () => window.clearInterval(id);
  }, [gaveUp]);

  const { data, refetch } = useQuery({
    queryKey: documentKeys.status(document.id),
    queryFn: () => getDocumentStatus(document.id),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      // Stop the moment it reaches a terminal state, or once we've given up.
      if (status === "ready" || status === "failed") return false;
      if (Date.now() - startedAt.current >= GIVE_UP_MS) return false;
      return POLL_INTERVAL_MS;
    },
    // Polling is the point — don't serve a cached status back.
    staleTime: 0,
  });

  const status = data?.status ?? document.status;

  // When ingestion finishes, the status payload is deliberately tiny (no
  // summary), so refresh the list to pull the full record and let this card
  // be replaced by a real DocumentCard.
  useEffect(() => {
    if (status === "ready" || status === "failed") {
      void queryClient.invalidateQueries({ queryKey: documentKeys.list() });
    }
  }, [status, queryClient]);

  const seconds = Math.floor(elapsed / 1000);

  return (
    <article className="lift relative flex flex-col overflow-hidden rounded-xl border border-border bg-card">
      <span
        className="spine"
        style={{ backgroundColor: spineColor({ status: "processing", doc_type: null }) }}
        aria-hidden
      />

      <div className="flex flex-1 flex-col gap-3.5 py-6 pl-7 pr-6 2xl:py-7 2xl:pl-8 2xl:pr-7">
        <div className="flex items-start justify-between gap-3">
          <Badge variant={gaveUp ? "failed" : "processing"}>
            <Clock className="size-3" aria-hidden />
            {gaveUp ? "Stalled" : "Processing"}
          </Badge>
          {!gaveUp && (
            <span className="meta tabular-nums">
              {seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`}
            </span>
          )}
        </div>

        <h3 className="line-clamp-2 break-words text-base font-medium leading-[1.35] tracking-[-0.011em] 2xl:text-[1.0625rem]">
          {document.filename}
        </h3>

        {gaveUp ? (
          <>
            <p className="text-sm leading-relaxed text-muted-foreground">
              This is taking much longer than expected. Ingestion may have stalled — the
              document is still safe, and checking again is harmless.
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-1 self-start"
              onClick={() => {
                startedAt.current = Date.now();
                setElapsed(0);
                void refetch();
              }}
            >
              <RotateCw className="size-4" aria-hidden />
              Check again
            </Button>
          </>
        ) : (
          <>
            {/* Skeleton standing in for the summary that's being generated. */}
            <div className="space-y-2" aria-hidden>
              <div className="shimmer h-3 w-full rounded-full" />
              <div className="shimmer h-3 w-[92%] rounded-full" />
              <div className="shimmer h-3 w-[64%] rounded-full" />
            </div>

            <div
              className="indeterminate relative mt-1 h-1 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-label={stageLabel(elapsed)}
            />

            <p className="meta" aria-live="polite">
              {stageLabel(elapsed)}
            </p>
          </>
        )}
      </div>
    </article>
  );
}
