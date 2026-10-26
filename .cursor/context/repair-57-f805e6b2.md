# Issue 57 — fresh repair validation / blocked handoff

## Frozen scope

- Assigned issue #57 only; worktree `/home/dev/Git/wt/auto-57`, branch `auto-57`.
- Clean starting HEAD `c13abb8e9773919865fee2cef3a4eb1fe5aca06f`;
  supplied develop base `1e6b080256026eec0136be31a1acb8abbb3cfc1f` resolves locally.
- Evidence snapshot: job `/home/dev/maistro/jobs/f805e6b28cec4b57a4874271f63b2c61/dispatch-context.json`
  and supplied prior result `d5cbf70c63254753b11a6aad55993327/result.json`.
  No driver `check-*.log` files were present. Prior checks were not adopted.
- Writer role assumed from explicit repair/local-commit assignment. No remote
  enumeration, GitHub mutation, merge, source redesign, or gate weakening.
- Scope reviewed: existing #57 production/test diff, SECURITY.md, adjacent tests,
  accepted ADR-050, ADR-068, ADR-081226-6b46, exact vulture gate and relevant gates.
  ADR reconciliation: exposures/classification do not grant authority or replace
  the canonical Invocation lifecycle; no new approval mechanism is implied.

## Findings reproduced (and not reproduced)

- Exact CI vulture scan **passes**: 1299 findings against 1303 reviewed
  identities, zero unclassified and never-allowlist findings. No retained/dead
  identity needs repair; no ledger amendment is justified.
- `SECURITY.md:35` already documents registry construction and distinguishes
  classification from Sentinel approval gating. The prior doc-drift finding is
  absent at starting HEAD. No cosmetic rewording was made.
- The older `docs/implementation/issue-57-repair-round.md` legacy-tier limitation
  is historical, not current behavior: `legacy_dag_node.py` now resolves
  `hive_tool_reversibility` and records it on the canonical Invocation. Fresh
  legacy registry-tier/reclassification tests passed.
- Frozen dispatch `issues/847` starts at line 73349 and records `state=open` at
  line 73452. Criterion 12 remains **UNMET**. This worker cannot change that
  external prerequisite or infer closure from passing adversarial subsets.
- One initial ADR read used a nonexistent filename; recorded not found/skipped,
  then resolved the actual ADR-050 filename before reading. No unresolved refs
  were executed.

## Executed checks

Logs are in the job directory above, named `repair-<name>.log`; commands used
1200-second subprocess timeouts. All commands exited 0.

| Command | Result / log |
| --- | --- |
| `uv sync --locked --extra dev` | passed / sync |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | passed; no unbanked identities / vulture |
| `uv run pytest` core tools + capabilities + Agent base/factory/schema/spec + ReAct/BuildersLearning/artificer + Sentinel audit, `-x -q` | 1583 passed, 12 skipped, 1 mock coroutine warning / core |
| `uv run pytest` Hive governed-tools/legacy-DAG/Agent-model-tools/core-adapter files, `-x -q` | 112 passed / hive |
| `uv run pytest packages/maistro-bootstrap/tests -x -q` | 255 passed, 7 skipped / bootstrap |
| `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q` | 74 passed / adversarial-gates |
| `uv run ruff check .` | passed / ruff-check |
| `uv run ruff format --check .` | 3479 files formatted / ruff-format |
| `uv run python scripts/check_direct_effects.py` | 51 sites, 4 TOOL_EFFECT, inventory matches / direct-effects |
| `uv run python scripts/check-model-egress.py` | passed ratchet; still 12 reachable #56 escapes / model-egress |
| `uv run python scripts/check-security-inventory.py` | passed; explicitly does not check all prose / security-inventory |
| `uv run python scripts/check-convergence-matrix.py` | 1457 modules classified / convergence |
| `uv run python scripts/check-suite-inventory.py` | all 21 suites match; 34025 unique identities / suite-inventory |
| `uv run mypy` exact seven source paths from AGENTS.md | 934 source files, no issues / mypy |
| `uv run pytest packages/maistro-bootstrap/tests -x -q -rs` | confirmed six unavailable Docker/builders-image tests and one Windows-only test skip / bootstrap-skips |

Full commands and additional checkpoint details are in job `worker-progress.md`.
No tests were added/removed, so no test inventory delta is necessary. No source,
quality ledger or grant changed; this handoff is the sole repository edit.

## Acceptance review (all twelve criteria)

1. **Consume #55 seam, no second executor:** inspected Hive composition over
   `container.capability_effects` and core `contracts.py` invoking the existing
   Invocation service. Fresh boot/legacy tests passed. Complete repository-wide
   #55 cutover **UNVERIFIED**; a green model-egress debt ratchet is not cutover proof.
2. **Authorization and required predictions:** core governed-contract persistence
   and Hive canonical Invocation tests passed, including policy/completion events.
   Universal deployed mutating-tool coverage **UNVERIFIED**; shipped Hive contracts
   are read-only and high-impact behavior is exercised through the core seam.
3. **Effective tool set before provider:** fresh Agent/ReAct/artificer allowlist,
   Hive refusal-before-backend and BuildersLearning no-effect tests passed.
   Complete current principal/Workspace/Goal/Run envelope equivalence **UNVERIFIED**.
4. **Missing/unknown schemas fail closed:** core unknown-schema/unsupported-type,
   Agent schema boundary and Hive/legacy malformed materialized-input tests passed
   and assert no backend effect. Not a claim of arbitrary JSON Schema support.
5. **Constrained command contract across backends:** bootstrap argv/injection and
   hardened backend-shape tests passed. Live container backend parity remains
   **UNVERIFIED**: six integration tests skipped for unavailable Docker/image.
6. **Host-owned reversibility:** Hive registry-tier tests and legacy shared-tier /
   host reclassification tests passed; caller tier strings do not determine it.
   Reversibility-driven approval is not claimed (`SECURITY.md:35`).
7. **Exact/recomputable effect identity:** core real-SQLite close/reopen tests passed
   for both interrupted-append cases; assert exact capability/provider/arguments,
   argument/pre-state digests, policy version, expected/observed state and Invocation
   id. Deployed PostgreSQL/restart behavior **UNVERIFIED**.
8. **Durable mismatch, not silent success:** same SQLite replay tests passed;
   mismatch cannot be overwritten, retries append idempotently and never redispatch
   the backend. Cross-process races **UNVERIFIED**; recovery requires replay.
9. **Required high-impact predictions:** incomplete high-impact registration is
   refused by `test_high_impact_contract_without_expected_effect_fails_closed`,
   with a complete-contract positive control; passed.
10. **Seven historical TOOL_EFFECT entries:** current inventory passes with four
    retained provider-backend sites, two removed chat direct-call entries, and
    passing boot/chat/legacy wiring/refusal tests. Exact historical seven-site
    equivalence is **UNVERIFIED**, not established by inventory counts alone.
11. **Intentionally introduced raw path rejected:** both raw Hive dispatcher and
    BrowserClient injection tests passed in the 74-test adversarial gate run.
12. **#847 closes first from adversarial evidence:** **UNMET**, frozen issue state
    is open. No issue closure actions performed.

Remote exact-head CI is **UNVERIFIED**: no driver logs supplied. Local passing
checks are not integration approval. Residual risks are the unmet prerequisite,
explicitly unverified production/legacy-envelope/historical coverage, unavailable
live backend legs, and one warning in the broader core test run.

## Checkpoint / next

Checked 1 assigned issue; done 1 focused validation handoff; skipped 0 issues;
remaining local check failures 0; acceptance completion blocked. No evidence-backed
production repair remained from the supplied vulture/doc findings. Commit this
handoff locally; owner/verifier must resolve #847 sequencing and missing acceptance
proof. Do not push, close, or claim merge readiness.
