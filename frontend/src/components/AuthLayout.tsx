import type { ReactNode } from "react";
import { Link2, ScanSearch, Sparkles, Quote } from "lucide-react";

/**
 * Split-screen shell for /login and /signup.
 *
 * ## Why the whole page is dark, not just the left half
 *
 * The first version put a dark panel beside the app's warm-paper background
 * and the seam read as a mistake — two unrelated pages stitched together.
 * Auth is a distinct moment from the app itself, so it commits to one
 * surface: the same ink used by the PDF reader, with the form as a light
 * card lifted off it. The contrast now points at the thing you're meant to
 * do instead of looking accidental.
 *
 * ## Why there's a specimen at all
 *
 * Benefits tell; the specimen shows. The card at the bottom is a real
 * grounded answer with a page citation AND the refusal underneath, because
 * "it declines when the document doesn't say" is the claim most worth
 * demonstrating rather than asserting — it's the first thing anyone
 * evaluating this will try to break.
 *
 * Below 1024px the left column is hidden and the form centres on the same
 * ink background, so the two breakpoints still look like one product.
 */

const BENEFITS = [
  {
    icon: Sparkles,
    title: "Summarised on upload",
    body: "Named parties, dates and amounts — not a generic restatement.",
  },
  {
    icon: Quote,
    title: "Answers cite their page",
    body: "Click any citation and the viewer jumps straight to the source.",
  },
  {
    icon: Link2,
    title: "Share without accounts",
    body: "Send a link. They read, comment and ask questions — no signup.",
  },
  {
    icon: ScanSearch,
    title: "Search by meaning",
    body: "Find the right document even when you can't recall its name.",
  },
];

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="relative flex min-h-dvh overflow-y-auto bg-reader">
      {/* Paper grid across the WHOLE page, so both halves share a texture
          and the split reads as one surface rather than two. */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.05]"
        style={{
          backgroundImage:
            "linear-gradient(to right, white 1px, transparent 1px), linear-gradient(to bottom, white 1px, transparent 1px)",
          backgroundSize: "44px 44px",
        }}
        aria-hidden
      />
      {/* Indigo bloom behind the copy — the app's primary hue, so the auth
          page and the dashboard share an accent. */}
      <div
        className="pointer-events-none absolute -left-32 top-0 size-[38rem] rounded-full opacity-30 blur-3xl"
        style={{ background: "radial-gradient(circle, oklch(0.47 0.148 268), transparent 70%)" }}
        aria-hidden
      />
      {/* A second, quieter bloom under the form so the right side isn't just
          flat ink beside the left panel's light — the whole page reads as
          one lit surface, not a lit half and a dark one. */}
      <div
        className="pointer-events-none absolute -right-40 bottom-0 size-[34rem] rounded-full opacity-20 blur-3xl"
        style={{ background: "radial-gradient(circle, oklch(0.55 0.09 80), transparent 70%)" }}
        aria-hidden
      />

      {/* ---- Left: what it does ---------------------------------------- */}
      <aside className="relative hidden w-[52%] shrink-0 flex-col justify-center px-10 py-8 lg:flex xl:px-16">
        <span className="font-display text-xl tracking-tight text-white/90">
          PDF Intelligence
        </span>

        <h1 className="mt-5 max-w-[16ch] font-display text-[2.5rem] leading-[1.05] tracking-tight text-white xl:text-[3rem]">
          Read less. Know more.
        </h1>
        <p className="mt-3 max-w-[42ch] text-[0.9375rem] leading-relaxed text-white/55">
          Upload a document and it&rsquo;s summarised, indexed and ready to answer
          questions — with every claim tied to the page it came from.
        </p>

        <ul className="mt-7 grid max-w-[34rem] gap-x-8 gap-y-4 sm:grid-cols-2">
          {BENEFITS.map(({ icon: Icon, title, body }) => (
            <li key={title} className="flex gap-3">
              <span
                className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-white/[0.07] text-white/70"
                aria-hidden
              >
                <Icon className="size-4" />
              </span>
              <div className="min-w-0">
                <p className="text-sm font-medium text-white/90">{title}</p>
                <p className="mt-0.5 text-[0.8125rem] leading-relaxed text-white/45">{body}</p>
              </div>
            </li>
          ))}
        </ul>

        {/* The specimen. One, not three — it's evidence, not a gallery. */}
        <figure className="mt-7 max-w-[34rem] rounded-xl border border-white/10 bg-white/[0.04] p-4 backdrop-blur-sm">
          <figcaption className="flex items-center gap-2 text-white/35">
            <Sparkles className="size-3.5" aria-hidden />
            <span className="font-mono text-[0.625rem] uppercase tracking-[0.12em]">
              A grounded answer
            </span>
          </figcaption>

          <p className="mt-3 text-[0.875rem] leading-relaxed text-white/80">
            The agreement runs for twelve months from 1 April and renews automatically
            unless either party gives 30 days&rsquo; notice
            <span className="mx-1 inline-flex items-center rounded border border-white/25 bg-white/10 px-1.5 py-px align-baseline font-mono text-[0.625rem] tabular-nums text-white/90">
              [p. 4]
            </span>
            .
          </p>

          <p className="mt-3 border-l-2 border-white/15 pl-3 text-[0.875rem] leading-relaxed text-white/40">
            &ldquo;I couldn&rsquo;t find anything about early-termination penalties in this
            document.&rdquo;
          </p>

          <p className="mt-3 font-mono text-[0.625rem] uppercase tracking-[0.1em] text-white/30">
            It declines rather than guesses
          </p>
        </figure>
      </aside>

      {/* ---- Right: the form ------------------------------------------- */}
      <main className="relative flex flex-1 items-center justify-center px-5 py-8">
        <div className="w-full max-w-sm">
          {/* Only below lg, where the left column is gone and the page would
              otherwise open on an unlabelled card. */}
          <span className="mb-6 block text-center font-display text-xl tracking-tight text-white/90 lg:hidden">
            PDF Intelligence
          </span>
          {children}
        </div>
      </main>
    </div>
  );
}
