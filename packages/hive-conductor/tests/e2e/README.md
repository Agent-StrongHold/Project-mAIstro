# tests/e2e — CI status

| File | Runs in CI (`ci.yml`'s `hive-conductor-e2e` job)? | Why |
|---|---|---|
| `test_pm_workflow_api.py` | **Yes** | 24 pytest tests against a real HTTP client, no browser. `docker-compose.test.yml`'s `api-tests` service builds `tests/Dockerfile` (installs only `pytest`+`httpx`) and its `CMD` runs only this file. |
| `pm-workflow.spec.ts` | No (not wired yet) | Playwright UI test; `docker-compose.test.yml`'s `e2e-tests` service exists for it but isn't invoked by any workflow. |
| `test_pm_agent.py` | **No — permanently excluded** | Standalone script (no `def test_*`, not pytest-collectible), requires `pip install browser-use` (not vendored anywhere in this repo) plus a real `GOOGLE_API_KEY`. |
| `test_pm_real_atlassian.py` | **No — permanently excluded** | Same `browser-use`/`GOOGLE_API_KEY` requirement, plus real Jira/Confluence credentials already saved in a running Hive instance. Not a CI-safe test under any circumstance. |
| `test_pm_vision.py` | **No — permanently excluded** | 7 pytest tests, but gated behind the same `browser-use`/`GOOGLE_API_KEY` import — `ModuleNotFoundError` on a clean checkout. |

The three excluded files are deliberate, not an oversight (see #286): they need an unvendored
heavy dependency and/or live third-party credentials that don't belong in a public CI run. Run
them locally per their own docstrings (`make test-agent`, `make test-vision`, or directly with
`GOOGLE_API_KEY` set) — see `../PM-WALKTHROUGH.md`.
