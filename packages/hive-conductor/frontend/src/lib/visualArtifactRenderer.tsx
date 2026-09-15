import { forwardRef, type HTMLAttributes } from "react";

const HTML_TAGS = new Set([
  "article",
  "b",
  "blockquote",
  "br",
  "caption",
  "code",
  "dd",
  "div",
  "dl",
  "dt",
  "em",
  "figcaption",
  "figure",
  "footer",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "header",
  "hr",
  "i",
  "li",
  "main",
  "ol",
  "p",
  "pre",
  "section",
  "small",
  "span",
  "strong",
  "sub",
  "sup",
  "table",
  "tbody",
  "td",
  "tfoot",
  "th",
  "thead",
  "tr",
  "u",
  "ul",
]);

const SVG_TAGS = new Set([
  "circle",
  "ellipse",
  "g",
  "line",
  "lineargradient",
  "path",
  "polygon",
  "polyline",
  "radialgradient",
  "rect",
  "stop",
  "svg",
  "text",
  "tspan",
]);

const HTML_ATTRIBUTES = new Set([
  "aria-hidden",
  "aria-label",
  "dir",
  "role",
  "style",
  "title",
]);

const SVG_ATTRIBUTES = new Set([
  "aria-hidden",
  "aria-label",
  "cx",
  "cy",
  "d",
  "dir",
  "fill",
  "fill-opacity",
  "font-size",
  "font-weight",
  "gradientunits",
  "height",
  "offset",
  "opacity",
  "points",
  "preserveaspectratio",
  "r",
  "role",
  "rx",
  "ry",
  "spreadmethod",
  "stop-color",
  "stop-opacity",
  "stroke",
  "stroke-dasharray",
  "stroke-dashoffset",
  "stroke-linecap",
  "stroke-linejoin",
  "stroke-opacity",
  "stroke-width",
  "style",
  "text-anchor",
  "text-transform",
  "title",
  "transform",
  "transform-origin",
  "viewbox",
  "width",
  "x",
  "x1",
  "x2",
  "y",
  "y1",
  "y2",
]);

// This is a presentation CSS subset, not a general stylesheet parser. In
// particular, it has no property that can load code, a URL, or a custom value.
const STYLE_PROPERTIES = new Set([
  "align-content",
  "align-items",
  "align-self",
  "aspect-ratio",
  "background",
  "background-color",
  "background-image",
  "background-position",
  "background-repeat",
  "background-size",
  "border",
  "border-bottom",
  "border-bottom-color",
  "border-bottom-left-radius",
  "border-bottom-right-radius",
  "border-bottom-style",
  "border-bottom-width",
  "border-color",
  "border-left",
  "border-left-color",
  "border-left-style",
  "border-left-width",
  "border-radius",
  "border-right",
  "border-right-color",
  "border-right-style",
  "border-right-width",
  "border-style",
  "border-top",
  "border-top-color",
  "border-top-left-radius",
  "border-top-right-radius",
  "border-top-style",
  "border-top-width",
  "border-width",
  "bottom",
  "box-sizing",
  "color",
  "column-gap",
  "display",
  "flex",
  "flex-basis",
  "flex-direction",
  "flex-grow",
  "flex-shrink",
  "flex-wrap",
  "font-family",
  "font-size",
  "font-style",
  "font-weight",
  "gap",
  "height",
  "justify-content",
  "left",
  "letter-spacing",
  "line-height",
  "margin",
  "margin-bottom",
  "margin-left",
  "margin-right",
  "margin-top",
  "max-height",
  "max-width",
  "min-height",
  "min-width",
  "object-fit",
  "opacity",
  "overflow",
  "overflow-x",
  "overflow-y",
  "padding",
  "padding-bottom",
  "padding-left",
  "padding-right",
  "padding-top",
  "position",
  "right",
  "row-gap",
  "text-align",
  "text-decoration",
  "text-overflow",
  "text-transform",
  "top",
  "transform",
  "transform-origin",
  "vertical-align",
  "white-space",
  "width",
  "word-break",
  "z-index",
  "-webkit-background-clip",
  "-webkit-text-fill-color",
]);

const NETWORK_OR_CODE_CSS = /(?:url\s*\(|image-set\s*\(|cross-fade\s*\(|element\s*\(|paint\s*\(|expression\s*\(|javascript\s*:|vbscript\s*:|data\s*:|@import|behavior\s*:|-moz-binding|var\s*\(|env\s*\()/i;
const NETWORK_OR_CODE_ATTRIBUTE = /(?:url\s*\(|javascript\s*:|vbscript\s*:|data\s*:|https?\s*:|\/\/)/i;

export const VISUAL_ARTIFACT_BLOCK_REASONS = [
  "active-element",
  "event-handler",
  "dangerous-url",
  "unsupported-attribute",
  "unsupported-css-property",
  "css-network-or-code",
] as const;

export type VisualArtifactBlockReason = (typeof VISUAL_ARTIFACT_BLOCK_REASONS)[number];

export type VisualArtifactScan = {
  blocked: boolean;
  reasons: VisualArtifactBlockReason[];
  sanitizedMarkup: string;
};

export type VisualArtifactTrustRecommendation = "upgrade" | "review";

type SanitizationContext = { reasons: Set<VisualArtifactBlockReason> };

function sanitizeStyle(styleText: string, context: SanitizationContext): string {
  const source = document.createElement("div");
  source.setAttribute("style", styleText);
  const target = document.createElement("div");

  for (const property of Array.from(source.style)) {
    const normalizedProperty = property.toLowerCase();
    if (!STYLE_PROPERTIES.has(normalizedProperty)) {
      if (
        normalizedProperty.includes("image") ||
        normalizedProperty === "mask" ||
        normalizedProperty === "content"
      ) {
        context.reasons.add("css-network-or-code");
      } else {
        context.reasons.add("unsupported-css-property");
      }
      continue;
    }

    const value = source.style.getPropertyValue(property).trim();
    if (!value || NETWORK_OR_CODE_CSS.test(value)) {
      context.reasons.add("css-network-or-code");
      continue;
    }

    // Browser-normalize declarations and discard !important escalation.
    target.style.setProperty(normalizedProperty, value);
  }

  return target.getAttribute("style") || "";
}

function attributeAllowed(
  element: Element,
  attribute: Attr,
  context: SanitizationContext,
): boolean {
  const name = attribute.name.toLowerCase();
  if (name.startsWith("on")) {
    context.reasons.add("event-handler");
    return false;
  }
  if (name.includes(":")) {
    context.reasons.add("unsupported-attribute");
    return false;
  }

  const isSvg = element.namespaceURI === "http://www.w3.org/2000/svg";
  const allowed = isSvg ? SVG_ATTRIBUTES : HTML_ATTRIBUTES;
  if (!allowed.has(name)) {
    context.reasons.add("unsupported-attribute");
    return false;
  }
  if (name === "style") return true;

  // No href/src attributes are allowlisted. Keep this check as defense in
  // depth for SVG paint and transform values that browsers may interpret.
  if (NETWORK_OR_CODE_ATTRIBUTE.test(attribute.value)) {
    context.reasons.add("dangerous-url");
    return false;
  }
  return true;
}

function scrubTree(root: ParentNode, context: SanitizationContext): void {
  for (const child of Array.from(root.children)) {
    const tag = child.localName.toLowerCase();
    const isSvg = child.namespaceURI === "http://www.w3.org/2000/svg";
    const tagAllowed = isSvg ? SVG_TAGS.has(tag) : HTML_TAGS.has(tag);

    if (!tagAllowed) {
      // Remove the subtree rather than unwrapping script-capable contexts.
      context.reasons.add("active-element");
      child.remove();
      continue;
    }

    for (const attribute of Array.from(child.attributes)) {
      const name = attribute.name.toLowerCase();
      if (!attributeAllowed(child, attribute, context)) {
        child.removeAttribute(attribute.name);
        continue;
      }
      if (name === "style") {
        const safeStyle = sanitizeStyle(attribute.value, context);
        if (safeStyle) child.setAttribute("style", safeStyle);
        else child.removeAttribute(attribute.name);
      }
    }

    scrubTree(child, context);
  }
}

function sanitizeOnce(markup: string, context: SanitizationContext): string {
  const parser = new DOMParser();
  const parsed = parser.parseFromString(`<body>${markup}</body>`, "text/html");
  scrubTree(parsed.body, context);
  return parsed.body.innerHTML;
}

/**
 * Inspect untrusted Design Studio markup before a trust recommendation.
 * Consumers should use `sanitizedMarkup` for every browser render/export and
 * use these same reasons when deciding whether content can be trusted.
 */
export function scanVisualArtifactMarkup(markup: string): VisualArtifactScan {
  if (!markup) return { blocked: false, reasons: [], sanitizedMarkup: "" };

  const context: SanitizationContext = { reasons: new Set() };
  const firstPass = sanitizeOnce(markup, context);
  const sanitizedMarkup = sanitizeOnce(firstPass, context);
  const reasons = VISUAL_ARTIFACT_BLOCK_REASONS.filter((reason) => context.reasons.has(reason));
  return { blocked: reasons.length > 0, reasons, sanitizedMarkup };
}

/**
 * Return the shared pre-scan recommendation. This is advisory, not an
 * authorization grant: blocked content is never eligible for an upgrade.
 */
export function recommendVisualArtifactTrust(markup: string): VisualArtifactTrustRecommendation {
  return scanVisualArtifactMarkup(markup).blocked ? "review" : "upgrade";
}

/** The one HTML/SVG trust boundary shared by every Design Studio visual mode. */
export function sanitizeVisualArtifactMarkup(markup: string): string {
  return scanVisualArtifactMarkup(markup).sanitizedMarkup;
}

export function createSanitizedVisualArtifactFragment(markup: string): DocumentFragment {
  const template = document.createElement("template");
  template.innerHTML = sanitizeVisualArtifactMarkup(markup);
  return template.content;
}

type SanitizedVisualArtifactProps = Omit<
  HTMLAttributes<HTMLDivElement>,
  "children" | "dangerouslySetInnerHTML"
> & { markup: string };

/**
 * Render sanitized markup through the reviewed React sink. Callers never pass
 * raw model or persisted strings to dangerouslySetInnerHTML themselves.
 */
export const SanitizedVisualArtifact = forwardRef<HTMLDivElement, SanitizedVisualArtifactProps>(
  function SanitizedVisualArtifact({ markup, ...props }, ref) {
    return <div {...props} ref={ref} dangerouslySetInnerHTML={{ __html: sanitizeVisualArtifactMarkup(markup) }} />;
  },
);
SanitizedVisualArtifact.displayName = "SanitizedVisualArtifact";

export function escapeVisualArtifactText(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
