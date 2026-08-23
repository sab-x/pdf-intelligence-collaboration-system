import { api } from "@/lib/api";

export interface Comment {
  id: string;
  parent_id: string | null;
  author_label: string;
  body_markdown: string;
  page_number: number | null;
  created_at: string;
  is_deleted: boolean;
  /** The author of this comment owns the document. */
  is_document_owner: boolean;
  /** The author of this comment is the signed-in user. */
  is_mine: boolean;
  /** The server says this user may delete it — never inferred client-side. */
  can_delete: boolean;
  replies: Comment[];
}

export interface CommentCreate {
  body_markdown: string;
  parent_id?: string | null;
  page_number?: number | null;
}

export const commentKeys = {
  all: ["comments"] as const,
  forDocument: (documentId: string) => [...commentKeys.all, documentId] as const,
};

export const listComments = (documentId: string) =>
  api.get<Comment[]>(`/documents/${documentId}/comments`);

export const createComment = (documentId: string, body: CommentCreate) =>
  api.post<Comment>(`/documents/${documentId}/comments`, body);

export const deleteComment = (commentId: string) =>
  api.delete<void>(`/comments/${commentId}`);

/** Total including replies — what the panel header counts. */
export function countComments(tree: Comment[]): number {
  return tree.reduce(
    (total, comment) => total + (comment.is_deleted ? 0 : 1) + comment.replies.length,
    0,
  );
}
