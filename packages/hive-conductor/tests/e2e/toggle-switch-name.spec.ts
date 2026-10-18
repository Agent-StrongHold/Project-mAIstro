/**
 * The role="switch" toggle announces both its name and its checked state (#1414).
 *
 * #1414 (WCAG 4.1.2 Name, Role, Value): shared.tsx's `Toggle` rendered its
 * label text as a sibling of the `role="switch"` button inside a wrapping
 * `<label>`. The external audit (A11Y-21) observed the switch announcing as
 * an unnamed switch — a screen-reader user tabbing to it learns nothing
 * about what it controls. The fix states the name on the button itself
 * (`aria-label={label}`) and keeps `aria-checked` as the announced state.
 *
 * `Toggle` has zero consumers in the frontend (checked across the tree and
 * full git history), so there is no routed page to drive; this spec mounts
 * the real component source on an ephemeral localhost page — the
 * deck-sanitization.spec.ts harness pattern — and asks the browser's
 * accessibility tree, not the DOM, whether the switch is named and checked.
 *
 * Two things are pinned, because they fail differently:
 * - the announcement: `getByRole` resolves the switch by its label, the
 *   accessible name matches the visible label text (WCAG 2.5.3), and the
 *   checked state tracks clicks;
 * - the mechanism: the button carries `aria-label` itself. Today's browsers
 *   derive a name from the wrapping `<label>` too, so the announcement
 *   assertions alone would pass even with the fix reverted — the attribute
 *   assertion is what catches the regression the audit actually flagged.
 * A nameless raw switch on the same page is asserted to be *rejected* by
 * the same tooling (axe `button-name`), so the harness cannot pass
 * vacuously.
 */

import AxeBuilder from "@axe-core/playwright";
import { build } from "esbuild";
import {
  expect,
  test,
  type Browser,
  type BrowserContext,
  type Page,
} from "@playwright/test";
import { createServer, type Server } from "node:http";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const LABEL = "Autonomous missions";

// CI mounts the repo at /tests (tests/Dockerfile.playwright); locally the
// worktree can point the harness at the real sources instead.
const SRC_ROOT = process.env.E2E_SRC_ROOT || "/tests";
const NODE_PATHS = [process.env.E2E_NODE_PATHS || "/tests/node_modules"];

let context: BrowserContext;
let page: Page;
let server: Server;
let harnessUrl: string;
let workDir: string;

async function startHarness(browser: Browser): Promise<void> {
  workDir = await mkdtemp(join(tmpdir(), "maistro-toggle-"));
  const entry = join(workDir, "toggle-harness.tsx");
  const bundle = join(workDir, "toggle-harness.js");

  await writeFile(
    entry,
    `import React from "react";
import { createRoot } from "react-dom/client";
import { Toggle } from "${SRC_ROOT}/frontend/src/components/shared.tsx";

// Stateful on purpose: the checked state must track clicks, so the harness
// owns real state rather than a frozen boolean.
function ToggleHarness() {
  const [on, setOn] = React.useState(false);
  return (
    <main>
      <p>
        <Toggle checked={on} onChange={setOn} label="${LABEL}" />
      </p>
      {/* The defect shape the tooling must still reject: a switch named by
          nothing at all. Raw element, deliberately not the Toggle. */}
      <button role="switch" aria-checked="true" id="nameless-probe" style={{ width: 28, height: 16 }} />
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<ToggleHarness />);
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
    if (request.url === "/toggle-harness.js") {
      response.writeHead(200, { "content-type": "text/javascript; charset=utf-8" });
      response.end(await readFile(bundle));
      return;
    }
    response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    response.end(
      '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Toggle test</title></head>' +
        '<body><div id="root"></div><script src="/toggle-harness.js"></script></body></html>',
    );
  });

  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve());
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Toggle harness did not bind a TCP port");
  }
  harnessUrl = `http://127.0.0.1:${address.port}`;

  // AxeBuilder refuses a page whose context it did not see created.
  context = await browser.newContext();
  page = await context.newPage();
}

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ browser }) => {
  await startHarness(browser);
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });
});

test.afterAll(async () => {
  await context?.close();
  await new Promise<void>((resolve) => server?.close(() => resolve()));
  if (workDir) await rm(workDir, { recursive: true, force: true });
});

test("the switch is named, by its own aria-label", async () => {
  const toggle = page.getByRole("switch", { name: LABEL, exact: true });
  await expect(toggle).toBeVisible();
  // The accessible name is the visible label text: a voice-control user
  // saying what they can see reaches the switch (WCAG 2.5.3, label in name).
  await expect(toggle).toHaveAccessibleName(LABEL);
  // ... and it is stated on the button itself, not borrowed from the
  // wrapping label's implicit association: React omits aria-label when the
  // value is undefined, so reverting the #1414 fix fails here even in an
  // engine that would still announce a borrowed name.
  await expect(toggle).toHaveAttribute("aria-label", LABEL);
});

test("the switch announces its checked state, and clicks flip it", async () => {
  const toggle = page.getByRole("switch", { name: LABEL, exact: true });
  await expect(toggle).not.toBeChecked();
  await toggle.click();
  await expect(toggle).toBeChecked();
  await toggle.click();
  await expect(toggle).not.toBeChecked();
  // The accessibility tree, not just the DOM attribute: the snapshot is what
  // a screen reader reads, and it must carry name and state together.
  await expect(toggle).toHaveAccessibleName(LABEL);
});

test("the harness rejects an unnamed switch", async () => {
  // Non-vacuity guard: the same page holds a raw switch named by nothing.
  // If the name-resolution assertions above ever loosen, this proves the
  // setup can still tell named from unnamed.
  await expect(page.locator("#nameless-probe")).toBeVisible();
  const results = await new AxeBuilder({ page }).withRules(["button-name"]).analyze();
  const offenders = results.violations
    .filter((violation) => violation.id === "button-name")
    .flatMap((violation) => violation.nodes.map((node) => node.target.join(" ")));
  expect(offenders).toEqual(["#nameless-probe"]);
});
