import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Check, Copy, Link2, Loader2, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import {
  copyToClipboard,
  createShareLink,
  listShareLinks,
  revokeShareLink,
  shareKeys,
  type ShareLink,
  type SharePermission,
} from "@/lib/shares";
import { cn } from "@/lib/utils";

interface ShareDialogProps {
  documentId: string;
  filename: string;
  open: boolean;
  onClose: () => void;
}

const PERMISSION_OPTIONS: { value: SharePermission; label: string; hint: string }[] = [
  { value: "comment", label: "View and comment", hint: "They can read it and join the discussion" },
  { value: "view", label: "View only", hint: "They can read it but not comment" },
];

/** Relative time, coarse on purpose — "3 days ago" beats a timestamp here. */
function relativeTime(iso: string): string {
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

function CopyButton({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);

  // Reset the confirmation so the button doesn't sit on "Copied" forever,
  // which would make a second copy feel like it did nothing.
  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  return (
    <Button
      type="button"
      variant={copied ? "default" : "outline"}
      size="sm"
      onClick={async () => {
        const ok = await copyToClipboard(url);
        setCopied(ok);
        setFailed(!ok);
      }}
      aria-label={copied ? "Link copied" : "Copy link"}
    >
      {copied ? (
        <Check className="size-4" aria-hidden />
      ) : (
        <Copy className="size-4" aria-hidden />
      )}
      {copied ? "Copied" : failed ? "Select it" : "Copy"}
    </Button>
  );
}

function ShareLinkRow({
  link,
  onRevoke,
  isRevoking,
}: {
  link: ShareLink;
  onRevoke: (link: ShareLink) => void;
  isRevoking: boolean;
}) {
  return (
    <li
      className={cn(
        "flex flex-col gap-2.5 rounded-lg border border-border p-3",
        !link.is_active && "opacity-55",
      )}
    >
      <div className="flex items-center gap-2">
        <Link2 className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
        {/* readOnly rather than plain text: the owner can select and copy it
            manually if the clipboard API is unavailable to us. */}
        <input
          readOnly
          value={link.url}
          onFocus={(event) => event.currentTarget.select()}
          className="min-w-0 flex-1 truncate bg-transparent font-mono text-xs text-muted-foreground focus:outline-none"
          aria-label="Share link"
        />
        {link.is_active && <CopyButton url={link.url} />}
      </div>

      <div className="flex items-center justify-between gap-3">
        <span className="meta">
          {link.permission === "comment" ? "View + comment" : "View only"}
          {" · "}
          {link.view_count} {link.view_count === 1 ? "open" : "opens"}
          {" · "}
          {link.is_active ? relativeTime(link.created_at) : "revoked"}
        </span>

        {link.is_active && (
          <button
            type="button"
            onClick={() => onRevoke(link)}
            disabled={isRevoking}
            className="flex items-center gap-1.5 rounded-md px-2 py-1 font-mono text-[0.6875rem] uppercase tracking-[0.1em] text-muted-foreground transition hover:bg-accent hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
          >
            <Trash2 className="size-3.5" aria-hidden />
            Revoke
          </button>
        )}
      </div>
    </li>
  );
}

export function ShareDialog({ documentId, filename, open, onClose }: ShareDialogProps) {
  const queryClient = useQueryClient();
  const [permission, setPermission] = useState<SharePermission>("comment");
  const [invitedEmail, setInvitedEmail] = useState("");

  const links = useQuery({
    queryKey: shareKeys.forDocument(documentId),
    queryFn: () => listShareLinks(documentId),
    // Only fetch once the dialog is actually open — no point paying for this
    // on every document page view when most are never shared.
    enabled: open && Boolean(documentId),
  });

  const create = useMutation({
    mutationFn: () =>
      createShareLink(documentId, {
        permission,
        invited_email: invitedEmail.trim() || null,
      }),
    onSuccess: () => {
      setInvitedEmail("");
      void queryClient.invalidateQueries({ queryKey: shareKeys.forDocument(documentId) });
    },
  });

  const revoke = useMutation({
    mutationFn: (link: ShareLink) => revokeShareLink(link.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: shareKeys.forDocument(documentId) });
    },
  });

  const activeLinks = links.data?.filter((link) => link.is_active) ?? [];
  const revokedLinks = links.data?.filter((link) => !link.is_active) ?? [];
  const error = create.error ?? revoke.error ?? links.error;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogHeader>
        <DialogTitle>Share this document</DialogTitle>
        <DialogDescription>
          Anyone with the link can open{" "}
          <span className="font-medium text-foreground">{filename}</span> — no account
          needed.
        </DialogDescription>
      </DialogHeader>

      <DialogBody className="space-y-5">
        {/* ---- Create ------------------------------------------------- */}
        <div className="space-y-3">
          <fieldset className="space-y-2">
            <legend className="meta mb-2">Permission</legend>
            {PERMISSION_OPTIONS.map((option) => (
              <label
                key={option.value}
                className={cn(
                  "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition",
                  permission === option.value
                    ? "border-primary bg-accent"
                    : "border-border hover:bg-accent/50",
                )}
              >
                <input
                  type="radio"
                  name="permission"
                  value={option.value}
                  checked={permission === option.value}
                  onChange={() => setPermission(option.value)}
                  className="mt-0.5 size-4 accent-primary"
                />
                <span className="min-w-0">
                  <span className="block text-sm font-medium">{option.label}</span>
                  <span className="block text-xs text-muted-foreground">{option.hint}</span>
                </span>
              </label>
            ))}
          </fieldset>

          <div className="space-y-1.5">
            <Label htmlFor="invited-email">Invitee email (optional)</Label>
            <Input
              id="invited-email"
              type="email"
              placeholder="colleague@example.com"
              value={invitedEmail}
              onChange={(event) => setInvitedEmail(event.target.value)}
            />
            {/* Stated plainly rather than left as a dead field the owner
                waits on. This is a declared trade-off, not a bug. */}
            <p className="text-xs text-muted-foreground">
              Recorded against the link for your reference. Email delivery isn&rsquo;t
              built — you&rsquo;ll need to send the link yourself.
            </p>
          </div>

          <Button
            type="button"
            onClick={() => create.mutate()}
            disabled={create.isPending}
            className="w-full"
          >
            {create.isPending ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <Link2 className="size-4" aria-hidden />
            )}
            {create.isPending ? "Creating…" : "Create link"}
          </Button>
        </div>

        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error instanceof ApiError ? error.message : "Something went wrong."}
          </p>
        )}

        {/* ---- Existing ----------------------------------------------- */}
        <div className="space-y-2">
          <h3 className="meta">Links</h3>

          {links.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading links…</p>
          ) : activeLinks.length === 0 && revokedLinks.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No links yet. Create one above and send it to whoever needs access.
            </p>
          ) : (
            <ul className="space-y-2">
              {activeLinks.map((link) => (
                <ShareLinkRow
                  key={link.id}
                  link={link}
                  onRevoke={revoke.mutate}
                  isRevoking={revoke.isPending}
                />
              ))}
              {/* Revoked links stay listed so the owner can see what they've
                  already turned off, instead of wondering whether a link they
                  remember sending still works. */}
              {revokedLinks.map((link) => (
                <ShareLinkRow
                  key={link.id}
                  link={link}
                  onRevoke={revoke.mutate}
                  isRevoking={revoke.isPending}
                />
              ))}
            </ul>
          )}
        </div>
      </DialogBody>

      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          Done
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
