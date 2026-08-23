import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type DragEvent, type RefObject } from "react";
import { UploadCloud } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  documentKeys,
  formatBytes,
  MAX_UPLOAD_MB,
  uploadDocument,
} from "@/lib/documents";
import { cn } from "@/lib/utils";

const MAX_BYTES = MAX_UPLOAD_MB * 1024 * 1024;

/**
 * Client-side pre-checks. These are a courtesy, not a control — the server
 * re-validates extension, content-type, %PDF- magic bytes and size, and it is
 * the only opinion that counts. Catching the obvious cases here just saves a
 * 20 MB round trip to be told no.
 */
function localRejection(file: File): string | null {
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    return `${file.name} isn't a PDF.`;
  }
  if (file.size > MAX_BYTES) {
    return `${file.name} is ${formatBytes(file.size)} — the limit is ${MAX_UPLOAD_MB} MB.`;
  }
  if (file.size === 0) {
    return `${file.name} is empty.`;
  }
  return null;
}

interface UploadDropzoneProps {
  /**
   * Lets an ancestor open the file picker — the empty state's call-to-action
   * needs to trigger the same input this dropzone owns, and passing the ref
   * down beats querying the DOM for it.
   */
  // React 18's RefObject<T> already types `current` as T | null.
  inputRef?: RefObject<HTMLInputElement>;
}

export function UploadDropzone({ inputRef: externalRef }: UploadDropzoneProps = {}) {
  const queryClient = useQueryClient();
  const localRef = useRef<HTMLInputElement>(null);
  const inputRef = externalRef ?? localRef;
  const [isDragging, setIsDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [currentFile, setCurrentFile] = useState<string | null>(null);

  // Nested drag events fire on every child element, so a naive
  // dragleave-clears-the-state approach flickers. Counting enter/leave pairs
  // is the standard fix.
  const dragDepth = useRef(0);

  const upload = useMutation({
    mutationFn: (file: File) => uploadDocument(file, setProgress),
    onMutate: (file: File) => {
      setCurrentFile(file.name);
      setProgress(0);
    },
    onSuccess: async () => {
      // The row exists as 'processing'; refetching swaps this dropzone's
      // progress bar for a real ProcessingCard in the grid.
      await queryClient.invalidateQueries({ queryKey: documentKeys.list() });
    },
    onError: (error) => {
      toast.error(
        error instanceof ApiError ? error.message : "Upload failed. Please try again.",
      );
    },
    onSettled: () => {
      setProgress(null);
      setCurrentFile(null);
    },
  });

  function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    // One at a time: the backend queues a background ingestion per upload and
    // a free-tier Gemini quota does not enjoy a parallel burst.
    const accepted: File[] = [];
    for (const file of Array.from(files)) {
      const rejection = localRejection(file);
      if (rejection) toast.error(rejection);
      else accepted.push(file);
    }
    if (accepted.length === 0) return;
    if (accepted.length > 1) {
      toast.info(`Uploading ${accepted[0].name} — please add the rest one at a time.`);
    }
    upload.mutate(accepted[0]);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    dragDepth.current = 0;
    setIsDragging(false);
    handleFiles(event.dataTransfer.files);
  }

  const isUploading = progress !== null;

  return (
    <div
      onDragEnter={(event) => {
        event.preventDefault();
        dragDepth.current += 1;
        setIsDragging(true);
      }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={(event) => {
        event.preventDefault();
        dragDepth.current -= 1;
        if (dragDepth.current <= 0) setIsDragging(false);
      }}
      onDrop={onDrop}
      className={cn(
        "relative rounded-xl border border-dashed border-input bg-card/60 px-6 py-7 transition-colors",
        isDragging && "border-primary bg-primary/[0.04]",
        isUploading && "border-solid border-progress bg-progress-soft/40",
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        multiple
        className="sr-only"
        onChange={(event) => {
          handleFiles(event.target.files);
          // Reset so re-picking the same file still fires a change event.
          event.target.value = "";
        }}
      />

      {isUploading ? (
        <div className="space-y-3">
          <div className="flex items-baseline justify-between gap-4">
            <span className="truncate text-sm font-medium">{currentFile}</span>
            <span className="meta tabular-nums">{progress}%</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-progress transition-[width] duration-200 ease-out"
              style={{ width: `${progress}%` }}
              role="progressbar"
              aria-valuenow={progress}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`Uploading ${currentFile}`}
            />
          </div>
          <p className="meta">
            {progress === 100 ? "Handing off to the server…" : "Uploading…"}
          </p>
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <span
              className={cn(
                "grid size-10 shrink-0 place-items-center rounded-lg bg-secondary text-muted-foreground transition-colors",
                isDragging && "bg-primary/10 text-primary",
              )}
            >
              <UploadCloud className="size-5" aria-hidden />
            </span>
            <div>
              <p className="text-sm font-medium">
                {isDragging ? "Drop it anywhere here" : "Drop a PDF to add it to your library"}
              </p>
              <p className="meta mt-1">PDF only · up to {MAX_UPLOAD_MB} MB</p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={() => inputRef.current?.click()}>
            Choose file
          </Button>
        </div>
      )}
    </div>
  );
}
