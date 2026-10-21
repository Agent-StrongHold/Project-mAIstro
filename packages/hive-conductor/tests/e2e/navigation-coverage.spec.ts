/**
 * Navigation coverage (#1417): every retained shipped surface is reachable
 * from the supported navigation without typing its URL, and every alias or
 * redirect resolves to its canonical surface with exactly one active nav
 * entry. The route/entry-point inventory this spec enforces is
 * `docs/route-inventory.md`.
 *
 * Deliberately not a link-count assertion: the inventory is the contract,
 * and a count alone would pass while hiding an orphaned or mislabeled
 * destination. Each row must exist in BOTH chrome modes (desktop icon rail,
 * narrow-screen drawer), be reachable by keyboard, land on its destination,
 * and leave exactly one active entry bearing its accessible name.
 *
 * Reachability is per principal, matching AppShell's `visibleNav`: the two
 * entries carrying a mutation `scope` (`schedules.write`,
 * `containers.control`) are asserted absent for the setup wizard's daily
 * user (granted only `dags.write`) and walked under the admin account, which
 * `principal_has_permission` passes through every gate.
 */

import { expect, test, type BrowserContext, type Locator, type Page } from "@playwright/test";
import { loginAsAdmin, loginAsPM, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let narrowContext: BrowserContext;
let page: Page;
let narrowPage: Page;
let adminContext: BrowserContext;
let adminNarrowContext: BrowserContext;
let adminPage: Page;
let adminNarrowPage: Page;

/** One row per `fullNav` entry in AppShell.tsx. A label that disappears from
 * the shell fails the visibility step; a destination that fails to render
 * fails the probe; an ambiguous active state fails the single-active check.
 *
 * `scope` marks the two entries AppShell renders conditionally
 * (`visibleNav`): the value mirrors the `AuthMiddleware` mutation gate for
 * that surface (backend/middleware/auth.py `_PROTECTED_OPS`), so the entry
 * is only expected for a principal holding the grant — the setup wizard's
 * admin (every permission) and not the daily user (see
 * DAILY_USER_ENTRIES below). */
const NAV_ENTRIES: Array<{ label: string; path: string; scope?: string; probe: (p: Page) => Locator }> = [
  { label: "Chat", path: "/chat", probe: (p) => p.getByLabel("Chat messages") },
  { label: "Dashboard", path: "/dashboard", probe: (p) => p.getByRole("heading", { name: "Live Operations", exact: true }) },
  { label: "Design Studio", path: "/design-studio", probe: (p) => p.getByRole("heading", { name: "Design Studio", exact: true }) },
  { label: "DAG Builder", path: "/dags", probe: (p) => p.getByRole("heading", { name: "DAG Builder", exact: true }) },
  { label: "DAG Runs", path: "/dag-runs", probe: (p) => p.getByRole("heading", { name: "Live DAG Runs", exact: true }) },
  { label: "Schedules", path: "/schedules", scope: "schedules.write", probe: (p) => p.getByRole("heading", { name: "Schedules", exact: true }) },
  { label: "Missions", path: "/missions", probe: (p) => p.getByRole("heading", { name: "Missions", exact: true }) },
  { label: "Backlog", path: "/backlog", probe: (p) => p.getByRole("heading", { name: "Backlog", exact: true }) },
  { label: "Agents", path: "/agents", probe: (p) => p.getByRole("heading", { name: "The Hive", exact: true }) },
  { label: "Topology", path: "/topology", probe: (p) => p.getByRole("heading", { name: "Topology", exact: true }) },
  { label: "Optimizer", path: "/optimizer", probe: (p) => p.getByRole("heading", { name: "Optimization Inbox", exact: true }) },
  { label: "Messages", path: "/messages", probe: (p) => p.getByRole("heading", { name: "Message Board", exact: true }) },
  { label: "Quotas", path: "/quotas", probe: (p) => p.getByRole("heading", { name: "Quotas & Stats", exact: true }) },
  { label: "Inner Temple", path: "/knowledge", probe: (p) => p.getByRole("heading", { name: "Inner Temple", exact: true }) },
  { label: "RSI", path: "/rsi", probe: (p) => p.getByRole("heading", { name: "RSI — Recursive Self-Improvement", exact: true }) },
  { label: "Integrations", path: "/mcp", probe: (p) => p.getByRole("heading", { name: "MCP", exact: true }) },
  { label: "Containers", path: "/containers", scope: "containers.control", probe: (p) => p.getByRole("heading", { name: "Containers", exact: true }) },
  { label: "CLI", path: "/cli", probe: (p) => p.getByRole("heading", { name: "CLI", exact: true }) },
  { label: "Credentials", path: "/credentials", probe: (p) => p.getByRole("heading", { name: "Integration credentials", exact: true }) },
  { label: "Audit", path: "/audit", probe: (p) => p.getByRole("heading", { name: "Audit Log", exact: true }) },
  { label: "Settings", path: "/settings", probe: (p) => p.getByRole("heading", { name: "Settings", exact: true }) },
];

/** Legacy rows the cutover plan replaces or hides (docs/route-inventory.md):
 * they must keep rendering at their URL while staying out of the nav. */
const URL_ONLY_ENTRIES: Array<{ path: string; heading: string; navLabel: string }> = [
  { path: "/work-items", heading: "Jira drafts", navLabel: "Work Items" },
  { path: "/skills", heading: "Skills", navLabel: "Skills" },
  { path: "/memory", heading: "Memory", navLabel: "Memory" },
  { path: "/evolution", heading: "Evolution Engine", navLabel: "Evolution" },
];

/** What the setup wizard's daily user is granted: routes/setup.py's
 * `_DEFAULT_DAILY_USER_PERMISSIONS` is `["dags.write"]`, and AppShell's
 * `visibleNav` hides any entry whose mutation scope the session lacks
 * (#1417 review: an entry must not imply access the principal lacks). The
 * ordinary-principal walk below covers exactly these rows; the two scoped
 * rows are asserted absent for this account and walked under the admin
 * account instead. */
const DAILY_USER_ENTRIES = NAV_ENTRIES.filter((entry) => !entry.scope);

/** CI's 20s per-test budget, not caution, splits the daily user's 19 rows
 * into chunks. */
function chunk<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

async function expectSingleActiveRailEntry(p: Page, label: string): Promise<void> {
  const active = p.locator(".icon-sidebar .nav-icon.active");
  await expect(active).toHaveCount(1);
  await expect(active).toHaveAccessibleName(label);
}

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({
    baseURL: test.info().project.use.baseURL,
    viewport: { width: 1440, height: 900 },
  });
  // Same onboarding skip the other authenticated specs seed: the modal would
  // otherwise sit over the chrome under test, and force-clicking past it is
  // exactly what these selectors must not need.
  await context.addInitScript(() => {
    window.localStorage.setItem("hive_onboarded", "1");
  });
  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsPM(page);

  // A second, narrow session for the drawer: drawer chrome replaces the rail
  // below 900px, and its login cookie is per-context.
  narrowContext = await browser.newContext({
    baseURL: test.info().project.use.baseURL,
    viewport: { width: 640, height: 900 },
  });
  await narrowContext.addInitScript(() => {
    window.localStorage.setItem("hive_onboarded", "1");
  });
  narrowPage = await narrowContext.newPage();
  await setupIfNeeded(narrowPage);
  await loginAsPM(narrowPage);

  // Admin sessions for the two scope-bearing rows: `principal_has_permission`
  // (middleware/auth.py) passes an admin through every gate, so `visibleNav`
  // shows them all — this is the principal for whom Schedules and Containers
  // are meant to appear.
  adminContext = await browser.newContext({
    baseURL: test.info().project.use.baseURL,
    viewport: { width: 1440, height: 900 },
  });
  await adminContext.addInitScript(() => {
    window.localStorage.setItem("hive_onboarded", "1");
  });
  adminPage = await adminContext.newPage();
  await setupIfNeeded(adminPage);
  await loginAsAdmin(adminPage);

  adminNarrowContext = await browser.newContext({
    baseURL: test.info().project.use.baseURL,
    viewport: { width: 640, height: 900 },
  });
  await adminNarrowContext.addInitScript(() => {
    window.localStorage.setItem("hive_onboarded", "1");
  });
  adminNarrowPage = await adminNarrowContext.newPage();
  await setupIfNeeded(adminNarrowPage);
  await loginAsAdmin(adminNarrowPage);
});

test.afterAll(async () => {
  await context.close();
  await narrowContext.close();
  await adminContext.close();
  await adminNarrowContext.close();
});

const RAIL_CHUNK_SIZE = 7;
const DRAWER_CHUNK_SIZE = 7;

for (const [index, group] of chunk(DAILY_USER_ENTRIES, RAIL_CHUNK_SIZE).entries()) {
  test(`desktop icon rail reaches destinations ${index + 1}/${chunk(DAILY_USER_ENTRIES, RAIL_CHUNK_SIZE).length} by keyboard (${group[0].label} → ${group[group.length - 1].label})`, async () => {
    await page.goto("/dashboard");
    for (const entry of group) {
      // Scoped to the rail: the drawer renders the same labels and is
      // display:none here — a page-level name query would resolve two links
      // and violate strict mode. The rail is visible from every destination,
      // so the chunk chains from wherever the previous row landed instead of
      // paying a full SPA reload per entry inside CI's 20s budget.
      const link = page.locator(".icon-sidebar").getByRole("link", { name: entry.label, exact: true });
      await expect(link).toBeVisible();
      // Keyboard activation, not click: the entry must be operable without a
      // pointer, per the acceptance criteria.
      await link.focus();
      await page.keyboard.press("Enter");
      await page.waitForURL(`**${entry.path}`);
      await expect(entry.probe(page)).toBeVisible();
      await expectSingleActiveRailEntry(page, entry.label);
    }
  });
}

for (const [index, group] of chunk(DAILY_USER_ENTRIES, DRAWER_CHUNK_SIZE).entries()) {
  test(`narrow-screen drawer reaches destinations ${index + 1}/${chunk(DAILY_USER_ENTRIES, DRAWER_CHUNK_SIZE).length} by keyboard and dismisses (${group[0].label} → ${group[group.length - 1].label})`, async () => {
    await narrowPage.goto("/dashboard");
    for (const entry of group) {
      const hamburger = narrowPage.getByRole("button", { name: "Open menu" });
      await expect(hamburger).toBeVisible();
      await hamburger.focus();
      await narrowPage.keyboard.press("Enter");
      // `nav.drawer`, not `.drawer`: Chat renders its own sessions `aside`
      // with class `drawer`, which would collide in strict mode.
      const drawerLink = narrowPage.locator("nav.drawer").getByRole("link", { name: entry.label, exact: true });
      await expect(drawerLink).toBeVisible();
      await drawerLink.focus();
      await narrowPage.keyboard.press("Enter");
      await narrowPage.waitForURL(`**${entry.path}`);
      // The drawer must close itself after choosing a destination — the
      // content underneath is otherwise unreachable on a 640px screen.
      await expect(narrowPage.locator(".drawer.open")).toHaveCount(0);
      await expect(entry.probe(narrowPage)).toBeVisible();
    }
  });
}

/** The permission half of the contract (route-inventory.md): the daily user
 * holds no `schedules.write`/`containers.control` grant, so AppShell must not
 * render those entries in EITHER chrome mode — the pages' every mutation
 * would 403 for this account. Hidden, not merely unlinked from the rail. */
test("mutation-scoped destinations stay out of both chrome modes without the grant", async () => {
  const scoped = NAV_ENTRIES.filter((entry) => entry.scope);
  await page.goto("/dashboard");
  for (const entry of scoped) {
    await expect(page.locator(".icon-sidebar").getByRole("link", { name: entry.label, exact: true })).toHaveCount(0);
  }
  const hamburger = narrowPage.getByRole("button", { name: "Open menu" });
  await expect(hamburger).toBeVisible();
  await hamburger.focus();
  await narrowPage.keyboard.press("Enter");
  for (const entry of scoped) {
    await expect(narrowPage.locator("nav.drawer").getByRole("link", { name: entry.label, exact: true })).toHaveCount(0);
  }
  // Dismiss via the drawer's own close control so the assertion above ran
  // against a genuinely open drawer and the session is left clean.
  await narrowPage.getByRole("button", { name: "Close menu" }).click();
  await expect(narrowPage.locator(".drawer.open")).toHaveCount(0);
});

for (const scopedGroup of chunk(NAV_ENTRIES.filter((entry) => entry.scope), 7)) {
  test(`admin icon rail reaches the grant-gated destinations by keyboard (${scopedGroup.map((e) => e.label).join(", ")})`, async () => {
    await adminPage.goto("/dashboard");
    for (const entry of scopedGroup) {
      const link = adminPage.locator(".icon-sidebar").getByRole("link", { name: entry.label, exact: true });
      await expect(link).toBeVisible();
      await link.focus();
      await adminPage.keyboard.press("Enter");
      await adminPage.waitForURL(`**${entry.path}`);
      await expect(entry.probe(adminPage)).toBeVisible();
      await expectSingleActiveRailEntry(adminPage, entry.label);
    }
  });

  test(`admin drawer reaches the grant-gated destinations by keyboard and dismisses (${scopedGroup.map((e) => e.label).join(", ")})`, async () => {
    await adminNarrowPage.goto("/dashboard");
    for (const entry of scopedGroup) {
      const hamburger = adminNarrowPage.getByRole("button", { name: "Open menu" });
      await expect(hamburger).toBeVisible();
      await hamburger.focus();
      await adminNarrowPage.keyboard.press("Enter");
      const drawerLink = adminNarrowPage.locator("nav.drawer").getByRole("link", { name: entry.label, exact: true });
      await expect(drawerLink).toBeVisible();
      await drawerLink.focus();
      await adminNarrowPage.keyboard.press("Enter");
      await adminNarrowPage.waitForURL(`**${entry.path}`);
      await expect(adminNarrowPage.locator(".drawer.open")).toHaveCount(0);
      await expect(entry.probe(adminNarrowPage)).toBeVisible();
    }
  });
}

test("alias /optimization-inbox resolves to the canonical /optimizer surface", async () => {
  await page.goto("/optimization-inbox");
  await page.waitForURL("**/optimizer");
  await expect(page.getByRole("heading", { name: "Optimization Inbox", exact: true })).toBeVisible();
  // One canonical entry, active; the alias itself is no menu item.
  await expectSingleActiveRailEntry(page, "Optimizer");
});

test("/cli/canvas keeps its compatibility redirect onto Design Studio", async () => {
  // Preserved contract (#95), asserted here alongside
  // design-studio-truthfulness.spec.ts so the nav-coverage inventory carries
  // the redirect's active-state half too.
  await page.goto("/cli/canvas");
  await page.waitForURL("**/design-studio");
  await expect(page.getByRole("heading", { name: "Design Studio", exact: true })).toBeVisible();
  await expectSingleActiveRailEntry(page, "Design Studio");
});

test("browser back and forward return canonical surfaces after rail navigation", async () => {
  // Messages, not Schedules: the back/forward invariant is about history and
  // active state, and the daily-user session driving it may not hold
  // `schedules.write` (the scoped rows are walked under the admin account).
  await page.goto("/dashboard");
  const link = page.locator(".icon-sidebar").getByRole("link", { name: "Messages", exact: true });
  await link.click();
  await page.waitForURL("**/messages");
  await expect(page.getByRole("heading", { name: "Message Board", exact: true })).toBeVisible();

  await page.goBack();
  await page.waitForURL("**/dashboard");
  await expect(page.getByRole("heading", { name: "Live Operations", exact: true })).toBeVisible();
  await expectSingleActiveRailEntry(page, "Dashboard");

  await page.goForward();
  await page.waitForURL("**/messages");
  await expect(page.getByRole("heading", { name: "Message Board", exact: true })).toBeVisible();
  await expectSingleActiveRailEntry(page, "Messages");
});

test("URL-only legacy rows still render but stay out of the navigation", async () => {
  for (const entry of URL_ONLY_ENTRIES) {
    // Not deleted: the route still serves its surface while its replacement
    // is owned by the cutover issues.
    await page.goto(entry.path);
    await expect(page.getByRole("heading", { name: entry.heading, exact: true })).toBeVisible();
  }
  const rail = page.locator(".icon-sidebar");
  for (const entry of URL_ONLY_ENTRIES) {
    await expect(rail.getByRole("link", { name: entry.navLabel, exact: true })).toHaveCount(0);
  }
});
