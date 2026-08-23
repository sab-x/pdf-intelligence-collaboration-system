// Modal built on the native <dialog> element.
//
// The project has no @radix-ui dependency, and this is the one place the app
// needs a modal — so rather than pulling in a package, this leans on
// showModal(), which the platform already gives us: focus is trapped inside
// the dialog, Escape closes it, the rest of the page becomes inert, and
// ::backdrop is a real pseudo-element. That is the whole accessibility
// contract of a modal, for free and with no bundle cost.

import * as React from "react";

import { cn } from "@/lib/utils";

interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Blocks Escape / backdrop dismissal — used while a delete is in flight. */
  dismissible?: boolean;
  className?: string;
  children: React.ReactNode;
}

export function Dialog({
  open,
  onOpenChange,
  dismissible = true,
  className,
  children,
}: DialogProps) {
  const ref = React.useRef<HTMLDialogElement>(null);

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // showModal() throws if called on an already-open dialog, and close() on
    // an already-closed one is a no-op that still fires events — so both are
    // guarded on the element's own state rather than on the prop alone.
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={cn(
        "m-auto w-[min(28rem,calc(100vw-2rem))] rounded-xl border border-border",
        "bg-card p-0 text-card-foreground shadow-2xl backdrop:bg-foreground/35",
        "backdrop:backdrop-blur-[2px] open:[animation:rise_140ms_ease-out]",
        className,
      )}
      onCancel={(event) => {
        // Fires on Escape. Prevent the browser's own close so React state
        // stays the single source of truth for `open`.
        event.preventDefault();
        if (dismissible) onOpenChange(false);
      }}
      onClick={(event) => {
        // <dialog> spans the whole viewport, so a click landing on the
        // element itself (rather than on the inner panel) is a backdrop click.
        if (dismissible && event.target === ref.current) onOpenChange(false);
      }}
    >
      {children}
    </dialog>
  );
}

export function DialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-6 pt-6", className)} {...props} />;
}

export function DialogTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2
      className={cn("font-display text-2xl leading-tight tracking-tight", className)}
      {...props}
    />
  );
}

export function DialogDescription({
  className,
  ...props
}: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("mt-2 text-sm text-muted-foreground", className)} {...props} />;
}

export function DialogBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-6 py-4", className)} {...props} />;
}

export function DialogFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "flex items-center justify-end gap-2 border-t border-border px-6 py-4",
        className,
      )}
      {...props}
    />
  );
}
