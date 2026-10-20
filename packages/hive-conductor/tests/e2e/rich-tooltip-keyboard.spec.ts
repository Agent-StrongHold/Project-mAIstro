/**
 * E2E proof for #1413 (WCAG 1.4.13 Content on Hover or Focus): the shared
 * RichTooltip hides on Escape while the trigger keeps focus.
 *
 * RichTooltip has no consumer inside the shipped SPA — the issue's own
 * comment records that, and wiring it in (or retiring it) is a product
 * decision that is deliberately not guessed at here. The component is
 * nevertheless the audit's named surface, so — like the Dashboard and Deck
 * Builder specs — this bundles the exact shipped `RichTooltip.tsx` into an
 * ephemeral localhost page and drives the behavior a real consumer gets the
 * moment it is wired up:
 *
 *   - keyboard focus alone shows the tip (the keyboard path a hover-only
 *     component would deny), and the tip stays shown while focus stays put
 *     (the persistent leg of 1.4.13);
 *   - Escape hides the tip WITHOUT moving focus (the dismissible leg, and
 *     the acceptance check);
 *   - the dismissal latches until the trigger is actually left: a re-hover
 *     while focus is retained does not resurrect it, but leaving and
 *     returning (blur + refocus) shows it again normally;
 *   - Escape with nothing shown is a no-op, and the pointer path
 *     (hover shows, leave hides) is unchanged.
 */

import { build } from "esbuild";
import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { createServer, type Server } from "node:http";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

// CI mounts the repo at /tests (tests/Dockerfile.playwright); locally point
// E2E_SRC_ROOT at the worktree and E2E_NODE_PATHS at ':'-joined module dirs.
const SRC_ROOT = process.env.E2E_SRC_ROOT || "/tests";
const NODE_PATHS = (process.env.E2E_NODE_PATHS || "/tests/node_modules").split(":");

let context: BrowserContext;
let page: Page;
let server: Server;
let harnessUrl: string;
let workDir: string;

const tooltip = () => page.getByRole("tooltip");
const trigger = () => page.getByRole("button", { name: "Trigger" });

async function startHarness(browser: Browser): Promise<void> {
  workDir = await mkdtemp(join(tmpdir(), "maistro-tip-"));
  const entry = join(workDir, "tooltip-harness.tsx");
  const bundle = join(workDir, "tooltip-harness.js");

  await writeFile(
    entry,
    `import React from "react";
import { createRoot } from "react-dom/client";
import { RichTooltip } from ${JSON.stringify(`${SRC_ROOT}/frontend/src/components/RichTooltip.tsx`)};

createRoot(document.getElementById("root")!).render(
  <RichTooltip content="Rich tooltip content" side="top">
    <button type="button" id="tooltip-trigger">Trigger</button>
  </RichTooltip>,
);
`,
    "utf8",
  );

  await build({
    entryPoints: [entry],
    outfile: bundle,
    bundle: true,
    platform: "browser",
    format: "esm",
    jsx: "automatic",
    define: {
      "process.env.NODE_ENV": '"test"',
    },
    nodePaths: NODE_PATHS,
    logLevel: "silent",
  });

  server = createServer(async (request, response) => {
    const path = (request.url || "/").split("?")[0];

    if (request.method === "GET" && path === "/tooltip-harness.js") {
      response.writeHead(200, { "content-type": "text/javascript; charset=utf-8" });
      response.end(await readFile(bundle));
      return;
    }
    if (request.method === "GET" && (path === "/" || path === "/index.html")) {
      response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      response.end(
        '<!doctype html><html><head><meta charset="utf-8"><title>RichTooltip test</title></head>' +
          '<body><div id="root"></div><script type="module" src="/tooltip-harness.js"></script></body></html>',
      );
      return;
    }
    response.writeHead(404, { "content-type": "application/json" });
    response.end(JSON.stringify({ error: "not found", path }));
  });

  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve());
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("RichTooltip harness did not bind a TCP port");
  }
  harnessUrl = `http://127.0.0.1:${address.port}`;

  context = await browser.newContext();
  page = await context.newPage();
}

async function loadFresh(): Promise<void> {
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });
  await trigger().waitFor({ state: "attached" });
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

test("focus alone shows the tooltip, and it stays shown while focus stays put", async () => {
  await loadFresh();

  await trigger().focus();
  await expect(tooltip()).toBeVisible();

  // The persistent leg of 1.4.13: the tip must not fade out on its own while
  // hover/focus is held. Five times the component's 120 ms show delay is
  // enough to catch a timeout-based hide without pinning wall-clock timing.
  await page.waitForTimeout(600);
  await expect(tooltip()).toBeVisible();
  await expect(trigger()).toBeFocused();
});

test("Escape hides the tooltip while the trigger keeps focus (#1413 acceptance)", async () => {
  await loadFresh();

  await trigger().focus();
  await expect(tooltip()).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(tooltip()).toBeHidden();
  // Dismissing must not cost the user their place: the trigger — not the
  // body, not the removed tooltip — still holds focus.
  await expect(trigger()).toBeFocused();
});

test("dismissal latches until the trigger is actually left, then returns", async () => {
  await loadFresh();

  await trigger().focus();
  await expect(tooltip()).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(tooltip()).toBeHidden();

  // A re-hover while focus is retained must not resurrect the dismissed tip.
  await trigger().hover();
  await page.waitForTimeout(600);
  await expect(tooltip()).toBeHidden();
  await expect(trigger()).toBeFocused();

  // Leaving (blur) resets the latch; returning shows the tip normally again.
  // An explicit blur is what Tab out does — the trigger is the page's only
  // focusable element, so it also keeps this independent of tab order.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await trigger().focus();
  await expect(tooltip()).toBeVisible();
});

test("Escape with nothing shown is a no-op, and the pointer path is unchanged", async () => {
  await loadFresh();

  // Escape while the tip is dismissed-latched: a second Escape is a no-op,
  // not an error and not a show.
  await trigger().focus();
  await expect(tooltip()).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(tooltip()).toBeHidden();
  await page.keyboard.press("Escape");
  await page.waitForTimeout(600);
  await expect(tooltip()).toBeHidden();

  // The pointer path still works after that. Blur first so the dismissal
  // latch resets — the point here is hover/leave, not the latch (pinned
  // above and in the previous test). Move the pointer off first: serial
  // tests share this page's mouse, and an earlier test may have left it on
  // the trigger, where a hover would fire no new mouseenter.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.mouse.move(2, 2);
  await trigger().hover();
  await expect(tooltip()).toBeVisible();
  await page.mouse.move(2, 2);
  await expect(tooltip()).toBeHidden();
});
