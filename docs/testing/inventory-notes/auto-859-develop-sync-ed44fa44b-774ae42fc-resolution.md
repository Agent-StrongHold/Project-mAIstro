---
inventory-delta:
  tests/: +0
  packages/maistro-turing/backend/tests: +0
  packages/maistro-turing/tests: +0
  packages/maistro-core/tests: +0
---

# auto-859-develop-sync-ed44fa44b-774ae42fc-resolution

Second sync round for #859 ([M5-A][#27] Scope Turing self-model/chat state to
canonical Workspace principals and enforce bounded state writes). Merges the
two develop tips that landed after the previous round's sync of `a9fdec4cb`:

- `ed44fa44b` — #2227 run-store actor binding; touched
  `packages/maistro-core/src/maistro/runs/*` (new `access.py`,
  `store_boundary.py`), `packages/maistro-server`, `quality/image-pins.json`
  and the golang builder pin.
- `774ae42fc` — Playwright image/clients 1.64.0 (#2097); e2e harness only.

## Conflict resolution

Four conflicted paths, all the same joint-discovery collision: both sides
refreshed the `golang:1.27.2-alpine` builder to `1.27.3-alpine` for
CVE-2026-111943 on the same day, but resolved the tag to two different index
digests (ours `d530cf60…`, develop's `b8c9b82a…`). Upstream re-serialized the
tag's index hours later with unchanged per-arch content, so develop's
`b8c9b82a…` is the current, canonical resolution and is taken verbatim for
`Dockerfile`, `Dockerfile.research`, `packages/hive-conductor/Dockerfile` and
`quality/image-pins.json` (`--theirs` for all four). `uv.lock` auto-merged.

## Merged-head evidence (846d299ba)

- Acceptance-state gate, CI's exact invocation
  (`uv sync --locked --all-extras` + maistro-evolve editable + pytest-timeout
  + age-keygen + pgvector:pg18 migrations + `MAISTRO_TEST_PG_DSN`):
  `scripts/check-ac-state.py --run-tests --ratchet` exits 0 with
  design_coverage measured at 44.2377, exactly on the banked floor, and the
  pre-landed grant #166 authorizes the floor at 39.641; with
  `--mandate 774ae42fc` the mandate legs also exit 0 (no unproven criteria,
  no absent links introduced). The earlier "stale vs measured 39.641" report
  was an under-instrumented local environment (`--extra dev` only), not a
  regression: without the evolve extra several @AC tests cannot run and the
  measured coverage lands on the granted floor value.
- Container gate re-proven first-hand at the merged head with all five
  `buildx-build-retry.sh` builds (engine, engine-research, rsi-runner,
  hive-conductor, hive-conductor-observability), both in-image contract
  checks (identity=operational / observability=importable, python 3.13.16),
  trivy 0.73.0 (HIGH,CRITICAL, ignore-unfixed, `.trivyignore.yaml`) exit 0 on
  all four gated images, grype 0.116.0 `--fail-on high --only-fixed` exit 0
  on all four (residual matches all Medium/Low/Negligible), and
  syft 1.49.0 SBOMs (8 surfaces, 25911 components) with
  `check-license-inventory.py` OK (copyleft=426, policy=review). The job's
  cosign leg is absent by design: signing was removed pending a real registry
  push (see security.yml).
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`: 1314 reviewed identities = 1314 findings, no amendment.
- Turing acceptance suites: 221 passed (chat, scope isolation, state, state
  scoping, bridge, runtime, self-model types, tiers); merge-touched core
  suites (runs access, store boundary, container chat/wiring, authz ladder):
  135 passed; `tests/test_pinned_digest_references.py`: 8 passed.
- `check-image-pins.py`: 8 pins across 10 Dockerfiles, all registered;
  `check-suite-inventory.py` reports the turing backend, turing and
  maistro-core suites matching the recorded inventory; ruff check + format
  clean.

No test nodes added or removed by this round (inventory-delta +0): the merged
test files are develop's own suites, whose counts the recorded baseline
already matches (verified for the three suites the merges touched).
