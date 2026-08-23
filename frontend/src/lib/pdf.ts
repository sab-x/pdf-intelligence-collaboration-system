// pdf.js worker configuration — imported once, for its side effect, by the
// viewer.
//
// The worker is resolved from the LOCALLY INSTALLED pdfjs-dist via
// import.meta.url, never from a CDN. Two reasons that matters:
//
//   1. Version pinning. react-pdf 9.2.1 is built against pdfjs-dist 4.8.69,
//      and pdf.js throws "API version does not match Worker version" if the
//      two drift apart. A CDN URL with a hand-written version string is a
//      silent time bomb the next time the lockfile moves; this expression
//      cannot disagree with what's installed, because it IS what's installed.
//   2. It keeps rendering working offline and behind a strict CSP, and stops
//      document contents from depending on a third-party host being up.
//
// Vite rewrites this URL at build time and emits the worker as an asset.

import { pdfjs } from "react-pdf";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

/**
 * Rendering options shared by every <Page>.
 *
 * Deliberately does NOT set cMapUrl / standardFontDataUrl. Those point at
 * DIRECTORIES inside pdfjs-dist, and `new URL(dir, import.meta.url)` is not
 * something Vite can resolve at build time — it warns and leaves the string
 * untouched, which yields a 404 at runtime and silently degrades rendering
 * rather than failing loudly.
 *
 * The cost is narrow: PDFs relying on bundled CJK character maps or the
 * standard-14 font data may render some glyphs incorrectly. Fixing it
 * properly means copying both directories into public/ via a build step
 * (vite-plugin-static-copy or a postinstall), which is a build-config change
 * rather than a viewer change — worth doing if non-Latin documents matter.
 */
export const PDF_OPTIONS = {} as const;

export const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3] as const;
export const DEFAULT_ZOOM_INDEX = 2; // 1.0
