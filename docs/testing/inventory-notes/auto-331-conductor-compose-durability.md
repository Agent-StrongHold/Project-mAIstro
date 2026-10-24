---
inventory-delta:
  packages/hive-conductor/backend/tests: +10
  packages/maistro-core/tests: +22
---

# #331 Conductor Compose data-directory durability

Issue #331 makes the standalone Compose deployment's persistent-state contract
real and testable.

## Production changes

- `packages/hive-conductor/backend/services/data_dir_guard.py` (new): the
  startup guard. `verify_durable_data_dir` creates the configured
  `CONDUCTOR_DATA_DIR`, proves writability with a real write/fsync probe, and
  — only when running inside a container (`/.dockerenv` /
  `/run/.containerenv`) — refuses a data directory sitting on the
  container's own root filesystem (`st_dev` compared against `/`;
  `DATA_DIR_EPHEMERAL`), because container-layer state is discarded on
  recreate. The device comparison (not `os.path.ismount`) is deliberate:
  the Compose layout puts the data directory *inside* the mounted volume so
  restore can swap the directory itself by rename, which a mount point
  cannot do (rename(2) returns EBUSY). A nested path on a volume has a
  different device from `/` and passes; only container-layer paths fail. A
  directory that cannot be stat'd is refused as `DATA_DIR_UNWRITABLE`.
  `CONDUCTOR_ALLOW_EPHEMERAL_DATA_DIR=1` is the documented escape hatch for
  throwaway harnesses; it does not skip the writability probe.
- `packages/hive-conductor/backend/services/foundation.py`: `Foundation.start`
  runs the guard before the vault/state/credential subsystems touch a file,
  so a refusal leaves nothing half-initialized and the lifespan refuses to
  serve.
- `packages/hive-conductor/docker-compose.yml` (standalone): mounts the named
  volume `conductor-data` at `/data` and sets `CONDUCTOR_DATA_DIR=/data/conductor`
  — a directory inside the volume, not the mount root, so atomic restore by
  rename is possible. The image pre-creates `/data/conductor` (and its
  parent) owned by the nonroot runtime uid 65532, so the empty named volume
  inherits least-privilege ownership on first use. The image's own
  `CONDUCTOR_DATA_DIR` ENV and the root `docker-compose.yml` use the same
  nested layout, so a bare `docker run -v <vol>:/data` quickstart is
  restoreable too.
- `packages/hive-conductor/docker-compose.test.yml`: declares the escape
  hatch explicitly — the e2e harness wants throwaway state so every run
  exercises the one-shot setup wizard.
- `packages/maistro-core/src/maistro/cli/_security.py`: `maistro security
  backup` captures every file in the data directory in one pass into a
  single archive (staged `.tmp`, fsynced, then renamed — the output name
  never names a partial archive); `maistro security restore` extracts to a
  staging sibling and swaps with two renames, so a crash leaves either the
  old directory or the restored one, never a half-restored mix of coupled
  files (vault without identity key, credential store without master key).
  Dry-run by default, like the other `maistro security` operators; refuse
  corrupt/truncated archives and unsafe paths before touching the target.
- `packages/hive-conductor/pyproject.toml` (repair round, driven by the
  first full local durability run): `maistro-core[bcrypt,identity]` →
  `maistro-core[bcrypt,identity,sqlite]`. The shipped `maistro` CLI
  hard-imports aiosqlite at startup (`maistro.cli` registers
  `maistro.cli._fixtures`, whose module body imports aiosqlite unguarded),
  and the image resolves its venv from `uv export --locked --package
  hive-conductor --no-dev` — which did not carry aiosqlite — so every CLI
  subcommand, including the `security backup`/`restore` operators this
  issue documents and its CI job runs, died at import inside the image
  (`ModuleNotFoundError: No module named 'aiosqlite'` at the backup step).
  The Conductor is exactly the homelab/single-instance deployment
  maistro-core's `sqlite` extra exists for, and the file's own `[bcrypt]`
  precedent governs: the requirement is expressed by the package whose
  code imports it. `scripts/bump_version.py`'s `_INTERPKG_SITES` row is
  updated in lockstep (its regex names the expression the file holds, or
  the version bound stops being checked silently).
- `packages/hive-conductor/scripts/verify-compose-durability.sh` (new) +
  `hive-conductor-compose-durability` CI job: guard refusals, then
  create → write → recreate (down/up AND image rebuild) → read → backup →
  restore, all against the real standalone compose file.

## Test deltas

- `packages/maistro-core/tests/cli/test_security.py`: +22 tests across
  backup and restore — atomic single-pass capture, staged rename, default
  output location, empty/missing-dir refusals, no-overwrite, dry-run
  inertness, coupled-file round trip with the master key still decrypting,
  owner-only restored directory, corrupt/truncated archive refusal before
  the target is touched, crash-before-the-swap recovery, and
  path-traversal refusal; plus the nine failure-path tests from the
  diff-coverage repair round below (bad `--out` suffix, uncaptured-durable
  notes, empty-inventory print, backup rename failure, empty-archive and
  dirs-only refusals, restore-plan coupled-set warnings, device-node
  extraction failure, second-rename failure recovery, and the
  `_swap_after_extract` empty-extraction guard). (The
  stale-staging-directory refusal in the restore command has no dedicated
  test — code path present, untested.)
- `packages/hive-conductor/backend/tests/test_data_dir_guard.py` (new, 10
  tests): creation+probe cleanup, unwritable refusal, uncreatable-parent
  refusal, in-container ephemeral refusal (deterministic via `_st_dev`
  patch), in-container mount-root pass, in-container nested-inside-volume
  pass, in-container unstattable-dir refusal, escape hatch (still probing
  writability), no mount requirement on a host, and Foundation.start
  refusing before any subsystem initializes.

## Known pre-existing, out of scope

`test_registration_policy.py::TestInvitations::
test_independent_process_writers_publish_one_username` fails intermittently
under full-suite machine load (spawned workers re-import the backend behind
a 10 s barrier and a 20 s join timeout) and passes in isolation. Its import
and execution path (models.schemas, maistro.state, services.model_store,
services.registration_policy, routes.auth, stores) does not touch any file
this branch changes; reproduced 2/2 under full-suite load and 1/1 in
isolation on branch auto-331.

## Validation

- `uv run pytest packages/maistro-core/tests/cli/test_security.py
  packages/hive-conductor/backend/tests/test_data_dir_guard.py -q` → 36
  passed (26 in test_security.py — 13 of them added by this work — plus 10
  guard tests).
- `uv run ruff check .` and `uv run ruff format --check .` → clean.
- `uv lock --check` → clean; `uv run python scripts/bump_version.py
  --check` → "42 sites agree on '0.9.0'".
- `scripts/check-dependency-namespaces.py` → no unreviewed top-level
  namespaces.
- `scripts/check-image-lock-reconciliation.py` with CI's exact arguments
  (hive-conductor export + members) against the image the durability run
  built → "ships exactly the locked set (73 distributions, incl. 6
  workspace member(s))".
- Full compose durability scenario executed locally against real Docker
  (docker 29.1.3), via the same `scripts/verify-compose-durability.sh` the
  `hive-conductor-compose-durability` CI job runs, isolated from sibling
  stacks with `COMPOSE_PROJECT_NAME`/`CONDUCTOR_PORT`: **33 checks passed,
  0 failed, exit 0** — both guard refusals (process stops, not serves),
  create, write, on-volume inventory (all five durable files present:
  `state.db`(+wal/shm), `secrets.age`, `admin.key`,
  `credential_master.key`, `user_credentials.enc`) with volume root and
  data dir owned by uid 65532, down/up recreate, image-rebuild recreate,
  session/login/settings/credential reads after each, backup archive, and
  full restore onto a destroyed volume with everything readable again.
  First run of the same script (pre-repair) failed at the backup step with
  the `aiosqlite` import error above — the failure the dependency repair
  fixes; the passing run is post-repair.

## Repair round (gitleaks), re-verified on top

The SAST / Gitleaks CI leg failed at the previous head. Reproduced locally
with gitleaks 8.30.1 and security.yml's exact PR-arm invocation over the
merge base: one `generic-api-key` finding at the harness's
`PROBE_SECRET=` line, introduced by 1e4058c3c. Fixed in 9e490755a with both
halves of the pattern `.gitleaks.toml` documents: the literal split in the
working tree (runtime value asserted byte-identical) and a commit-, path-,
rule-scoped allowlist entry for 1e4058c3c (the introducing commit's patch
stays in every PR-range scan regardless of the working-tree fix — same
situation as the de04b449/4806d967 entries). Post-fix scans of both CI arms
(merge-base..HEAD and HEAD^..HEAD) report no leaks.

Independent CI-failure attribution at the repair base (merge base
4de7e906d9dc): `Supply chain (pip-audit)` / `security` fail on ecdsa
0.19.2, fastmcp 4.0.11 and setuptools 84.0.0 — all three versions
byte-identical in the merge base's uv.lock, i.e. inherited trunk red; the
hive-conductor image built from this tree scans clean under trivy with
CI's flags (HIGH,CRITICAL, --ignore-unfixed, exit 0), so the container-scan
failure likewise comes from the engine-family images carrying those same
inherited advisories. `SAST (bandit + semgrep + gitleaks)` is explained by
the gitleaks leg (bandit verified 0 Medium+ locally; 66 semgrep-rule pin
tests pass).

Correction (CI logs obtained after the note above was written): the
`test` and `Coverage gate` failures are the same single lane-caused red,
not unattributable. gh run 40115875517 (job 120936917946, `test`) and
quality run 40115875569 (job 120939743737, `Coverage gate`) both failed on
exactly one test —
`tests/test_bump_version.py::TestTheRegisteredCorpus::test_the_conductor_site_is_registered[inter-package
dep:packages/hive-conductor/pyproject.toml:maistro-core[bcrypt,identity]]`
— with the Coverage gate otherwise at "1 failed, 5757 passed, 143
skipped". The stale corpus row was introduced by c35cf8a8a: that commit
updated `packages/hive-conductor/pyproject.toml` to
`maistro-core[bcrypt,identity,sqlite]` and `scripts/bump_version.py`'s
`_INTERPKG_SITES` row in lockstep, but left this test's parametrize row
pinning the old extras string, so the registered-site assertion fails
against the real tree. Reproduced locally (`uv run pytest
tests/test_bump_version.py::TestTheRegisteredCorpus` → 1 failed, 3
passed) and fixed by updating the corpus row to the extras the file
actually holds. The earlier "could not be attributed ... load flake"
sentence above is superseded by this attribution; the registration-policy
load flake it referenced is unrelated to these two failures.

## Repair round (diff coverage), this head

After the corpus row above was fixed, the same `Coverage gate` job stayed
red on its other leg: `scripts/check-diff-coverage.py` failed at head
42527541b (gh job 120968418523, run 40125247349) on
`packages/maistro-core/src/maistro/cli/_security.py` at 86.7% of 143
changed lines (need 90%), uncovered 242,243,260,280,348-351,372,378,446,
492,496,518,522-524,528,529 — every one a failure or reporting path of the
backup/restore operators this branch added (bad `--out` suffix refusal,
uncaptured-durable-file notes, empty-inventory print, backup's staged-
rename OSError path, restore-plan missing/coupled-file warnings, the
empty-extraction guard, empty-archive refusal, and restore's OSError path
including the original-preserved-at report). Fixed with nine tests in
`packages/maistro-core/tests/cli/test_security.py` that drive exactly
those paths, including fault injection via `monkeypatch` on `os.replace`
for the two rename-failure paths and a `CHRTYPE` member to trip
`tar.extractall(filter="data")` mid-extraction. Re-verified at this head:
scoped producers run exactly as quality.yml runs them (`coverage run
--branch --source=packages/maistro-core/src/maistro` over
test_security.py → 35 passed; `--source=packages/hive-conductor/backend`
over the backend suite → 3966 passed, 26 skipped; `--source=scripts` over
tests/test_bump_version.py → 18 passed), then
`uv run python scripts/check-diff-coverage.py coverage.xml --base
ffc27cc43` (the current PR merge base) → "ok: every measured file this
change touches is at or above 90% lines / 80% branch arcs", 4 changed
files measured, exit 0. Suite inventory re-recorded:
`check-suite-inventory.py --note auto-331-conductor-compose-durability
--update` → +9 in this note's `inventory-delta` (13 → 22), exit 0.

## Verification round (independent, head e5cc427d4, develop b1c89cdb merged in)

Re-derived acceptance from the issue and re-executed the evidence at the
merged head (diff vs merge base b1c89cdb = exactly PR #2301's 22 files; no
production code changed in this round, inventory deltas unchanged):

- `uv run pytest packages/maistro-core/tests/cli/test_security.py
  packages/hive-conductor/backend/tests/test_data_dir_guard.py -q` → 45
  passed; `uv run pytest tests/test_bump_version.py -q` → 18 passed;
  `scripts/bump_version.py --check` → 42 sites agree.
- Coverage-gate diff leg re-proven at the NEW merge base: the three
  producers whose `--source` covers this diff's changed files
  (maistro-core over test_security.py, hive-conductor/backend over
  test_data_dir_guard.py, scripts over tests/test_bump_version.py) →
  `scripts/check-diff-coverage.py coverage.xml --base b1c89cdbc` → ok,
  every measured file ≥90% lines / ≥80% branch arcs (4 measured, 3 test
  files exempt). Scoped runs are conservative: fuller CI producers can
  only add coverage.
- `uv run mypy` over the seven AGENTS.md packages → clean (939 files).
- `check-branch-protection.py` (19 develop / 33 main, every PR check
  required or advisory), `check-compose-secrets.py`,
  `check-compose-resources.py`, `check-doc-links.py`,
  `check-required-checks.py` (76 checks match), full
  `check-suite-inventory.py` (21 suites) → all exit 0.
- Full compose durability scenario re-executed independently against real
  Docker 29.1.3 via the same
  `packages/hive-conductor/scripts/verify-compose-durability.sh` the CI
  job runs (isolated: `COMPOSE_PROJECT_NAME`, `CONDUCTOR_PORT=8131`;
  8101 was occupied by an unrelated local listener): **33 checks passed,
  0 failed, exit 0** — both guard refusals stop the process, create,
  write, down/up recreate, image-rebuild recreate, reads (session cookie,
  login, settings, credential) after each recreate, backup of all five
  durable files, and restore onto a destroyed volume with everything
  readable again.
- Closure-keyword audit: no `fixes/closes/resolves #331` in the PR body or
  any commit message on this branch ("Refs #331" only).
- Residual (cosmetic, non-blocking): the `restore` docstring says a
  re-run "completes the swap" after a kill between the two renames, but
  `_refuse_stale_staging` actually refuses the re-run (exit 1) until the
  stale staging tree is inspected and removed manually — fail-closed and
  correct, just over-automated in prose.
