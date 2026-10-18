import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

// Issue #768 contract evidence: there is exactly one browser trust boundary for
// model-authored Design Studio HTML/SVG. These checks run in plain Node (no
// browser) and read the shipped frontend source, so adding a new visual mode
// that renders markup through any sink other than the shared
// visualArtifactRenderer fails here instead of shipping a second trust
// boundary. The path resolves the same way locally and inside
// Dockerfile.playwright, which copies frontend/src next to tests/e2e.

// Every form of "this string becomes live DOM" that shipped frontend source
// could use. The shared renderer is the only module allowed to hold one: it is
// the single place that calls sanitizeVisualArtifactMarkup before insertion,
// which is the whole point of #768 — one reviewed boundary, not one per
// artifact type. `srcdoc` and `document.write` are listed even though no
// production file uses them today: the hostile corpus feeds `srcdoc`
// (deck-sanitization.spec.ts) and it is a full-document sink, not a fragment
// one; a scan that only knew about dangerouslySetInnerHTML would wave a new
// `el.innerHTML = modelMarkup` mode straight through.
const EXECUTABLE_SINK_PATTERNS: ReadonlyArray<readonly [string, RegExp]> = [
  ["dangerouslySetInnerHTML", /dangerouslySetInnerHTML\s*=\s*\{/],
  [".innerHTML assignment", /\.innerHTML\s*=[^=]/],
  [".outerHTML assignment", /\.outerHTML\s*=[^=]/],
  ["insertAdjacentHTML", /\.insertAdjacentHTML\s*\(/],
  ["document.write(ln)", /\bdocument\.write(?:ln)?\s*\(/],
  ["iframe srcdoc", /srcdoc\s*=\s*[{"']/],
  ["createContextualFragment", /createContextualFragment\s*\(/],
];

const frontendSrc = path.resolve(__dirname, "..", "..", "frontend", "src");
const sharedRendererRelative = path.join("lib", "visualArtifactRenderer.tsx");

function listSourceFiles(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) {
      found.push(...listSourceFiles(full));
    } else if (/\.(tsx?|jsx?)$/.test(entry)) {
      found.push(full);
    }
  }
  return found;
}

test("model-authored visual markup has exactly one executable sink: the shared renderer", () => {
  const sharedRenderer = path.join(frontendSrc, sharedRendererRelative);
  // The boundary itself must exist; deleting it must fail loudly here.
  expect(() => readFileSync(sharedRenderer, "utf8")).not.toThrow();

  const offenders = listSourceFiles(frontendSrc)
    .filter((file) => path.relative(frontendSrc, file) !== sharedRendererRelative)
    .flatMap((file) => {
      const source = readFileSync(file, "utf8");
      return EXECUTABLE_SINK_PATTERNS
        .filter(([, pattern]) => pattern.test(source))
        .map(([name]) => `${path.relative(frontendSrc, file)} uses ${name}`);
    });
  expect(offenders).toEqual([]);
});

test("the sink scan recognizes every sink form it claims to, and no benign read", () => {
  // A contract scan is only evidence if its patterns still match what they
  // claim to match. A future edit that typos one of the regexes above would
  // otherwise keep the spec green while letting that sink form back into the
  // tree — exactly the silent second boundary #768 exists to prevent. So the
  // table is tested against synthetic source lines, both hostile and benign.
  const hostileSamples = [
    "return <div dangerouslySetInnerHTML={{ __html: markup }} />;",
    "el.innerHTML = markup;",
    "el.innerHTML=markup;",
    "el.outerHTML = markup;",
    'el.insertAdjacentHTML("beforeend", markup);',
    "document.write(markup);",
    "document.writeln(markup);",
    "<iframe srcdoc={markup} />",
    '<iframe srcdoc="<script>x<\/script>"></iframe>',
    "range.createContextualFragment(markup);",
  ];
  for (const sample of hostileSamples) {
    const hits = EXECUTABLE_SINK_PATTERNS.filter(([, pattern]) => pattern.test(sample));
    expect(hits.length, `sample must be recognized as a sink: ${sample}`).toBeGreaterThan(0);
  }

  // Reads of serialized DOM (committing a contentEditable's own HTML for
  // sanitization, asserting in tests) are not sinks and must not be flagged.
  const benignSamples = [
    "commitMarkup(target.innerHTML);",
    "const html = await preview.innerHTML();",
    "if (el.innerHTML === markup) return;",
    "markup !== prev.innerHTML",
  ];
  for (const sample of benignSamples) {
    const hits = EXECUTABLE_SINK_PATTERNS.filter(([, pattern]) => pattern.test(sample));
    expect(hits.length, `benign sample must not be flagged: ${sample}`).toEqual(0);
  }
});

test("every HTML/SVG-capable Design Studio surface consumes the shared renderer", () => {
  for (const relative of [
    path.join("pages", "DeckBuilder.tsx"),
    path.join("pages", "DesignStudio.tsx"),
    path.join("pages", "FixedPageArtifactEditor.tsx"),
  ]) {
    const source = readFileSync(path.join(frontendSrc, relative), "utf8");
    expect(
      source.includes("visualArtifactRenderer"),
      `${relative} must render model-authored markup through the shared visual artifact renderer`,
    ).toBe(true);
  }
});
