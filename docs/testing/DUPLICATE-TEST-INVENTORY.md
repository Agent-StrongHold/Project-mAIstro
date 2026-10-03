# Duplicate test inventory (#396)

Parent initiative: #450. Related CI governance owner: #160.

At the base of this change, every test file listed below existed twice: once
under the package tree that owns the tested module, and once under the root
`tests/` tree. Both roots are in `testpaths`, so both copies were collected
and executed on every full run — suite totals, AC-outcome pass counts, and
coverage all double-credited evidence for behavior that was tested once.

## Method

- **Exact**: sha256 over every `test_*.py` / `*_test.py` under the gated
  suite roots (`RECIPES` in `scripts/check-suite-inventory.py`). At the base
  this produced 11 content hashes shared by two files each; after this
  change, zero (gated by `scripts/check-test-duplicates.py`).
- **Structural**: two passes over every root file sharing a basename with a
  package or `formal/` file. First `difflib.SequenceMatcher` line similarity
  plus a test-function-name diff; pairs ≥ 0.99 were drifted twins and pairs
  in 0.5–0.8 subset/superset relationships. The similarity threshold alone
  under-included: `test_conductor.py` (3-of-53 tests) and
  `test_secret_equal.py` (small, drifted) sit below 0.5 and were caught only
  by the second pass — a test-function-name-set comparison of *all*
  same-basename pairs, which flags any shared name at any similarity. Every
  flagged pair was then read, not just measured.

## Origin / history

All 26 removed root-tree files first appear in `48ee34bcb` (the initial
public release, 2026-08-21) *already byte-identical* to their package
counterparts, which also first appear there. They are wholesale copies made
when the monorepo was assembled, not independent evolutions. After that
commit the package copies were maintained — `packages/maistro-server/tests/
api/test_auth.py` gained identity-keyed rate-limit cases in `5d5de04aa`
(#1074); the core `test_queue.py` copy gained sixteen queue-behavior tests —
while the root copies fossilized. Every drift between a pair is therefore
the package copy moving *ahead*; no removed root file contained an assertion
the package copy lacked, except the two files in Table C, which were folded
into their package copies before deletion, and the two retired-by-design
cases called out under Table B.

## Authoritative location

The package tree that owns the tested module
(`packages/maistro-core/tests/…`, `packages/maistro-server/tests/…`) is
authoritative in every case. Reasons, in the order they matter:

1. CI executes each package suite standalone (`ci.yml` runs
   `uv run pytest packages/maistro-core/tests` and
   `packages/maistro-server/tests` as their own steps), so the package copy
   is the one whose green run is load-bearing.
2. The repo's layout rule (`AGENTS.md`) puts Python work under `packages/`;
   the root `tests/` tree is repo substrate — CI-gate self-checks, migration
   and cross-suite tests.
3. Import isolation is preserved: the byte-identical files imported the same
   modules under both roots, and each tree's conftest chain supplies the
   same fixtures (verified by both copies passing today under separate
   roots). Removing the root copy removes a runner, not an import path.

## Table A — byte-identical copies (11), root file removed

| Root copy (removed) | Authoritative copy |
| --- | --- |
| `tests/agents/test_types.py` | `packages/maistro-core/tests/agents/test_types.py` |
| `tests/api/test_auth.py` | `packages/maistro-server/tests/api/test_auth.py` |
| `tests/api/test_startup.py` | `packages/maistro-server/tests/api/test_startup.py` |
| `tests/api/test_status.py` | `packages/maistro-server/tests/api/test_status.py` |
| `tests/memory/episodic/test_episodic.py` | `packages/maistro-core/tests/memory/episodic/test_episodic.py` |
| `tests/memory/test_outcome_store.py` | `packages/maistro-core/tests/memory/test_outcome_store.py` |
| `tests/memory/test_protocols.py` | `packages/maistro-core/tests/memory/test_protocols.py` |
| `tests/memory/test_types_and_scopes.py` | `packages/maistro-core/tests/memory/test_types_and_scopes.py` |
| `tests/security/test_dangerous_tools.py` | `packages/maistro-core/tests/security/test_dangerous_tools.py` |
| `tests/security/test_sandbox_security.py` | `packages/maistro-core/tests/security/test_sandbox_security.py` |
| `tests/security/test_secure_random.py` | `packages/maistro-core/tests/security/test_secure_random.py` |

## Table B — near-duplicates consolidated (13), root file removed

Same test behaviors under both roots with drifted bodies; the package copy
is the strict superset in every row, so no behavior is lost. Similarity is
line ratio on the pair.

| Root copy (removed) | Authoritative copy | Evidence of supersession |
| --- | --- | --- |
| `tests/api/test_tasks.py` | `packages/maistro-server/tests/api/test_tasks.py` | Same test names; server adds `TestOwnerId`, a parametrized workspace-rejection case, `TestGetTaskResult` |
| `tests/api/test_webhooks.py` | `packages/maistro-server/tests/api/test_webhooks.py` | 0.99; server adds six `actor_kind`/principal asserts per webhook path |
| `tests/api/test_health.py` | `packages/maistro-server/tests/api/test_health.py` | Server has both root tests (`test_health_returns_ok`, `test_health_has_no_operational_details`) plus 25 more |
| `tests/memory/learnings/test_learning_store.py` | `packages/maistro-core/tests/memory/learnings/test_learning_store.py` | 0.80; server adds `TestMarkOutcome` (4 tests); one differing assert is same-behavior different-data |
| `tests/memory/test_engine.py` | `packages/maistro-core/tests/memory/test_engine.py` | Strict subset; core adds `test_vector_is_none_when_pgvector_unavailable` |
| `tests/security/test_external_content.py` | `packages/maistro-core/tests/security/test_external_content.py` | 0.99; differs by one docstring word |
| `tests/security/test_trust_boundary.py` | `packages/maistro-core/tests/security/test_trust_boundary.py` | 0.99; differs by one docstring word |
| `tests/test_metrics.py` | `packages/maistro-core/tests/test_metrics.py` | Root's 5 tests appear by name in core's 34; 58 of 59 root lines matched |
| `tests/test_circuit_breaker.py` | `packages/maistro-core/tests/test_circuit_breaker.py` | Root's 6 tests re-done in core with a fake clock (no `time.sleep`) plus 3 more |
| `tests/test_queue.py` | `packages/maistro-core/tests/test_queue.py` | Strict subset; core adds 16 queue-behavior tests |
| `tests/agents/test_conductor.py` | `packages/maistro-core/tests/agents/test_conductor.py` | Strict subset: root's 3 `TestConductorDryRun` bodies byte-match core's; core has 53 more tests |
| `tests/security/test_secret_equal.py` | `packages/maistro-core/tests/security/test_secret_equal.py` | Root's 10 shared-name tests match core's; root's 2 "extra" tests are `inspect.getsource` text-greps that core deliberately replaced with behavioral monkeypatch tests — core's docstring states the rationale (a source grep is satisfied by a comment; a live-call assertion is not). Folding them back would reintroduce retired-by-design tests |
| `tests/tools/test_env_sanitize.py` | `packages/maistro-core/tests/tools/test_env_sanitize.py` | Strict subset; core adds secret-pattern boundary tests and Hypothesis properties |

## Table C — root-only tests folded first (2), then root file removed

These two root files each held tests the package copy lacked. The tests were
folded into the package copy *verbatim* before deletion, so the node-ID
count they contribute is preserved under the authoritative path.

| Root copy (removed) | Folded into | Folded tests |
| --- | --- | --- |
| `tests/tools/test_sandbox_paths.py` | `packages/maistro-core/tests/tools/test_sandbox_paths.py` | `test_sandbox_grep_rejects_path_traversal_before_container` (3 params), `test_sandbox_glob_rejects_path_traversal_before_container` (3 params) |
| `tests/tools/test_workspace.py` | `packages/maistro-core/tests/tools/test_workspace.py` | `test_blocked_prefix_sibling_path` (5 params: `_evil`, underscore, `/private/tmp`, `/repos_evil`, `/repos2` lookalikes) |

## Table D — same name, distinct environment (kept, documented)

These pairs share a basename but not a test population. They are not
duplicates and were deliberately not consolidated; collapsing either side
would reduce platform coverage.

| Pair | Why both exist |
| --- | --- |
| `formal/models/test_{trust_boundary, secure_random, secret_equal, external_content, dangerous_tools}.py` vs `packages/maistro-core/tests/security/…` | `formal/models/` are Hypothesis property/state-machine oracles (I-numbered items) run by `formal-conformance.yml` and audited by `scripts/check-formal-oracle-independence.py`; line similarity 0.06–0.20 with the unit suites. Different method, different job, same module under test. `test_secret_equal.py` shares exactly one test *name* across the pair — a collision, not a copy; the bodies share no assertions. |

After Table B was read individually, no other cross-tree pair among root,
package, and `formal` trees shares a test population.

## Governance going forward

- `scripts/check-test-duplicates.py` (wired into `ci.yml`'s `test` job next
  to the suite-inventory gate) fails on any byte-identical test-file group
  across the gated roots, unless the whole group is covered by an entry in
  [`generated-test-contracts.json`](generated-test-contracts.json) — the
  explicit generated-test contract escape hatch (generator, files,
  justification). Partial contract coverage approves nothing.
- `scripts/check-suite-inventory.py` now reports, on every run and from the
  collection it already performs, how many collected node IDs are unique
  cross-suite versus duplicate evidence from copied files — see
  [SUITE-INVENTORY.md](SUITE-INVENTORY.md).

## Effect on evidence

The root `tests/` suite's recorded node-ID count drops by exactly the node
IDs these 24 files contributed (recorded in the `inventory-notes/` delta for
this change). Total *unique* evidence is unchanged: every removed node ID
was a second collection of a test that still runs — and is executed
standalone in CI — under its package tree.
