# Repair #859 — security gate (branch auto-859), round at 04b3d9b20

Starting head `04b3d9b20263`, develop base `e20e9f52ea94` (0 behind / 16 ahead:
no sync merge needed, `git merge-base HEAD origin/develop` == the assigned base).
Worktree arrived clean. Nothing from the previous round was assumed; every
claim below was re-derived here.

## What the red gate actually said (evidence, not a guess)

`security` (ci.yml job 118599753689) failed at its last step. Job log:

    pip-audit found advisories outside the triaged allowlist:
      aiohttp==3.14.3 CVE-2026-111064 -> upgrade to 3.14.4
      aiohttp==3.14.3 GHSA-2g87-pp6c-29x5 -> upgrade to 3.14.4
      aiohttp==3.14.3 CVE-2026-111063 -> upgrade to 3.14.4
    Fix by upgrading the dependency. Only add a (package, advisory) pair to
    ALLOWED when no fixed version exists, and say why.

The same three lines are the whole of the standalone `Supply chain (pip-audit)`
failure (security.yml job 118599754756). SAST (bandit + semgrep + gitleaks) is
green at this head — the earlier note's "semgrep would flag the new code" was a
hypothesis; the log is the answer and it points at a dependency, not at
`packages/maistro-turing`.

`aiohttp` is not a direct dependency anywhere in this repo. `uv.lock` pulls it
in only through `cosmic-ray` (the mutation-testing dev tool), which is why
`scripts/pip_audit_gate.py`'s allowlist has nothing to say about it and why the
fix is a lock refresh, not an allowlist entry: a fixed version exists.

## The repair

    uv lock --upgrade-package aiohttp
      Updated aiohttp v3.14.3 -> v3.14.5
      Updated yarl    v1.24.2 -> v1.25.1   (aiohttp 3.14.5's own floor)

`uv.lock` only — one dependency edge moved, `uv lock --check` is clean, and no
`packages/*/pyproject.toml`, `quality/*.json` or ALLOWED entry was touched.

## Fail-before / fail-after (both executed here)

| shape | pip-audit report | `scripts/pip_audit_gate.py` |
|---|---|---|
| `aiohttp==3.14.3` (the pre-repair pin) | 3 advisories, exactly the CI three | **exit 1**, same message as CI |
| `uv sync --locked --extra dev` (ci.yml `security`) | aiohttp 3.14.5, only ecdsa PYSEC-2026-1325 | **exit 0** — "1 known, all triaged in ALLOWED" |
| `uv sync --locked --all-extras` (security.yml `Supply chain`) | same, only ecdsa | **exit 0** |

The pre-repair row was produced by re-running pip-audit over the same frozen
set with `aiohttp` pinned back to 3.14.3 — the gate reproduces the CI failure
from the old lock and clears it from the new one, so the pass is not vacuous.

## Gates re-run at this head (CI's exact arguments)

| check | rc |
|---|---|
| `uv lock --check` | 0 |
| `uv run ruff check .` / `ruff format --check .` | 0 / 0 (3363 files) |
| `uv run mypy <the seven CI src trees>` | 0 (906 files) |
| `uv run pytest packages/maistro-turing -x -q` | 0 (341 passed) |
| `check-suite-inventory.py --suite packages/maistro-turing{/backend}/tests` | 0 / 0 (216 / 125, no delta — no test touched) |
| `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 0 (1326 reviewed == 1326 findings) |
| `check-dependency-namespaces.py` (ci.yml `security` step 2) | 0 (233 distributions, no unreviewed namespace) |
| `pytest tests/test_dependency_namespaces.py` | 0 (67 passed) |
| `scripts/pip_audit_gate.py` both sync shapes | 0 / 0 |

## Not fixed here, and why (attribution checked, not assumed)

Every other red job at 04b3d9b20 is the same single inherited item, not this
lane's branch:

- `Quality / Reachability`, `exact-debt-ledger` (reachability ratchet),
  `Quality gate (Pillars 1–4, 7, 8)` ("quality-reachability: dependency did not
  succeed"), `Coverage gate` and three `test` cases all name
  `maistro.runs.admission_identity` as the one NEWLY UNREACHABLE module.
  Reproduced locally at this head:
  `RATCHET_BASE_REV=origin/develop uv run python scripts/check-reachability.py`
  reports exactly that one module; `git diff --stat origin/develop...HEAD --
  packages/maistro-core` is **empty**, so the branch cannot have made it
  unreachable. `origin/develop`'s own `quality/reachability-baseline.json` is
  `_generated_from: 1302 production modules` while the tree now has 1417 —
  #1851's module landed without a ledger row, so develop is red independently.
- Fixing it would mean adding a row to a reachability ledger, which an ordinary
  implementation PR may not do. Disposition belongs to #1851.

## Residual risks (unchanged by this round)

The four from `repair-859-50bc0e959.md` still stand (ephemeral self-model store
by design; replica enablement needs a shared Workspace store as well as a
shared `SelfModelStateStore`; blank principal id; `mood_snapshot`
materializes a default scope on first read). This round touched no Python.
