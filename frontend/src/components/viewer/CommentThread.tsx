import { formatDistanceToNow } from "date-fns";
import { useState } from "react";
import { CornerDownRight, Trash2 } from "lucide-react";

import { CommentComposer } from "@/components/viewer/CommentComposer";
import { MarkdownBody } from "@/components/viewer/MarkdownBody";
import type { Comment } from "@/lib/comments";
import { cn } from "@/lib/utils";

/** Initials for the avatar chip — two letters at most, always uppercase. */
function initials(label: string): string {
  const parts = label.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
}

interface CommentItemProps {
  comment: Comment;
  onDelete: (comment: Comment) => void;
  onJumpToPage?: (page: number) => void;
  isReply?: boolean;
}

function CommentItem({ comment, onDelete, onJumpToPage, isReply }: CommentItemProps) {
  if (comment.is_deleted) {
    // Tombstone: kept only because replies hang off it. Carries no author, no
    // body, no affordances — just enough to keep the thread coherent.
    return (
      <div className="flex items-center gap-2.5 py-1">
        <span className="grid size-7 shrink-0 place-items-center rounded-full border border-dashed border-border" />
        <p className="meta italic">This comment was deleted</p>
      </div>
    );
  }

  return (
    <article className="group/comment flex gap-2.5">
      <span
        className={cn(
          "mt-0.5 grid size-7 shrink-0 place-items-center rounded-full font-mono text-[0.625rem] font-medium",
          // The owner-vs-not distinction: filled indigo for the document's
          // owner, quiet outline for everyone else. Phase 8's guests will
          // slot into the same "not owner" treatment.
          comment.is_document_owner
            ? "bg-primary text-primary-foreground"
            : "border border-border bg-secondary text-muted-foreground",
        )}
        aria-hidden
      >
        {initials(comment.author_label)}
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <span className="text-[0.8125rem] font-medium leading-none">
            {comment.author_label}
          </span>
          {comment.is_document_owner && (
            <span className="font-mono text-[0.5625rem] uppercase tracking-[0.1em] text-primary">
              owner
            </span>
          )}
          {comment.is_mine && !comment.is_document_owner && (
            <span className="font-mono text-[0.5625rem] uppercase tracking-[0.1em] text-muted-foreground">
              you
            </span>
          )}
          <time
            dateTime={comment.created_at}
            className="meta"
            title={new Date(comment.created_at).toLocaleString()}
          >
            {formatDistanceToNow(new Date(comment.created_at), { addSuffix: true })}
          </time>

          {comment.page_number != null && onJumpToPage && (
            <button
              type="button"
              onClick={() => onJumpToPage(comment.page_number!)}
              className="rounded font-mono text-[0.625rem] tabular-nums text-primary transition hover:underline focus-visible:ring-2 focus-visible:ring-ring"
            >
              [p. {comment.page_number}]
            </button>
          )}

          {comment.can_delete && (
            <button
              type="button"
              onClick={() => onDelete(comment)}
              aria-label="Delete comment"
              className={cn(
                "ml-auto rounded-md p-1 text-muted-foreground transition",
                "opacity-0 hover:bg-destructive/10 hover:text-destructive",
                "focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring",
                "group-hover/comment:opacity-100 max-sm:opacity-100",
              )}
            >
              <Trash2 className="size-3.5" aria-hidden />
            </button>
          )}
        </div>

        <MarkdownBody className={cn("mt-1.5", isReply && "text-[0.8125rem]")}>
          {comment.body_markdown}
        </MarkdownBody>
      </div>
    </article>
  );
}

interface CommentThreadProps {
  comment: Comment;
  onReply: (parentId: string, body: string) => void;
  onDelete: (comment: Comment) => void;
  onJumpToPage?: (page: number) => void;
  isReplying: boolean;
}

export function CommentThread({
  comment,
  onReply,
  onDelete,
  onJumpToPage,
  isReplying,
}: CommentThreadProps) {
  const [composerOpen, setComposerOpen] = useState(false);

  return (
    <div className="border-b border-border px-5 py-4 last:border-b-0">
      <CommentItem comment={comment} onDelete={onDelete} onJumpToPage={onJumpToPage} />

      {comment.replies.length > 0 && (
        // The rule is the thread line — replies read as hanging off the
        // parent rather than as separate top-level items.
        <div className="mt-3.5 space-y-3.5 border-l border-border pl-4 sm:ml-3.5">
          {comment.replies.map((reply) => (
            <CommentItem
              key={reply.id}
              comment={reply}
              onDelete={onDelete}
              onJumpToPage={onJumpToPage}
              isReply
            />
          ))}
        </div>
      )}

      {composerOpen ? (
        <div className="mt-3.5 sm:ml-3.5 sm:pl-4">
          <CommentComposer
            autoFocus
            placeholder={`Reply to ${comment.author_label}…`}
            submitLabel="Reply"
            isSubmitting={isReplying}
            onCancel={() => setComposerOpen(false)}
            onSubmit={(body) => {
              onReply(comment.id, body);
              setComposerOpen(false);
            }}
          />
        </div>
      ) : (
        // A deleted parent can't take new replies — the server rejects it, so
        // the affordance shouldn't be offered.
        !comment.is_deleted && (
          <button
            type="button"
            onClick={() => setComposerOpen(true)}
            className="meta mt-2.5 inline-flex items-center gap-1.5 rounded transition hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring sm:ml-[2.625rem]"
          >
            <CornerDownRight className="size-3" aria-hidden />
            Reply
          </button>
        )
      )}
    </div>
  );
}
