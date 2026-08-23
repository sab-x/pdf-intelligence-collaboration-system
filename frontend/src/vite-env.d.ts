/// <reference types="vite/client" />

/**
 * Vite's ambient types, plus this app's own environment variables.
 *
 * This file is part of Vite's standard scaffold but was missing from the
 * project — nothing referenced `import.meta.env` until the chat stream
 * needed to know its own origin, so the gap went unnoticed until `tsc -b`
 * failed the production build with:
 *
 *     error TS2339: Property 'env' does not exist on type 'ImportMeta'.
 *
 * Note that `npm run dev` never caught this: Vite transpiles without type
 * checking, so the dev server was perfectly happy. Only `npm run build`
 * runs tsc, which is why the first sign of it was a red deployment.
 *
 * Declaring each variable here rather than casting at the call site means a
 * typo in the name is a compile error instead of `undefined` at runtime —
 * and `undefined` here would silently route the SSE stream back through the
 * Vercel rewrite, where it gets buffered and stops being a stream at all.
 */
interface ImportMetaEnv {
  /**
   * Origin for the SSE chat endpoint. Empty in development so the request
   * goes through Vite's dev proxy; set to the Render origin on Vercel so the
   * stream bypasses the edge rewrite. See frontend/src/lib/chat.ts.
   */
  readonly VITE_STREAM_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
