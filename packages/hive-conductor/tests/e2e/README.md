# tests/e2e — CI status

| File | Runs in CI (`ci.yml`'s `hive-conductor-e2e` job)? | Why |
|---|---|---|
| `test_pm_workflow_api.py` | **Yes** | 24 pytest tests against a real HTTP client, no browser. `docker-compose.test.yml`'s `api-tests` service builds `tests/Dockerfile` (installs only `pytest`+`httpx`) and its `CMD` runs only this file. |
| `pm-workflow.spec.ts` | **Yes** | Playwright UI test. `ci.yml`'s `hive-conductor-e2e-ui` job runs `docker-compose.test.yml`'s `e2e-tests` service, which builds `tests/Dockerfile.playwright` and runs every `*.spec.ts` in this directory. (This row said "not wired yet" until #371; the job had been added in the meantime.) |
| `modal-a11y.spec.ts` | **Yes** | Same job, same config. Dialog semantics for the shared `Modal` (#371) — accessible name, focus trap, inert background, focus restoration — plus an axe scan of the open dialog. The image installs `@axe-core/playwright` for it. |
| `offline-assets.spec.ts` | **Yes** | Same job, same config. Aborts every request that would leave the app's origin and asks it to load anyway (#377) — the air-gap check for the self-hosted typefaces. |
| `credential-labels.spec.ts` | **Yes** | Same job, same config. Asks the browser's accessibility tree what each credential field is actually called (#375) — including the reveal control and an axe scan of the sign-in form. |
| `session.ts` | n/a | Not a spec (Playwright matches `*.spec.ts`). The setup-wizard and login helpers both UI specs share; every comment in it records a selector that has already gone wrong once. |
| `test_pm_agent.py` | **No — permanently excluded** | Standalone script (no `def test_*`, not pytest-collectible), requires `pip install browser-use` (not vendored anywhere in this repo) plus a real `GOOGLE_API_KEY`. |
| `test_pm_real_atlassian.py` | **No — permanently excluded** | Same `browser-use`/`GOOGLE_API_KEY` requirement, plus real Jira/Confluence credentials already saved in a running Hive instance. Not a CI-safe test under any circumstance. |
| `test_pm_vision.py` | **No — permanently excluded** | 7 pytest tests, but gated behind the same `browser-use`/`GOOGLE_API_KEY` import — `ModuleNotFoundError` on a clean checkout. |

The three excluded files are deliberate, not an oversight (see #286): they need an unvendored
heavy dependency and/or live third-party credentials that don't belong in a public CI run. Run
them locally per their own docstrings (`make test-agent`, `make test-vision`, or directly with
`GOOGLE_API_KEY` set) — see `../PM-WALKTHROUGH.md`.
