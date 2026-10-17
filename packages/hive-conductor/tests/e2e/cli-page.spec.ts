/**
 * #292 — the CLI page contract, end to end, in the CI-run suite.
 *
 * `docker-compose.test.yml`'s `e2e-tests` service runs every `*.spec.ts` in
 * this directory, so this file is the executable half of #292's acceptance
 * criterion "E2E covers every shipped command plus unauthorized,
 * unsupported, timeout, and backend-unavailable states". (An earlier draft
 * of the coverage landed in `frontend/e2e/`, a directory no CI job or
 * script executes — and whose shared wizard fixture predates the five-step
 * Accounts wizard, so it cannot even boot the app locally. The coverage
 * lives here so the criterion is backed by a run, not by files.)
 *
 * What runs against the real backend, un-intercepted: the manifest-driven
 * pass over every shipped command (each one's console output must come from
 * a `POST /v1/cli/exec` round trip, and `help` must render the manifest
 * itself), the unsupported-command 404, and refresh-restores-history. What
 * is route-intercepted, per this suite's established pattern
 * (api-timeout.spec.ts): the failure answers a healthy deployment cannot
 * produce on demand — 401, 504, 503, and a transport failure. `/cli` sits
 * inside `AuthGuard`, so a cookieless browser is redirected to /login
 * before the page could render anything; interception is the honest way to
 * pin what the page does when the backend answers 401 anyway (a session
 * that expired mid-page), exactly as the timeout specs pin the budget.
 */

import { test, expect, type Page } from "@playwright/test";
import { loginAsAdmin, setupIfNeeded } from "./session";

// The console card is the page's only card; its input is the command line.
const consoleCard = (page: Page) => page.locator("div.card");
const input = (page: Page) => consoleCard(page).locator("input");

async function runCommand(page: Page, command: string) {
  await input(page).fill(command);
  await input(page).press("Enter");
}

// Navigate to /cli and wait for the mount effect to settle. Arming a
// response listener AFTER the sessions GET answers can miss the boot exec
// (it fires immediately and local responses beat any later listener), so
// the empty-session case settles on the boot's rendered effect instead:
// the page really executes `hctl status`, and a later waitForResponse in a
// test cannot mistake that boot POST for the test's own command.
async function gotoCliSettled(page: Page) {
  const sessionsResponse = page.waitForResponse(
    (r) => r.url().includes("/v1/cli/sessions") && r.request().method() === "GET",
  );
  await page.goto("/cli");
  await expect(input(page)).toBeVisible({ timeout: 15000 });
  const sessions = (await (await sessionsResponse).json()) as {
    id: string;
    history: unknown[];
  }[];
  const session = sessions.find((s) => s.id === "default") ?? sessions[0];
  if (session && session.history.length === 0) {
    // Empty session: the console boots with one real `hctl status`
    // execution — wait for its prompt line, not its response event.
    await expect(
      consoleCard(page).getByText("$ hctl status", { exact: true }).first(),
    ).toBeVisible({ timeout: 15000 });
  }
}

test.describe("CLI page contract (#292)", () => {
  test.beforeEach(async ({ page }) => {
    await setupIfNeeded(page);
    await loginAsAdmin(page);
    // OnboardingGate covers authenticated pages with a modal otherwise —
    // same reason api-timeout.spec.ts sets this key.
    await page.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));
  });

  test("every shipped command executes through the backend", async ({ page }) => {
    await gotoCliSettled(page);

    // Drive the UI *from* the machine-readable manifest, so a registry
    // entry without coverage is impossible to miss.
    const manifestResponse = await page.request.get("/v1/cli/commands");
    expect(manifestResponse.status()).toBe(200);
    const manifest = await manifestResponse.json();
    const commands: { name: string; summary: string }[] = manifest.commands;
    expect(commands.length).toBeGreaterThanOrEqual(4);

    for (const command of commands) {
      const exec = page.waitForResponse(
        (r) =>
          r.url().includes("/v1/cli/exec") &&
          r.request().method() === "POST" &&
          r.status() === 200,
      );
      await runCommand(page, command.name);
      const response = await exec;
      const body = await response.json();
      expect(body.command, `${command.name} must echo the executed command`).toBe(command.name);
      expect(body.lines.length, `${command.name} must produce backend output`).toBeGreaterThan(
        0,
      );
      // `.last()`: prior history may already contain the same prompt line
      // from an earlier execution in this session store.
      await expect(
        consoleCard(page).getByText(`$ ${command.name}`, { exact: true }).last(),
      ).toBeVisible();
      // `help` is rendered from the registry, never hard-coded client copy:
      // every manifest entry's name+summary must appear in its output.
      if (command.name === "help") {
        for (const listed of commands) {
          await expect(
            consoleCard(page).getByText(listed.summary, { exact: false }).first(),
          ).toBeVisible();
        }
      }
    }
  });

  test("an unsupported command is refused by the backend, never simulated", async ({ page }) => {
    await gotoCliSettled(page);

    const refused = page.waitForResponse(
      (r) =>
        r.url().includes("/v1/cli/exec") &&
        r.request().method() === "POST" &&
        r.status() === 404,
    );
    await runCommand(page, "hctl deploy --prod");
    const response = await refused;
    const detail = (await response.json()).detail;
    expect(detail.error).toBe("unsupported_command");
    await expect(consoleCard(page).getByText("error: unsupported command")).toBeVisible();
    await expect(consoleCard(page).getByText("type 'help' for the supported set")).toBeVisible();
    // The refusal is all it rendered for this command — no fabricated
    // deployment progress.
    expect(await consoleCard(page).getByText("deploying", { exact: false }).count()).toBe(0);
  });

  test("an unauthorized execution is reported, never faked", async ({ page }) => {
    // An empty session list, so no earlier command's restored output can
    // satisfy the "nothing was invented" assertions below: the page boots
    // straight into the refused execution.
    await page.route("**/v1/cli/sessions", (r) => r.fulfill({ json: [] }));
    await page.route("**/v1/cli/exec", (r) =>
      r.fulfill({ status: 401, json: { detail: "Authentication required" } }),
    );
    const sessionsResponse = page.waitForResponse(
      (r) => r.url().includes("/v1/cli/sessions") && r.request().method() === "GET",
    );
    await page.goto("/cli");
    await sessionsResponse;

    // Empty session: the page boots by executing `hctl status`, which the
    // backend refuses with 401 — rendered, not simulated.
    const unauthorized = consoleCard(page).getByText("error: unauthorized — sign in and retry");
    await expect(unauthorized).toBeVisible({ timeout: 15000 });

    await runCommand(page, "help");
    await expect(unauthorized).toHaveCount(2);
    // No help output was invented to soften the refusal.
    expect(await consoleCard(page).getByText("this message", { exact: false }).count()).toBe(0);
  });

  test("a timed-out command is reported, never faked", async ({ page }) => {
    await page.route("**/v1/cli/exec", (r) =>
      r.fulfill({
        status: 504,
        json: { detail: { error: "cli_command_timeout", command: "hctl health" } },
      }),
    );
    await gotoCliSettled(page);

    await runCommand(page, "hctl health");
    await expect(consoleCard(page).getByText("error: command timed out")).toBeVisible();
  });

  test("a backend-unavailable answer is reported, never faked", async ({ page }) => {
    await page.route("**/v1/cli/exec", (r) =>
      r.fulfill({
        status: 503,
        json: { detail: { error: "backend_unavailable", command: "hctl health" } },
      }),
    );
    await gotoCliSettled(page);

    await runCommand(page, "hctl health");
    await expect(consoleCard(page).getByText("error: backend unavailable")).toBeVisible();
  });

  test("an unreachable backend is reported, never faked", async ({ page }) => {
    await page.route("**/v1/cli/sessions", (r) => r.abort());
    await page.route("**/v1/cli/exec", (r) => r.abort());
    await page.goto("/cli");

    // Boot itself cannot restore a session: the console says so rather than
    // inventing output.
    const unreachable = consoleCard(page).getByText("error: could not reach hive-conductor");
    await expect(unreachable.first()).toBeVisible({ timeout: 15000 });

    // The exec path renders the same transport line (lib/api.ts wraps every
    // transport failure as ApiError status 0) — the count grows, it does not
    // turn into a fake success or a raw status dump.
    await runCommand(page, "hctl status");
    await expect(unreachable).toHaveCount(2);
  });

  test("refresh restores the session's real history from the backend", async ({ page }) => {
    await gotoCliSettled(page);

    const exec = page.waitForResponse(
      (r) =>
        r.url().includes("/v1/cli/exec") &&
        r.request().method() === "POST" &&
        r.status() === 200,
    );
    await runCommand(page, "hctl agents");
    await exec;
    await expect(
      consoleCard(page).getByText("$ hctl agents", { exact: true }).last(),
    ).toBeVisible();

    // After reload the page replays the session's durable history from
    // `GET /v1/cli/sessions` — server-side state, not localStorage — so the
    // command and its real output survive the refresh.
    await page.reload();
    await expect(
      consoleCard(page).getByText("$ hctl agents", { exact: true }).first(),
    ).toBeVisible({ timeout: 15000 });
    await expect(input(page)).toBeVisible();
  });
});
