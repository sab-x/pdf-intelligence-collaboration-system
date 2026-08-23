import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { FileSearch, Library, Upload } from "lucide-react";
import { toast } from "sonner";

import { DeleteDocumentDialog } from "@/components/DeleteDocumentDialog";
import { DocumentCard } from "@/components/DocumentCard";
import { ProcessingCard } from "@/components/ProcessingCard";
import { SearchBar } from "@/components/SearchBar";
import { StatStrip } from "@/components/StatStrip";
import { UploadDropzone } from "@/components/UploadDropzone";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  deleteDocument,
  documentKeys,
  listDocuments,
  computeLibraryStats,
  searchDocuments,
  type DocumentSummary,
  type SearchResult,
} from "@/lib/documents";

export default function DashboardPage() {
  const { user, logout } = useAuth();
  const queryClient = useQueryClient();

  const uploadInputRef = useRef<HTMLInputElement>(null);

  const [query, setQuery] = useState("");
  const [pendingDelete, setPendingDelete] = useState<DocumentSummary | null>(null);
  // Kept separate from the mutation's own pending flag so the card stays
  // dimmed for the specific row being removed, not for all of them.
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const isSearching = query.trim().length > 0;

  const documents = useQuery({
    queryKey: documentKeys.list(),
    queryFn: listDocuments,
  });

  const search = useQuery({
    queryKey: documentKeys.search(query),
    queryFn: () => searchDocuments(query),
    enabled: isSearching,
    // Results should feel live against a library that's actively changing.
    staleTime: 10_000,
  });

  const remove = useMutation({
    mutationFn: (document: DocumentSummary) => deleteDocument(document.id),

    // Optimistic: the card disappears on click, not on round trip.
    onMutate: async (document: DocumentSummary) => {
      setDeletingId(document.id);
      // Cancel in-flight refetches, or one landing mid-mutation would
      // overwrite the optimistic cache with a list that still has the row.
      await queryClient.cancelQueries({ queryKey: documentKeys.all });

      const previousList = queryClient.getQueryData<DocumentSummary[]>(documentKeys.list());
      const previousSearch = queryClient.getQueryData<SearchResult[]>(
        documentKeys.search(query),
      );

      queryClient.setQueryData<DocumentSummary[]>(documentKeys.list(), (old) =>
        old?.filter((doc) => doc.id !== document.id),
      );
      // The same document can also be on screen as a search hit; drop it from
      // both caches or it reappears the moment the user clears the box.
      queryClient.setQueryData<SearchResult[]>(documentKeys.search(query), (old) =>
        old?.filter((doc) => doc.id !== document.id),
      );

      return { previousList, previousSearch, document };
    },

    onError: (error, _document, context) => {
      // Roll back both caches to exactly what they were.
      if (context?.previousList) {
        queryClient.setQueryData(documentKeys.list(), context.previousList);
      }
      if (context?.previousSearch) {
        queryClient.setQueryData(documentKeys.search(query), context.previousSearch);
      }
      toast.error(
        error instanceof ApiError
          ? error.message
          : `Couldn't delete ${context?.document.filename ?? "that document"}.`,
      );
    },

    onSuccess: (_data, document) => {
      toast.success(`Deleted ${document.filename}`);
    },

    onSettled: () => {
      setDeletingId(null);
      void queryClient.invalidateQueries({ queryKey: documentKeys.all });
    },
  });

  function confirmDelete(document: DocumentSummary) {
    setPendingDelete(null);
    remove.mutate(document);
  }

  const visible: (DocumentSummary | SearchResult)[] = isSearching
    ? (search.data ?? [])
    : (documents.data ?? []);

  const isLoading = isSearching ? search.isLoading : documents.isLoading;
  const error = isSearching ? search.error : documents.error;
  const hasNoDocumentsAtAll = !isSearching && (documents.data?.length ?? 0) === 0;

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-10 border-b border-border bg-background/85 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-4 2xl:max-w-[88rem] 2xl:px-10">
          <span className="font-display text-xl leading-none tracking-tight">
            PDF Intelligence
          </span>
          <div className="flex items-center gap-4">
            <span className="meta hidden sm:inline">{user?.email}</span>
            <Button variant="outline" size="sm" onClick={() => void logout()}>
              Log out
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 2xl:max-w-[88rem] 2xl:px-10 py-10 2xl:py-14">
        <div className="flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="font-display text-[2.75rem] leading-[0.95] tracking-tight 2xl:text-6xl">
              Your library
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Upload a PDF and it&rsquo;s summarised, indexed, and ready to question.
            </p>
          </div>
          <SearchBar onSearch={setQuery} isSearching={isSearching} />
        </div>

        {!isSearching && (documents.data?.length ?? 0) > 0 && (
          <StatStrip stats={computeLibraryStats(documents.data ?? [])} className="mt-8" />
        )}

        <div className="mt-5">
          <UploadDropzone inputRef={uploadInputRef} />
        </div>

        {isSearching && (
          <p className="meta mt-8">
            {search.isLoading
              ? "Searching…"
              : `${visible.length} ${visible.length === 1 ? "result" : "results"} for “${query.trim()}”`}
          </p>
        )}

        {error && (
          <div className="mt-8 rounded-xl border border-destructive/30 bg-destructive/5 p-6">
            <p className="text-sm text-destructive">
              {error instanceof ApiError ? error.message : "Something went wrong."}
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-4"
              onClick={() =>
                void queryClient.invalidateQueries({ queryKey: documentKeys.all })
              }
            >
              Try again
            </Button>
          </div>
        )}

        {isLoading && !error && (
          <div className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-3 2xl:gap-7">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-52 rounded-xl border border-border bg-card p-5 shadow-sm"
                aria-hidden
              >
                <div className="shimmer h-5 w-28 rounded-full" />
                <div className="shimmer mt-5 h-4 w-3/4 rounded-full" />
                <div className="shimmer mt-3 h-3 w-full rounded-full" />
                <div className="shimmer mt-2 h-3 w-5/6 rounded-full" />
              </div>
            ))}
          </div>
        )}

        {/* Empty states: "no documents yet" and "no search hits" are different
            situations and deserve different words. */}
        {!isLoading && !error && visible.length === 0 && (
          <div className="mt-8 rounded-xl border border-dashed border-border bg-card/50 px-8 py-16 text-center">
            <span className="mx-auto grid size-12 place-items-center rounded-xl bg-secondary text-muted-foreground">
              {hasNoDocumentsAtAll ? (
                <Library className="size-6" aria-hidden />
              ) : (
                <FileSearch className="size-6" aria-hidden />
              )}
            </span>
            {hasNoDocumentsAtAll ? (
              <>
                <h2 className="mt-5 font-display text-2xl tracking-tight">
                  Your library is empty
                </h2>
                <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
                  Add your first PDF — a contract, a report, a paper — and you&rsquo;ll get a
                  summary and a document you can ask questions about.
                </p>
                <Button className="mt-6" onClick={() => uploadInputRef.current?.click()}>
                  <Upload className="size-4" aria-hidden />
                  Upload your first PDF
                </Button>
                <p className="meta mt-4">or drag one onto the panel above</p>
              </>
            ) : (
              <>
                <h2 className="mt-5 font-display text-2xl tracking-tight">No matches</h2>
                <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
                  Nothing in your library has a filename matching &ldquo;{query.trim()}
                  &rdquo;.
                </p>
              </>
            )}
          </div>
        )}

        {!isLoading && visible.length > 0 && (
          <div className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-3 2xl:gap-7">
            {visible.map((doc) =>
              doc.status === "processing" ? (
                <ProcessingCard key={doc.id} document={doc} />
              ) : (
                <DocumentCard
                  key={doc.id}
                  document={doc}
                  isDeleting={deletingId === doc.id}
                  onDelete={setPendingDelete}
                />
              ),
            )}
          </div>
        )}
      </main>

      <DeleteDocumentDialog
        document={pendingDelete}
        isDeleting={remove.isPending}
        onCancel={() => setPendingDelete(null)}
        onConfirm={confirmDelete}
      />
    </div>
  );
}
