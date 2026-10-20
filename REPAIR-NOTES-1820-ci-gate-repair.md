# Repair round: #1820 — CI gate failures at 0f7134057 (security + the develop-owned reachability family)

Candidate under repair: `auto-1820` @ `0f7134057a220176ef6bc66f05c30874c6d87d95`
Base: `origin/develop` @ `e20e9f52ea94b393184f210cc9379f9f693f13d0`
CI runs inspected (read-only): `CI` 39381778356, `quality` 39381778510,
`Vulture Ratchet` 39381778396, `security` 39381778406.

Red at that SHA: `security`, `test`, `Quality / Reachability`,
`Quality gate (Pillars 1–4, 7, 8)`, `Coverage gate (publish-set floor + diff
coverage)`, `Vulture Ratchet` (`exact-debt-ledger`). This round repairs the
one that belongs to this lane (`security`) and attributes the rest to the base
commit with a reproduction that does not involve this branch.

---

## 1. `security` — the gate this lane owns (REPAIRED)

### What CI actually failed on

Job `security` (118492287929) of run 39381778356. The dependency-namespace
gate passed (`no unreviewed top-level namespaces.`), pip-audit produced a
usable report, and the gate script rejected it:

```
::error::pip-audit found advisories outside the triaged allowlist:
  aiohttp==3.14.3 CVE-2026-111064 -> upgrade to 3.14.4
  aiohttp==3.14.3 GHSA-2g87-pp6c-29x5 -> upgrade to 3.14.4
  aiohttp==3.14.3 CVE-2026-111063 -> upgrade to 3.14.4
```

The report held 5 advisories in 2 packages: the three `aiohttp` ones above
plus the triaged `ecdsa==0.19.2 PYSEC-2026-1325` (allowed in
`scripts/pip_audit_gate.py`). Nothing else was wrong — the branch's own diff
touches no dependency declaration.

### Repair

`uv.lock` only, refreshed the way the gate itself prescribes:

```
uv lock --upgrade-package aiohttp==3.14.4
```

`aiohttp` 3.14.3 → 3.14.4 (the fixed version the advisory names) and its
transitive requirement `yarl` 1.24.2 → 1.25.1. The lock diff changes **no
other package's version and no requirement edge**:

```
$ git diff uv.lock | grep -E '^[-+](name|version|source|    \{ name)'
-version = "3.14.3"
+version = "3.14.4"
-version = "1.24.2"
+version = "1.25.1"
```

No manifest, no `quality/*.json`, no grant was edited; `uv lock --check`
resolves cleanly (`Resolved 260 packages`).

### Proof, with CI's exact sequence

`ci.yml`'s `security` job shape:

```
uv sync --locked --extra dev
uv pip install pip-audit
uv run python scripts/check-dependency-namespaces.py      # exit 0
uv pip freeze --exclude-editable > /tmp/deps.txt           # 223 distributions
uv run pip-audit --strict --format=json -r /tmp/deps.txt  # exit 1 (ecdsa only)
uv run python scripts/pip_audit_gate.py /tmp/pip-audit.json
```

```
allowed: ecdsa==0.19.2 PYSEC-2026-1325
pip-audit OK (1 known, all triaged in ALLOWED)
direct-dependency usage OK: 11 packages, 62 runtime dependencies, 4 reviewed dispositions
→ gate exit 0
```

`security.yml`'s `Supply chain (pip-audit)` job shape
(`uv sync --locked --all-extras`, 225 frozen distributions) → same gate →
exit 0.

The pre-fix state is the finding itself, re-proved against the advisory
database: `pip-audit --strict -r` with `aiohttp==3.14.3` returns
`CVE-2026-111064`, `GHSA-2g87-pp6c-29x5`, `CVE-2026-111063`, all fixed in
`3.14.4`.

---

## 2. The reachability family — inherited from the base commit (OWNER-HELD, not repaired here)

### What CI actually failed on

Every remaining red check traces to **one** module:

```
1417 production modules, 169 unreachable from any entry point
1 module(s) are NEWLY UNREACHABLE:
  maistro.runs.admission_identity  (maistro.runs.admission_identity)
```

- `Quality / Reachability` (118492288849): `scripts/check-reachability.py`,
  `RATCHET_BASE_REV=origin/develop` → exit 1.
- `Vulture Ratchet` / `exact-debt-ledger` (118492287506): step 1
  `scripts/check-ratchet-provenance.py` →
  `FAIL: reachability ratchet moved away from trusted state` /
  `- maistro.runs.admission_identity: NEW unreachable module absent from
  trusted base and not previously authorized`.
- `CI` / `test` (118492287911): `3 failed, 5427 passed, 138 skipped` — the
  three failures are `tests/test_check_reachability.py::test_baseline_matches_the_tree`,
  `tests/test_reachability_baseline_identity.py::test_the_committed_baseline_passes_the_gate_it_now_carries`
  and `…::test_the_baseline_is_exactly_the_unreachable_set`.
- `Coverage gate (publish-set floor + diff coverage)` (118497440413): the
  job's own publish-set floor **passed** (`TOTAL … 94%`, `--fail-under=87`);
  the job then failed inside its root-suite producer on the same three
  reachability tests (`3 failed, 5531 passed`), so the diff-coverage gate
  was never reached.
- `Quality gate (Pillars 1–4, 7, 8)`: the summary that aggregates the above.

### Proof that this branch did not cause it

The base commit reproduces it with no branch code involved — a pristine
`origin/develop` worktree (`git worktree add --detach /tmp/devbase-check
origin/develop`, e20e9f52):

```
$ cd /tmp/devbase-check && RATCHET_BASE_REV=origin/develop \
    uv run python scripts/check-reachability.py
1417 production modules, 169 unreachable from any entry point
1 module(s) are NEWLY UNREACHABLE:
  maistro.runs.admission_identity  (maistro.runs.admission_identity)
→ exit 1
```

The module was introduced by the base commit's own merge
(`e20e9f52e Merge pull request #1936 from Agent-StrongHold/auto-1851`) and is
imported only by `packages/maistro-core/tests/runs/test_root_admission_identity.py`.
`quality/reachability-baseline.json` (168 rows on develop) has no row for it.
This branch's diff against `origin/develop` touches neither the module nor
that ledger.

### Why this round does not repair it

- The lane brief for this round permits a ledger amendment to
  **`quality/vulture-baseline.json` only**, and "no other ledger/grant
  edits". `quality/reachability-baseline.json` is out of scope, and banking
  another lane's unwired leaf would bless a module the owning lane
  (`auto-1851`, PR #1936) documents as issue-mandated-but-not-yet-wired — see
  `.cursor/context/repair-1851-9ddea59d.md`.
- The vulture ledger this round *is* allowed to amend needs no amendment:
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → `unclassified: 0`,
  `never_allowlist: 0`, `1326 reviewed identities -> 1326 findings`, exit 0;
  `scripts/check-shipped-surface-truth.py` → exit 0. The exact-debt-ledger
  job never reached those two steps because step 1 aborted.

---

## 3. Validation run locally (candidate tree, this round)

| Command | Outcome |
|---|---|
| `uv lock --check` | ok — `Resolved 260 packages` |
| `uv run ruff check .` | `All checks passed!` |
| `uv run ruff format --check .` | `3363 files already formatted` |
| `uv run pytest tests/ --ignore=tests/tools/registry -q --timeout=60` | `3 failed, 5427 passed, 138 skipped` — the three develop-owned reachability tests, byte-identical to CI's `test` job |
| `uv run pytest packages/maistro-core/tests/cli -q` | `247 passed` |
| `uv run pytest packages/maistro-bootstrap/tests -q` | `245 passed, 7 skipped` |
| `uv run pytest tests/test_install_runtime_selection.py tests/test_backup_restore_oracle.py tests/test_install_compose_floor.py tests/test_install_engine_floor.py -q` | `82 passed` |
| `uv run python scripts/check-suite-inventory.py` | `ok: 21 suite(s) match the recorded inventory` |
| `uv run python scripts/check-diff-coverage.py <coverage.xml> --base origin/develop` | `ok: every measured file this change touches is at or above 90% lines / 80% branch arcs` (5 changed measured files) |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | `1326 reviewed identities -> 1326 findings`, exit 0 |
| `uv run python scripts/check-shipped-surface-truth.py` | exit 0 |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py` | exit 1 — reachability ratchet only (base-owned, §2) |
| `uv run python scripts/pip_audit_gate.py <report>` | exit 0 (§1) |

Compose rendering, both runtimes, same file
(`docker compose -f docker-compose.yml config` and
`podman compose -f docker-compose.yml config`) — the CMD-SHELL healthchecks
the podman provider needs render identically:

```yaml
healthcheck:
  test:
    - CMD-SHELL
    - python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live')"
```

### Mutation checks (the new tests fail without the behaviour they name)

| Mutation | Tests that fail |
|---|---|
| remove the persisted-plan branch of `selected_container_runtime` | 11 |
| revert `detect_compose_cmd` to the docker-first probe | 4 (`test_selected_podman_wins_when_both_clis_are_present`, `test_selected_podman_never_probes_inaccessible_docker`, …) |
| remove the elevation prerequisite guard in `bootstrap_apt_docker_runtime` | 1 (`test_missing_sudo_reports_a_recoverable_prerequisite`) |

`install.sh` was restored byte-for-byte after each mutation
(`git status` clean apart from `uv.lock`).

---

## 4. Acceptance criteria of #1820 → evidence

| Criterion | Evidence | Status |
|---|---|---|
| Explicit selection survives planning, materialization, startup, health/status/logs, stop/restart, generated recovery/upgrade commands; an unavailable selection fails actionably and never silently switches | `packages/maistro-bootstrap/src/maistro_bootstrap/plan.py::effective_runtime` → `delivery.json` → `materialize.py::_plan_runtime` → `delivery.py::render_makefile`; `install.sh::selected_container_runtime`/`detect_compose_cmd`/`selected_runtime_ready`/`compose_line_cmd`; `packages/maistro-core/src/maistro/cli/_upgrade.py::_resolve_compose_runtime(manifest)` | VERIFIED |
| Regression tests cover both CLIs present, selected Podman with inaccessible Docker, Docker-only, Podman-only, unavailable selected runtime, documented `auto`; unselected probes do not block the selected path | `tests/test_install_runtime_selection.py` (32 node IDs, hermetic PATH + canary shims); mutation table above | VERIFIED |
| Advertised non-elevated/rootless profile exercised from an ordinary host account; state and credentials owned by it; lifecycle works after a new shell/login and a service restart | `docs/install/runtime-selection-evidence-1820.md` (Profiles 1–3: `maistro-clean` uid 1001, `stat` ownership checks, `bash -l` fresh environment, `restart`, teardown) | VERIFIED (transcript evidence; macOS/Windows rows remain UNVERIFIED — no such host) |
| Required one-time elevation identified before mutation and handled explicitly; lack/denial of elevation gives a recoverable prerequisite report, without unexplained root-owned artifacts | `install.sh::bootstrap_apt_docker_runtime` (sudo pre-check + `run_elevated` guarded), daemon log moved to the install's own state dir; `test_denied_elevation_reports_a_recoverable_prerequisite`, `test_missing_sudo_reports_a_recoverable_prerequisite` | VERIFIED |
| No silent docker-group add, no privileged socket mount, no root-run WSL install, no weakened sandbox policy | `install.sh` never calls `usermod`/`gpasswd`; `docker.sock` discovery is docker-only and read-only; root is refused as an unsupported profile (`docs/install/default-installer.md` matrix) | VERIFIED |
| Runtime access/version/capability validation uses the selected runtime | `install.sh::selected_runtime_ready` (`docker info` / `podman info`), `runtime_compose_cmd`, `ensure_compose_supported`; docker-only preflights gated by `docker_only_preflight_checks` | VERIFIED |
| Tests cover interruption/retry and ownership of persisted volumes/configuration; unsupported combinations fail before a success/ready claim | `test_interrupted_install_retry_keeps_the_persisted_selection_and_ownership`; `ensure_compose_runtime` fails before the "Compose runtime:" ok line | VERIFIED |
| Documentation and generated commands match the tested support matrix and separate host privilege, container-runtime privilege, and application roles | `docs/install/default-installer.md` ("Container runtime selection and host privilege" matrix), `docs/install/runtime-selection-evidence-1820.md` | VERIFIED |

## 5. Residual risk

- The branch cannot go green until the base commit's reachability regression
  is repaired by its owner (`auto-1851` / PR #1936). Every check named in §2
  fails identically on a pristine `origin/develop`.
- macOS and Windows-side elevation rows of the support matrix remain design
  claims — no such host was available in this lane (stated in
  `docs/install/runtime-selection-evidence-1820.md`, "Not exercised in this
  lane").
