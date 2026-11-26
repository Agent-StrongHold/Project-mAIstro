---
inventory-delta:
  tests/: +0
---

# cr-1532 verifier validation at 6e94972e — sole hosted red remains the external, unpatched picomatch advisory

Re-validation round for PR #1532 (retire body status lines, ADR-092126-a28a).
Exact head `6e94972e1f56126d3e775f0d8e076c43bd87fa37` (local verifier-notes
commit on top of the develop sync `26ce281dc22e`), base
`d0e8e235a896d2644b33852f64cbdca1766ec59e` = origin/develop tip (re-fetched
2026-11-18: develop has not moved, so no new sync was needed). Worktree
arrived clean; every claim below was re-executed in this tree this round.

## 1. Merge-queue state — the old conflict block is gone

- `GET pulls/1532` (read-only, 2026-11-18): `mergeable: true`,
  `mergeable_state: "blocked"`, base `d0e8e235a8` — the earlier
  CONFLICTING disposition is resolved by the `26ce281dc22e` develop sync; the
  branch is blocked only by commit statuses.
- Hosted check runs at `26ce281dc22e` (captured in this round's dispatch
  context, 2026-11-18T05:40Z): **77 of 78 `success`, 1 `failure`** — the
  single failure is the `test` job. The previously-unobserved `Coverage gate`
  now appears inside the 77 successes; nothing else is red.
- Head `6e94972e1f` is local-only (docs-only note; not pushed, per lane
  rules), so hosted CI has not evaluated it; it changes no frontend or
  workflow file.

## 2. The one failing step, re-proven external this round

CI's exact step (`ci.yml:702`, `npm audit --audit-level=high` in
`packages/maistro-canvas/frontend`): re-run locally → **exit 1**, 6 high
findings, all one root — picomatch GHSA-fc5q-39xc-vjpf via
`vitest 5.1.0 → tinyglobby 0.2.17 → fdir 6.5.0 → picomatch 4.0.7`
(dev tooling only).

- Advisory re-checked live (2026-11-18): `GHSA-fc5q-39xc-vjpf` →
  `vulnerable_version_range: "<= 4.0.7"`, **`first_patched_version: null`**
  (advisory updated 2026-11-17T15:56:44Z, not withdrawn); `npm view picomatch
  version` → **4.0.7**, registry last modified 2026-08-24. There is still **no
  patched release to lock-regenerate to** (the #859 recipe has nothing to
  pick up).
- npm's only offered fix remains `vitest@3.1.4` — a breaking semver-major
  downgrade contradicting develop's `vite ^8.1.6` / `vitest ^5.0.0` pins.
  `git diff origin/develop..HEAD` over the canvas `package.json` +
  `package-lock.json` is **empty** (re-verified): the failure is inherited
  from develop tip, not introduced by this branch.
- The step immediately before it in CI was re-run with CI's exact commands:
  canvas `npm ci` exit 0 and `npm run test:ci` → **84/84 passed** — the
  advisory breaks install-time audit metadata, not tests or builds.
- Disposition unchanged from the prior round and consistent with the #1896
  CI-repair precedent (`.cursor/context/pi-foremen-recovery.md`): **no
  non-weakening in-tree fix exists**. Re-run once upstream publishes
  picomatch > 4.0.7 (then `npm install --package-lock-only` per #859) or a
  policy owner re-scopes the audit gate.

## 3. Acceptance surface re-derived at this head (all exit 0 unless noted)

- `check-adr-status-language.py` → "0 baselined body-status contradiction(s),
  no new ones, none stale"; `check-adr-status-language-provenance.py` →
  metric v2, empty-ledger migration, "0 contradiction(s), no candidate-
  approved expansion"; `check-adr-index.py`; `check-contract-markers.py`;
  `check-release-consistency.py`; `check-ratchet-provenance.py` (55
  consumers); `check-merge-markers.py`;
  `check-citation-status-provenance.py`; `tools/lint_lifecycle.py`.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` (CI-exact) → exit 0, **1236 reviewed identities =
  1236 findings**, candidate `6e94972e1f56` — no unbanked identities, no
  ledger amendment needed or made.
- `check-suite-inventory.py` → ok, 21 suites match the recorded inventory.
- `ruff check .` clean; `ruff format --check .` → 3573 files already
  formatted.
- Targeted evidence suites: `tests/test_check_adr_status_language.py` +
  `tests/test_check_adr_status_language_provenance.py` +
  `tests/test_check_adr_index.py` + `tests/test_check_contract_markers.py`
  → **158 passed**.
- Independent corpus scan (not via the gate): 450 `.md` files under
  `docs/adr` + `docs/specs`, **zero** `**Status:**` body lines at ≤3-space
  indent, either spelling. `CHANGELOG.md:623` carries the literal `(#1532)`
  marker under `### Changed` (:620) inside `## [Unreleased]` (:24);
  `docs/adr/ADR-092126-a28a-retire-body-status-lines.md` present; ADR-INDEX
  row at :219.

## 4. Residual risks for the integrator

- The `test` job (audit step) stays red — and therefore the `gates-ran`
  rollup statuses — until upstream ships a patched picomatch or the gate is
  re-scoped by a policy owner. Everything else on the branch is proven green
  locally with CI-exact commands and the hosted run agrees (77/78).
- Commit-message auto-close risk carried from earlier rounds
  (`e9aad7356` "Closes #1127, #1098, #1056, #1109, #1143", `0df275362`
  "(Closes #76 AC-2)") remains in ancestry; `check-closure-targets.py`
  scans only PR title/body. History rewrite is prohibited — merge-time
  policy decision, not an in-tree fix.
- One order-dependent flake observed once in the prior round
  (`test_property_marked_field_is_immediately_locked`, passes standalone)
  sits after the audit step in CI and never ran there.

No tests added or moved this round → `+0`.
