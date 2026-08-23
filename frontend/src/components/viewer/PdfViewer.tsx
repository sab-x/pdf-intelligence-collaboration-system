import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { Document, Page } from "react-pdf";
import { AlertTriangle, Maximize2, Minus, Plus } from "lucide-react";

import { PageRail } from "@/components/viewer/PageRail";
import { Button } from "@/components/ui/button";
import { DEFAULT_ZOOM_INDEX, PDF_OPTIONS, ZOOM_STEPS } from "@/lib/pdf";
import { cn } from "@/lib/utils";

import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

export interface PdfViewerHandle {
  /**
   * Scroll the given 1-based page into view. This is the seam Phase 9's chat
   * citations plug into: a [p. 7] chip calls jumpToPage(7) and the reader
   * follows, which is the interaction that makes grounded answers feel real.
   */
  jumpToPage: (page: number) => void;
}

interface PdfViewerProps {
  /** Signed URL from GET /documents/{id}/file. */
  fileUrl: string;
  onPageCountChange?: (pageCount: number) => void;
  /** Reports the page currently in view, so the panel can anchor to it. */
  onPageChange?: (page: number) => void;
}

export const PdfViewer = forwardRef<PdfViewerHandle, PdfViewerProps>(function PdfViewer(
  { fileUrl, onPageCountChange, onPageChange },
  ref,
) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<(HTMLDivElement | null)[]>([]);

  const [pageCount, setPageCount] = useState(0);
  const [page, setPage] = useState(1);
  const [zoomIndex, setZoomIndex] = useState(DEFAULT_ZOOM_INDEX);
  const [fitWidth, setFitWidth] = useState(true);
  const [containerWidth, setContainerWidth] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);

  // react-pdf re-downloads the file whenever the `file` prop is a new object
  // identity, so the URL string is memoised into a stable object once.
  const file = useMemo(() => ({ url: fileUrl }), [fileUrl]);

  // Fit-width needs the live container width; ResizeObserver keeps it correct
  // through panel collapse, window resize, and the mobile sheet opening.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      setContainerWidth(entry.contentRect.width);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const jumpToPage = useCallback((target: number) => {
    const node = pageRefs.current[target - 1];
    if (!node) return;
    node.scrollIntoView({ behavior: "smooth", block: "start" });
    setPage(target);
  }, []);

  useImperativeHandle(ref, () => ({ jumpToPage }), [jumpToPage]);

  // Lift the current page out. Reported from an effect rather than from each
  // setPage call site so scroll-driven and jump-driven changes both surface
  // through exactly one path.
  useEffect(() => {
    onPageChange?.(page);
  }, [page, onPageChange]);

  // Track the page currently under the top of the viewport, so the rail
  // reflects free scrolling and not just explicit jumps.
  useEffect(() => {
    const root = scrollRef.current;
    if (!root || pageCount === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (!visible) return;
        const index = pageRefs.current.indexOf(visible.target as HTMLDivElement);
        if (index >= 0) setPage(index + 1);
      },
      { root, threshold: [0.1, 0.5] },
    );

    pageRefs.current.slice(0, pageCount).forEach((node) => node && observer.observe(node));
    return () => observer.disconnect();
  }, [pageCount]);

  const scale = ZOOM_STEPS[zoomIndex];
  // 48px of breathing room either side of the page inside the reader panel.
  const pageWidth = fitWidth && containerWidth > 0 ? Math.max(containerWidth - 96, 240) : undefined;

  return (
    <div className="relative flex h-full flex-col overflow-hidden rounded-xl bg-reader">
      {/* Toolbar sits above the reader surface, in its own register. */}
      <div className="flex items-center justify-between gap-3 border-b border-reader-edge/50 px-4 py-3">
        <PageRail page={page} pageCount={pageCount} onJump={jumpToPage} />

        <div className="flex items-center gap-1 rounded-lg border border-reader-edge/60 bg-reader/80 px-1.5 py-1.5">
          <button
            type="button"
            onClick={() => {
              setFitWidth(false);
              setZoomIndex((i) => Math.max(0, i - 1));
            }}
            disabled={!fitWidth && zoomIndex === 0}
            aria-label="Zoom out"
            className="rounded-md p-1.5 text-white/70 transition hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-white/40 disabled:pointer-events-none disabled:opacity-30"
          >
            <Minus className="size-4" aria-hidden />
          </button>
          <span className="w-11 text-center font-mono text-[0.625rem] uppercase tracking-[0.08em] tabular-nums text-white/70">
            {fitWidth ? "Fit" : `${Math.round(scale * 100)}%`}
          </span>
          <button
            type="button"
            onClick={() => {
              setFitWidth(false);
              setZoomIndex((i) => Math.min(ZOOM_STEPS.length - 1, i + 1));
            }}
            disabled={!fitWidth && zoomIndex === ZOOM_STEPS.length - 1}
            aria-label="Zoom in"
            className="rounded-md p-1.5 text-white/70 transition hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-white/40 disabled:pointer-events-none disabled:opacity-30"
          >
            <Plus className="size-4" aria-hidden />
          </button>
          <span className="mx-0.5 h-4 w-px bg-white/15" aria-hidden />
          <button
            type="button"
            onClick={() => setFitWidth(true)}
            aria-pressed={fitWidth}
            aria-label="Fit to width"
            className={cn(
              "rounded-md p-1.5 transition hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-white/40",
              fitWidth ? "bg-white/15 text-white" : "text-white/70",
            )}
          >
            <Maximize2 className="size-4" aria-hidden />
          </button>
        </div>
      </div>

      {/* The reader surface. The page is white and everything around it is
          near-charcoal, so the document reads as an object with edges. */}
      <div ref={scrollRef} className="flex-1 overflow-auto overscroll-contain px-12 py-10">
        {loadError ? (
          <div className="mx-auto flex max-w-sm flex-col items-center gap-4 rounded-xl border border-reader-edge bg-reader-edge/30 px-8 py-12 text-center">
            <AlertTriangle className="size-6 text-white/60" aria-hidden />
            <p className="text-sm text-white/70">{loadError}</p>
            <Button
              variant="outline"
              size="sm"
              className="border-white/25 bg-transparent text-white hover:bg-white/10 hover:text-white"
              onClick={() => window.location.reload()}
            >
              Reload
            </Button>
          </div>
        ) : (
          <Document
            file={file}
            options={PDF_OPTIONS}
            onLoadSuccess={({ numPages }) => {
              setPageCount(numPages);
              setLoadError(null);
              onPageCountChange?.(numPages);
            }}
            onLoadError={(error) =>
              setLoadError(
                // The signed URL is short-lived, so an expired link is the
                // most likely failure and deserves its own wording.
                /expired|403|forbidden/i.test(error.message)
                  ? "This document link has expired. Reload the page to get a fresh one."
                  : "This PDF could not be displayed.",
              )
            }
            loading={
              <div className="mx-auto h-[60vh] w-full max-w-3xl animate-pulse rounded-lg bg-white/5" />
            }
            error={null}
            className="flex flex-col items-center gap-10"
          >
            {Array.from({ length: pageCount }, (_, index) => (
              <div
                key={index}
                ref={(node) => {
                  pageRefs.current[index] = node;
                }}
                // scroll-margin keeps jumpToPage from tucking the page top
                // underneath the sticky toolbar.
                className="scroll-mt-6"
              >
                <Page
                  pageNumber={index + 1}
                  width={pageWidth}
                  scale={fitWidth ? undefined : scale}
                  renderAnnotationLayer
                  renderTextLayer
                  className="overflow-hidden rounded-sm shadow-[0_8px_30px_-6px_rgba(0,0,0,0.5)]"
                  loading={
                    <div className="h-[60vh] w-full max-w-3xl animate-pulse rounded-sm bg-white/5" />
                  }
                />
                <p className="meta mt-3 text-center text-white/35">
                  Page {index + 1}
                </p>
              </div>
            ))}
          </Document>
        )}
      </div>
    </div>
  );
});
