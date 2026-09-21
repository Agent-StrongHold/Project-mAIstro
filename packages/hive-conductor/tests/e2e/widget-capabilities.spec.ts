/**
 * Browser-level security proof for the dashboard widget capability boundary (#314).
 *
 * Like the deck spec beside it, this bundles the exact shipped Dashboard.tsx +
 * widgetCapabilities.ts into the Playwright image and mounts them on an
 * ephemeral localhost page. A canned /v1/dashboard/layout, a scripted
 * /v1/chat/stream, and request recording on the harness server let the spec
 * prove the issue's Definition of Done directly: hostile model output cannot
 * turn widget configuration into an authenticated request primitive — no
 * model-authored configuration reaches a generic fetch, and persisted unsafe
 * configs are sanitized before use.
 */

import { build } from "esbuild";
import {
  expect,
  test,
  type Browser,
  type BrowserContext,
  type Page,
} from "@playwright/test";
import { createServer, type Server } from "node:http";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
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

/** Configurable model reply for POST /v1/chat/stream. */
let chatReply = "ok";

/** Every request the page issued, in order, for provenance assertions. */
let pageRequests: string[] = [];
/** Every PUT /v1/dashboard/layout body, parsed. */
let savedLayouts: any[] = [];
/** The canned server layout handed to the SPA on load. */
let cannedLayout: Record<string, unknown> = {
  tabs: [
    {
      name: "Overview",
      widgets: [
        {
          id: "w-1",
          type: "custom",
          title: "Pipeline",
          size: "3",
          config: { source: "airtable", table: "Use Cases", field: "Status" },
        },
        {
          id: "kpi-1",
          type: "kpi",
          title: "Runs",
          size: "1",
          config: { field: "runs_today", sub: "today" },
        },
      ],
    },
  ],
  activeTab: 0,
};

async function startHarness(browser: Browser): Promise<void> {
  workDir = await mkdtemp(join(tmpdir(), "maistro-widget-"));
  const entry = join(workDir, "widget-harness.tsx");
  const bundle = join(workDir, "widget-harness.js");

  await writeFile(
    entry,
    `import React from "react";
import { createRoot } from "react-dom/client";
import Dashboard from ${JSON.stringify(`${SRC_ROOT}/frontend/src/pages/Dashboard.tsx`)};

createRoot(document.getElementById("root")!).render(<Dashboard />);
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
    // The shipped sources read Vite's `import.meta.env` in a module context;
    // define the subpaths they touch so the bundle runs without Vite.
    define: {
      "process.env.NODE_ENV": '"test"',
      "import.meta.env.DEV": "false",
      "import.meta.env.VITE_DEBUG_API": '"false"',
      "import.meta.env.VITE_JIRA_BASE_URL": '""',
    },
    nodePaths: NODE_PATHS,
    logLevel: "silent",
  });

  const sse = (content: string) =>
    `data: ${JSON.stringify({ type: "done", content })}\n\n`;

  server = createServer(async (request, response) => {
    const url = request.url || "/";
    const path = url.split("?")[0];

    if (request.method === "POST" && path === "/v1/chat/stream") {
      for await (const _chunk of request) {
        // body ignored; the scripted reply below is the model's answer
      }
      response.writeHead(200, { "content-type": "text/event-stream" });
      response.end(sse(chatReply));
      return;
    }

    if (request.method === "PUT" && path === "/v1/dashboard/layout") {
      const chunks: Buffer[] = [];
      for await (const chunk of request) chunks.push(chunk as Buffer);
      try {
        savedLayouts.push(JSON.parse(Buffer.concat(chunks).toString("utf8")));
      } catch {
        savedLayouts.push(null);
      }
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ ok: true, revision: 1 }));
      return;
    }

    if (request.method === "GET" && path === "/v1/dashboard/layout") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify(cannedLayout));
      return;
    }

    if (path === "/v1/agents") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end("[]");
      return;
    }

    if (path === "/v1/dashboard/metrics") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ count: 3, latency_ms_p50: 12 }));
      return;
    }

    if (path === "/v1/setup-checklist") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ items: [] }));
      return;
    }

    // Named widget capability routes — the only data paths a widget may use.
    if (path === "/v1/widgets/airtable") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(
        JSON.stringify({ breakdown: { Development: 4, Open: 2 }, total: 6 }),
      );
      return;
    }

    if (path === "/v1/widgets/metrics") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ value: 9, unit: "runs" }));
      return;
    }

    if (path === "/widget-harness.js") {
      response.writeHead(200, { "content-type": "text/javascript; charset=utf-8" });
      response.end(await import("node:fs/promises").then((m) => m.readFile(bundle)));
      return;
    }

    if (path === "/" || path === "/index.html") {
      response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      response.end(
        '<!doctype html><html><head><meta charset="utf-8"><title>Widget test</title></head>' +
          '<body><div id="root"></div><script type="module" src="/widget-harness.js"></script></body></html>',
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
    throw new Error("Widget harness did not bind a TCP port");
  }
  harnessUrl = `http://127.0.0.1:${address.port}`;

  context = await browser.newContext();
  page = await context.newPage();
  page.on("request", (request) => pageRequests.push(request.url()));
}

async function loadFresh(expectedTitle = "Pipeline"): Promise<void> {
  pageRequests = [];
  savedLayouts = [];
  chatReply = "ok";
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });
  await expect(page.getByText(expectedTitle)).toBeVisible();
}

async function chat(content: string): Promise<void> {
  chatReply = content;
  const input = page.locator("input[placeholder*='Ask'], input[placeholder*='Build']").first();
  await input.fill("apply the model's suggested changes");
  await input.press("Enter");
  // The reply renders in the chat transcript once the stream completes.
  await expect(page.getByText("apply the model's suggested changes").last()).toBeVisible();
  await page.waitForTimeout(250); // let widget effects and the layout save settle
}

function lastSavedConfigOf(widgetId: string): Record<string, unknown> {
  const layout = savedLayouts[savedLayouts.length - 1];
  expect(layout, "the SPA must have persisted a layout").toBeTruthy();
  const widgets = (layout.tabs || []).flatMap((t: any) => t.widgets || []);
  const widget = widgets.find((w: any) => w.id === widgetId);
  expect(widget, `widget ${widgetId} should survive`).toBeTruthy();
  return widget.config || {};
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

test("hostile widget_update cannot install an authenticated request primitive", async () => {
  await loadFresh();
  await chat(
    "Here is your change:\n\n```widget_update\n" +
      JSON.stringify({
        action: "update",
        id: "w-1",
        changes: {
          title: "Hostile",
          size: "6",
          config: {
            endpoint: "/v1/settings",
            method: "DELETE",
            params: { admin: "true" },
            headers: { "X-Evil": "1" },
            body: { boom: true },
            credentials: "include",
            url: `http://${ATTACKER}/exfil`,
            source: "airtable",
            table: "Use Cases",
          },
        },
      }) +
      "\n```",
  );

  const config = lastSavedConfigOf("w-1");
  // No request primitive survives into the applied/persisted configuration.
  for (const key of ["endpoint", "method", "params", "headers", "body", "credentials", "url"]) {
    expect(config, `config.${key} must not survive`).not.toHaveProperty(key);
  }
  // Declarative fields do survive.
  expect(config).toMatchObject({ source: "airtable", table: "Use Cases" });

  // And nothing hostile was ever requested.
  const paths = pageRequests.map((u) => new URL(u).pathname + new URL(u).search);
  expect(pageRequests.filter((u) => u.includes(ATTACKER))).toEqual([]);
  expect(paths.filter((p) => p.startsWith("/v1/settings"))).toEqual([]);
});

test("benign declarative updates apply and fetch only named capabilities", async () => {
  await loadFresh();
  await chat(
    "```widget_update\n" +
      JSON.stringify({
        action: "update",
        id: "w-1",
        changes: { config: { source: "airtable", table: "Use Cases", field: "Status" } },
      }) +
      "\n```",
  );

  const config = lastSavedConfigOf("w-1");
  expect(config).toMatchObject({ source: "airtable", table: "Use Cases", field: "Status" });

  // The widget fetched its data through the named server-side capability.
  expect(
    pageRequests.filter((u) => new URL(u).pathname === "/v1/widgets/airtable").length,
  ).toBeGreaterThan(0);
  const paths = pageRequests.map((u) => new URL(u).pathname);
  const allowed = new Set([
    "/",
    "/widget-harness.js",
    "/v1/dashboard/layout",
    "/v1/agents",
    "/v1/dashboard/metrics",
    "/v1/setup-checklist",
    "/v1/chat/stream",
    "/v1/widgets/airtable",
    "/v1/widgets/metrics",
  ]);
  const unexpected = paths.filter(
    (p) => !allowed.has(p) && !p.startsWith("/v1/widgets/"),
  );
  expect(unexpected).toEqual([]);
});

test("encoded traversal and unknown fields are rejected, not applied", async () => {
  await loadFresh();
  await chat(
    "```widget_update\n" +
      JSON.stringify({
        action: "update",
        id: "w-1",
        changes: {
          config: {
            table: "%2e%2e%2f../../admin",
            source: "https://evil.invalid",
            mystery_field: "x",
          },
        },
      }) +
      "\n```",
  );

  // The update's config sanitized to nothing declarative, so it was rejected
  // — the widget keeps its working config rather than being blanked.
  const config = lastSavedConfigOf("w-1");
  expect(JSON.stringify(config)).not.toContain("%2e%2e");
  expect(JSON.stringify(config)).not.toContain("evil.invalid");
  expect(JSON.stringify(config)).not.toContain("mystery_field");

  const paths = pageRequests.map((u) => new URL(u).pathname + new URL(u).search);
  expect(paths.filter((p) => p.includes("admin"))).toEqual([]);
});

test("remove actions still require explicit confirmation", async () => {
  await loadFresh();
  let confirmShown = false;
  page.once("dialog", async (dialog) => {
    confirmShown = dialog.type() === "confirm";
    await dialog.dismiss(); // the user says no
  });

  await chat(
    "```widget_update\n" +
      JSON.stringify({ action: "remove", id: "w-1" }) +
      "\n```",
  );

  expect(confirmShown).toBe(true);
  await expect(page.getByText("Pipeline")).toBeVisible(); // declined: still there
});

test("persisted unsafe layout is sanitized before use", async () => {
  // A hostile config that somehow persisted (pre-boundary layout) is handed
  // back by the server. It must not fetch its primitives on load.
  cannedLayout = {
    widgets: [
      {
        id: "w-legacy",
        type: "custom",
        title: "Legacy",
        size: "2",
        config: {
          endpoint: "/v1/settings",
          method: "DELETE",
          url: `http://${ATTACKER}/legacy`,
          credentials: "include",
        },
      },
    ],
  };
  await loadFresh("Legacy");

  await expect(page.getByText("Legacy")).toBeVisible();
  const paths = pageRequests.map((u) => new URL(u).pathname);
  expect(pageRequests.filter((u) => u.includes(ATTACKER))).toEqual([]);
  expect(paths.filter((p) => p.startsWith("/v1/settings"))).toEqual([]);
});
