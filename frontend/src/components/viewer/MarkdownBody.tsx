import Markdown from "react-markdown";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

/**
 * Comment bodies are user-authored markdown from anyone who can comment —
 * including, from Phase 8, unauthenticated guests holding a share link. So
 * this component never touches dangerouslySetInnerHTML: react-markdown parses
 * to an AST and rehype-sanitize prunes it before anything becomes a React
 * element.
 *
 * The allowlist below is deliberately narrower than rehype-sanitize's default
 * (which already blocks scripts). Comments need emphasis, lists, links, and
 * code — they do not need images, tables, headings, iframes, or arbitrary
 * class names, and every element left out is one that can't be abused for
 * layout-breaking or phishing inside a narrow panel.
 */
const COMMENT_SCHEMA = {
  ...defaultSchema,
  tagNames: [
    "p",
    "br",
    "strong",
    "em",
    "del",
    "code",
    "pre",
    "blockquote",
    "ul",
    "ol",
    "li",
    "a",
  ],
  attributes: {
    // Only href/title on links. No id/class/style anywhere, so comment markup
    // can never target or restyle the surrounding app.
    a: ["href", "title"],
  },
  // Disallowed ELEMENTS are unwrapped to their text, not dropped — verified:
  // "# Important note" renders as the words "Important note" rather than
  // vanishing, so nobody loses a comment to an unsupported syntax. Images are
  // the exception (no text node to keep), and a pasted <script> survives only
  // as inert literal text.
  protocols: {
    ...defaultSchema.protocols,
    href: ["http", "https", "mailto"],
  },
  clobberPrefix: "comment-",
};

export function MarkdownBody({
  children,
  className,
}: {
  children: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "text-sm leading-relaxed text-foreground/90",
        // Spacing is applied here rather than via a typography plugin (not a
        // dependency of this project) so the panel stays self-contained.
        "[&_p]:my-0 [&_p+p]:mt-2",
        "[&_strong]:font-semibold [&_em]:italic",
        "[&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5",
        "[&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5",
        "[&_li]:my-0.5 [&_li]:marker:text-muted-foreground",
        "[&_code]:rounded [&_code]:bg-secondary [&_code]:px-1 [&_code]:py-0.5",
        "[&_code]:font-mono [&_code]:text-[0.8125em]",
        "[&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-secondary [&_pre]:p-3",
        "[&_blockquote]:my-2 [&_blockquote]:border-l-2 [&_blockquote]:border-border",
        "[&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground",
        "[&_a]:font-medium [&_a]:text-primary [&_a]:underline [&_a]:underline-offset-2",
        className,
      )}
    >
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeSanitize, COMMENT_SCHEMA]]}
        components={{
          // Links go to arbitrary user-supplied URLs — never let one navigate
          // the app itself or reach window.opener.
          a: ({ children: linkChildren, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer nofollow">
              {linkChildren}
            </a>
          ),
        }}
      >
        {children}
      </Markdown>
    </div>
  );
}
