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

## Resolving a merge conflict here

This file conflicts between any two branches that both add tests, because both
edit the same counts. **Regenerate; do not hand-merge.** Taking either side
gives a number that matches neither branch, and hand-adding the two deltas is
guesswork that happens to be right until it is not:

```bash
git checkout --theirs docs/testing/SUITE-INVENTORY.md   # placeholder, either side
python3 scripts/check-suite-inventory.py --update       # the real answer
```

Then rewrite the paragraph above the table so it explains the merged number
rather than one branch's half of it. The count is the alarm, not the record —
its whole value is that a suite silently dropping out of collection changes it,
and a hand-merged number is one that was never measured.

`quality/ac-state.json` conflicts the same way and for the same reason;
regenerate it with `python3 scripts/check-ac-state.py --run-tests --ratchet`.

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

Everything below this heading is generated. `check-suite-inventory.py
--update` rewrites the counts by collecting each suite; do not edit them by
hand, and resolve any merge conflict here by regenerating rather than by
picking a side.

*Why* a count moved is recorded in [`inventory-notes/`](inventory-notes/),
one file per change. That used to be a block of prose right here, which meant
every branch adding tests rewrote the same lines and collided with every other
such branch on merge (#208). Notes moved out so this file could stay purely
derived.

| Suite | Node IDs | Runs in CI |
|---|---:|---|
| `packages/maistro-core/tests` | 7451 | `ci.yml` |
| `packages/maistro-evolve/tests` | 629 | `ci.yml` |
| `packages/maistro-rsi/tests` | 428 | `ci.yml` |
| `packages/maistro-server/tests` | 226 | `ci.yml` |
| `packages/maistro-turing/tests` | 177 | `ci.yml` |
| `packages/maistro-design/tests` | 161 | `ci.yml` |
| `packages/maistro-bootstrap/tests` | 124 | `ci.yml` |
| `packages/maistro-canvas/tests` | 250 | `ci.yml` |
| `packages/maistro-turing/backend/tests` | 26 | `ci.yml` (own invocation) |
| `tests/` (root) | 1098 | `ci.yml` (minus `tests/tools/registry`, which `registry.yml` owns) |
| `formal/` | 417 | `formal-conformance.yml` + `quality.yml` Pillar 2 |
| `packages/hive-conductor/backend/tests` | 1235 | `ci.yml` (bare python) |
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
