---
inventory-delta:
  tests/: +0
---

# cr-1532 verifier validation at 26ce281dc2 — `test` job red = external, unpatched npm advisory

Round for PR #1532 (retire body status lines, ADR-092126-a28a). Exact head
`26ce281dc22e260bb077c339bbd05e5fad77659a` (merge of origin/develop
`d0e8e235a8`, node 26-alpine #2120), base `d0e8e235a896d2644b33852f64cbdca1766ec59e`.
Worktree arrived clean; every claim below was re-derived in this tree, not
carried over from prior rounds.

## 1. The one hosted failure at this head, and its step

Hosted check runs at this exact head (captured 2026-11-18T02:02:01Z): 76 of 78
concluded `success`; `Coverage gate` was `in_progress` at capture; exactly one
concluded `failure`: the **`test`** job (run 44213795823, job 134498440230,
01:10:58Z → 01:27:09Z). All six `gates-ran` commit statuses were `pending` at
capture (they settle only after every workflow does, so the failed `test` job
is what holds them).

Step-level diagnosis, reproduced locally with CI's exact commands and order
(ci.yml `test` job). Every step green except one:

| step | result |
| --- | --- |
| `uv run pytest packages/maistro-server/tests -v` | 660 passed, 10 skipped |
| `uv run pytest packages/maistro-turing/tests` + `backend/tests` | 363 passed |
| `uv run pytest packages/maistro-design/tests` + `ext-harness` | 935 passed, 1 skipped |
| `uv run pytest packages/maistro-ext-sdk/tests` | 147 passed |
| `uv run pytest tests/ --ignore=tests/tools/registry` | 5901 passed, 139 skipped |
| hive-conductor frontend `npm ci` / `npm run lint` / `npm run build` | green (0 errors, 96 pre-existing warnings) |
| generated API types match OpenAPI (`dump-hive-openapi.py` + `gen:api` + `git diff --exit-code`) | green, no drift |
| canvas frontend `npm ci` / `test:ci` / `lint` / `build` | green: 84/84 vitest, 0 errors, built |
| **canvas frontend `npm audit --audit-level=high`** (ci.yml:702) | **exit 1 — the failing step** |
| hive-conductor backend tests | 4184 passed, 28 skipped (one order-dependent flake that passes standalone, see §4) |
| `check-suite-inventory.py` (venv interpreter, bare-python semantics) | ok: 21 suites, 35570 node IDs, 0 duplicates |
| `check-test-duplicates.py` | ok: 1764 files, 0 byte-identical groups |

The 16m11s CI job duration is consistent with reaching the audit step at the
end of the frontend block; the steps after it (hive backend, leakage,
inventory, duplicates) take ~20 more minutes and cannot have run.

## 2. Why the failing step cannot be repaired in this tree (without weakening a gate)

`npm audit --json` for `packages/maistro-canvas/frontend`: 6 high findings,
all one root — **picomatch GHSA-fc5q-39xc-vjpf** ("ReDoS through single-branch
repeated extglobs", CVSS 7.5), vulnerable range **`<=4.0.7`**, reached via the
dev-tooling chain `vite 8.3.8` / `vitest 5.1.0` → `tinyglobby 0.2.17` →
`fdir 6.5.0` → `picomatch 4.0.7`. Build/runtime bundles are untouched; this is
test/build tooling only.

- Registry re-checked fresh in this round: `npm view picomatch version` →
  **4.0.7** (latest; matches the #1896 lane's 2026-11-17 re-check). The
  advisory covers every published version, so there is **no patched release to
  pin or lock-regenerate to** — the #859 repair recipe
  (`npm install --package-lock-only` to pick up a fixed parent) has nothing to
  pick up.
- npm's only auto-fix is `vitest@3.1.4` + `vite@6.2.7` — a **breaking
  semver-major downgrade** of the canvas toolchain (`package.json` declares
  `vite ^8.1.6` / `vitest ^5.0.0`; the build uses rolldown-era APIs). That
  would diverge the frontend from develop's own pins on a governance PR whose
  contract says "No quality baseline, architecture decision, product package,
  or workflow changes", and it is a gate-weakening-by-another-name. Not done.
- **The failure is inherited, not introduced.** `git diff origin/develop..HEAD`
  over `packages/maistro-canvas/frontend/package.json` and
  `package-lock.json` is **empty** (byte-identical to develop tip
  `d0e8e235a8`), so develop's own `test` job is red on the same step today.
  The `test` job was green at the PR's September heads (`9ff899c5`,
  `12d32963` — pre-advisory).
- Precedent: the #1896 CI-repair lane hit the identical block at the same
  develop tip and independently recorded "no non-weakening in-tree fix exists
  … blocked on upstream or a policy-owner re-scope"
  (`.cursor/context/pi-foremen-recovery.md` round of 2026-11-18, commit
  `99d07cccf5`, and `06fa24df46`/`a7da3a4917`). The prior finding that the
  container scan failed on python 3.13.16 CVE-2026-115557 is **resolved** at
  this head: pins were refreshed to 3.13.18 (`95b226191b`) and hosted
  `Container scan + SBOM + cosign` concluded `success` here.

Disposition: **blocked externally**. Re-run is worthwhile once upstream
publishes picomatch > 4.0.7 (then `npm install --package-lock-only` per the
#859 recipe) or a policy owner re-scopes the audit gate.

## 3. Acceptance surface of ADR-092126-a28a, re-derived at this head

- CI-exact gates, all exit 0: `check-adr-status-language.py` ("0 baselined
  body-status contradiction(s), no new ones, none stale"),
  `check-adr-status-language-provenance.py` (metric v2 migration, 0
  contradictions, no candidate-approved expansion), `check-adr-index.py`,
  `check-contract-markers.py`, `check-ratchet-provenance.py` (55 consumers),
  `tools/lint_lifecycle.py` (baseline 0 accepted),
  `check-citation-status-provenance.py` (0 exceptions),
  `check-merge-markers.py`, `check-release-consistency.py`.
- Targeted suites: `tests/test_check_adr_status_language.py` +
  `tests/test_check_adr_status_language_provenance.py` +
  `tests/test_check_adr_index.py` → **119 passed**.
- Corpus measurement (independent of the gate): all 450 `.md` files under
  `docs/adr` + `docs/specs` scanned; **zero** bare or list-item `**Status:**`
  body lines at ≤3-space indent. Changelog `## [Unreleased] → ### Changed`
  carries the literal owning marker `(#1532)` (CHANGELOG.md:623); ADR
  `ADR-092126-a28a` present (status Accepted, `contracts: behavioral`, `tests:`
  → the evidence suite); ADR-INDEX row at line 219.
- Metric v2 chain: `quality/adr-status-language-baseline.json` records
  `metric_definition_version: "2"` with empty `known`/`details`; the checker
  emits v2 (`METRIC_DEFINITION_VERSION`), the adapter enforces
  `require_metric_version` (trusted mismatch fails; only a structurally empty
  unversioned trusted ledger can transition). Tests cover indents 0–3 across
  spellings and four-space code exemption (`test_a_body_status_line_fails_even_
  when_it_agrees`, `test_four_space_code_is_not_a_body_status_declaration`).
- Hygiene: `uv run ruff check .` clean; `uv run ruff format --check .` clean
  (3573 files); `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` exit 0 — 1236 reviewed identities = 1236
  findings, trusted base resolves to `d0e8e235a896`. No ledger amendment made
  (none needed).
- `docs/testing/inventory-notes/retire-body-status-lines.md` carries the
  `inventory-delta:` front matter (+52). No tests added or moved this round →
  this note records `+0`.

## 4. Residual risks for the integrator

- The audit step stays red until upstream ships a fixed picomatch; the
  `gates-ran` rollup statuses cannot go green before `test` does.
- `packages/hive-conductor/backend/tests/test_property_substrate.py::
  test_property_marked_field_is_immediately_locked` failed once in the full
  local backend run and passed standalone on re-run (order/resource
  dependence, not asserted-by-this-branch behavior; this step sits after the
  failing audit step in CI and never ran there).
- `Coverage gate` was still `in_progress` at context capture; its final
  conclusion at this head was not observed.
- Commit-message auto-close risk carried from earlier rounds remains:
  `e9aad7356` / `0df275362` sit in branch ancestry with `Closes #1127, #1098,
  #1056, #1109, #1143` / `(Closes #76 AC-2)`; `check-closure-targets.py`
  scans only PR title/body, so a merge auto-closes those OPEN issues.
  History rewrite is prohibited, so this is a merge-time policy decision, not
  an in-tree fix.
