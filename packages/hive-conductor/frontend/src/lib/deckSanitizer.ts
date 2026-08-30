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
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
  "i",
  "li",
  "ol",
  "p",
  "pre",
  "s",
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
  "path",
  "polygon",
  "polyline",
  "rect",
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
  "height",
  "opacity",
  "points",
  "preserveaspectratio",
  "r",
  "role",
  "rx",
  "ry",
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
  "viewbox",
  "width",
  "x",
  "x1",
  "x2",
  "y",
  "y1",
  "y2",
]);

// Deck markup is presentation-only. Keep this deliberately smaller than the
// browser's CSS surface: no property below can itself name a remote resource.
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

function sanitizeStyle(styleText: string): string {
  const source = document.createElement("div");
  source.setAttribute("style", styleText);
  const target = document.createElement("div");

  for (let i = 0; i < source.style.length; i += 1) {
    const property = source.style.item(i).toLowerCase();
    if (!STYLE_PROPERTIES.has(property)) continue;

    const value = source.style.getPropertyValue(property).trim();
    if (!value || NETWORK_OR_CODE_CSS.test(value)) continue;

    // The browser parser has already normalized the declaration. Store the
    // normalized value without !important so slide markup cannot override the
    // product shell's security/containment rules by priority escalation.
    target.style.setProperty(property, value);
  }

  return target.getAttribute("style") || "";
}

function attributeAllowed(element: Element, attribute: Attr): boolean {
  const name = attribute.name.toLowerCase();
  if (name.startsWith("on") || name.includes(":")) return false;

  const isSvg = element.namespaceURI === "http://www.w3.org/2000/svg";
  const allowed = isSvg ? SVG_ATTRIBUTES : HTML_ATTRIBUTES;
  if (!allowed.has(name)) return false;

  if (name === "style") return true;

  // SVG paint/transform attributes are the only non-style attributes in the
  // allowlist that can be interpreted beyond plain text/numbers. Do not allow
  // any remote/data URL or executable scheme through them. `class` is not in
  // either allowlist: model output cannot activate unrelated global app CSS.
  if (NETWORK_OR_CODE_ATTRIBUTE.test(attribute.value)) return false;
  return true;
}

function scrubTree(root: ParentNode): void {
  for (const child of Array.from(root.children)) {
    const tag = child.localName.toLowerCase();
    const isSvg = child.namespaceURI === "http://www.w3.org/2000/svg";
    const tagAllowed = isSvg ? SVG_TAGS.has(tag) : HTML_TAGS.has(tag);

    if (!tagAllowed) {
      // Remove the whole subtree. Unwrapping is unsafe for elements such as
      // script/style/foreignObject because their descendants may acquire a new
      // interpretation when reparsed outside their original context.
      child.remove();
      continue;
    }

    for (const attribute of Array.from(child.attributes)) {
      const name = attribute.name.toLowerCase();
      if (!attributeAllowed(child, attribute)) {
        child.removeAttribute(attribute.name);
        continue;
      }
      if (name === "style") {
        const safeStyle = sanitizeStyle(attribute.value);
        if (safeStyle) child.setAttribute("style", safeStyle);
        else child.removeAttribute(attribute.name);
      }
    }

    scrubTree(child);
  }
}

function sanitizeOnce(markup: string): string {
  const parser = new DOMParser();
  const parsed = parser.parseFromString(`<body>${markup}</body>`, "text/html");
  scrubTree(parsed.body);
  return parsed.body.innerHTML;
}

/**
 * Sanitize untrusted Deck HTML/SVG into the product's presentation-only subset.
 *
 * Two passes intentionally sanitize the serialized result again. That makes a
 * parser mutation unable to introduce a construct that was not examined in its
 * final browser interpretation.
 */
export function sanitizeDeckMarkup(markup: string): string {
  if (!markup) return "";
  return sanitizeOnce(sanitizeOnce(markup));
}

/** Escape plain text before embedding it into an exported HTML document. */
export function escapeDeckText(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
