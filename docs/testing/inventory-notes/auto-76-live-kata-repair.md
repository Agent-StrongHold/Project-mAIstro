---
inventory-delta:
    packages/maistro-core/tests: 3
---

# Issue 76 live-Kata repair inventory delta

This repair round stood up the real Kata deployment profile on the
development host (`/dev/kvm` access, kata-containers 3.32.0 static bundle,
docker `kata` runtime via `runtimeType: io.containerd.kata.v2`) and fixed the
three production defects the live conformance then exposed:

1. `KataSandboxBackend.exec` now re-asserts the spawn-time
   no-new-privileges promise per exec (`setpriv --no-new-privs`), because
   Kata's guest agent applies NNP to the container init process but not to
   `docker exec` processes (`test_kata_backend.py` +1: the mocked argv pin).
2. Kata's virtiofs share enforces host mode bits against the guest's id
   mapping, so the 0700/0600 transfer defaults were unreadable in-guest.
   `make_beneath_guest_readable` widens the written chain through the same
   no-follow walk, and the bind root gets /tmp semantics
   (`test_host_path_boundary.py` +2: chain widening incl. fd-root caller,
   swapped-symlink refusal).
3. `_probe_vm` now absorbs a launcher `RuntimeError` as tier-absent instead
   of aborting detection — the same #1328 contract the bubblewrap probe
   already honored. No test-count change: the existing
   `test_an_unsupported_preexec_hook_reads_as_absent_not_an_abort` previously
   passed vacuously on hosts without the Kata profile and now exercises the
   real docker-info call path.

Net +3 tests across `packages/maistro-core/tests` (13→14 in
`test_kata_backend.py`, 25→27 in `test_host_path_boundary.py`).
`test_kata_live_conformance.py` keeps its 10 tests; on this host they now
run and pass against real Kata VMs instead of skipping.
