import { useEffect, useRef, useState } from "react";
import { Search, X } from "lucide-react";

import { cn } from "@/lib/utils";

// Longer than a pure-text search would need. Every keystroke that gets
// through here costs an embedding API call on the backend, so the debounce
// is a cost control as much as a UX one.
const DEBOUNCE_MS = 400;

interface SearchBarProps {
  /** Fires with the debounced value — the parent drives the query from this. */
  onSearch: (query: string) => void;
  isSearching?: boolean;
}

export function SearchBar({ onSearch, isSearching }: SearchBarProps) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Keep the callback in a ref so changing its identity between renders
  // doesn't restart the debounce timer mid-typing.
  const onSearchRef = useRef(onSearch);
  onSearchRef.current = onSearch;

  useEffect(() => {
    const trimmed = value.trim();
    // Clearing the box should restore the full list immediately rather than
    // making the user wait out a debounce for nothing to happen.
    if (trimmed === "") {
      onSearchRef.current("");
      return;
    }
    const id = window.setTimeout(() => onSearchRef.current(trimmed), DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [value]);

  return (
    <div className="relative w-full sm:max-w-sm">
      <Search
        className={cn(
          "pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 transition-colors",
          isSearching ? "text-primary" : "text-muted-foreground",
        )}
        aria-hidden
      />
      <input
        ref={inputRef}
        type="search"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setValue("");
        }}
        placeholder="Search by name or meaning…"
        aria-label="Search documents"
        className={cn(
          "h-10 w-full rounded-lg border border-input bg-card pl-9 pr-9 text-sm",
          "placeholder:text-muted-foreground focus-visible:border-primary",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30",
          // Safari renders its own clear affordance for type=search; ours is
          // consistent across browsers and keyboard-reachable.
          "[&::-webkit-search-cancel-button]:appearance-none",
        )}
      />
      {value && (
        <button
          type="button"
          onClick={() => {
            setValue("");
            inputRef.current?.focus();
          }}
          aria-label="Clear search"
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
        >
          <X className="size-3.5" aria-hidden />
        </button>
      )}
    </div>
  );
}
