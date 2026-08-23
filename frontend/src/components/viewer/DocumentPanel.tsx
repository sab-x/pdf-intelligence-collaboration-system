import { useState } from "react";
import { MessagesSquare, Sparkles, X } from "lucide-react";

import { ChatPanel } from "@/components/viewer/ChatPanel";
import { CommentsPanel } from "@/components/viewer/CommentsPanel";
import { cn } from "@/lib/utils";

type PanelTab = "comments" | "chat";

const TABS: { id: PanelTab; label: string; Icon: typeof MessagesSquare }[] = [
  { id: "comments", label: "Comments", Icon: MessagesSquare },
  { id: "chat", label: "Chat", Icon: Sparkles },
];

interface PanelContentProps {
  documentId: string;
  pageNumber: number;
  pageCount: number;
  onJumpToPage: (page: number) => void;
}

/** Icon-led tab bar — the icon carries the identity, the label confirms it. */
function TabBar({
  active,
  onChange,
  className,
}: {
  active: PanelTab;
  onChange: (tab: PanelTab) => void;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      aria-label="Document panel"
      className={cn("flex gap-1 border-b border-border p-2", className)}
    >
      {TABS.map(({ id, label, Icon }) => {
        const selected = active === id;
        return (
          <button
            key={id}
            role="tab"
            aria-selected={selected}
            aria-controls={`panel-${id}`}
            onClick={() => onChange(id)}
            className={cn(
              "flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2.5 transition",
              "font-mono text-[0.6875rem] uppercase tracking-[0.1em]",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              selected
                ? "bg-secondary text-foreground"
                : "text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
          >
            <Icon className="size-4" aria-hidden />
            {label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Three layouts, one component:
 *
 *   >= 1280px (xl)  both panels stacked and visible at once — the reason the
 *                   spec calls for it is that comments and chat inform each
 *                   other, and tabbing between them on a wide screen wastes
 *                   the space that makes that possible.
 *   768-1279px      tabs, because a 400px column can't carry both.
 *   < 768px         a bottom sheet over the viewer, so the PDF keeps the
 *                   full width of a phone.
 */
export function DocumentPanel({
  documentId,
  pageNumber,
  pageCount,
  onJumpToPage,
}: PanelContentProps) {
  const [tab, setTab] = useState<PanelTab>("comments");

  return (
    <>
      {/* --- >= 1280px: stacked, no tabs ------------------------------- */}
      <aside className="hidden h-full min-h-0 flex-col gap-5 xl:flex">
        <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-card">
          <header className="flex items-center gap-2 border-b border-border px-5 py-3.5">
            <MessagesSquare className="size-4 text-muted-foreground" aria-hidden />
            <h2 className="meta">Comments</h2>
          </header>
          <div className="min-h-0 flex-1 overflow-auto">
            <CommentsPanel
              documentId={documentId}
              pageNumber={pageNumber}
              onJumpToPage={onJumpToPage}
            />
          </div>
        </section>

        <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-card">
          <header className="flex items-center gap-2 border-b border-border px-5 py-3.5">
            <Sparkles className="size-4 text-muted-foreground" aria-hidden />
            <h2 className="meta">Chat</h2>
          </header>
          <div className="min-h-0 flex-1 overflow-auto">
            <ChatPanel onJumpToPage={onJumpToPage} pageCount={pageCount} />
          </div>
        </section>
      </aside>

      {/* --- 768-1279px: tabbed ---------------------------------------- */}
      <aside className="hidden h-full min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-card md:flex xl:hidden">
        <TabBar active={tab} onChange={setTab} />
        <div
          id={`panel-${tab}`}
          role="tabpanel"
          className="min-h-0 flex-1 overflow-auto"
        >
          {tab === "comments" ? (
            <CommentsPanel
              documentId={documentId}
              pageNumber={pageNumber}
              onJumpToPage={onJumpToPage}
            />
          ) : (
            <ChatPanel onJumpToPage={onJumpToPage} pageCount={pageCount} />
          )}
        </div>
      </aside>
    </>
  );
}

/** Mobile (<768px): the same two panels in a bottom sheet over the viewer. */
export function MobilePanelSheet({
  open,
  onClose,
  documentId,
  pageNumber,
  pageCount,
  onJumpToPage,
}: PanelContentProps & { open: boolean; onClose: () => void }) {
  const [tab, setTab] = useState<PanelTab>("comments");

  return (
    <div
      className={cn(
        "fixed inset-0 z-40 md:hidden",
        open ? "pointer-events-auto" : "pointer-events-none",
      )}
      aria-hidden={!open}
    >
      <div
        className={cn(
          "absolute inset-0 bg-foreground/35 transition-opacity duration-200",
          open ? "opacity-100" : "opacity-0",
        )}
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal={open}
        aria-label="Comments and chat"
        className={cn(
          "absolute inset-x-0 bottom-0 flex h-[78dvh] flex-col rounded-t-2xl border-t border-border bg-card",
          "shadow-[0_-8px_40px_-12px_rgba(0,0,0,0.3)] transition-transform duration-300 ease-out",
          open ? "translate-y-0" : "translate-y-full",
        )}
      >
        {/* Grab handle — the affordance that says "this sheet moves". */}
        <div className="flex items-center justify-between px-4 pt-3">
          <span className="mx-auto h-1 w-10 rounded-full bg-border" aria-hidden />
          <button
            type="button"
            onClick={onClose}
            aria-label="Close panel"
            className="absolute right-3 top-3 rounded-md p-1.5 text-muted-foreground transition hover:bg-accent hover:text-foreground"
          >
            <X className="size-4" aria-hidden />
          </button>
        </div>

        <TabBar active={tab} onChange={setTab} className="mt-2" />
        <div className="min-h-0 flex-1 overflow-auto">
          {tab === "comments" ? (
            <CommentsPanel
              documentId={documentId}
              pageNumber={pageNumber}
              onJumpToPage={onJumpToPage}
            />
          ) : (
            <ChatPanel onJumpToPage={onJumpToPage} pageCount={pageCount} />
          )}
        </div>
      </div>
    </div>
  );
}
