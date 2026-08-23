import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { MessagesSquare } from "lucide-react";
import { toast } from "sonner";

import { CommentComposer } from "@/components/viewer/CommentComposer";
import { CommentThread } from "@/components/viewer/CommentThread";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  commentKeys,
  countComments,
  createComment,
  deleteComment,
  listComments,
  type Comment,
  type CommentCreate,
} from "@/lib/comments";

interface CommentsPanelProps {
  documentId: string;
  pageNumber: number;
  onJumpToPage?: (page: number) => void;
}

export function CommentsPanel({
  documentId,
  pageNumber,
  onJumpToPage,
}: CommentsPanelProps) {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [replyingTo, setReplyingTo] = useState<string | null>(null);

  const key = commentKeys.forDocument(documentId);

  const comments = useQuery({
    queryKey: key,
    queryFn: () => listComments(documentId),
    enabled: Boolean(documentId),
  });

  const post = useMutation({
    mutationFn: (payload: CommentCreate) => createComment(documentId, payload),

    onMutate: async (payload) => {
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData<Comment[]>(key);

      // The optimistic stand-in. `is_document_owner` is a guess here — the
      // server is authoritative and the invalidate in onSettled corrects it
      // moments later; guessing wrong only means the avatar changes shade
      // once, which beats the comment not appearing at all.
      const optimistic: Comment = {
        id: `optimistic-${crypto.randomUUID()}`,
        parent_id: payload.parent_id ?? null,
        author_label: user?.name ?? "You",
        body_markdown: payload.body_markdown,
        page_number: payload.page_number ?? null,
        created_at: new Date().toISOString(),
        is_deleted: false,
        is_document_owner: true,
        is_mine: true,
        can_delete: true,
        replies: [],
      };

      queryClient.setQueryData<Comment[]>(key, (old = []) =>
        payload.parent_id
          ? old.map((comment) =>
              comment.id === payload.parent_id
                ? { ...comment, replies: [...comment.replies, optimistic] }
                : comment,
            )
          : [...old, optimistic],
      );

      return { previous };
    },

    onError: (error, _payload, context) => {
      if (context?.previous) queryClient.setQueryData(key, context.previous);
      toast.error(
        error instanceof ApiError ? error.message : "Couldn't post that comment.",
      );
    },

    onSettled: () => {
      setReplyingTo(null);
      void queryClient.invalidateQueries({ queryKey: key });
    },
  });

  const remove = useMutation({
    mutationFn: (comment: Comment) => deleteComment(comment.id),

    onMutate: async (comment) => {
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData<Comment[]>(key);

      queryClient.setQueryData<Comment[]>(key, (old = []) =>
        old
          .map((root) => {
            if (root.id === comment.id) {
              // Mirror the server's rule locally: a top-level comment with
              // replies becomes a tombstone so the thread stays intact;
              // without replies it goes away entirely (filtered below).
              return root.replies.length > 0
                ? {
                    ...root,
                    is_deleted: true,
                    author_label: "[deleted]",
                    body_markdown: "",
                    can_delete: false,
                  }
                : null;
            }
            return {
              ...root,
              replies: root.replies.filter((reply) => reply.id !== comment.id),
            };
          })
          .filter((root): root is Comment => root !== null),
      );

      return { previous };
    },

    onError: (error, _comment, context) => {
      if (context?.previous) queryClient.setQueryData(key, context.previous);
      toast.error(
        error instanceof ApiError ? error.message : "Couldn't delete that comment.",
      );
    },

    onSettled: () => void queryClient.invalidateQueries({ queryKey: key }),
  });

  const tree = comments.data ?? [];
  const total = countComments(tree);

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-auto">
        {comments.isLoading ? (
          <div className="space-y-4 p-5" aria-hidden>
            {[0, 1].map((i) => (
              <div key={i} className="flex gap-2.5">
                <div className="shimmer size-7 shrink-0 rounded-full" />
                <div className="flex-1 space-y-2">
                  <div className="shimmer h-3 w-24 rounded-full" />
                  <div className="shimmer h-3 w-full rounded-full" />
                  <div className="shimmer h-3 w-4/5 rounded-full" />
                </div>
              </div>
            ))}
          </div>
        ) : comments.error ? (
          <div className="p-5">
            <p className="text-sm text-destructive">
              {comments.error instanceof ApiError
                ? comments.error.message
                : "Couldn't load comments."}
            </p>
          </div>
        ) : tree.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 px-8 py-12 text-center">
            <span className="grid size-11 place-items-center rounded-xl bg-secondary text-muted-foreground">
              <MessagesSquare className="size-5" aria-hidden />
            </span>
            <div>
              <p className="font-display text-xl leading-tight tracking-tight">
                No comments yet
              </p>
              <p className="mx-auto mt-2 max-w-[26ch] text-sm leading-relaxed text-muted-foreground">
                Start the thread — comments anchor to the page you&rsquo;re reading.
              </p>
            </div>
          </div>
        ) : (
          <>
            <p className="meta border-b border-border px-5 py-3">
              {total} {total === 1 ? "comment" : "comments"}
            </p>
            {tree.map((comment) => (
              <CommentThread
                key={comment.id}
                comment={comment}
                onDelete={(target) => remove.mutate(target)}
                onJumpToPage={onJumpToPage}
                isReplying={post.isPending && replyingTo === comment.id}
                onReply={(parentId, body) => {
                  setReplyingTo(parentId);
                  post.mutate({ body_markdown: body, parent_id: parentId });
                }}
              />
            ))}
          </>
        )}
      </div>

      <div className="border-t border-border p-4">
        <CommentComposer
          pageNumber={pageNumber}
          isSubmitting={post.isPending && replyingTo === null}
          onSubmit={(body) => {
            setReplyingTo(null);
            // Anchor to whatever page the reader is on — the panel already
            // shows this in the composer chip so it's never a surprise.
            post.mutate({ body_markdown: body, page_number: pageNumber });
          }}
        />
      </div>
    </div>
  );
}
