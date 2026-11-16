# Inventory note — P0.3 typed-client debt burn wave 1 (#1995)

Rebased onto current `develop` after organic burns past the original
wave-1 ledger (60→43 raw / 142→131 hand-typed). Those earlier page
migrations landed via other PRs; this branch keeps only remaining
wave-1 value without regressing the develop floor.

## Changes

- Add `packages/hive-conductor/frontend/src/api/entities.ts` (OpenAPI
  aliases from `types.gen.ts`, plus path-derived / loose demo+provider
  shapes).
- Route remaining bare `fetch(` sites through `lib/api` helpers:
  AccountBanner logout, TemplatePicker demos, Settings elevate,
  LlmProviders list/key/activate.
- Drop the local `Template` type and LlmProviders local interfaces in
  favor of `entities.ts`.
- Preserve develop's AuthorizationContext / AuthorizationNotice on
  LlmProviders and Settings (do not reintroduce #2283 debt).

## Ratchet

`quality/frontend-typed-client-baseline.json`: **42 → 40** raw fetch,
**120 → 119** hand-typed (net of develop's already-lower floor).
(An earlier draft of this note said 124 → 123 hand-typed; that figure
predated the final rebase and disagreed with the ledger JSON — the gate
run below is the authority.)

## Verification (repair round, head `6b8c0921ecab`)

The hosted run at this head shows no content-gate failure: every leaf job
was `cancelled` by a concurrency supersede at 11:07Z and only the
`if: always()` aggregators (`Quality gate (Pillars 1–4, 7, 8)`,
`SAST (bandit + semgrep + gitleaks)`) then failed on cancelled needs.
The change-bearing gates were re-run locally with CI's exact arguments,
all green:

- `uv run python scripts/check-frontend-typed-client.py` → exit 0
  ("40 raw fetch and 119 hand-typed declaration(s) tolerated, none new").
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0 (1253
  identities, exact ledger match, `unclassified: 0`).
- `uv run python scripts/check-ratchet-provenance.py` → exit 0.
- `uv run python scripts/check-shipped-surface-truth.py` → exit 0
  (matrix complete after dropping the 4 stale `mutating-api-call` rows).
- SAST legs: bandit Medium+ count 0; semgrep 1.182.1, 364 rules, 0
  findings with `--error`; gitleaks 8.30.1 over
  `78133c093..6b8c0921` — no leaks.
- `uv run python scripts/check-doc-links.py` → exit 0 (CHANGELOG fix).
- `npm run build` in `packages/hive-conductor/frontend` → exit 0.

The diff vs merge base `78133c093` touches no Python and no workflow
files, so the Python-only quality pillars measure trees identical to
protected `develop`. Settings/Skills/Profile smoke from the original
test plan remains UNVERIFIED here — it needs the live stack.

## Verification (develop-sync round, head `ff367f356`)

The preserved `origin/develop` sync conflict (CHANGELOG.md, three-way
diff3 on the CodeQL scope-test Unreleased line) was resolved by taking
develop's wording (`#2359; follow-up to #2357`, a superset of the
branch-side `#2359` edit), and `origin/develop` (`10f872fa7be3`) was
merged; merge head `ff367f356`. Every gate was re-run locally at the
new head, all green:

- `uv run python scripts/check-frontend-typed-client.py` → exit 0:
  base `10f872fa7be3` → candidate `ff367f356f69`, **42 → 40 raw fetch,
  120 → 119 hand-typed, none new**.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0: 1248
  identities, exact ledger match, `unclassified: 0`,
  `never_allowlist: 0` (count moved 1253 → 1248 with develop's own
  churn; the ledger needed no candidate-side amendment).
- `uv run python scripts/check-shipped-surface-truth.py` → exit 0
  ("matrix is complete"; the 4 stale `mutating-api-call` rows stay
  dropped).
- `uv run python scripts/check-ratchet-provenance.py` → exit 0.
- `uv run python scripts/check-doc-links.py` → exit 0 (covers the
  resolved CHANGELOG conflict).
- `uv run python scripts/check-release-consistency.py` → exit 0.
- `uv run python scripts/check-suite-inventory.py` → exit 0 (21
  suites match; the branch adds no tests, and a no-count note records
  no `inventory-delta` block by design).
- `uv run ruff check .` and `uv run ruff format --check .` → clean.
- `npm run build` in `packages/hive-conductor/frontend` → exit 0
  (tsc + vite, built in ~2s).

The wave-1 SSE waiver holds at this head: the Profile stream fetch
lives under `lib/profile.ts` (detector-exempt, per its own comment
about the 30s shared-client body budget). Live-stack smoke
(Settings load/save, Skills list, Profile stream, `hctl status`)
remains UNVERIFIED.

## Verification + supply-chain repair round, head `42d433c2c3c2`

Branch merged `origin/develop` (`f8a2df966a1d`, the then-tip) so the
merge base measures the tree the queue integrates into; `origin/develop`
still resolved to `f8a2df966a1d` at repair time (no newer sync needed).
All branch-content gates re-run green at the merge head:

- `uv run python scripts/check-frontend-typed-client.py` → exit 0:
  base `f8a2df966a1d` → candidate `42d433c2c3c2`, **42 → 40 raw fetch,
  120 → 119 hand-typed, none new**.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0: 1238
  identities, exact ledger match, `never_allowlist: 0` (no candidate
  ledger amendment needed).
- `uv run python scripts/check-shipped-surface-truth.py`,
  `check-ratchet-provenance.py`, `check-suite-inventory.py` (21
  suites), `check-doc-links.py`, `check-release-consistency.py` → all
  exit 0.
- `uv run ruff check .` and `uv run ruff format --check .` → clean.
- `npm run build` in `packages/hive-conductor/frontend` → exit 0
  (tsc ×2 + vite, ~4s).

### Supply chain (pip-audit) — reproduced and repaired

The hosted failure was reproduced locally against the frozen env:
four advisories outside the triaged allowlist — dnspython 2.9.0
CVE-2026-128089 (fix 2.9.2), graphql-core 3.3.0 CVE-2026-119286 (fix
3.3.1), joserfc 1.7.5 CVE-2026-119284 (fix 1.7.6), opentelemetry-api
1.45.1 CVE-2026-126360 (fix 1.45.2). The branch's diff touches no
Python dependency input (no `uv.lock`, no `pyproject.toml`), so the
advisories fail identically on the develop base — trunk drift, not a
regression — but they are concretely fixable, so this round fixed them
per the gate's own instruction ("Fix by upgrading the dependency") and
the documented `constraint-dependencies` precedent (#891/#2238, #1084,
CONNECT tip #2327 rounds):

- Dev transitive floors raised in `[tool.uv] constraint-dependencies`:
  `dnspython>=2.9.2` (was 2.9.0), `graphql-core>=3.3.1` (was 3.3.0),
  new `joserfc>=1.7.6` — each annotated with the advisory and round.
- Production floor raised where the package actually ships:
  `opentelemetry-api>=1.45.2` in the root `dependencies` and
  `>=1.45.2,<2` in `maistro-core`'s `observability` extra.
- `uv lock` moved exactly the 6-package security closure (the four
  targets plus opentelemetry-sdk and opentelemetry-semantic-conventions
  pulled by the sdk); `uv sync --locked` clean.
- CI-exact re-run (`uv sync --locked --all-extras` → freeze →
  `pip-audit --strict` → `scripts/pip_audit_gate.py`) → exit 0:
  "pip-audit OK (1 known, all triaged in ALLOWED)"; direct-dependency
  usage OK.
- The hive-conductor runtime export (`uv export --locked --package
  hive-conductor --no-dev`) contains exactly one of the four packages —
  opentelemetry-api, now 1.45.2 — so the image's Python closure clears
  the advisory set too. `maistro-core[observability]` (the image's
  second dependency contract) imports cleanly at 1.45.2 with the
  tracer resolvable.

### Container scan + SBOM + cosign — not branch-attributable, partially addressed

The hosted log excerpt carries no step-level finding (bare exit 1).
This branch cannot introduce HIGH/CRITICAL image findings: it changes
no Dockerfile, no npm dependency, and its only image-relevant input is
frontend TS source. The single image-visible Python advisory
(opentelemetry-api) is fixed by the lock bump above; an OS-package or
infrastructure verdict (the workflow documents the libexpat/cache
classes) would fail identically on develop and needs a hosted re-run —
UNVERIFIED locally by design (a 4-image Trivy/Grype pipeline does not
fit this repair round's budget).

`security` is the workflow-level aggregate: its SAST legs passed on
this head and its remaining children are the two jobs above.

