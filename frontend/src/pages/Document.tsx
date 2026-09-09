import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertTriangle, ArrowLeft, PanelBottom, Share2 } from "lucide-react";

import { ShareDialog } from "@/components/ShareDialog";
import type { PendingExcerpt } from "@/components/viewer/ChatPanel";
import { DocumentPanel, MobilePanelSheet } from "@/components/viewer/DocumentPanel";
import { PdfViewer, type PdfViewerHandle } from "@/components/viewer/PdfViewer";
import { SummaryAbstract } from "@/components/viewer/SummaryAbstract";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  documentKeys,
  getDocument,
  getDocumentFileUrl,
  formatBytes,
} from "@/lib/documents";

export default function DocumentPage() {
  const { id = "" } = useParams();
  const viewerRef = useRef<PdfViewerHandle>(null);

  const [page, setPage] = useState(1);
  const [pageCount, setPageCount] = useState(0);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  // A highlight the reader selected in the PDF and asked the AI about —
  // owns this at the page level because it has to reach both PdfViewer
  // (where it's captured) and DocumentPanel/MobilePanelSheet (where it's
  // spent), which are siblings.
  const [pendingExcerpt, setPendingExcerpt] = useState<PendingExcerpt | null>(null);

  function handleAskSelection(text: string, selectionPage: number) {
    setPendingExcerpt({ text, page: selectionPage });
    // No-op at >=768px; on a phone this is what actually surfaces Chat.
    setSheetOpen(true);
  }

  const document = useQuery({
    queryKey: [...documentKeys.all, "detail", id],
    queryFn: () => getDocument(id),
    enabled: Boolean(id),
  });

  const fileUrl = useQuery({
    queryKey: [...documentKeys.all, "file", id],
    queryFn: () => getDocumentFileUrl(id),
    // Signed URLs live 15 minutes (SIGNED_URL_TTL_SECONDS); refetch well
    // inside that so a long reading session never hits an expired link.
    enabled: Boolean(id) && document.data?.status === "ready",
    staleTime: 10 * 60 * 1000,
    refetchInterval: 10 * 60 * 1000,
  });

  function jumpToPage(target: number) {
    viewerRef.current?.jumpToPage(target);
    setSheetOpen(false);
  }

  const error = document.error ?? fileUrl.error;

  if (document.isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="meta">Loading document…</p>
      </div>
    );
  }

  if (error || !document.data) {
    return (
      <div className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-5 px-6 text-center">
        <span className="grid size-12 place-items-center rounded-xl bg-secondary text-muted-foreground">
          <AlertTriangle className="size-6" aria-hidden />
        </span>
        <div>
          <h1 className="font-display text-3xl tracking-tight">Can&rsquo;t open this document</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {error instanceof ApiError
              ? error.message
              : "It may have been deleted, or you may not have access to it."}
          </p>
        </div>
        <Button onClick={() => window.history.back()}>Go back</Button>
      </div>
    );
  }

  const doc = document.data;
  const notReady = doc.status !== "ready";

  return (
    <div className="flex h-dvh flex-col bg-background">
      <header className="flex shrink-0 items-center gap-4 border-b border-border px-5 py-3.5 md:px-8">
        <Link
          to="/"
          className="flex items-center gap-2 rounded-md px-1 py-1 text-muted-foreground transition hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ArrowLeft className="size-4" aria-hidden />
          <span className="meta">Library</span>
        </Link>

        <span className="h-4 w-px bg-border" aria-hidden />

        <div className="min-w-0 flex-1">
          <h1 className="truncate text-sm font-medium tracking-[-0.011em]">{doc.filename}</h1>
        </div>

        <span className="meta hidden sm:inline">
          {formatBytes(doc.size_bytes)}
          {doc.page_count !== null && ` · ${doc.page_count} pages`}
        </span>

        <Button variant="outline" size="sm" onClick={() => setShareOpen(true)}>
          <Share2 className="size-4" aria-hidden />
          {/* Label hidden on the narrowest screens; the icon carries it and
              the aria-label keeps it announced. */}
          <span className="sr-only sm:not-sr-only">Share</span>
        </Button>

        {/* Mobile entry point to the bottom sheet. */}
        <Button
          variant="outline"
          size="sm"
          className="md:hidden"
          onClick={() => setSheetOpen(true)}
        >
          <PanelBottom className="size-4" aria-hidden />
          Panel
        </Button>
      </header>

      <div className="min-h-0 flex-1 overflow-hidden px-4 py-4 md:px-6 md:py-5 2xl:px-8 2xl:py-6">
        <div className="mx-auto flex h-full min-h-0 max-w-[110rem] flex-col gap-4 md:flex-row md:gap-5 2xl:gap-6">
          {/* ---- Viewer column ---- */}
          <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4">
            <SummaryAbstract document={doc} />

            <div className="min-h-0 flex-1">
              {notReady ? (
                <div className="flex h-full min-h-[24rem] flex-col items-center justify-center gap-4 rounded-xl bg-reader px-8 py-16 text-center">
                  <p className="font-display text-2xl tracking-tight text-white/90">
                    {doc.status === "processing"
                      ? "Still being processed"
                      : "This document isn't available"}
                  </p>
                  <p className="max-w-sm text-sm leading-relaxed text-white/55">
                    {doc.status === "processing"
                      ? "The text is still being extracted and summarised. This page will work as soon as it's ready."
                      : (doc.error_message ??
                        "Text extraction failed, so the document can't be displayed.")}
                  </p>
                </div>
              ) : fileUrl.data ? (
                <PdfViewer
                  ref={viewerRef}
                  fileUrl={fileUrl.data.url}
                  onPageCountChange={setPageCount}
                  onPageChange={setPage}
                  onAskSelection={handleAskSelection}
                />
              ) : (
                <div className="flex h-full min-h-[24rem] items-center justify-center rounded-xl bg-reader">
                  <p className="meta text-white/50">Fetching document…</p>
                </div>
              )}
            </div>
          </div>

          {/* ---- Panel column: 400px at md, wider at 2xl ---- */}
          <div className="min-h-0 md:w-[21rem] lg:w-[24rem] xl:w-[26rem] 2xl:w-[30rem]">
            <DocumentPanel
              documentId={doc.id}
              pageNumber={page}
              pageCount={pageCount}
              onJumpToPage={jumpToPage}
              pendingExcerpt={pendingExcerpt}
              onConsumeExcerpt={() => setPendingExcerpt(null)}
            />
          </div>
        </div>
      </div>

      <MobilePanelSheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        documentId={doc.id}
        pageNumber={page}
        pageCount={pageCount}
        onJumpToPage={jumpToPage}
        pendingExcerpt={pendingExcerpt}
        onConsumeExcerpt={() => setPendingExcerpt(null)}
      />

      <ShareDialog
        documentId={doc.id}
        filename={doc.filename}
        open={shareOpen}
        onClose={() => setShareOpen(false)}
      />
    </div>
  );
}
