import { cva, type VariantProps } from "class-variance-authority";
import type * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full font-mono text-[0.625rem] uppercase tracking-[0.08em] leading-none whitespace-nowrap",
  {
    variants: {
      variant: {
        // doc_type — the badge that carries real information, so it gets the
        // most contrast of the three.
        type: "border border-border bg-secondary px-2.5 py-1 text-secondary-foreground",
        processing: "bg-progress-soft px-2.5 py-1 text-progress-ink",
        failed: "bg-destructive/10 px-2.5 py-1 text-destructive",
        // Search "why did this match" chip — quiet by design; it annotates a
        // result rather than competing with the filename.
        match: "border border-dashed border-border px-2 py-0.5 text-muted-foreground",
      },
    },
    defaultVariants: { variant: "type" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
