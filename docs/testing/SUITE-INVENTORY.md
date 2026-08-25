# Test suite inventory

Per-suite collected **node-ID counts**, for C1 (#286). Node IDs, not static
`def test_` counts — parametrization expands one `def` into many IDs, so
counting definitions understates every parametrized suite.

**This is enforced.** `ci.yml`'s `test` job runs
[`scripts/check-suite-inventory.py`](../../scripts/check-suite-inventory.py) as
its last step; it collects every suite listed below and fails the build if any
count drifts from what the ledger expects.

The counts themselves are not in this file. They are
`inventory/baseline.json` plus one delta per change in
[`inventory-notes/`](inventory-notes/) — see
[Recording a count that moved](#recording-a-count-that-moved) for why, and
`ADR-082526-547c` for the decision. Render the current expected counts with:

```bash
python3 scripts/check-suite-inventory.py --show
```

## Recording a count that moved

**You will not get a conflict here.** Since ADR-082526-547c the expected count
is not stored in this file, or in any other single place two branches both
write. It is a sum:

```
expected(suite) = baseline(suite) + Σ delta(suite) over every recorded change
```

- `inventory/baseline.json` — the counts as of the last compaction. It moves
  only when someone runs `--compact`, deliberately.
- `inventory-notes/<your-branch>.md` — your change's delta, in front matter,
  beside the prose explaining it.

So when you add or remove tests:

```bash
python3 scripts/check-suite-inventory.py            # check (what CI runs)
python3 scripts/check-suite-inventory.py --update   # write YOUR note's delta
python3 scripts/check-suite-inventory.py --show     # render current expected counts
```

`--update` writes one file named after your branch. Another branch doing the
same writes a different file, so git has nothing to reconcile — even if you
both changed the same suite.

**A base move needs no regeneration.** Your delta is still true after someone
else merges, and the sum absorbs theirs. This is the part worth internalizing:
under the old shared-absolute table, a branch that had not touched a single
test still had to re-collect thirteen suites every time its base moved,
because someone else's merge invalidated the number it had recorded.

Write the prose in the note too. The count alone hides compensating changes —
when #130 added nineteen maistro-core node IDs while PM-demo retirement removed
eighteen backend node IDs and one e2e case, the total barely moved and a reader
checking only the number would have seen nothing. That is the case the notes
exist for.

`quality/ac-state.json` still conflicts the way this file used to, and for the
same reason; regenerate it with
`python3 scripts/check-ac-state.py --run-tests --ratchet`.

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

## The gated suites

Every suite below is collected and compared on every CI run. The counts are
**not** here — see the section above for where they live and why. This table
records which suites exist and which workflow executes each, which changes only
when a suite is added, removed, or rewired.

A row here must have a matching entry in `RECIPES` in
[`check-suite-inventory.py`](../../scripts/check-suite-inventory.py), and a
recorded count for a suite with no recipe is an error rather than a silent
skip — otherwise recording a number for it would look like gating that is not
happening.

*Why* a count moved is recorded in [`inventory-notes/`](inventory-notes/), one
file per change, alongside the delta itself.

| Suite | Runs in CI |
|---|---|
| `packages/maistro-core/tests` | `ci.yml` |
| `packages/maistro-evolve/tests` | `ci.yml` |
| `packages/maistro-rsi/tests` | `ci.yml` |
| `packages/maistro-server/tests` | `ci.yml` |
| `packages/maistro-turing/tests` | `ci.yml` |
| `packages/maistro-design/tests` | `ci.yml` |
| `packages/maistro-bootstrap/tests` | `ci.yml` |
| `packages/maistro-canvas/tests` | `ci.yml` |
| `packages/maistro-turing/backend/tests` | `ci.yml` (own invocation) |
| `tests/` (root) | `ci.yml` (minus `tests/tools/registry`, which `registry.yml` owns) |
| `formal/` | `formal-conformance.yml` + `quality.yml` Pillar 2 |
| `packages/hive-conductor/backend/tests` | `ci.yml` (bare python) |
| `packages/hive-conductor/tests/e2e` | `ci.yml` `hive-conductor-e2e` (docker-compose) |

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
