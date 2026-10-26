/**
 * Approvals projection (#2278 / Parity P-1): nav reaches the surface that
 * calls the same capability + HITL APIs as CLI; pending → answer surfaces the
 * Run resume link (AC-5).
 */
import { expect, test, type Page, type Route } from "@playwright/test";
import { loginAsPM, setupIfNeeded } from "./session";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("hive_onboarded", "1");
  });
  await setupIfNeeded(page);
  await loginAsPM(page);
});

test("Approvals is reachable from the icon rail and shows both queues", async ({ page }) => {
  await page.goto("/dashboard");
  const link = page.locator(".icon-sidebar").getByRole("link", { name: "Approvals", exact: true });
  await expect(link).toBeVisible();
  await link.click();
  await page.waitForURL("**/approvals");
  await expect(page.getByRole("heading", { name: "Approvals", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Capability inbox" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "HITL (paused Runs)" })).toBeVisible();
});

async function stubApprovalsQueues(
  page: Page,
  opts: {
    caps?: unknown[];
    hitl?: unknown[];
  },
): Promise<void> {
  const caps = opts.caps ?? [];
  const hitl = opts.hitl ?? [];
  await page.route("**/v1/capabilities/approvals", async (route: Route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ pending: caps }),
      });
      return;
    }
    await route.continue();
  });
  await page.route("**/v1/hitl/pending", async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(hitl),
    });
  });
}

test("AC-5: pending HITL → answer → Run resume link to dag-runs is visible", async ({ page }) => {
  const runId = "run-approvals-e2e-ac5";
  const nodeId = "ask-human";
  let answered = false;

  await stubApprovalsQueues(page, {
    caps: [],
    hitl: [
      {
        run_id: runId,
        node_id: nodeId,
        project_id: "proj-ac5",
        payload: { question: "Approve deploy?" },
        paused_at: "2026-10-26T00:00:00Z",
      },
    ],
  });

  await page.route(`**/v1/hitl/${runId}/${nodeId}/answer`, async (route: Route) => {
    expect(route.request().method()).toBe("POST");
    const body = route.request().postDataJSON() as Record<string, unknown>;
    expect(body).toMatchObject({ decision: "approved" });
    answered = true;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true }),
    });
  });

  await page.goto("/approvals");
  await expect(page.getByRole("heading", { name: "HITL (paused Runs)" })).toBeVisible();

  const runLink = page.getByRole("link", { name: `Run ${runId}` });
  await expect(runLink).toBeVisible();
  await expect(runLink).toHaveAttribute("href", `/dag-runs?run=${encodeURIComponent(runId)}`);

  await page.getByRole("button", { name: "Submit answer" }).click();
  await expect.poll(() => answered).toBe(true);
});

test("AC-1/AC-2: capability inbox approve posts CLI-shaped body to canonical door", async ({
  page,
}) => {
  const requestId = "cap-req-e2e-parity";
  let posted: { url: string; body: unknown } | null = null;

  await stubApprovalsQueues(page, {
    caps: [
      {
        request_id: requestId,
        action: "restart_stack",
        params: {},
        tier: "destructive",
        requester: "agent",
        rationale: "e2e parity",
      },
    ],
    hitl: [],
  });

  await page.route(`**/v1/capabilities/approvals/${requestId}`, async (route: Route) => {
    if (route.request().method() === "POST") {
      posted = {
        url: new URL(route.request().url()).pathname,
        body: route.request().postDataJSON(),
      };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ request_id: requestId, resolved: true }),
      });
      return;
    }
    await route.continue();
  });

  await page.goto("/approvals");
  await expect(page.getByText(requestId)).toBeVisible();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect.poll(() => posted).not.toBeNull();
  expect(posted!.url).toBe(`/v1/capabilities/approvals/${requestId}`);
  expect(posted!.body).toEqual({ approved: true });
});

test("AC-3: foreign capability id surfaces fail-closed error toast", async ({ page }) => {
  const foreignId = "foreign-cap-id-e2e";
  await stubApprovalsQueues(page, {
    caps: [
      {
        request_id: foreignId,
        action: "docker_prune",
        params: {},
        tier: "destructive",
        requester: "other",
        rationale: "should 404",
      },
    ],
    hitl: [],
  });

  await page.route(`**/v1/capabilities/approvals/${foreignId}`, async (route: Route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: `no pending approval '${foreignId}'` }),
      });
      return;
    }
    await route.continue();
  });

  await page.goto("/approvals");
  await page.getByRole("button", { name: "Deny", exact: true }).click();
  // ApiError surfaces FastAPI string detail verbatim (or the 404 fallback).
  await expect(
    page
      .getByRole("status")
      .getByText(/no pending approval|couldn't be found|Resolve failed/i)
      .first(),
  ).toBeVisible();
});
