# Issue #860 — a8afdb65 repair checkpoint

## Frozen scope

- Issue #860 only; assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD verified as `928442eb29dbf6efa16a4bb0bff1daed307f3741`;
  dispatch base `879d66a11bf924a80bb632295e30487c49f2e9b0`.
- Initial worktree clean; no incoming edits to salvage.
- Process the supplied dispatch snapshot only (no GitHub refresh).
- Review existing soak scripts/tests/evidence and relevant ADRs; run exact
  vulture CI scan; change source/ledger only for demonstrated findings.
- Candidate write scope: this report, `quality/vulture-baseline.json` (explicit
  CI-repair exception), and existing #860 soak files only if evidence requires.
- No `check-*.log` files were present in the supplied job directory at start.

## Interpretation

This is a writer repair lane. Existing partial soak evidence is not promotion
approval. Production acceptance must remain unverified unless newly executed.
No competing execution, authorization, or event authority will be introduced.

## Progress

Initial repository identity and clean status verified. Read the captured issue
body and all 26 comments, and the supplied prior result. Prior BLOCKED was not a
develop-sync conflict, so no merge is warranted.

- Exact requested vulture gate passed: 1,338 findings / reviewed identities,
  zero unclassified and zero never-allowlist; no ledger amendment is justified.
- `git diff --check 879d66a11bf924a80bb632295e30487c49f2e9b0...HEAD`
  reproduced one concrete failure: the preceding repair report
  `issue-860-dd1bb6b8-repair.md:113` has a new blank line at EOF. Remove only that
  trailing blank line, preserving its evidence. Earlier cited whitespace
  failures did not reproduce.
- The load profile explicitly declares host-process preflight, not exact RC
  topology, and lists missing production workloads. No promotion waiver inferred.

## Executed focused validation

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 2,920 files.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests -x -q`:
  547 passed, 8 skipped, 22 Starlette deprecation warnings, 41.49 seconds.
  This includes the real middleware replica-selection counterexample for both
  authenticated and unauthenticated identities, plus live child-process sampling.
  Skips and synthetic ASGI transport tests are not production-soak evidence.
- `uv run python scripts/check-ratchet-provenance.py`: passed, 49 consumers;
  existing invalid-escape SyntaxWarning did not fail the gate.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `uv run python scripts/check-suite-inventory.py`: passed, 14 suites / 26,020
  unique identities, zero copied-file duplicate evidence.
- `uv run python scripts/check-backlog-consistency.py`: passed, 168 items.

No tests added or changed: this round repairs an evidenced whitespace gate only,
so no inventory delta is required. No source or ledger changes are justified by
the passing vulture scan.

Additional executed checks:

- With `RATCHET_BASE_REV=879d66a11bf924a80bb632295e30487c49f2e9b0`, the exact
  vulture command again passed, 1,338 reviewed identities / findings. Its trusted
  base `94781cf6b708` agrees with the independently executed
  `git merge-base HEAD 879d66a11bf924a80bb632295e30487c49f2e9b0`.
- Inline `uv run python` loaded the current soak evaluator and historical
  `evidence/m3a-round6-shakedown.json`; asserted failed checks exactly
  `sustain_duration` and `exact_rc_artifact`, and that the current driver's
  artifact check remains false. This checks rejection, not historical truth.
- `git diff --check` passed after the EOF repair. The complete branch diff is
  checked again after committing; a worktree-only check cannot clear an
  inherited committed whitespace failure.

## Architecture reconciliation

Read the repository documentation authority map, ADR-032 (contracts), ADR-081
(Proposed deployment contract), ADR-085 (Accepted principal rate limiting),
ADR-081226-a66b (Accepted execution lifecycle), and ADR-081626-f383 (Accepted
Attempt leases/fencing). The canonical `Goal -> Graph -> Run -> NodeRun -> Attempt`
model remains unchanged. Durable fences belong to the Run store and physical
execution service, not a soak-side scheduler. ADR-081 is not an accepted waiver
of production-topology acceptance. ADR-085 does not establish a cluster budget
implementation or waive #860's replica-selection criterion. The existing
middleware uses the canonical principal resolver, but has independent in-memory
state per replica; `main.py:593` installs it in the shipping application.

## Acceptance review — all ten issue criteria

| Criterion | Executed evidence / disposition |
|---|---|
| Representative release profile | PARTIAL: read `m3a-load-profile.md`; lines 152-166 explicitly omit concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background work. Representative production workload UNVERIFIED. |
| At least two supported production replicas | UNVERIFIED: production Compose declares two replicas, but current runner identifies itself as host-uvicorn preflight (`run_soak.py:635-647`). No production RC deployment executed. |
| Sustained saturation, queue growth, reclaim, retries and leaks | UNVERIFIED: current evaluator rejects historical 90.43 seconds against 14,400 minimum (`m3a-round6-shakedown.json:221-224`). Passing sampler tests do not prove a long production window. |
| No duplicate physical work, including Goal reconciliation | UNVERIFIED: historical schedule probe cancels its queued Run (`m3a-round6-shakedown.json:12-15`); admission uniqueness is not physical Attempt fencing. No current production execution/reconciliation race was observed. |
| Rate limiting/security/degraded behavior cannot be bypassed by replica selection | NOT MET for a shared allowance: executed `test_replica_selection_has_an_independent_production_allowance` for both identity classes (`tests/test_soak_promotion_gates.py:439-488`), obtaining `[200, 200, 429]` independently from both instances. Sustained RC security/degraded behavior remains UNVERIFIED. |
| Complete telemetry with explicit thresholds | PARTIAL: live `uv` child sampling tests passed; application-loop lag, worker coverage and sustained production database/queue/leak/error observations remain UNVERIFIED (`m3a-load-profile.md:158-166`). |
| Active-work replica kill/restart and recovery | UNVERIFIED: historical exit/rejoin record does not correlate in-flight physical work with fence/recovery outcomes; no new RC fault injection executed. |
| Long exact-RC artifact/config soak | NOT MET: executed evaluator rejects historical duration and artifact; even a four-hour host-process run is deliberately rejected. |
| Findings filed/reclassified to earliest broken invariant | PARTIAL: existing findings documentation and backlog gate pass; completeness of external filing/reclassification UNVERIFIED. No GitHub mutation permitted or performed. |
| Published machine/human evidence bound to exact hashes | PARTIAL: historical JSON and Markdown exist, but JSON records `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not this lane's head; exact promoted application-image/config evidence UNVERIFIED. |

## Disposition and bounded handoff

**BLOCKED.** This round fixes the reproduced branch whitespace failure and records
fresh validation; it does not complete the requested production soak. Changed
files: this report and the preceding report's trailing blank line only. No gates
weakened, ledger debt invented, runtime redesigned, or historical evidence altered.

Next prerequisites: choose the immutable RC artifact and deployment configuration;
resolve replica-wide allowance semantics through the existing security owner;
complete representative workloads and physical-work/application telemetry; then
execute at least four hours on that exact production topology with active-work
kill/restart and publish hash-bound evidence. Another vulture-only retry cannot
satisfy these prerequisites: the scanner is already green.

Checkpoint: checked 1 assigned issue; done 0 acceptance completions; skipped 0
assigned issues; errors 1 reproduced whitespace failure repaired. Local commit is
validation/handoff only, never integration approval.
