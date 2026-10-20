# Repair round 2: #1820 — develop sync and the security gate at the real base

Candidate: `auto-1820` @ `d1431c0ea` (merge of `origin/develop` `c2d7209f1`
into `auto-1820`, plus the security repair).
Base: `origin/develop` @ `c2d7209f1dbc1039e8ca9d99444b88ded3bbe26b`.

Round 1 (`REPAIR-NOTES-1820-ci-gate-repair.md`) repaired the `security` job at
the old PR head `0f7134057` by moving `aiohttp` 3.14.3 → 3.14.4. That fix was
pushed on a branch whose base was `e20e9f52e`, and the advisory database has
moved since. This round syncs the branch to the real base and repairs the
`security` job as it fails *now*.

---

## 1. Develop sync

`git merge --no-ff origin/develop` — one conflict, `uv.lock` (aiohttp
3.14.4 vs 3.14.5). Resolved in favour of develop's `aiohttp==3.14.5` (the
newer fixed release) and re-resolved with the security upgrades below. No
other conflict. `uv.lock` vs `origin/develop` now differs **only** in the two
security packages:

```
$ git diff origin/develop -- uv.lock | grep -E '^[-+](name|version) = '
-version = "2026.4.22"     # certifi
+version = "2026.10.19"
-version = "12.3.0"        # pillow
+version = "13.0.0"
```

## 2. `security` — re-diagnosed, repaired

### The finding (this round)

The lane's `security: failure` is **not** an aiohttp failure. At
`auto-1820` @ `3fb65042e` (pre-sync) the exact CI sequence produces:

```
Found 11 known vulnerabilities in 3 packages
  ecdsa    0.19.2   PYSEC-2026-1325                                  (triaged/allowed)
  certifi  2026.4.22  PYSEC-2026-4320   -> upgrade to 2026.10.19    (outside allowlist)
  pillow   12.3.0    8 × CVE-2026-11239x/11240x/11289x -> upgrade to 13.0.0 (outside allowlist)
```

`certifi` is trivially upgradeable. `pillow==13.0.0` — the version every
advisory names — is **blocked by the project's own constraint**
`packages/maistro-canvas/pyproject.toml`: `"pillow>=12.3.0,<13"`. So
`uv lock --upgrade-package pillow` alone moves nothing.

The failure is base-owned too: a pristine `origin/develop` @ `c2d7209f1`
carries the same `certifi==2026.4.22` and `pillow==12.3.0`, and its own
`ci.yml` `security` job (run 39483249186, job 118846660434) fails the same
way. Fixing it here makes the merge-queue merged tree green.

### The repair

```
packages/maistro-canvas/pyproject.toml:  "pillow>=12.3.0,<13"  ->  "pillow>=12.3.0,<14"
uv.lock --upgrade-package certifi --upgrade-package pillow
  certifi 2026.4.22 -> 2026.10.19
  pillow   12.3.0   -> 13.0.0
```

No `quality/*.json` ledger, grant, or manifest was edited. `uv lock --check`
resolves cleanly.

Pillow 13 is API-compatible with the canvas usage
(`Image.Resampling.{LANCZOS,BICUBIC}`, `Image.{new,open,merge,alpha_composite}`,
`ImageChops`, `ImageDraw`, `ImageFont`, `resize`, `rotate`, `convert`) — the
only new warnings are `Image.Image.getdata` deprecations scheduled for
**Pillow 14**, not 13. Full `packages/maistro-canvas/tests` passes (§4).

## 3. Proof — CI's exact sequences, both security jobs

`ci.yml` `security` job (`uv sync --locked --extra dev`, 223 frozen dists):

```
uv run python scripts/check-dependency-namespaces.py   -> no unreviewed top-level namespaces. (exit 0)
uv run pip-audit --strict --format=json -r /tmp/...    -> exit 1: 2 known vulns, 1 package (ecdsa)
uv run python scripts/pip_audit_gate.py /tmp/...       ->
    allowed: ecdsa==0.19.2 PYSEC-2026-1325
    pip-audit OK (1 known, all triaged in ALLOWED)
    direct-dependency usage OK: 11 packages, 62 runtime dependencies, 4 reviewed dispositions
    -> gate exit 0
```

`security.yml` `Supply chain (pip-audit)` job (`uv sync --locked --all-extras`,
225 frozen dists) → same gate → exit 0.

The pre-fix state is the finding itself: `pip-audit --strict -r` at
`certifi==2026.4.22` / `pillow==12.3.0` reports the advisories above.

## 4. Validation run locally (merged tree, this round)

| Command | Outcome |
|---|---|
| `uv sync --locked --extra dev` | ok |
| `uv sync --locked --all-extras` | ok |
| `uv lock --check` | `Resolved 260 packages` |
| `uv run ruff check .` | `All checks passed!` |
| `uv run ruff format --check .` | `3370 files already formatted` |
| `uv run pytest tests/test_install_runtime_selection.py tests/test_install_compose_floor.py tests/test_install_engine_floor.py tests/test_backup_restore_oracle.py -q` | `82 passed` |
| `uv run pytest tests/test_install_*.py tests/test_installer_entrypoints.py tests/test_installer_repository.py tests/test_check_install_functions.py tests/installer -q` | `219 passed, 1 skipped` |
| `uv run pytest packages/maistro-canvas/tests -q` | `465 passed, 75 skipped` |
| `uv run pytest packages/maistro-bootstrap/tests -q` | `245 passed, 7 skipped` |
| `uv run pytest packages/maistro-core/tests/cli -q` | `247 passed` |
| `uv run pytest packages/maistro-bootstrap/tests/test_delivery.py packages/maistro-bootstrap/tests/test_plan.py packages/maistro-core/tests/cli/test_upgrade.py -q -x` | `120 passed` |
| `uv run python scripts/check-dependency-namespaces.py` | exit 0 |
| `uv run python scripts/pip_audit_gate.py <report>` (dev + all-extras) | exit 0 (§3) |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | `1326 reviewed identities -> 1326 findings`, `unclassified: 0`, exit 0 |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-bootstrap/tests` | `ok: 1 suite(s) match the recorded inventory` (252 = 245+7) |

## 5. Regression proof for #1820's runtime-selection tests

`tests/test_install_runtime_selection.py` lifts the selection functions
**verbatim** out of `install.sh`, so it is coupled to this branch's code.
Run against `origin/develop`'s `install.sh` (copied to a scratch root, no
branch code present):

```
$ pytest tests/test_install_runtime_selection.py -q
25 failed, 7 passed          (develop install.sh)
$ pytest tests/test_install_runtime_selection.py -q
32 passed                    (auto-1820 install.sh)
```

The seven that pass on develop are the ones that only exercise pre-existing
functions; every test that names the new selection/elevation behaviour fails
without it.

## 6. Acceptance criteria of #1820 → evidence

Unchanged from round 1 (`REPAIR-NOTES-1820-ci-gate-repair.md` §4); the merge
preserves the branch's own diff (`git diff origin/develop HEAD` still shows
only the #1820 installer/engine/CLI changes plus this round's two dependency
lines). The dependency repair does not weaken any of the criteria: the
installer still never calls `usermod`/`gpasswd`, never mounts a privileged
socket, and still refuses to silently switch runtimes.

## 7. Residual risk

- `quality/reachability-baseline.json` still lacks a row for
  `maistro.runs.admission_identity` (base-owned; the reachability family is
  out of this lane's scope, see round 1 §2). The merged tree therefore cannot
  be fully green until `auto-1851` / PR #1936 lands its own repair.
- macOS and Windows-side elevation rows of the support matrix remain design
  claims — no such host was available in this lane.
- `pillow` moved a major version. The canvas suite is green, but the lock
  change is a dependency-policy move that reviewers should confirm against
  the canvas roadmap.
