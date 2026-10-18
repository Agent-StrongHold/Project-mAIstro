---
inventory-delta:
  packages/maistro-core/tests: +30
---
# #1198 — sandbox host-path boundary

The added cases exercise positive writable-root authorization and denial of
root, home, repository-secret, Docker-socket, and traversal paths. They also
cover symlink targets, descriptor-relative file transfer, a final-open symlink
swap, and the backend's teardown/file-access ownership lock. The conformance
coverage remains in the real bubblewrap backend suite; no fake backend is used
to claim host-boundary evidence.

Round-2 verification on the auto-1198 host: with the default
`max_processes=128` budget the suite reports 129 passed / 35 skipped — the
kernel-level conformance cases skip because this WSL host counts namespaces
against `RLIMIT_NPROC` and cannot honor a 128-process budget (the probe's
skip reason says exactly that). Re-run under a process budget the host can
honor (`max_processes=4096`), every case runs live: 164 passed / 0 skipped,
including `test_host_side_file_transfer_keeps_symlinked_results_beneath_workdir`
and the whole kernel isolation ladder against the new mount policy. A
standalone live probe additionally confirmed: spawn refuses `/etc` as a
writable mount and cleans up its workdir; inside a real sandbox
`/etc/passwd` is absent, the host tree is read-only, only `/work` is
writable, and an authorized extra mount is usable and lands on its
authorized host root.

Round-3 correction (round-4 audit): the round-3 paragraph below claims the
suite-inventory gate was re-run green. That was wrong for the root `tests/`
suite: at `41d2a73d7` it collected 5210 nodes against an expected 5260 (the
develop-side content the first sync brought was never fully recorded), and the
second sync merge (`201c7ea22`, develop `2f56be40ad`) left a residual +1 in
`tests/` — recorded with node-ID evidence in
[1198-develop-sync-suite-delta.md](1198-develop-sync-suite-delta.md). No
#1198 test moved; the drift is entirely develop-side content merged in. All
other 16 suites matched.

Round-3 (develop sync + repair): merged `origin/develop` (`ab8b3737f`) into
`auto-1198`, resolving the `bubblewrap.py` conflict so writable binds go
through `authorized_host_mounts` while develop's `read_paths` profile feature
stays a read-only `--ro-bind`. The trusted-base radon ratchet failed on
`validate_host_root@C(14)` and `_relative_parts@C(11)` (introduced by the
original fix commit, unauthorized at the base); repaired by extracting
behavior-preserving helpers — both blocks now rank A, gate 137 -> 137, no
ledger edit. A loop-variable collision from the resolution (`extra: Path`
rebound to `str`) was renamed for mypy; `mypy packages/maistro-core/src` is
clean (790 files). Re-verified against a live kernel (`max_processes=4096`
probe): `/etc` and generic `/tmp` spawn denial with workdir cleanup,
authorized scratch mount writable at its stable guest name, and
symlink-to-outside read/write denied with the outside file unchanged. Full
sandbox suite 137 passed / 35 skipped (same host budget artifact as round 2);
`test_host_side_file_transfer_keeps_symlinked_results_beneath_workdir` and
the denial evidence covered by the fd-relative unit cases. Gates re-run: ruff
check/format, suite inventory (17 suites), vulture 1322 -> 1322, reachability,
radon, direct-effects, model-egress, security-inventory.

Round-7 repair (descriptor lifetime under cancellation): the round-6 verifier
accepted the boundary but held NEEDS-REPAIR on one blocking defect class: the
per-instance ownership lock is released when a transfer's caller is cancelled,
while the `to_thread` worker cannot be stopped — so `destroy` could close
`workdir_fd` (and rmtree the workdir) while a worker was still queued or
running, and the worker's internal `os.dup(workdir_fd)` could capture a
descriptor number the kernel had already reused. Repair, in
`bubblewrap.py`: transfers now run on a backend-owned executor and each
submission's real `concurrent.futures.Future` is registered on the instance
in the same synchronous, lock-held step that submits it (no await between
lock acquisition, `_require`, submission, and registration, so a cancellation
cannot release the lock for an unregistered transfer); `destroy` pops the
entry and then waits every registered future out through a fresh
`asyncio.wrap_future` before `os.close(workdir_fd)` and rmtree, so the
descriptor a worker was handed stays open — and pointing at the checked
workdir — for the worker's whole lifetime. A deregistration happens only when
the underlying future is actually done (`pending.done()`), because cancelling
the awaiting wrapper neither stops the thread nor completes the future.
The borrowed-descriptor contract of `read_beneath`/`write_beneath` is
unchanged; `paths.py` only gained the comment that states the caller-side
certificate. Three tests pin the contract (`test_host_path_boundary.py`):
cancellation during a blocked write with concurrent destroy (descriptor stays
`fstat`-valid with the workdir's inode for the whole blocked window, teardown
is observed waiting, exactly-once close proven by no `/proc/self/fd` link into
the removed tree), the abandoned write landing in the authorized workdir (the
worker records the inode it wrote through; no worker error), and the read path
with a worker that fails after cancellation (teardown waits, swallows, drains
the registry and locks, and the instance refuses further use). All three fail
against the pre-fix head (`3e65811e2`, verified in a scratch worktree: the
first two with the live `OSError(9, 'Bad file descriptor')` race, the third
because the registry did not exist) and pass against the fix; the full
boundary + conformance files report 34 passed / 26 skipped (29 tests in the
boundary file alone). Follow-up in the same round: destroy originally popped
the instance entry *before* waiting out the registered workers, so a destroy
cancelled mid-wait left an instance with no handle to finish teardown; the
entry is now popped only after the wait and a cancelled teardown closes
nothing (descriptor stays live for the blocked worker) while an idempotent
retry waits the same worker out — pinned by
`test_cancelling_teardown_mid_wait_keeps_the_contract_repairable` (+1, delta
29 -> 30). The round's develop sync (35a72ff54, uv bootstrap +
canvas engine image) merged conflict-free as `030288017`; the named CI gate
failures at the previous evaluation (SAST/Bandit at `0bf126137`) were already
repaired at `3e65811e2` and re-proven with CI's exact bandit invocation
(Medium+ count 0) in this round.

Round-6 CI repair (at the round-6 develop sync): hosted CI at `0bf126137`
failed two gates, both reproduced and repaired locally.

1. SAST / Bandit (strict 0 Medium+ baseline): bandit B108 flagged the
   `Path("/tmp")` *denylist* literal in `_SENSITIVE_ROOTS`
   (`paths.py:30`) as "insecure usage of temp file/directory". The literal
   exists precisely to refuse a writable root resolving to `/tmp` — the same
   false-positive class the module already annotates on its allowlist lines,
   so the line now carries `# nosec B108 - denylisted, refused as a writable
   root`. CI-exact bandit invocation reports Medium+ count 0 after the
   change.
2. Coverage gate, diff pillar: `paths.py` measured 76.2% of 126 changed
   lines (floor 90%). Every uncovered statement was a real policy edge with
   no test: invalid/relative root spellings, a sensitive *allowed root*,
   allowed roots that do not exist or are not directories (fail closed),
   the documented `create=True` exists-first contract, guest spellings that
   name no file, the multi-component `O_NOFOLLOW` walk (read, refuse-missing,
   provision-parents, symlinked middle component, non-directory abort with
   descriptor cleanup), and the no-`O_NOFOLLOW` fail-closed guard. Ten tests
   pin those behaviors (+10 here, delta 16 -> 26); re-running CI's exact
   producer (`coverage run --branch --source=packages/maistro-core/src/maistro
   -m pytest packages/maistro-core/tests`) and
   `scripts/check-diff-coverage.py coverage.xml --base 420d503d4` reports
   every measured file at or above 90% lines / 80% branch arcs.

Round-4 independent re-validation (at `75845bad0`): the round-3 gate list above
was stale for the root suite — the final sync merge (`f70cbba2f`) brought
develop's own
[1993 note](1993-hive-permission-preset-inventory.md), which charged the same
node this branch's sync note already carried, so CI-exact
`python3 scripts/check-suite-inventory.py` reported `DRIFT tests/: expected
5505, collected 5504` at that head. The duplicate delta is withdrawn from the
sync note (`75845bad0`), and re-running CI's exact invocations at this head
collects 31,672 node IDs across all 17 suites and matches (`tests/` = 5504).
Vulture 1322 -> 1322, radon 137 -> 137, reachability, security-inventory,
model-egress (direct-effect inventory matches), promotion-surface,
ratchet-provenance (0 violations), shipped-surface-truth, test-duplicates,
ruff check/format, and canonical mypy (901 files) all pass. The sandbox suite
itself runs fully live at a process budget this host honors
(`max_processes=4096`): 172 passed / 0 skipped — every kernel conformance
case, including the host-transfer boundary case, executed against a real
namespace. A standalone kernel probe additionally re-confirmed: `/etc` spawn
denial with workdir cleanup, an authorized scratch mount writable at its
guest name and landing on its authorized host root, host `/etc` invisible
with the ro-bound host tree read-only and `/work` writable as a non-root
user, and symlink-to-outside host transfer denied (ELOOP) with the outside
file unchanged. Residual, non-blocking: `validate_host_root(create=True)`
still raises for a not-yet-existing path before its mkdir step — it fails
closed, and no caller passes `create=True`.

Round-8 develop sync (merge `64aa176ce`): `origin/develop` advanced to
`da3b04438`, a squash of an earlier PR #2165 snapshot. All five conflicted
files (`paths.py`, `bubblewrap.py`, `test_host_path_boundary.py`,
`SANDBOX-SUPPORT-MATRIX.md`, this note) are byte-identical on the develop
side to ancestor states of this branch (`3e65811e2` / `0bf126137`), so every
conflict resolves `--ours` and the merge tree equals the pre-sync HEAD
exactly — no suite delta, no source change. Gates re-run at `64aa176ce`:
CI-exact bandit (`packages/maistro-core/src packages/hive-conductor/backend
packages/maistro-server/src -ll --confidence-level=medium`) reports Medium+
count 0 (the develop-side copy predates the `3e65811e2` B108 nosec fix, which
is why the queue's bandit leg failed on the unsynced branch); ruff check and
format pass; the boundary + conformance suites collect 34 passed / 26 skipped
and the full sandbox suite 165 passed / 38 skipped (skips are the documented
namespace-budget environment, live-covered in round 4); CI-exact
check-suite-inventory matches (16,493 node IDs for packages/maistro-core/tests);
vulture and radon ratchets compare against the new base `da3b04438` and match
(1322 -> 1322, 137 -> 137). `mypy --strict` on the sandbox tree is clean; the
five `import-not-found` errors repo-wide come from `maistro_bootstrap` missing
in this worktree's base-deps venv (CI syncs `--all-extras`, where the gate
passes).
