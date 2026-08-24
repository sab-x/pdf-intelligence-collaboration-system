import { useRef, useState, type KeyboardEvent } from "react";
import { Bold, Italic, List, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type MarkAction = "bold" | "italic" | "bullets";

interface CommentComposerProps {
  onSubmit: (body: string) => void;
  isSubmitting?: boolean;
  placeholder?: string;
  submitLabel?: string;
  onCancel?: () => void;
  autoFocus?: boolean;
  /** Shown as a chip so the author can see what the comment anchors to. */
  pageNumber?: number | null;
}

export function CommentComposer({
  onSubmit,
  isSubmitting,
  placeholder = "Add a comment…",
  submitLabel = "Comment",
  onCancel,
  autoFocus,
  pageNumber,
}: CommentComposerProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  /**
   * Applies markdown to the selection and — critically — restores the
   * selection afterwards. A toolbar that wraps your text but drops the caret
   * to the end is worse than no toolbar, because it breaks the next keystroke.
   */
  function applyMark(action: MarkAction) {
    const el = textareaRef.current;
    if (!el) return;

    const start = el.selectionStart;
    const end = el.selectionEnd;
    const selected = value.slice(start, end);

    let next: string;
    let caretStart: number;
    let caretEnd: number;

    if (action === "bullets") {
      // Operate on whole lines: bullets are a block-level mark.
      const lineStart = value.lastIndexOf("\n", start - 1) + 1;
      const lineEnd = end === start ? value.indexOf("\n", start) : end;
      const sliceEnd = lineEnd === -1 ? value.length : lineEnd;
      const block = value.slice(lineStart, sliceEnd) || "";
      const bulleted = block
        .split("\n")
        .map((line) => (line.startsWith("- ") ? line : `- ${line}`))
        .join("\n");
      next = value.slice(0, lineStart) + bulleted + value.slice(sliceEnd);
      caretStart = lineStart;
      caretEnd = lineStart + bulleted.length;
    } else {
      const token = action === "bold" ? "**" : "_";
      const placeholderText = action === "bold" ? "bold text" : "italic text";
      const inner = selected || placeholderText;
      next = value.slice(0, start) + token + inner + token + value.slice(end);
      // With no selection, land the caret on the placeholder so typing
      // replaces it.
      caretStart = start + token.length;
      caretEnd = caretStart + inner.length;
    }

    setValue(next);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(caretStart, caretEnd);
    });
  }

  function submit() {
    const trimmed = value.trim();
    if (!trimmed || isSubmitting) return;
    onSubmit(trimmed);
    setValue("");
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Cmd/Ctrl+Enter submits — Enter alone must stay newline, since comments
    // are multi-line markdown.
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      submit();
    }
    if (event.key === "Escape" && onCancel) {
      event.preventDefault();
      onCancel();
    }
  }

  const tools: { id: MarkAction; label: string; Icon: typeof Bold }[] = [
    { id: "bold", label: "Bold", Icon: Bold },
    { id: "italic", label: "Italic", Icon: Italic },
    { id: "bullets", label: "Bulleted list", Icon: List },
  ];

  return (
    <div className="rounded-lg border border-input bg-card focus-within:border-primary focus-within:ring-2 focus-within:ring-ring/25">
      <div className="flex items-center gap-0.5 border-b border-border px-2 py-1.5">
        {tools.map(({ id, label, Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => applyMark(id)}
            aria-label={label}
            title={label}
            className="rounded-md p-1.5 text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Icon className="size-3.5" aria-hidden />
          </button>
        ))}
        {pageNumber != null && (
          <span className="meta ml-auto pr-1">on page {pageNumber}</span>
        )}
      </div>

      <textarea
        ref={textareaRef}
        value={value}
        autoFocus={autoFocus}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        rows={2}
        className={cn(
          "w-full resize-y bg-transparent px-3.5 py-3 text-sm leading-relaxed",
          "placeholder:text-muted-foreground focus:outline-none",
        )}
      />

      <div className="flex items-center justify-between gap-2 border-t border-border px-3 py-2">
        <span className="meta hidden sm:inline">**bold** · _italic_ · - list</span>
        <div className="ml-auto flex items-center gap-2">
          {onCancel && (
            <Button variant="ghost" size="sm" onClick={onCancel} disabled={isSubmitting}>
              Cancel
            </Button>
          )}
          <Button size="sm" onClick={submit} disabled={!value.trim() || isSubmitting}>
            {isSubmitting && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
            {submitLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
