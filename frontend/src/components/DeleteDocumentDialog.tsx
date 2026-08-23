import { Loader2, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { DocumentSummary } from "@/lib/documents";

interface DeleteDocumentDialogProps {
  /** The document pending confirmation, or null when the dialog is closed. */
  document: DocumentSummary | null;
  isDeleting: boolean;
  onCancel: () => void;
  onConfirm: (document: DocumentSummary) => void;
}

export function DeleteDocumentDialog({
  document,
  isDeleting,
  onCancel,
  onConfirm,
}: DeleteDocumentDialogProps) {
  return (
    <Dialog
      open={document !== null}
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
      // Deletion is irreversible and already in flight — dismissing here
      // would leave the user unsure whether it happened.
      dismissible={!isDeleting}
    >
      <DialogHeader>
        <DialogTitle>Delete this document?</DialogTitle>
        <DialogDescription>
          {/* Naming the file is what makes this a real confirmation rather
              than a reflexive "are you sure". */}
          <span className="font-medium text-foreground">{document?.filename}</span> and its
          summary will be permanently removed. This cannot be undone.
        </DialogDescription>
      </DialogHeader>

      <DialogBody className="pt-0" />

      <DialogFooter>
        <Button variant="ghost" onClick={onCancel} disabled={isDeleting}>
          Cancel
        </Button>
        <Button
          className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
          onClick={() => document && onConfirm(document)}
          disabled={isDeleting}
          // Autofocus lands on Cancel by default (first focusable); this is
          // the deliberate choice NOT to autofocus the destructive action.
        >
          {isDeleting ? (
            <Loader2 className="size-4 animate-spin" aria-hidden />
          ) : (
            <Trash2 className="size-4" aria-hidden />
          )}
          {isDeleting ? "Deleting…" : "Delete"}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
