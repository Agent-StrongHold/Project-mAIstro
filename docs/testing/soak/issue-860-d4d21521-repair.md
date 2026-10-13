# Issue #860 validation — job d4d21521

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`8ab52ec5d6ecb94ad9dde48fe4250acbeb207c0e`, supplied develop base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Worktree clean at start; no
salvage needed; no remote mutations. Re-resolution of the previous round's
`BLOCKED` handoff (job 5f3a18a8) was attempted; nothing else.

This job directory contains **no driver `check-*.log` files**. The only
supplied failure log is the prior job's
`98a113…/check-3.log` (schema-fence DDL count). It was revalidated directly.

## Deterministic checks executed on HEAD

| Command | Result |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | **37 passed, 6 skipped.** The reported 24-vs-21 DDL fence failure is stale; the current test asserts the full ordered DDL body. |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | **Clean:** 1323 reviewed identities → 1323 findings, `unclassified: 0`, `never_allowlist: 0`. No ledger amendment warranted in this round. |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | **65 passed.** Includes the contrary-evidence replica-allowance tests. |
| `uv run ruff check .` | All checks passed. |
| `uv run ruff format --check .` | 3270 files already formatted. |
| Executed evaluator on retained `evidence/m3a-round43-shakedown.json` | `failed_promotion_checks` → `['sustain_duration', 'exact_rc_artifact']`; observed 420.09 s vs 14400 s minimum; `preflight_artifact_check()` → `ok: False`, "not the exact production Compose image and configuration". |

## Prior findings re-confirmed at HEAD (real, not stale)

- `tests/test_soak_promotion_gates.py:439` — passing test documents that each
  replica grants an independent allowance: production installs
  `RateLimitMiddleware` per process (`main.py:648`) and each instance
  constructs its own `InMemoryRateLimiter` (`api/rate_limit.py:93`). Same
  identity + same IP receives fresh budget per replica, so the "cannot be
  bypassed by replica selection" criterion has standing contrary evidence.
  Architecture change belongs to the security/rate-limiting owner (#842),
  not this soak lane.
- `scripts/soak/run_soak.py:730` — `preflight_artifact_check()` rejects
  host-process equivalence by design, with no CLI override; a
  promotion-signing soak requires the exact Compose image/config identity per
  `m3a-load-profile.md` (artifact identity contract).

## Acceptance audit (unchanged outcome, re-executed evidence)

| Criterion | Evidence / gap |
| --- | --- |
| Representative RC load profile | Profile documented with explicit remaining gaps (concurrent users/Workspaces, Graph fan-out, model/tool success paths, Design/Canvas, Goal workers). UNVERIFIED as complete. |
| ≥ 2 deployed RC replicas | Preflight emulator runs two host uvicorn processes, not the RC Compose topology. UNVERIFIED for RC. |
| Sustained saturation/reclaim/leak/restart observations | Evaluator requires ≥ 14400 s; retained evidence is 420.09 s. UNVERIFIED. |
| Physical-work uniqueness / Goal reconciliation | Admission probes race one occurrence; not physical-effect accounting at promotion grade. UNVERIFIED. |
| Rate-limit non-bypass under replica selection | **Contrary evidence reproduced** (per-replica in-memory limiter); needs security-owner disposition. |
| Telemetry with thresholds | Driver-loop lag measured; application event-loop lag and worker/container-cgroup series absent. UNVERIFIED. |
| Kill/restart drain/fencing/recovery | Drain probe machinery exists and is gate-enforced; no live RC recovery evidence. UNVERIFIED. |
| Long soak of exact RC artifact/configuration | Blocked mechanically by `exact_rc_artifact`; no RC identity supplied this round. UNVERIFIED. |
| Findings filed/reclassified to earliest invariant | Local filing exists (drain defect, H3 allowance note); remote filing is prohibited for this worker. Partial. |
| Hash-bound machine/human evidence | Exists for preflight rounds only; cannot sign promotion. UNVERIFIED for RC. |

## Disposition

**NEEDS-DEEP-REVIEW.** Every check a repair worker can execute is green; the
one supplied CI failure is stale on HEAD; the vulture ledger needs no
amendment. The remaining acceptance criteria are not code defects in this
lane — they require ownership decisions and resources an isolated worker
cannot supply:

1. Release owner selects and publishes the exact RC artifact/configuration
   (#89 promotion candidate) for the soak.
2. A production-equivalent environment runs the ≥ 4 h Compose soak with the
   artifact-identity contract captured.
3. Security owner disposes the replica-selection rate-limit bypass (#842) —
   fix or formally re-scope the acceptance criterion.
4. Maintainer disposition of remaining load-discovered findings to their
   earliest broken milestone invariants.

No code, test, or ledger edit was made: changing anything to generate a diff
would not address actual evidence. No test added or changed, so no inventory
delta is required. Existing evidence, sources and ledgers preserved.

Checkpoint: `{checked: 6, done: 0, skipped: 0, errors: 0, next: "RC selection, soak environment, #842 disposition, finding routing"}`.
