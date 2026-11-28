# Issue #860 — assigned-round acceptance revalidation

Scope: issue #860 only, in `auto-860` at `10d7ed472009f9548feab314ebaec53eb4e6ef91`. Dispatch job `fa14555c7ab24e53a4e8c9c3a1d90374` contains no `check-*.log` files. The supplied prior result was reviewed, and its key promotion blockers were checked against repository behavior and evidence. No source change can safely create an exact production-RC soak without the selected immutable RC/configuration and authorized multi-replica deployment; this note records the unresolved acceptance rather than claiming implementation evidence.

## Architecture and policy

Read `docs/README.md`, accepted `docs/adr/ADR-081-deployment-backup-dr.md` (supported horizontal Stronghold profile, drain, measure-first capacity), and the soak profile. ADR-081 sets no numeric throughput target and does not waive measured production acceptance. A guessed `ADR-047-distributed-rate-coordination.md` path did not resolve; not read or used. No execution authority or rate-limit policy was changed.

## Executed checks

- `uv run python` imported `scripts.soak.run_soak`, ran `preflight_artifact_check()` and `failed_promotion_checks()` on `docs/testing/soak/evidence/m3a-round109-shakedown.json`: preflight returned `ok: false`, topology `host-uvicorn-preflight`; recorded sustain was `420.05` seconds against `14400`; promotion checks failed `sustain_duration` and `exact_rc_artifact`.
- `uv run pytest packages/maistro-server/tests -q -x -k 'replica_selection'`: exit 5, 626 deselected, no matching tests. The prior result's claim of two passing replica-selection tests is therefore not independently reproduced in this checkout; it is not counted as acceptance evidence.
- Source inspection: `scripts/soak/run_soak.py:744-752` intentionally hard-codes exact-RC preflight failure because it boots host processes; `docs/testing/soak/m3a-load-profile.md` documents profile gaps and states these are blockers.
- No tests were added; no suite inventory delta is applicable.

## Acceptance disposition

| Issue #860 criterion | Evidence / disposition |
|---|---|
| Representative RC profile across users/Workspaces, request mix, Graph, schedules, tasks, tools/models, Canvas and workers | **NOT MET** — `docs/testing/soak/m3a-load-profile.md` documents unresolved population and surface gaps; no selected RC deployment profile evidence. |
| At least two application replicas | **UNVERIFIED** — observed harness topology is `host-uvicorn-preflight`, not production Compose. |
| Sustained saturation, lease/reclaim, retry, leak and restart window | **NOT MET** — round 109 ran 420.05 seconds, not the 14,400-second minimum; long-window required signals are not established by that evidence. |
| No duplicate physical work across claimed fenced/exactly-once operations | **UNVERIFIED** — no qualifying exact-RC multi-replica physical-work evidence. |
| Rate limiting/security cannot be bypassed by replica selection | **UNVERIFIED** — targeted selection test command found no matching tests; no production multi-replica proof. |
| Required telemetry and explicit thresholds | **PARTIAL** — harness has thresholds/signals, but this short host preflight is not promotion-grade evidence. |
| Kill/restart graceful drain, fencing and recovery under active work | **UNVERIFIED** — no qualifying production artifact result. |
| Long-running soak of exact RC artifact/configuration | **NOT MET** — driver returns exact-RC `ok:false`; round 109 fails `sustain_duration` and `exact_rc_artifact`. |
| Findings filed/reclassified before promotion | **PARTIAL** — existing notes identify gaps; no production soak findings to classify. |
| Human/machine evidence tied to exact artifact and hashes | **NOT MET** — supplied shakedown is not an exact-RC artifact run. |

Disposition: **BLOCKED** for issue acceptance; no integration/promotion approval. The missing requirement is production-topology evidence, not a justified harness gate relaxation. No production claim or source behavior was altered.
