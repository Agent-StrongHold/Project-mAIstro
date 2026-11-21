# Issue #860 — bounded repair result (job `6c6bc52a`)

## Scope and validation

Processed only issue #860 in `/home/dev/Git/wt/auto-860`, branch `auto-860`, at dispatched HEAD `aac04b99a83eb5e9236f8f43c64330ec584b0692` (develop base `c2d7209f1dbc1039e8ca9d99444b88ded3bbe26b`). Worktree was clean at entry. Dispatch job directory had no `check-*.log` files; the supplied prior result was read as evidence, not accepted as current validation. No GitHub queries or mutations were performed.

Read repository guidance and accepted ADR-081226-a66b (Run/NodeRun/Attempt lifecycle), ADR-081626-f383 (Attempt lease fencing), and ADR-085 (per-principal rate limits); see the docs/adr corpus. The execution authority remains the canonical `Goal -> Graph -> Run -> NodeRun -> Attempt`; no alternate scheduler, state store, event authority, or authorization path was introduced. ADR-085's per-principal wording does not erase issue #860's explicit replica-selection falsification criterion.

Fresh validation at the dispatched HEAD:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS, 1326 findings / 1326 reviewed identities, zero unclassified or never-allowlist findings. No ledger repair justified.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — PASS, 84 passed.
- `uv run ruff check . && uv run ruff format --check .` — PASS; 3373 files formatted.
- `uv run python scripts/check-backlog-consistency.py` — PASS, 168 backlog items.

No code or tests were changed: the current request supplies no deterministic acceptance failure that can be repaired by changing this test harness or recording invented deployment results. No inventory note is needed (inventory delta zero). The production soak prerequisites/evidence gaps remain substantive.

## Acceptance assessment

| #860 criterion | Evidence / disposition |
|---|---|
| Representative profile covering concurrent users/Workspaces, request mix, fan-out, schedules, tools/models, Canvas and workers | **UNVERIFIED** — `docs/testing/soak/m3a-load-profile.md` explicitly lists missing population, fan-out, successful tool/model, Canvas and Goal/background traffic. |
| At least two supported production replicas | **UNVERIFIED** — host-process preflight is not the promoted Compose topology; exact-RC evidence is unavailable. |
| Sustained saturation, queue/lease/retry behavior, memory/descriptors, shutdown/restart | **UNVERIFIED** — no >=4-hour deployed soak was run. Historical evidence is shorter and fails the declared duration/artifact conditions. |
| Exactly-once/fenced physical execution and Goal reconciliation | **UNVERIFIED** — `scripts/soak/run_soak.py` schedule probe races admission then terminalizes its queued Run; it does not execute a physical Attempt or prove cross-replica fencing. |
| Rate limiting/security cannot be bypassed by replica selection | **NOT SATISFIED by available implementation evidence** — middleware has process-local state and tests demonstrate independent per-replica allowances for the same identity; this is not a shared aggregate budget. |
| PostgreSQL, application-loop, worker, RSS, descriptors, queue and error telemetry with thresholds | **UNVERIFIED** — profile records that driver-loop lag is not application-loop lag and that production-grade worker/pool and long-window measurements are missing. |
| Kill/restart active replica and prove drain/fencing/recovery | **UNVERIFIED** — no active physical Attempt recovery experiment on the exact deployment artifact. |
| Long soak of exact RC artifact/configuration | **NOT SATISFIED** — no exact RC topology/image/config hash pack; host preflight is expressly not promotion evidence. |
| Classify load findings before promotion | **PARTIAL / UNVERIFIED** — an existing rate-limit budget gap is categorized, but no representative RC soak exists to identify/classify its findings. |
| Machine- and human-readable evidence tied to exact hashes | **UNVERIFIED** — local deterministic validation is not a production soak evidence pack tied to immutable image/configuration hashes. |

Disposition: **BLOCKED for acceptance**. Passing deterministic checks do not establish the required production soak. Next evidence prerequisite is a designated immutable RC artifact/configuration and a representative multi-replica deployment run meeting the profile's duration, telemetry, active-work recovery and hash-binding requirements. This is a local handoff, not integration or promotion approval.
