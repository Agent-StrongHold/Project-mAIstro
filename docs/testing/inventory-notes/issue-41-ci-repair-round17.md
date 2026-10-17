---
inventory-delta:
  tests/: +0
---

# Issue 41 CI repair (round 17): publisher contract harness resolved `node` through a hand-picked PATH

No test delta: this round repairs the round-15 harness helper
(`_run_publish_script` in `tests/test_gates_ran_publisher_contract.py`) so the
six node IDs it added actually execute on GitHub-hosted runners. The set of
collected tests is unchanged.

## The failure this round closes

At head `ca41eb74df71b744306a8e44aaeddbdc68053bf6` exactly two checks failed:

- CI `test` job, step "Run `uv run pytest tests/ --ignore=tests/tools/registry`"
  (run 36280079552, job 108510121603);
- quality "Coverage gate (publish-set floor + diff coverage)", step `combine`
  (run 36280079571, job 108511039210).

The prior green CI picture is `05e46f7a7` (run at 2026-09-26T21:55Z, both
workflows success). `tests/test_gates_ran_publisher_contract.py` was added in
round 15 (`577fab0f5`) — after that green picture — and never executed in CI
before the failing run. The head-to-head delta is otherwise the `8bfd35903`
develop merge (core warden/normalize + design scan, all of whose suites pass
in CI as steps 1–13 of the same `test` job).

## Root cause

`_run_publish_script` invoked the publish-script harness as
`subprocess.run(["node", ...], env={"__FAKE_ENV": ..., "PATH": "/usr/bin:/bin"})`.
Two lookups disagree:

1. `shutil.which("node")` (the skip guard) runs against the *job's* PATH. On
   GitHub runners that resolves — node 22 from `setup-node`/the hosted
   toolcache lives outside `/usr/bin`.
2. The subsequent exec of the bare name `"node"` consults only the *hand-picked*
   `PATH=/usr/bin:/bin`, which on hosted runners contains no node at all
   (`setup-node` installs into `/opt/hostedtoolcache/node/...`), so the
   subprocess raised `FileNotFoundError`.

On a dev box `/usr/bin/node` exists, so both lookups succeed and the tests
pass locally — which is why the defect survived round-15's local battery. In
CI it failed the root suite directly (test job step 14) and again inside the
coverage gate's `combine` step, which re-runs the root suite as the `scripts`
producer under `set -euo pipefail` — one root-suite crash explains both red
checks, and the "Event loop is closed" job annotations are ambient stderr
noise (they appear in passing jobs too, e.g. 10× in the passing
`coverage (no services)` producer of the same run).

The two other restricted-PATH subprocesses in the tree
(`tests/test_verify_wheel_imports.py`, `packages/maistro-rsi/tests/test_model_identifiers.py`)
invoke `sys.executable` by absolute path and were never affected — which is
the pattern this harness now follows.

## The fix

`_run_publish_script` resolves node once, passes the absolute path as
`argv[0]` (no PATH exec lookup), and lists the resolved directory first in the
child `PATH`. The script under test is unaffected: its prelude swaps
`process.env` for the faked step env, so the ambient PATH never reaches the
publish script's logic.

## Validation

- `uv run pytest tests/test_gates_ran_publisher_contract.py -v`: 12 passed.
- Full root suite on the repaired tree:
  `uv run pytest tests/ --ignore=tests/tools/registry --timeout=30 -q`
  → 3943 passed, 104 skipped.
- Publish-set coverage floor reproduced from all three producers
  (unit / PostgreSQL pg17 / MinIO archive) on the merged tree:
  `coverage report --fail-under=87` → 93% total, gate green.
- Vulture per-identity ledger (CI-scope invocation):
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → rc 0,
  1402 reviewed identities = 1402 findings, `unclassified: 0`.
