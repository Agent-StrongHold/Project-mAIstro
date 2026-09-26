/**
 * Browser-level security proof for Deck Builder's untrusted markup boundary (#752).
 *
 * #769 lifted the M0 /decks route containment once this sanitizer landed, so the
 * shipped SPA now exposes Deck Builder. This spec deliberately keeps bundling
 * the exact DeckBuilder.tsx + deckSanitizer.ts sources onto an ephemeral
 * localhost page: it isolates the untrusted-markup boundary from auth, setup
 * state, and routing, and proves the real component, React event path, browser
 * HTML parser, presentation mode, and HTML export against attacker payload
 * families. The keyboard journeys (design-studio-keyboard.spec.ts) cover
 * the routed /decks and /cli/canvas surfaces on top of this boundary proof.
 */

import { build } from "esbuild";
import {
  expect,
  test,
  type Browser,
  type BrowserContext,
  type Download,
  type Page,
} from "@playwright/test";
import { createServer, type Server } from "node:http";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const ATTACKER = "attacker.invalid";

// CI mounts the repo at /tests (tests/Dockerfile.playwright); locally the
// worktree can point the harness at the real sources instead.
const SRC_ROOT = process.env.E2E_SRC_ROOT || "/tests";
const NODE_PATHS = [process.env.E2E_NODE_PATHS || "/tests/node_modules"];

let context: BrowserContext;
let page: Page;
let server: Server;
let harnessUrl: string;
let workDir: string;
let chatReply = "<slide><h1>Safe slide</h1></slide>";
let attackerRequests: string[] = [];

async function readDownload(download: Download): Promise<string> {
  const path = await download.path();
  if (!path) throw new Error("Playwright did not expose the downloaded Deck HTML path");
  return readFile(path, "utf8");
}

async function startHarness(browser: Browser): Promise<void> {
  workDir = await mkdtemp(join(tmpdir(), "maistro-deck-"));
  const entry = join(workDir, "deck-harness.tsx");
  const bundle = join(workDir, "deck-harness.js");

  await writeFile(
    entry,
    `import React from "react";
import { createRoot } from "react-dom/client";
import DeckBuilder from "${SRC_ROOT}/frontend/src/pages/DeckBuilder.tsx";
import FixedPageArtifactEditor from "${SRC_ROOT}/frontend/src/pages/FixedPageArtifactEditor.tsx";
import { sanitizeDeckMarkup } from "${SRC_ROOT}/frontend/src/lib/deckSanitizer.ts";
import { sanitizeVisualArtifactMarkup, scanVisualArtifactMarkup } from "${SRC_ROOT}/frontend/src/lib/visualArtifactRenderer.tsx";

declare global {
  interface Window { __sanitizeDeckMarkup: (markup: string) => string; __sanitizeVisualArtifactMarkup: (markup: string) => string; __scanVisualArtifactMarkup: (markup: string) => { blocked: boolean; reasons: string[]; sanitizedMarkup: string }; __deckPwned?: number; }
}
window.__sanitizeDeckMarkup = sanitizeDeckMarkup;
window.__sanitizeVisualArtifactMarkup = sanitizeVisualArtifactMarkup;
window.__scanVisualArtifactMarkup = scanVisualArtifactMarkup;
const params = new URLSearchParams(window.location.search);
const mode = params.get("mode");
const hostile = "<h1>Safe fixed page</h1><script>window.__deckPwned=20</script><img src=\\\"http://${ATTACKER}/fixed\\\" onerror=\\\"window.__deckPwned=21\\\"><svg><foreignObject><iframe src=\\\"http://${ATTACKER}/fixed-frame\\\"></iframe></foreignObject><circle cx=\\\"10\\\" cy=\\\"10\\\" r=\\\"8\\\" fill=\\\"#b15b3e\\\" onload=\\\"window.__deckPwned=22\\\"></circle></svg><div style=\\\"background-image:url(http://${ATTACKER}/fixed-css);color:#17202a\\\">safe text</div>";
createRoot(document.getElementById("root")!).render(
  mode ? <FixedPageArtifactEditor mode={mode as "poster" | "infographic" | "flyer"} initialMarkup={params.has("hostile") ? hostile : undefined} /> : <DeckBuilder />,
);
`,
    "utf8",
  );

  await build({
    entryPoints: [entry],
    outfile: bundle,
    bundle: true,
    platform: "browser",
    format: "iife",
    jsx: "automatic",
    define: { "process.env.NODE_ENV": '"test"' },
    nodePaths: NODE_PATHS,
    logLevel: "silent",
  });

  server = createServer(async (request, response) => {
    if (request.method === "POST" && request.url === "/v1/chat/complete") {
      for await (const _chunk of request) {
        // body intentionally ignored; the browser path is what this spec owns
      }
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ choices: [{ message: { content: chatReply } }] }));
      return;
    }

    if (request.url === "/deck-harness.js") {
      response.writeHead(200, { "content-type": "text/javascript; charset=utf-8" });
      response.end(await readFile(bundle));
      return;
    }

    response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    response.end(
      '<!doctype html><html><head><meta charset="utf-8"><title>Deck test</title></head>' +
        '<body><div id="root"></div><script src="/deck-harness.js"></script></body></html>',
    );
  });

  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve());
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Deck harness did not bind a TCP port");
  }
  harnessUrl = `http://127.0.0.1:${address.port}`;

  context = await browser.newContext();
  page = await context.newPage();
  page.on("request", (request) => {
    if (request.url().includes(ATTACKER)) attackerRequests.push(request.url());
  });
  await page.addInitScript(() => {
    (window as Window & { __deckPwned?: number }).__deckPwned = 0;
  });
}

async function loadFresh(): Promise<void> {
  attackerRequests = [];
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });
  await expect(page.getByPlaceholder(/Describe slides to generate/)).toBeVisible();
}

async function loadFixedFresh(mode: "poster" | "infographic" | "flyer", hostile = true): Promise<void> {
  attackerRequests = [];
  await page.goto(`${harnessUrl}?mode=${mode}${hostile ? "&hostile=1" : ""}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("fixed-page-editor")).toBeVisible();
}

async function generate(reply: string): Promise<void> {
  chatReply = reply;
  const prompt = page.getByPlaceholder(/Describe slides to generate/);
  await prompt.fill("Generate the security test slide");
  await page.getByRole("button", { name: "Generate" }).click();
  await expect(prompt).toHaveValue("");
}

async function putCaretAtEnd(locator: ReturnType<Page["locator"]>): Promise<void> {
  await locator.evaluate((element) => {
    const range = document.createRange();
    range.selectNodeContents(element);
    range.collapse(false);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  });
}

function expectNoExecutableMarkup(html: string, allowTrustedDocumentMeta = false): void {
  expect(html).not.toMatch(
    /<\s*(?:script|iframe|form|img|object|embed|link|base|foreignObject|use|animate|image|a)\b/i,
  );
  if (allowTrustedDocumentMeta) {
    expect(html).not.toMatch(/<meta\b[^>]*(?:http-equiv|content\s*=)/i);
  } else {
    expect(html).not.toMatch(/<meta\b/i);
  }
  expect(html).not.toMatch(/\son[a-z]+\s*=/i);
  expect(html).not.toMatch(
    /(?:javascript|vbscript|data|blob|file|filesystem|ftp|https?|wss?|ws|about|mailto|tel|cid)\s*:/i,
  );
  expect(html).not.toMatch(/url\s*\(/i);
  expect(html).not.toContain(ATTACKER);
}

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ browser }) => {
  await startHarness(browser);
});

test.afterAll(async () => {
  await context.close();
  await new Promise<void>((resolve, reject) =>
    server.close((error) => (error ? reject(error) : resolve())),
  );
  await rm(workDir, { recursive: true, force: true });
});

test("model-authored HTML/SVG is sanitized before preview and presentation render", async () => {
  await loadFresh();
  const hostile = `<slide index="1">
    <h1>Safe deck content</h1>
    <script>window.__deckPwned = 1</script>
    <img src="http://${ATTACKER}/pixel" onerror="window.__deckPwned = 2">
    <a href="javascript:window.__deckPwned=3">navigate</a>
    <iframe src="http://${ATTACKER}/frame"></iframe>
    <form action="http://${ATTACKER}/submit"><input name="secret"></form>
    <div style="background-image:url(http://${ATTACKER}/css);color:rgb(255,0,0)">CSS survivor</div>
    <svg viewBox="0 0 20 20" width="20" height="20">
      <foreignObject><iframe src="http://${ATTACKER}/svg-frame"></iframe></foreignObject>
      <circle cx="10" cy="10" r="8" fill="#a78bfa" onload="window.__deckPwned=4" />
    </svg>
  </slide>`;

  await generate(hostile);

  const preview = page.locator('[contenteditable="true"]');
  await expect(preview).toContainText("Safe deck content");
  await expect(preview.locator("svg circle")).toHaveCount(1);
  await expect(preview.locator("script, img, a, iframe, form, foreignObject")).toHaveCount(0);
  const previewHtml = await preview.innerHTML();
  expectNoExecutableMarkup(previewHtml);
  expect(previewHtml).toContain("color: rgb(255, 0, 0)");
  expect(
    await page.evaluate(() => (window as Window & { __deckPwned?: number }).__deckPwned),
  ).toBe(0);
  expect(attackerRequests).toEqual([]);

  await page.getByRole("button", { name: "Present" }).click();
  const exit = page.getByRole("button", { name: "Exit (Esc)" });
  await expect(exit).toBeVisible();
  const presentation = exit.locator("..");
  await expect(presentation).toContainText("Safe deck content");
  await expect(presentation.locator("svg circle")).toHaveCount(1);
  const presentationHtml = await presentation.innerHTML();
  expectNoExecutableMarkup(presentationHtml);
  expect(
    await page.evaluate(() => (window as Window & { __deckPwned?: number }).__deckPwned),
  ).toBe(0);
  expect(attackerRequests).toEqual([]);
});

test("rich paste and drop are sanitized before browser insertion, then export stays safe", async () => {
  await loadFresh();
  const preview = page.locator('[contenteditable="true"]');
  await expect(preview).toBeVisible();
  await preview.focus();
  await putCaretAtEnd(preview);

  const pasteHostile = `<h2>Edited safely</h2><img src="http://${ATTACKER}/paste" onerror="window.__deckPwned=5"><svg><foreignObject><script>window.__deckPwned=6</script></foreignObject><rect width="10" height="10" fill="#fff"></rect></svg>`;
  const pastePrevented = await preview.evaluate((element, payload) => {
    const transfer = new DataTransfer();
    transfer.setData("text/html", payload);
    transfer.setData("text/plain", "Edited safely");
    return !element.dispatchEvent(new ClipboardEvent("paste", {
      bubbles: true,
      cancelable: true,
      clipboardData: transfer,
    }));
  }, pasteHostile);

  expect(pastePrevented).toBe(true);
  await expect(preview).toContainText("Edited safely");
  await expect(preview.locator("img, foreignObject, script")).toHaveCount(0);
  expectNoExecutableMarkup(await preview.innerHTML());
  expect(attackerRequests).toEqual([]);

  await putCaretAtEnd(preview);
  const dragOverPrevented = await preview.evaluate((element) => {
    const transfer = new DataTransfer();
    transfer.setData("text/uri-list", "http://attacker.invalid/dragover");
    return !element.dispatchEvent(new DragEvent("dragover", {
      bubbles: true,
      cancelable: true,
      dataTransfer: transfer,
    }));
  });
  expect(dragOverPrevented).toBe(true);

  const dropHostile = `<strong>Dropped safely</strong><iframe src="http://${ATTACKER}/drop"></iframe><a href="javascript:window.__deckPwned=8">bad</a>`;
  const dropPrevented = await preview.evaluate((element, payload) => {
    const transfer = new DataTransfer();
    transfer.setData("text/html", payload);
    transfer.setData("text/plain", "Dropped safely");
    transfer.setData("text/uri-list", "http://attacker.invalid/navigate");
    return !element.dispatchEvent(new DragEvent("drop", {
      bubbles: true,
      cancelable: true,
      dataTransfer: transfer,
    }));
  }, dropHostile);

  expect(dropPrevented).toBe(true);
  await expect(preview).toContainText("Dropped safely");
  await expect(preview.locator("iframe, a")).toHaveCount(0);
  expectNoExecutableMarkup(await preview.innerHTML());
  expect(attackerRequests).toEqual([]);

  // The title used to be interpolated raw into the exported <title> element.
  await page.locator("input").first().fill('</title><script>window.__deckPwned=7</script><title>');
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export HTML" }).click();
  const exported = await readDownload(await downloadPromise);

  expect(exported).toContain("Edited safely");
  expect(exported).toContain("Dropped safely");
  expect(exported).toContain("&lt;/title&gt;");
  expectNoExecutableMarkup(exported, true);
  expect(
    await page.evaluate(() => (window as Window & { __deckPwned?: number }).__deckPwned),
  ).toBe(0);
  expect(attackerRequests).toEqual([]);
});

test("edited DOM is sanitized again before it can become stored slide state", async () => {
  await loadFresh();
  const preview = page.locator('[contenteditable="true"]');
  await preview.focus();
  const htmlAfterBlur = await preview.evaluate((element) => {
    // Model the browser DOM after an edit/undo operation. The production blur
    // handler must treat this DOM as untrusted before copying it into state.
    element.innerHTML =
      '<h2>Edited through the DOM</h2><script>window.__deckPwned=16</script>' +
      '<img onerror="window.__deckPwned=17">';
    element.blur();
    // Return the DOM immediately, before a later assertion could hide a
    // boundary failure behind React's state update.
    return element.innerHTML;
  });

  expectNoExecutableMarkup(htmlAfterBlur);
  await expect(preview).toContainText("Edited through the DOM");
  await expect(preview.locator("script, img")).toHaveCount(0);
  expectNoExecutableMarkup(await preview.innerHTML());
  expect(
    await page.evaluate(() => (window as Window & { __deckPwned?: number }).__deckPwned),
  ).toBe(0);

  await page.getByRole("button", { name: "Present" }).click();
  const exit = page.getByRole("button", { name: "Exit (Esc)" });
  await expect(exit.locator("..")).toContainText("Edited through the DOM");
  await expect(exit.locator("..").locator("script, img")).toHaveCount(0);
  expect(attackerRequests).toEqual([]);
});

test("malformed stored values fail closed at the shared Deck boundary", async () => {
  await loadFresh();
  const outputs = await page.evaluate(() => {
    const sanitize = (
      window as Window & { __sanitizeDeckMarkup: (markup: unknown) => string }
    ).__sanitizeDeckMarkup;
    return [null, 42, {}, ["<script>bad</script>"]].map((value) => sanitize(value));
  });
  expect(outputs).toEqual(["", "", "", ""]);
  expect(attackerRequests).toEqual([]);
});

test("mutation, encoded, SVG, and CSS payload families fail closed while presentation markup survives", async () => {
  await loadFresh();
  const payloads = [
    '<svg><g/onload=window.__deckPwned=10//<p>safe</p></svg>',
    '<math><mtext><img src=x onerror=window.__deckPwned=11></mtext></math><strong>safe</strong>',
    '<a href="jav&#x61;script:window.__deckPwned=12">bad</a><em>safe</em>',
    '<svg><use href="http://attacker.invalid/icon#x"></use><image href="data:text/html,<script>alert(1)</script>"></image><circle cx="5" cy="5" r="4" fill="blob:http://attacker.invalid/id" stroke="ftp://attacker.invalid/line"></circle></svg>',
    '<div style="background:url(\\6a avascript:alert(1));color:#fff">safe</div>',
    '<div style="background-image:image-set(url(http://attacker.invalid/a) 1x);font-size:20px">safe</div>',
    '<style>@import url(http://attacker.invalid/x);</style><p>safe</p>',
    '<iframe srcdoc="<script>window.__deckPwned=13<\/script>"></iframe><u>safe</u>',
    '<meta http-equiv="refresh" content="0;url=http://attacker.invalid/refresh"><small>safe</small>',
  ];

  const outputs = await page.evaluate((items) => {
    const sanitize = (
      window as Window & { __sanitizeDeckMarkup: (markup: string) => string }
    ).__sanitizeDeckMarkup;
    return items.map((item) => sanitize(item));
  }, payloads);

  for (const output of outputs) expectNoExecutableMarkup(output);
  expect(outputs.join(" ")).toContain("safe");

  const scanResults = await page.evaluate((items) => {
    const scan = (
      window as Window & { __scanVisualArtifactMarkup: (markup: string) => { blocked: boolean; reasons: string[]; sanitizedMarkup: string } }
    ).__scanVisualArtifactMarkup;
    return items.slice(0, 3).map((item) => scan(item));
  }, [
    '<div onclick="alert(1)">handler</div>',
    '<a href="data:text/html,<script>alert(1)</script>">navigation</a>',
    '<div style="background-image:url(http://attacker.invalid/css)">network</div>',
  ]);
  expect(scanResults.every((result) => result.blocked)).toBe(true);
  expect(scanResults[0].reasons).toContain("event-handler");
  expect(scanResults[1].reasons.length).toBeGreaterThan(0);
  expect(scanResults[2].reasons).toContain("css-network-or-code");

  // Read the recommendation from the shipped fixed-page component, not a
  // test-harness global. This exercises the production trust check against the
  // same initial/persisted content path as preview and export.
  await loadFixedFresh("poster");
  await expect(page.getByTestId("fixed-page-editor")).toHaveAttribute("data-trust-recommendation", "review");
  const fixedPreview = page.locator('[contenteditable="true"]');
  await fixedPreview.focus();
  await putCaretAtEnd(fixedPreview);
  await fixedPreview.evaluate((element) => {
    const transfer = new DataTransfer();
    transfer.setData("text/html", "<p>Safe replacement</p>");
    element.dispatchEvent(new ClipboardEvent("paste", {
      bubbles: true,
      cancelable: true,
      clipboardData: transfer,
    }));
  });
  await expect(page.getByTestId("fixed-page-editor")).toHaveAttribute("data-trust-recommendation", "upgrade");

  const safePresentation = await page.evaluate(() => {
    const sanitize = (
      window as Window & { __sanitizeDeckMarkup: (markup: string) => string }
    ).__sanitizeDeckMarkup;
    return sanitize(
      '<div style="display:flex;background:linear-gradient(135deg,#0f0c29,#302b63);color:#fff"><strong>Portfolio</strong><svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="8" fill="#a78bfa" stroke="#fff" stroke-width="2"></circle></svg></div>',
    );
  });

  expect(safePresentation).toContain("linear-gradient");
  expect(safePresentation).toContain("<strong>Portfolio</strong>");
  expect(safePresentation).toContain("<circle");
  expect(
    await page.evaluate(() => (window as Window & { __deckPwned?: number }).__deckPwned),
  ).toBe(0);
  expect(attackerRequests).toEqual([]);
});

test("CSS obfuscation and active SVG families fail closed in preview and presentation", async () => {
  await loadFresh();
  const hostile = `<slide index="1">
    <div style="background-image:u\\72l(http://${ATTACKER}/css);color:#fff">CSS escape survives as text</div>
    <div style="background-image:/*hidden*/url(http://${ATTACKER}/comment);color:#fff">CSS comment survives as text</div>
    <svg><animate attributeName="x" onbegin="window.__deckPwned=14" /><image href="http://${ATTACKER}/image" /><circle cx="5" cy="5" r="4" fill="#fff" /></svg>
    <a href="jav&#x61;script:window.__deckPwned=15">Encoded navigation</a>
    <object data="http://${ATTACKER}/object"></object><embed src="http://${ATTACKER}/embed"><p>Embedded-safe text</p>
  </slide>`;

  await generate(hostile);

  const preview = page.locator('[contenteditable="true"]');
  await expect(preview).toContainText("CSS escape survives as text");
  await expect(preview).toContainText("CSS comment survives as text");
  await expect(preview).toContainText("Embedded-safe text");
  await expect(
    preview.getByText("CSS comment survives as text", { exact: true }),
  ).not.toHaveAttribute("style");
  await expect(preview.locator("svg circle")).toHaveCount(1);
  await expect(preview.locator("animate, image, object, embed")).toHaveCount(0);
  const previewHtml = await preview.innerHTML();
  expectNoExecutableMarkup(previewHtml);
  expect(previewHtml).toContain("CSS escape survives as text");
  expect(previewHtml).toContain("CSS comment survives as text");
  expect(attackerRequests).toEqual([]);
  expect(
    await page.evaluate(() => (window as Window & { __deckPwned?: number }).__deckPwned),
  ).toBe(0);

  await page.getByRole("button", { name: "Present" }).click();
  const exit = page.getByRole("button", { name: "Exit (Esc)" });
  await expect(exit).toBeVisible();
  const presentation = exit.locator("..");
  await expect(presentation).toContainText("CSS escape survives as text");
  await expect(presentation).toContainText("CSS comment survives as text");
  await expect(
    presentation.getByText("CSS comment survives as text", { exact: true }),
  ).not.toHaveAttribute("style");
  await expect(presentation.locator("svg circle")).toHaveCount(1);
  await expect(presentation.locator("animate, image, object, embed")).toHaveCount(0);
  const presentationHtml = await presentation.innerHTML();
  expectNoExecutableMarkup(presentationHtml);
  expect(presentationHtml).toContain("CSS escape survives as text");
  expect(presentationHtml).toContain("CSS comment survives as text");
  expect(attackerRequests).toEqual([]);
  expect(
    await page.evaluate(() => (window as Window & { __deckPwned?: number }).__deckPwned),
  ).toBe(0);
});

test("all built-in Deck templates remain renderable through the sanitizer", async () => {
  await loadFresh();
  const preview = page.locator('[contenteditable="true"]');
  const templates = [
    { button: /Hero KPI/, text: "Portfolio Snapshot" },
    { button: /Status Funnel/, text: "Lifecycle Funnel" },
    { button: /Category Mix/, text: "Automations & Agents" },
    { button: /Migration Progress/, text: "Platform v2 Migration" },
    { button: /PM Load/, text: "PM Workload Distribution" },
    { button: /Record List/, text: "Closest to Migration" },
    { button: /Title Slide/, text: "Use Case Portfolio Health" },
    { button: /Thank You/, text: "Thank You" },
  ];

  for (const template of templates) {
    await page.getByRole("button", { name: template.button }).click();
    await expect(preview).toContainText(template.text);
    const html = await preview.innerHTML();
    expect(html).toContain("style");
    expectNoExecutableMarkup(html);
  }
  expect(attackerRequests).toEqual([]);
});

test("poster, infographic, and flyer use the shared boundary for preview, edit, and export", async () => {
  for (const mode of ["poster", "infographic", "flyer"] as const) {
    await loadFixedFresh(mode);
    const preview = page.locator('[contenteditable="true"]');
    await expect(preview).toContainText("Safe fixed page");
    await expect(preview.locator("script, img, iframe, foreignObject")).toHaveCount(0);
    expectNoExecutableMarkup(await preview.innerHTML());

    await preview.focus();
    await putCaretAtEnd(preview);
    const pastePrevented = await preview.evaluate((element, currentMode) => {
      const transfer = new DataTransfer();
      transfer.setData("text/html", `<strong>Edited ${currentMode}</strong><img src="http://attacker.invalid/edit">`);
      return !element.dispatchEvent(new ClipboardEvent("paste", {
        bubbles: true,
        cancelable: true,
        clipboardData: transfer,
      }));
    }, mode);
    expect(pastePrevented).toBe(true);
    await expect(preview).toContainText(`Edited ${mode}`);
    expectNoExecutableMarkup(await preview.innerHTML());

    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export HTML" }).click();
    const exported = await readDownload(await downloadPromise);
    expect(exported).toContain(`Edited ${mode}`);
    expectNoExecutableMarkup(exported, true);
    expect(attackerRequests).toEqual([]);
  }

  await loadFixedFresh("infographic", false);
  const safeTemplate = page.locator('[contenteditable="true"]');
  await expect(safeTemplate).toContainText("One clear idea");
  await expect(safeTemplate.locator("svg circle")).toHaveCount(2);
  expectNoExecutableMarkup(await safeTemplate.innerHTML());
});
