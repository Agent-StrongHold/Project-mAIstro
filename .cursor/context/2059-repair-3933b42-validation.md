# #2059 repair round — exact-head validation log (2026-11-17)

Lane CR2059, job `5b0e27b0ceba4aa095b3b29c0fe3fc7e`.
Head: `3933b42ed2a1ab0e2e2ccaf6e21cf60fa1516609`
(= PR #2059 head on GitHub; merge of develop `a660bc2a9d0b` into
`fix/vulture-single-owner-1357`). Base: `a660bc2a9d0b` (develop).
No code changes were required this round; this file is the evidence record.

## Driver brief vs reality

- Brief said "CI GATE FAILURES from your last merge-queue evaluation — CI
  response truncated". Read-only check-run inspection of the exact head shows
  **zero failures**: every formerly-RED gate (exact-debt-ledger, Quality /
  Acceptance state, Architecture fitness, Agent store writes, BFCL provenance,
  Backlog consistency, Contract markers, Convergence matrix, Vulture) is
  `success` at this head; `Container scan + SBOM + cosign` is `skipped`
  (expected for the event shape; its develop-targeted sibling succeeded).
  Only `Coverage gate` and `test` were still running at 08:32Z.
- The lane's named repair (vulture per-identity ledger amendment) is NOT
  needed: the ledger already reconciles.

## Local replays at the exact head (CI-exact or CI-shaped)

| Gate | Invocation | Result |
|---|---|---|
| sync | `uv sync --locked --all-extras` + maistro-evolve + vulture/radon/xenon/interrogate/pytest-timeout | OK |
| Ruff | `uv run ruff check .` / `ruff format --check .` | exit 0 |
| exact-debt-ledger | `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | exit 0 — 1236 reviewed identities = 1236 findings, base a660bc2a9d0b |
| ratchet provenance | `scripts/check-ratchet-provenance.py` | exit 0 (55 consumers) |
| shipped surfaces | `scripts/check-shipped-surface-truth.py` | exit 0 |
| suite inventory | `scripts/check-suite-inventory.py` | exit 0 — 21 suites, 35,599 unique identities |
| backlog | `scripts/check-backlog-consistency.py` | exit 0 (167 items) |
| Acceptance state | pgvector:pg18 @127.0.0.1:55433 + `alembic upgrade head` + `RATCHET_BASE_REV=origin/develop MANDATE_BASE_SHA=a660bc2a9… scripts/check-ac-state.py --run-tests --ratchet --mandate …` | exit 0 — design_coverage **44.4608** exactly on the bank (`quality/ac-state-notes/fix-vulture-single-owner-1357.json`); mandate + chain mandate OK |
| 23 static quality gates | radon-baseline, release-consistency, doc-links, enumerations, workspace-retirement, route-permissions, principal-identity, frontend-typed-client, reachability, credential-authority, wiring-reads, agent-store-writes, contract-markers, convergence-matrix, reachability-dispositions, security-inventory, image-inventory, image-pins, workflow-inventory, execution-lifecycles, model-egress, design-model-egress, foreign-harness-egress | all exit 0 |
| provenance vendors | `vendor_bfcl.py --check`, `vendor_ifeval.py --check`, `bump_version.py --check` | exit 0 (42 sites @ 0.9.0) |
| Architecture fitness | `pytest packages/maistro-core/tests/fitness -q --timeout=30` | 39 passed |
| mypy strict | `mypy --strict packages/maistro-core/src` | Success (842 files) |
| pyright gate | `pyright --outputjson packages/maistro-core/src` + `check-pyright-report.py --baseline 23` | 12 errors ≤ 23, exit 0 |
| radon scan | `radon cc packages/*/src -i third_party --min B --total-average` (+ mi) | exit 0 |
| xenon | CI-exact `xenon --max-absolute B --max-modules B --max-average A -i third_party <10 packages>` | 126 block identities = XENON_BASELINE 126; module ledger 0 added / 0 fixed |
| docstrings | all 13 `interrogate -f <floor>` invocations | all pass |
| pip-audit | `uv pip freeze --exclude-editable` + `pip-audit --strict` + `scripts/pip_audit_gate.py` | 1 known (ecdsa, allowlisted); exit 0 |
| merge-touch tests | root tests union of both merge sides (incl. `test_ci_vulture_ownership.py`, `test_devskim_scan_scope.py`, `test_prepull_base_images.py`, `test_check_image_pins.py`, 4 floor tests) | 215 passed |

## Findings resolution

1. **design_coverage "non-reproducible bank" (prior finding) — REFUTED with
   evidence.** The earlier unstable values (39.86 / 44.39 / 44.23) came from
   incomplete environment replays (no DB / missing extras / missing
   maistro-evolve). With the full CI shape the measured value reproduces the
   banked 44.4608 exactly. Bank is sound; no ledger edit made.
2. **Issue-body prose staleness** ("1,328 identities", "5,066 cases", draft
   status, "sole semantic workflow change"): confirmed stale (actual: 1,236
   identities at this head, gate passing; inventory 21 suites matching).
   Prose only — GitHub mutations are out of scope for this lane.
3. **Vulture ledger**: no unbanked identities; the instructed amendment is a
   no-op. Gate green locally and hosted.

## Hosted CI at the exact head (read-only API inspection, 08:29–08:32Z)

- 122 check runs completed, 0 failures; formerly-RED set all `success`.
- Pending at last poll: `Coverage gate (publish-set floor + diff coverage)`
  ×2 (started 08:24/08:28Z) and `test` (started 08:09Z). Their content is
  locally covered: candidate `packages/*/src` is byte-identical to develop's
  green tree (branch overlay touches no src), and every root test the merge
  touched passes locally.
- PR state: open, non-draft, `mergeable: true`, `mergeable_state: blocked`
  (branch protection holding on the still-running checks / review — not a
  gate failure).
