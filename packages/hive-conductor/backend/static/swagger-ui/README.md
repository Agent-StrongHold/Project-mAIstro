# Vendored Swagger UI for `/docs` (#1425)

The backend API reference is served entirely from the files in this directory.
The enforced Content-Security-Policy (`services/csp_policy.py` — `script-src
'self'`, `style-src 'self'`, no `'unsafe-inline'`, no third-party origin)
refused everything FastAPI's default docs page referenced: the stylesheet and
bundle it loaded from jsdelivr, the favicon from fastapi.tiangolo.com, and the
bootstrap `<script>` it inlined into the document. The policy is correct and
did not move; the page now satisfies it.

## Provenance

| File | Origin | Version | sha256 |
|---|---|---|---|
| `swagger-ui-bundle.js` | `https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.33.1/swagger-ui-bundle.js` | 5.33.1 | `050bc415ee7048dcd881682678f720264e7da5e373f7461d7c58c755305255f7` |
| `swagger-ui.css` | `https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.33.1/swagger-ui.css` | 5.33.1 | `1ac324f7dcd27e4b9386b4bd6421271ec147e922a22c05ba24b11515e9aa6321` |
| `favicon-32x32.png` | `https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.33.1/favicon-32x32.png` | 5.33.1 | `3ed612f41e050ca5e7000cad6f1cbe7e7da39f65fca99c02e99e6591056e5837` |
| `favicon-16x16.png` | `https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.33.1/favicon-16x16.png` | 5.33.1 | `af24ad604dd7b3bcda8f975ab973075f4a2f70a4087944a12f8ef8b63a3e07c2` |
| `swagger-initializer.js` | **written here, not upstream** | — | `96d494c655e51cb4455d21a0c47102ded63070f6dd1381e7fb752c51e51d87ff` |

- Upstream release: `swagger-ui-dist` 5.33.1 (npm, published 2026-10-01;
  FastAPI's own default pins the floating `@5` on the same CDN).
- Files were fetched verbatim from the CDN, hashed, and committed. Nothing was
  modified, minified further, or subset. The `.map` files, the standalone
  preset, and upstream's `index.html`/`index.css`/`oauth2-redirect.html` were
  deliberately **not** vendored: nothing references them, and the whitelist in
  `routes/api_docs.py` refuses to serve them.
- `swagger-initializer.js` is this repository's bootstrap. FastAPI inlines
  this object literal into the document, and inline is exactly what the
  policy forbids; as a served file it is just another first-party script. It
  mirrors FastAPI's default parameters and reads the schema URL from the
  page's `<meta name="openapi-url">` so a sub-path (root_path) deployment
  needs no deployment-specific asset.
- The hashes are re-checked against the bytes on disk by
  `backend/tests/test_docs_first_party.py::TestTheVendoredAssets`, so a
  truncated copy or a hand-patched bundle fails CI rather than blanking the
  page somewhere.

## To refresh

1. Pick the new `swagger-ui-dist` version on npm/jsdelivr.
2. Re-download the four upstream files above verbatim into this directory.
3. Update `SWAGGER_UI_DIST_VERSION` and the `_ASSETS` hashes in
   `routes/api_docs.py` (`sha256sum *` here gives them).
4. Run `backend/tests/test_docs_first_party.py` and
   `tests/e2e/api-docs.spec.ts` against a locally served app; both must pass
   with zero CSP violations before the new hash row lands here.

## CSP accounting for the whole document

| What the document fetches | Served by | Directive that allows it |
|---|---|---|
| `swagger-ui.css` | `/docs/static/swagger-ui.css` (this origin) | `style-src 'self'` |
| `swagger-ui-bundle.js` | `/docs/static/swagger-ui-bundle.js` | `script-src 'self'` |
| bootstrap script | `/docs/static/swagger-initializer.js` (file, not inline) | `script-src 'self'` |
| favicons | `/docs/static/favicon-*.png` | `img-src 'self'` |
| OpenAPI schema | `/openapi.json` (same-origin fetch) | `connect-src 'self'` |
| runtime images in the bundle/CSS (inline SVG data URIs) | `data:` URIs | `img-src ... data:` |

No `eval` / `new Function` executes on the page: the only `new Function` in
the bundle is webpack's `globalThis` fallback, unreachable where `globalThis`
exists (every current browser). No web worker, no `<style>` injection at
runtime. `connect-src 'self'` covers the schema fetch in both the development
and production policies.

## Evidence (recorded 2026-10-06)

**Backend unit/route level** (`packages/hive-conductor/backend/tests/test_docs_first_party.py`,
41 assertions across 17 tests, `uv run pytest ... -q` → 41 passed):

- `/docs` served 200; every `href`/`src`/`meta` URL it names is root-relative
  (no scheme, no authority); zero `<script>` tags without `src`; the
  referenced set is exactly the vendored whitelist; `/openapi.json` served
  with `info.title == "Hive Conductor"` and 215 paths.
- Served CSP on `/docs` is byte-identical to the header on `/health`, under
  the enforcing name; with `ALLOW_INSECURE_TRANSPORT=false` the header reads:
  `default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self';
  img-src 'self' data: blob:; connect-src 'self'; frame-src 'none';
  frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action
  'self'; upgrade-insecure-requests` — no `unsafe-inline`, no `unsafe-eval`,
  no `http(s)` source anywhere.
- Vendored bytes match the hashes in the table above; a missing file is an
  explicit 404 (never the SPA shell); names outside the whitelist (README,
  standalone preset, `main.py`) 404; `%2e%2e` and `..%2Fmain.py` serve
  nothing; a sub-path mount (`root_path=/pm`) prefixes every URL in the
  document.

**Browser level** (`packages/hive-conductor/tests/e2e/api-docs.spec.ts`,
Playwright/Chromium headless, all off-origin requests aborted before the page
loads):

- Development profile — `uv run python -m uvicorn main:app` on
  `http://127.0.0.1:8155` with `ALLOW_INSECURE_TRANSPORT=true
  SESSION_COOKIE_SECURE=false` (the documented local loop; its policy omits
  only `upgrade-insecure-requests`, which exists to force HTTPS, and adds the
  Vite dev origins to `connect-src`): 2/2 passed. The API title rendered, the
  operation list rendered, an operation expanded, `/openapi.json` returned
  200, and `window.ui` had parsed the real schema (`spec.json.info.title ==
  "Hive Conductor"`). Console CSP violations: **0**. Page errors: **0**.
  Failed requests: **0**. Off-origin attempts: **0**.
- Production profile — the same app on `https://127.0.0.1:8443` (self-signed
  cert) with **no** dev flags, serving the exact header quoted above plus
  HSTS: the same assertions all pass (title, operation list, expansion, schema
  fetch, parsed title `Hive Conductor`; zero violations / errors / failures /
  off-origin attempts).
- Tested URL/origin: `http://127.0.0.1:8155/docs` (development profile) and
  `https://127.0.0.1:8443/docs` (production profile, direct container-equivalent
  load — no gateway, no base path). The sub-path arrangement is covered at the
  document level by the `root_path` unit test: a gateway mounting the app at a
  prefix changes the URLs the document names, not the assets or policy.

**Commands and results** (2026-10-06, worktree `auto-1425` @ 9bd1a93e):

```text
# backend route/policy level
uv run pytest packages/hive-conductor/backend/tests/test_docs_first_party.py \
  packages/hive-conductor/backend/tests/test_csp.py -q
  → 41 passed, 1 skipped   (skip = pre-existing "frontend not built" case)
uv run pytest packages/hive-conductor/backend/tests -q
  → 3434 passed, 6 skipped in 145.54s   (whole suite, nothing regressed)

# browser level
cd packages/hive-conductor/backend
SESSION_COOKIE_SECURE=false ALLOW_INSECURE_TRANSPORT=true CONDUCTOR_DATA_DIR=/tmp/... \
  uv run --project <repo-root> python -m uvicorn main:app --host 127.0.0.1 --port 8155
cd ../tests/e2e && npm ci
HIVE_BASE_URL=http://127.0.0.1:8155 npx playwright test api-docs.spec.ts
  → 2 passed (dev profile)

# production profile (no dev flags; self-signed TLS on 8443)
uv run --project <repo-root> python -m uvicorn main:app --host 127.0.0.1 --port 8443 \
  --ssl-keyfile ... --ssl-certfile ...
# same spec assertions re-run against https://127.0.0.1:8443/docs → all pass
```

The Dockerfile copies all of `backend/` into the image, so a fresh container
ships these assets; if one is ever missing, `/docs/static/<asset>` answers 404
with `docs asset missing from deployment` instead of quietly rendering an
empty container.
