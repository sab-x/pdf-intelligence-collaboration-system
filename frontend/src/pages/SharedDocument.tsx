import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { AlertTriangle, FileText, Loader2, PanelBottom } from "lucide-react";

import { DocumentPanel, MobilePanelSheet } from "@/components/viewer/DocumentPanel";
import { PdfViewer, type PdfViewerHandle } from "@/components/viewer/PdfViewer";
import { SummaryAbstract } from "@/components/viewer/SummaryAbstract";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ApiError,
  getGuestCredentials,
  setGuestCredentials,
  type GuestCredentials,
} from "@/lib/api";
import { documentKeys, getDocument, getDocumentFileUrl, formatBytes } from "@/lib/documents";
import { createGuestSession, previewShare, shareKeys } from "@/lib/shares";

/**
 * The guest-facing page. Two states, gated on whether this tab has a guest
 * session for THIS share token:
 *
 *   1. Display-name gate — a public preview (filename, who shared it) and a
 *      single field. No credential exists yet.
 *   2. Reader — the same PDF viewer and comment panel the owner sees.
 *
 * Chat is deliberately absent: it lands in Phase 10, and showing a guest a
 * placeholder panel would be worse than showing them nothing.
 *
 * This route is NOT wrapped in ProtectedRoute (see router.tsx) — that is the
 * entire point. Authorization comes from the guest JWT minted below, not
 * from a user session.
 */
export default function SharedDocumentPage() {
  const { token = "" } = useParams();

  // Seeded from sessionStorage so a reload doesn't re-prompt, but only when
  // the stored credential belongs to this exact share token.
  const [guest, setGuest] = useState<GuestCredentials | null>(() => {
    const stored = getGuestCredentials();
    return stored && stored.shareToken === token ? stored : null;
  });

  if (!guest) {
    return <DisplayNameGate token={token} onAuthenticated={setGuest} />;
  }

  return <GuestReader guest={guest} onExpired={() => setGuest(null)} />;
}

// ---------------------------------------------------------------------------
// 1. Display-name gate
// ---------------------------------------------------------------------------

function DisplayNameGate({
  token,
  onAuthenticated,
}: {
  token: string;
  onAuthenticated: (guest: GuestCredentials) => void;
}) {
  const [displayName, setDisplayName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const preview = useQuery({
    queryKey: shareKeys.preview(token),
    queryFn: () => previewShare(token),
    enabled: Boolean(token),
    retry: false,
  });

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const name = displayName.trim();
    if (!name) return;

    setSubmitting(true);
    setError(null);
    try {
      const session = await createGuestSession(token, name);
      const credentials: GuestCredentials = {
        token: session.guest_token,
        documentId: session.document_id,
        displayName: session.display_name,
        permission: session.permission,
        shareToken: token,
      };
      // Persist BEFORE handing back up: the reader's very first query fires
      // on the next render and reads the credential from this module.
      setGuestCredentials(credentials);
      onAuthenticated(credentials);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't open this link. Try again.",
      );
      setSubmitting(false);
    }
  }

  if (preview.isLoading) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <p className="meta">Opening link…</p>
      </div>
    );
  }

  // Revoked, expired and never-existed all arrive here identically — the API
  // deliberately doesn't distinguish them, and neither does this copy.
  if (preview.error || !preview.data) {
    return (
      <div className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-5 px-6 text-center">
        <span className="grid size-12 place-items-center rounded-xl bg-secondary text-muted-foreground">
          <AlertTriangle className="size-6" aria-hidden />
        </span>
        <div>
          <h1 className="font-display text-3xl tracking-tight">This link doesn&rsquo;t work</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            It may have been revoked by the owner, expired, or been typed incorrectly.
            Ask whoever shared it for a new one.
          </p>
        </div>
      </div>
    );
  }

  const share = preview.data;

  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-7 px-6 py-12">
      <header className="space-y-3">
        <span className="grid size-11 place-items-center rounded-xl bg-secondary text-muted-foreground">
          <FileText className="size-5" aria-hidden />
        </span>
        <h1 className="font-display text-3xl leading-tight tracking-tight">
          {share.shared_by} shared a document with you
        </h1>
        <p className="text-sm text-muted-foreground">
          <span className="font-medium text-foreground">{share.filename}</span>
          {share.page_count !== null && ` · ${share.page_count} pages`}
          {" · "}
          {share.permission === "comment" ? "you can read and comment" : "read only"}
        </p>
      </header>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="display-name">Your name</Label>
          <Input
            id="display-name"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            placeholder="e.g. Priya Raman"
            maxLength={60}
            autoFocus
            required
          />
          <p className="text-xs text-muted-foreground">
            Shown next to anything you write. No account or password needed.
          </p>
        </div>

        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}

        <Button type="submit" className="w-full" disabled={submitting || !displayName.trim()}>
          {submitting && <Loader2 className="size-4 animate-spin" aria-hidden />}
          {submitting ? "Opening…" : "Open document"}
        </Button>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 2. Reader
// ---------------------------------------------------------------------------

function GuestReader({
  guest,
  onExpired,
}: {
  guest: GuestCredentials;
  onExpired: () => void;
}) {
  const viewerRef = useRef<PdfViewerHandle>(null);
  const [page, setPage] = useState(1);
  const [pageCount, setPageCount] = useState(0);
  const [sheetOpen, setSheetOpen] = useState(false);

  function jumpToPage(target: number) {
    viewerRef.current?.jumpToPage(target);
    setSheetOpen(false);
  }

  const document = useQuery({
    queryKey: [...documentKeys.all, "detail", guest.documentId],
    queryFn: () => getDocument(guest.documentId),
    retry: false,
  });

  const fileUrl = useQuery({
    queryKey: [...documentKeys.all, "file", guest.documentId],
    queryFn: () => getDocumentFileUrl(guest.documentId),
    enabled: document.data?.status === "ready",
    staleTime: 10 * 60 * 1000,
    refetchInterval: 10 * 60 * 1000,
    retry: false,
  });

  const error = document.error ?? fileUrl.error;

  // A 401 here means the link was revoked mid-session (api.ts has already
  // cleared the stored credential). Drop back to the gate, which will show
  // the honest "this link doesn't work" state.
  if (error instanceof ApiError && error.status === 401) {
    onExpired();
    return null;
  }

  if (document.isLoading) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <p className="meta">Loading document…</p>
      </div>
    );
  }

  if (error || !document.data) {
    return (
      <div className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-5 px-6 text-center">
        <span className="grid size-12 place-items-center rounded-xl bg-secondary text-muted-foreground">
          <AlertTriangle className="size-6" aria-hidden />
        </span>
        <div>
          <h1 className="font-display text-3xl tracking-tight">Can&rsquo;t open this document</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {error instanceof ApiError
              ? error.message
              : "The link may have been revoked since you opened it."}
          </p>
        </div>
      </div>
    );
  }

  const doc = document.data;
  const canComment = guest.permission === "comment";
  const notReady = doc.status !== "ready";

  return (
    <div className="flex h-dvh flex-col bg-background">
      <header className="flex shrink-0 items-center gap-4 border-b border-border px-5 py-3.5 md:px-8">
        <span className="font-display text-lg tracking-tight">PDF Intelligence</span>
        <span className="h-4 w-px bg-border" aria-hidden />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-sm font-medium tracking-[-0.011em]">{doc.filename}</h1>
        </div>
        <span className="meta hidden sm:inline">
          {formatBytes(doc.size_bytes)}
          {doc.page_count !== null && ` · ${doc.page_count} pages`}
        </span>
        {/* The guest's identity, so they can see which name they're posting
            under before they write anything. */}
        <span className="meta hidden truncate md:inline">{guest.displayName}</span>
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

      <div className="min-h-0 flex-1 overflow-hidden px-4 py-4 md:px-6 md:py-5">
        <div className="mx-auto flex h-full min-h-0 max-w-[110rem] flex-col gap-4 md:flex-row md:gap-5 2xl:gap-6">
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
                      ? "The owner uploaded this moments ago. Refresh in a little while."
                      : "Text extraction failed, so the document can't be displayed."}
                  </p>
                </div>
              ) : fileUrl.data ? (
                <PdfViewer
                  ref={viewerRef}
                  fileUrl={fileUrl.data.url}
                  onPageCountChange={setPageCount}
                  onPageChange={setPage}
                />
              ) : (
                <div className="flex h-full min-h-[24rem] items-center justify-center rounded-xl bg-reader">
                  <p className="meta text-white/50">Fetching document…</p>
                </div>
              )}
            </div>
          </div>

          {/* The SAME panel the owner sees — comments AND chat. Must-have 7
              says AI chat is available to invited users too, and reusing
              DocumentPanel means the guest gets the identical responsive
              behaviour rather than a second, quietly diverging layout. */}
          <div className="min-h-0 md:w-[21rem] lg:w-[24rem] xl:w-[26rem] 2xl:w-[30rem]">
            <DocumentPanel
              documentId={doc.id}
              pageNumber={page}
              pageCount={pageCount}
              onJumpToPage={jumpToPage}
              canComment={canComment}
              guestDisplayName={guest.displayName}
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
        canComment={canComment}
        guestDisplayName={guest.displayName}
      />
    </div>
  );
}
