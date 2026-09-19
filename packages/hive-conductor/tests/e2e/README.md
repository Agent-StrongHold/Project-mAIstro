# tests/e2e — CI status

| File | Runs in CI (`ci.yml`'s `hive-conductor-e2e` job)? | Why |
|---|---|---|
| `test_pm_workflow_api.py` | **Yes** | 24 pytest tests against a real HTTP client, no browser. `docker-compose.test.yml`'s `api-tests` service builds `tests/Dockerfile` (installs only `pytest`+`httpx`) and its `CMD` runs only this file. |
| `pm-workflow.spec.ts` | **Yes** | Playwright UI test. `ci.yml`'s `hive-conductor-e2e-ui` job runs `docker-compose.test.yml`'s `e2e-tests` service, which builds `tests/Dockerfile.playwright` and runs every `*.spec.ts` in this directory. (This row said "not wired yet" until #371; the job had been added in the meantime.) |
| `modal-a11y.spec.ts` | **Yes** | Same job, same config. Dialog semantics for the shared `Modal` (#371) — accessible name, focus trap, inert background, focus restoration — plus an axe scan of the open dialog. The image installs `@axe-core/playwright` for it. |
| `offline-assets.spec.ts` | **Yes** | Same job, same config. Aborts every request that would leave the app's origin and asks it to load anyway (#377) — the air-gap check for the self-hosted typefaces. |
| `credential-labels.spec.ts` | **Yes** | Same job, same config. Asks the browser's accessibility tree what each credential field is actually called (#375) — including the reveal control and an axe scan of the sign-in form. |
| `workspace-scope.spec.ts` | **Yes** | Same job, same config. Records every request the workspace-scoped pages make on a first-ever session and fails on one that names a workspace and leaves it blank (#1427); then creates a workspace and requires the scoped requests to carry its id. |
| `workspace-a11y.spec.ts` | **Yes** | Same job, same config. Asks the accessibility tree whether a toast is a status message and a refused workspace invite is an alert (#1405), and whether the persona wizard's renamed fields are named by their full visible labels (#1416). |
| `workspace-lifecycle.spec.ts` | **Yes** | Same job, same config. As the admin account: creating a workspace confirms and selects it; the Tools panel shows unsaved edits, asks before discarding and confirms a save (#1430, #1407); Archive asks first like Delete (#1429), costs one PATCH and no list refetch (#1434), and the archived workspace is restorable from the tab bar (#1428). Adds `loginAsAdmin` to `session.ts`. |
| `workspace-toolbar.spec.ts` | **Yes** | Same job, same config. As the admin account: a zero-workspace toolbar explains what a workspace is and offers to create one (#1426, #1431); the persona picker shows name and tagline and is keyboard-operable (#1437); a 100-character name truncates with its full text in the tooltip and the toolbar stays bounded at phone width (#1424); signing out clears the four per-account localStorage keys (#1418, #1433). |
| `app-shell-loading.spec.ts` | **Yes** | Same job, same config. The setup-status and whoami probes fire together rather than in series, and the shell's sidebar-plus-content skeleton, not a loading sentence, is what first paints while either is slow (#1408), and a hung whoami doesn't hold up the setup wizard on a fresh instance. |
| `work-item-draft-labels.spec.ts` | **Yes** | Same job, same config. The Jira draft modal's clarifying-question and edit-step fields answer to their full visible labels by role, and a required clarifying question carries `aria-required` (#1406). |
| `template-picker-skeleton.spec.ts` | **Yes** | Same job, same config. The Dashboard's template picker shows a real, sized loading skeleton while `/v1/dashboard/demos` is in flight, not an invisible div with no matching CSS rule (#1421). |
| `dashboard-reduced-motion.spec.ts` | **Yes** | Same job, same config. The Dashboard header's status dot only pulses when the OS has no reduced-motion preference (#1415). |
| `route-code-splitting.spec.ts` | **Yes** | Same job, same config. A routed page's JS chunk is fetched only once its route is visited, not bundled into every cold load (#1435). |
| `session.ts` | n/a | Not a spec (Playwright matches `*.spec.ts`). The setup-wizard and login helpers both UI specs share; every comment in it records a selector that has already gone wrong once. |
| `test_pm_agent.py` | **No — permanently excluded** | Standalone script (no `def test_*`, not pytest-collectible), requires `pip install browser-use` (not vendored anywhere in this repo) plus a real `GOOGLE_API_KEY`. |
| `test_pm_real_atlassian.py` | **No — permanently excluded** | Same `browser-use`/`GOOGLE_API_KEY` requirement, plus real Jira/Confluence credentials already saved in a running Hive instance. Not a CI-safe test under any circumstance. |
| `test_pm_vision.py` | **No — permanently excluded** | 7 pytest tests, but gated behind the same `browser-use`/`GOOGLE_API_KEY` import — `ModuleNotFoundError` on a clean checkout. |

The three excluded files are deliberate, not an oversight (see #286): they need an unvendored
heavy dependency and/or live third-party credentials that don't belong in a public CI run. Run
them locally per their own docstrings (`make test-agent`, `make test-vision`, or directly with
`GOOGLE_API_KEY` set) — see `../PM-WALKTHROUGH.md`.
