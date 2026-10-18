---
inventory-delta:
  packages/hive-conductor/backend/tests: +18
  tests/: +1
---
# 1425-api-docs-first-party

Backend coverage for #1425: `/docs` rebuilt on vendored first-party assets so
the enforced Content-Security-Policy stops blanking it.

The eighteen tests live in `packages/hive-conductor/backend/tests/test_docs_first_party.py`
and answer the issue's acceptance check at the HTTP level, in three groups:

- **The document could render** (8): every URL the page names is
  root-relative; there is no inline `<script>` (the bootstrap FastAPI used to
  inline is what `script-src 'self'` refused); the referenced set is exactly
  the vendored whitelist — JavaScript, stylesheet, bootstrap, favicons, and
  the schema fetch, nothing more; every referenced asset is actually served
  with its recorded media type; `/openapi.json` serves the real document; a
  sub-path mount (`root_path=/pm`) prefixes every URL and stays coherent.
- **The vendored assets** (6): bytes on disk match the provenance hashes
  recorded in `routes/api_docs.py`; a missing vendored file is an explicit 404
  naming the deployment, never the SPA shell; nothing outside the whitelist
  serves; dot-segment and encoded-slash paths serve nothing; a nested
  docs-asset path — or its percent-encoded-separator form — is rejected with
  the SPA shell actually built, the exact condition under which CI's `test`
  job caught the whitelist alone answering 200 (`frontend/dist` exists after
  the frontend build step, so `main.py`'s catch-all registered); `/docs`
  exists exactly once now that `docs_url=None` retired FastAPI's built-in
  page.
- **The policy is unchanged by docs** (4): the header on `/docs` is
  byte-identical to the header on `/health` under the enforcing name; in the
  production posture it admits no `unsafe-inline`, no `unsafe-eval`, and no
  http(s) source; the two shortcuts the issue forbids — a docs exception woven
  from `'unsafe-inline'` or an `'unsafe-eval'` permission — are refused by the
  canonical validator, asserted here so a future attempt dies in CI; and the
  served schema declares no OAuth2 security scheme, which is why no
  `oauth2-redirect.html` was vendored (the first scheme added fails this test
  with a pointer to the fix).

Browser coverage is deliberately **not** in this count: header and HTML checks
cannot prove Swagger executes, so that lives as a Playwright spec,
`packages/hive-conductor/tests/e2e/api-docs.spec.ts`, which runs in CI's
`hive-conductor-e2e-ui` job against the live app and is not a pytest suite.
Provenance, hashes, and the recorded browser evidence are in
`packages/hive-conductor/backend/static/swagger-ui/README.md`.

`test_csp.py` was left untouched: it keeps owning the policy itself. The
`tests/` +1 is the vendored-bundle case added to the DevSkim scan-scope guard
(`tests/test_devskim_scan_scope.py`), pinning that `**/static/swagger-ui/**`
stays on the ignore list without the glob reaching any reviewed file. The one
nearby count that moved otherwise is the two import-order fixes ruff applied
inside the new file only.
