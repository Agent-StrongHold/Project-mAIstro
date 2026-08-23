# Test suite inventory

Per-suite collected **node-ID counts**, for C1 (#286). Node IDs, not static
`def test_` counts — parametrization expands one `def` into many IDs, so
counting definitions understates every parametrized suite.

**This table is enforced.** `ci.yml`'s `test` job runs
[`scripts/check-suite-inventory.py`](../../scripts/check-suite-inventory.py) as
its last step; it collects every suite below and fails the build if any count
drifts. When you legitimately add or remove tests, refresh the table and commit
it with your change:

```bash
python3 scripts/check-suite-inventory.py            # check (what CI runs)
python3 scripts/check-suite-inventory.py --update   # rewrite the counts below
```

The gate compares **counts, not node-ID sets** — a checked-in manifest of ~9,500
node IDs would churn on every `@parametrize` tweak, and the rename case it would
catch is already covered by the suites actually *running* in CI. What counts
catch, and nothing else does, is a suite silently dropping to zero collected.
Rationale in full in the script's module docstring.

Regenerate a single suite by hand with:

```bash
# Everything under the uv workspace:
REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest <suite> --collect-only -q | tail -3

# hive-conductor is the exception — bare python, never uv. Its conftest
# re-inserts the backend dir at sys.path[0] because the monorepo root has a
# `services/` package that shadows its own (ci.yml:149 runs it this way).
REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 python3 -m pytest packages/hive-conductor/backend/tests --collect-only -q | tail -3

# formal/ needs evolve + rsi on PYTHONPATH, not just core — omitting them is
# a collection ImportError, not a test failure, and reads like a broken suite:
PYTHONPATH=packages/maistro-core/src:packages/maistro-evolve/src:packages/maistro-rsi/src \
  uv run pytest formal --collect-only -q | tail -3
```

## Counts as of current branch

Refreshed after the runtime cleanup queue (#355, #359, #361), the promotion
CI reconciliation, the Workspace/Persona convergence slice, and Stream 5 parity
characterization. The convergence work adds 44 maistro-core node IDs covering
ExecutionRuntime mechanics, Project to Workspace compatibility,
WorkspaceMembership role semantics, the live Persona model, and
one-Persona-per-Workspace persistence. Stream 5 adds four maistro-core node IDs.
Graph routing parity in #402 adds 10 maistro-core node IDs.
Graph execution-state frontier coverage in #403 adds nine maistro-core node IDs.
Durable graph canonical-persistence convergence in #416 replaces legacy
DurableRun/DurableNode lifecycle tests with canonical Run/NodeRun coverage,
for a net reduction of six maistro-core node IDs while retaining the
durability, routing, HITL, restart, mutation, and persistence invariants.
Real durable Graph frontier execution adds six maistro-core node IDs covering
concurrent fan-out, deterministic NodeRun ordering, source-correlated routing,
and fan-in input merging.
Durable Attempt/Runtime-boundary convergence adds nine maistro-core node IDs
covering Attempt ownership, shared durable persistence, deferred domain
reconciliation, real frontier execution through Attempt execution IDs,
cancellation terminalization across Attempt, NodeRun, and Run, and recovery by
appending a second Attempt under the same logical NodeRun.
Accepted AttemptResult/NodeRun outcome separation adds nine maistro-core node
IDs. Durable execution-lease fencing adds five more maistro-core node IDs.
Authoritative TraversalCommit/TraversalCheckpoint contracts add eleven
maistro-core node IDs.
PR #447 adds six maistro-core node IDs covering checkpoint-bridged traversal
history, reuse of frozen execution state across transitions, and rejection of
execution continuation after an accepted logical completion.
Stream 1 adds 99 maistro-core node IDs for the canonical Project,
Run/NodeRun/Attempt, runtime, persistence, and execution-service contracts.
Stream 6 adds five provider-parity node IDs.
Stream 3 authorization/resource-scope coverage adds 19 maistro-core node IDs.
Stream 7 product-adapter parity adds four maistro-core and two maistro-canvas
node IDs.
Stream 2 event, checkpoint, and outbox coverage adds 51 maistro-core node IDs.
The repo-task wrapper compatibility regression adds one maistro-evolve node ID.
Reachability production-root coverage adds four root-suite node IDs.
Mutation scheduler/history coverage adds ten root-suite node IDs.
Mutation continuation and repository-health aggregation add fifteen root-suite
node IDs, including checkpoint cache stability, complete-row-only baseline
aggregation, and single-tool-fingerprint sweep validation.
Mutation ratchet coverage adds seven root-suite node IDs for the global floor,
source-specific non-regression, monotonic baseline improvement, survivor
identity reporting, runtime regression confidence, and incomplete telemetry
rejection. Two more come from splitting the superseded unbaselined-source case
into the floor-fails, floor-passes, and candidate-merge assertions it had been
conflating.
Workspace creation was deliberately moved out of the scope-gated parametrized
Hive cases and into the ordinary product-surface check, so Hive loses one
collected node ID while retaining the intended assertion. Durable approval
coverage now includes stateful policy charging of human-approved effects before
provider dispatch. The Graph capability-effect adapter adds one maistro-core
node ID, covering the pause-then-resume path: the first Attempt pauses with
durable approval provenance and the second executes the approved effect without
a duplicate approval or Invocation. Other suite counts are unchanged.

Merging `develop` into the canonical-Run branch moves three rows at once, and
the net is `+0` — which is why the paragraph matters more than the number. The
canonical-Run work adds nineteen maistro-core node IDs (Run retention, the
non-finite evidence codec, chat/schedule/delegation admission, graph
templates). Retiring the PM-demo surface removes eighteen Hive backend node IDs
and one e2e case along with the routes and services they covered. A reader who
only checked the total would see no change at all.

| Suite | Node IDs | Runs in CI |
|---|---:|---|
| `packages/maistro-core/tests` | 6695 | `ci.yml` |
| `packages/maistro-evolve/tests` | 629 | `ci.yml` |
| `packages/maistro-rsi/tests` | 427 | `ci.yml` |
| `packages/maistro-server/tests` | 202 | `ci.yml` |
| `packages/maistro-turing/tests` | 177 | `ci.yml` |
| `packages/maistro-design/tests` | 161 | `ci.yml` |
| `packages/maistro-bootstrap/tests` | 124 | `ci.yml` |
| `packages/maistro-canvas/tests` | 127 | `ci.yml` |
| `packages/maistro-turing/backend/tests` | 26 | `ci.yml` (own invocation) |
| `tests/` (root) | 830 | `ci.yml` (minus `tests/tools/registry`, which `registry.yml` owns) |
| `formal/` | 417 | `formal-conformance.yml` + `quality.yml` Pillar 2 |
| `packages/hive-conductor/backend/tests` | 1223 | `ci.yml` (bare python) |
| `packages/hive-conductor/tests/e2e` | 23 | `ci.yml` `hive-conductor-e2e` (docker-compose) |

## `packages/hive-conductor/tests/e2e` — read before "wiring it in"

C1's context lists this directory as ~31 orphaned tests. That count does not
survive contact with the files. It contains four `test_*.py` modules, and only
**one** is a pytest suite:

- **`test_pm_workflow_api.py`** — 24 real tests. **Already covered**: the
  `hive-conductor-e2e` job runs it against the docker-compose stack. It is not
  orphaned.
- **`test_pm_agent.py`**, **`test_pm_real_atlassian.py`** — **not test suites**.
  Neither defines a single `test_*` function; both are manual scripts whose
  entry point is `run_pm_workflow()` / `run()` under
  `if __name__ == "__main__"`. They contribute **zero** node IDs. Adding them
  to a CI invocation would run nothing.
- **`test_pm_vision.py`** — real tests, but they drive a real browser against a
  live conductor and need a real `GOOGLE_API_KEY`.

All three of the latter imported `browser_use` unguarded at module scope. That
package ships only in `Dockerfile.research` (the main image deliberately sheds
the browser surface — see the root `Dockerfile` header), so importing it raised
`ModuleNotFoundError` **at collection time**, which aborted collection for the
entire directory — all four modules, including the 24 real tests. They are now
`pytest.importorskip`-guarded, so the directory collects cleanly and each
skip states its reason.

**`test_pm_workflow_api.py` is deliberately left unguarded.** A
`skipif`-on-unreachable-server would make it silently skip inside the very
compose job that exists to run it — converting a real test into a green no-op.
It should error loudly when the stack it needs is absent.

## C1's acceptance criterion — how it is met

C1 asks that "CI-collected node IDs match [this inventory] (± documented
skips)". This document is the inventory half; `scripts/check-suite-inventory.py`
is the comparison half, wired into `ci.yml`'s `test` job (C1/#286). Every row
above has an entry in that script's `RECIPES` table — a row with no recipe is a
hard error rather than a silent skip, so adding a suite here cannot look gated
without being gated.

Two things the gate deliberately does **not** do:

- **It does not compare node-ID sets.** See the rationale at the top.
- **It does not distinguish skips from passes.** `--collect-only` counts
  collected node IDs, which is the right denominator for "did this suite stop
  collecting". Whether a collected test then skips is the runtime suites' and
  the coverage gate's business (C2/#287), not this one's — the
  `pytest.importorskip` guards on `packages/hive-conductor/tests/e2e` are
  exactly why: they keep the directory *collecting* 24 node IDs whether or not
  `browser_use` is installed, which is the property this gate wants to hold.
