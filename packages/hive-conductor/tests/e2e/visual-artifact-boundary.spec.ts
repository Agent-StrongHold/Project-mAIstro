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
    .filter((file) => /dangerouslySetInnerHTML\s*=\s*\{/.test(readFileSync(file, "utf8")));
  expect(offenders).toEqual([]);
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
