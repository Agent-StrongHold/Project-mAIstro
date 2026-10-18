---
inventory-delta:
  packages/maistro-core/tests: +16
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
