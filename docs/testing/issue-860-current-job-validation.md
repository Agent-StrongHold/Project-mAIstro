# Issue #860 current-job validation checkpoint

## Scope and starting state

This writer round is limited to issue #860 on `auto-860`, starting at
`4ebc4ae035bf287a069e773ae3956ffde5d8ad82` (base
`a9fdec4cb40a62ada3e897448eabc81f2410135a`). The worktree was clean on entry.
No `check-*.log` files were present in the supplied job directory. The supplied
prior result and historical claims are not treated as fresh evidence.

## Findings and acceptance

The acceptance requires a representative production-profile soak and
promotion-grade evidence, including the exact RC artifact/configuration and a
long run. The current harness (`scripts/soak/run_soak.py`) is explicitly a
host-process preflight. `preflight_artifact_check()` hard-codes
`ok: false` for `host-uvicorn-preflight` (currently lines 744–755); changing
that result or relabeling the preflight would misrepresent what it executed.

The checked historical evidence
`docs/testing/soak/evidence/m3a-round109-shakedown.json` records
`sustain_seconds: 420.05` (line 221) against the profile minimum of 14,400
seconds (`docs/testing/soak/m3a-load-profile.md`, “Soak duration requirement &
executed evidence”). Its `exact_rc_artifact` and `sustain_duration` checks are
false. This evidence is not a qualifying exact-RC soak.

The profile itself identifies unclosed representative-coverage blockers:
multiple concurrent users/Workspaces, Graph/node fan-out, successful
provider/tool calls, Design/Canvas, Goal/background-worker reconciliation,
physical worker fencing/recovery, and application event-loop/worker/process
measurements (`docs/testing/soak/m3a-load-profile.md`, “Remaining
representative-profile gaps” and “Round-2 amendments”). Rate limiting is
explicitly process-local and does not prove an aggregate principal budget or
that replica selection cannot increase allowance. No exact-RC Compose artifact
and configuration or four-hour execution was supplied, so these criteria
cannot be demonstrated in this worktree.

No product or gate change is justified by the evidence available. This
checkpoint records blockers; it does not waive acceptance or authorize
promotion.

## ADR reconciliation

ADR-073126-c4e1 (release and versioning process) says an RC is cut from
`develop` and soaked there, with any fix requiring a new RC. It does not permit
substituting host-process evidence for the candidate artifact. ADR-081626-f383
assigns lease identity/fencing enforcement to the canonical Run store and
production Attempt execution; no competing execution authority is introduced.
The canonical execution model remains `Goal -> Graph -> Run -> NodeRun ->
Attempt`.

## Validation executed on the assigned head

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — **84 passed**.
  These test harness gate logic only, not the production topology or soak.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — **passed**; base `a9fdec4cb40a`, candidate `4ebc4ae035bf`, 1,314 reviewed identities/findings, zero unclassified and zero never-allowlist. No quality ledger was edited.
- `uv run ruff check .` — **passed**.
- `uv run ruff format --check .` — **passed** (3,454 files already formatted).
- `git diff --check` — **passed** before this checkpoint update.

No soak was run: exact RC artifact/configuration and four-hour runtime were not
available. A promotion-grade result additionally requires closure/reclassification
of load-discovered defects and proof of the listed coverage/fencing criteria.
