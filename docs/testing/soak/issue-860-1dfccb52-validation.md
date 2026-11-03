# Issue #860 — validation checkpoint (job `1dfccb5269334bef929d96655e2cca4a`)

**Disposition: NEEDS-REPAIR; no promotion approval.** The dispatched tree at
`5e22cfdc5faf981e288dc888e24871cbd18e8bc1` was clean at start. The supplied job
directory contains no `check-*.log` files; prior verification reports were
used only as pointers and key checks were rerun below. Issue #860 is the frozen
scope; no live GitHub queries or mutations were made.

## Fresh checks

- `uv run pytest tests/test_soak_promotion_gates.py -q -x` — **84 passed**.
  Regression test `tests/test_soak_promotion_gates.py:480` exercises replica
  selection with the real limiter seam; these tests do not establish
  cluster-wide rate-limit state or production RC behavior.
- `uv run ruff check .` — **passed**.
- `uv run ruff format --check .` — **passed**, 3366 files formatted.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — **passed**, 1326 reviewed identities / 1326 findings, base `e20e9f52ea94`.
- `uv run python scripts/check-reachability.py` — **failed**: `maistro.runs.admission_identity` is newly unreachable (169 unreachable modules vs trusted baseline 168). This gate's diagnostic says nothing imports the module. The finding is not a test/fixture to waive; determine its intended production call path or remove dead code in a separately scoped repair.

No test was added, so no suite-inventory delta is applicable.

## Acceptance evidence and blockers

The issue's ten criteria remain governed by the production RC, not by a host
preflight. `scripts/soak/run_soak.py:19-20` says host-process preflight cannot
sign promotion; its `PROMOTION_MIN_SUSTAIN_SECONDS` is 14,400 at line 69. The
tracked round-109 artifact is therefore useful bounded historical evidence,
not acceptance of the present candidate:

- `docs/testing/soak/evidence/m3a-round109-shakedown.json:219-224,283-287`
  records 420.05 seconds, `exact_rc_artifact.ok=false`, host-uvicorn topology,
  and the 14,400-second minimum. It is not a four-hour exact-RC soak.
- `docs/testing/soak/m3a-load-profile.md:167-183` explicitly marks concurrent
  users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas,
  and Goal/background reconciliation as gaps. The profile also notes its
  process/telemetry limitations.
- `packages/maistro-server/src/maistro_server/api/rate_limit.py:32-37,93`
  documents a separate in-memory budget per replica (N replicas yield N times
  the configured aggregate budget). This is contrary to issue criterion 5's
  replica-selection resistance, despite the passing local enforcement tests.
- `scripts/soak/run_soak.py:1064-1088` terminalizes the schedule probe Run as
  cleanup; a cancelled admission probe is not physical-work fencing/recovery
  evidence. Preserve the canonical `Goal -> Graph -> Run -> NodeRun -> Attempt`
  execution authority; do not treat the soak harness as a competing scheduler.
- The evidence's commit hash must be checked against the candidate before use;
  historical soak data cannot certify a later code/configuration identity.
  The required exact-RC artifact/configuration and authorized >=4-hour
  production window are not established by this dispatch.

Accordingly: representative exact-RC workload, production multi-replica
execution, long-window saturation/queue/reclaim/leak behavior, exactly-once
physical work, full production telemetry, active-work kill/restart recovery,
exact-RC soak, pre-promotion finding disposition, and RC-hash-bound published
evidence are **UNVERIFIED or unmet**. The bounded historical run does provide
partial functional observations only; it does not close those criteria.

## Architecture and next step

Read ADR-085 (principal-keyed limits), ADR-081426-1f7c (ExecutionRuntime owns
mechanics, not persisted lifecycle), ADR-081626-f383 (canonical Run store owns
lease/fencing authority), and ADR-073126-c4e1 (RC artifacts are cut from
`develop` and soaked before promotion). These decisions do not waive the issue's
cluster-selection, physical-work, or exact-artifact proofs. No competing
scheduler, event authority, or authorization path is introduced.

Next: resolve the genuine unreachable production module separately; reconcile
and fix replica rate-limit semantics; select an immutable RC/configuration and
supported representative topology; then run and publish a >=4-hour exact-RC
soak with physical-work fencing/recovery and production telemetry coverage.
This lane has no basis to fabricate those external operational proofs or weaken
the promotion gates. Progress: checked 1 issue, done 0 acceptance-complete,
skipped 0, validation errors 1 (reachability gate), acceptance blockers
recorded above.
