---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
  packages/maistro-core/tests: +10
---
# 989-pack-fixtures

Issue #989 (M7-A13) seeds two inspectable pack fixture Runs — `book` (accepted)
and `game` (parked) — through the canonical spine only
(`ProjectScopeStore` + `RunStore` create/transition APIs; no fixture JSON, no
frontend store). Seven new tests in
`packages/maistro-core/tests/graph/seeds/test_pack_fixtures.py` and two in
`packages/hive-conductor/backend/tests/test_pack_fixture_run_list.py` pin the
lineage a reviewer must be able to query without executing explore/judge:

- book: Goal/Rubric revisions plus the wave-1 → wave-2 redirect in
  `Run.provenance`, ≥2 wave-1 rejected theses each carrying an eval record,
  a wave-2 `BookPages` winner with per-spread `turn` notes, the planted
  earlier failure still queryable as the winner's failed Attempt 1, the
  refine Attempt 2 the accepted outcome names, and the accept fence.
- game: a scored thesis with a failing dimension (`taught_by_play`), the park
  fence (Run + fence NodeRun `WAITING`), and resume restoring the same
  identities — including after a SQLite reconnect, which also re-reads the
  accepted book lineage from disk.
- ontology: both fixtures resolve in one canonical Workspace/Project scope.
- anti-fixture-store: the seeders must take canonical stores (a frontend-only
  fixture cannot), and no frontend tree may carry fixture identity or copy, so
  a fixture that exists only as JSON/zustand/localStorage fails the suite.
- host open path: with the fixture Workspace visible through the workspace
  authority's canonical-membership import (#37), both fixture Runs list and
  open through `services.dag_run_inspection` — the door `GET /v1/dag-runs`
  answers through — a member sees them, a non-member cannot, and opening
  changes no canonical status.

No existing node IDs moved; the deltas are purely additive.

## Lane reconciliation (repair round)

- **Branch naming.** The issue's acceptance line names a `feat/m7-a13-pack-fixtures`
  PR branch. Lane workers are assigned driver-owned worktree branches (`auto-989`);
  the driver applies the integration branch/PR name when the lane lands. The
  `feat/...` criterion is satisfied at integration, not in the worktree.
- **Suite-inventory gate timeout was environmental, not a regression.** The
  prior round's failed check was
  `check-suite-inventory.py --suite packages/maistro-core/tests` timing out at
  900 s; re-run on the same head it collects 11565 tests and matches the
  ledger in ~8 s (the hive-conductor suite likewise: 2945 in ~4 s). No code
  change was needed; the count in the delta block above is unchanged.
- **Vulture per-identity ledger (CI-repair).**
  `scripts/check-vulture-baseline.py` initially failed: the three host-facing
  functions (`seed_book_fixture`, `seed_game_fixture`, `open_pack_fixture`) were
  unbanked `core-public-api-surface` findings. They are the issue's deliverable,
  not dead code, and a grant in `quality/ratchet-authorizations.json` cannot take
  effect inside the branch that introduces it (the gate reads grants from the
  merge base — two-merge design). Repaired by declaring the module's public
  exports in `__all__` (the pattern `graph/seeds/__init__.py` already uses), which
  eliminates the false positives: the gate passes with 1402 reviewed identities →
  1402 findings, no ledger amendment required.

## Verify round (independent, head 3bc4e71fd138e04c0954a373c1f5a1bd3a1a1de7)

Re-executed locally, all green: both fixture suites (7 + 2 tests), the full
`packages/maistro-core/tests/graph` tree (1485 passed, 97 skipped), `ruff check .`,
canonical all-package mypy (728 files, clean), both `check-suite-inventory.py`
gates, and the vulture identity gate with CI's exact arguments
(`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
1402 reviewed → 1402 findings, exit 0). Frontend anti-fixture scan is
non-vacuous: 121 scan-eligible files across both frontend trees.

**Blocking finding (reproduced locally, red on CI at this head): the
reachability candidate baseline was never re-banked for the new module.**
`RATCHET_BASE_REV=origin/develop uv run python scripts/check-reachability-provenance.py`
exits 1 — `maistro.graph.seeds.pack_fixtures: NEW unreachable module absent
from trusted base and not previously authorized` / `current unreachable module
missing from candidate baseline` (188 → 189 unreachable of 1144 modules). This
is one root cause under three CI failures on the PR head: `exact-debt-ledger`
(Vulture Ratchet) FAIL, the quality gate's `reachability ratchet
(built-but-never-wired modules)` step exit 1, and three unit tests
(`tests/test_check_reachability.py::test_baseline_matches_the_tree`,
`tests/test_reachability_baseline_identity.py::test_the_committed_baseline_passes_the_gate_it_now_carries`,
`tests/test_reachability_baseline_identity.py::test_the_baseline_is_exactly_the_unreachable_set`;
reproduced locally: 3 failed in 11.71s). The prior round repaired the vulture
*identity* gate via `__all__` but missed this second gate. Repair: re-bank
`quality/reachability-baseline.json` (`unreachable`) — and the matching
`quality/reachability-dispositions.json` entry if required — for
`maistro.graph.seeds.pack_fixtures`.

**Inherited red (not lane code):** CI `Supply chain (pip-audit)` fails at this
head on `urllib3==2.7.0` CVE-2026-97687/88/89 (upgrade to 2.8.0). The lane
diff touches no lockfile; the bump is repo-wide work the integration lane must
absorb.

**Environmental:** this round's first local test attempt failed with ENOSPC —
`/tmp` tmpfs at 100% inode usage from stale prior-run scratch. Only `/tmp`
entries older than one day were purged; no repository or job-artifact paths
were touched. This corroborates the prior round's environmental-failure
attribution for its suite-inventory timeout.

## Repair round 2: the fixture module is wired, not banked (head 5f5003180+)

The owed repair was examined before executing it, and the re-bank was
**rejected on evidence**: `scripts/check-reachability-provenance.py` reads the
trusted ledger *and* its authorizations from the merge base
(two-merge design, `scripts/ratchet_provenance.py`). A branch cannot authorize
its own new unreachable module, so adding `maistro.graph.seeds.pack_fixtures`
to `quality/reachability-baseline.json` here would still leave
`added = current - trusted` non-empty and the provenance ratchet — and CI —
red at this head. The same rule is stated in the checker's own failure text:
new debt "may grow only behind a prior landed reachability authorization".

The repair actually applied is the checker's other prescription — "give them
a call path" — which is also the issue's own alternative fixture contract
("a documented seed command that writes those APIs"):

- `maistro/cli/_fixtures.py` — new `maistro fixtures seed [--db PATH] [--json]`
  subcommand on the existing `maistro.cli` STATIC_ROOT. It constructs the
canonical SQLite stores (`SqliteProjectScopeStore`, `SqliteRunStore`) and
invokes `seed_book_fixture` / `seed_game_fixture` — the same calls the tests
make, and nothing else. Precedent: maistro-turing's `provision` root ("a
script a person launches is an entry point the import graph can root — not
unreachable debt to baseline") and `maistro archive` ("a library nobody can
invoke does not make history reachable").
- `maistro/graph/seeds/pack_fixtures.py` — docstring now documents the seed
command, so the module's Design-Studio claim is backed by a production path.

Effect: the module is genuinely reachable, so **no baseline or dispositions
edit is needed at all** — `check-reachability-provenance.py` reports 188 → 188
unreachable of 1145 modules (no candidate-approved expansion),
`check-reachability-dispositions.py` still passes on 188, and the three
baseline-identity unit tests pass unchanged. An operator can now provision a
real store; the printed identities are canonical and durable.

Vulture (CI-args run): the new command function was one unbanked
`maistro-cli-command-surface` identity — new debt this branch cannot authorize
either. Eliminated the same way the prior round cleared pack_fixtures' host
functions: `__all__` declares the module's public exports, so the
decorator-registered, test-exercised command is not a dead-code finding
(1402 reviewed → 1402 findings, exit 0; no ledger amendment).

Test delta +3 (`packages/maistro-core/tests/test_cli_pack_fixtures.py`): the
command's `--json` output is the open path and the store it leaves survives a
fresh reopen (book COMPLETED over the redirected lineage, game WAITING with
the parked fence decision and `taught_by_play` reason readable through
canonical NodeRun reads); the table output names the shared Workspace and the
provisioned file; the unified `maistro --help` routes the command. Canonical
all-package mypy stays clean (729 files); ruff check/format clean.
