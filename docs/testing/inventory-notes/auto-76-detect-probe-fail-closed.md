---
inventory-delta:
  packages/maistro-core/tests: +2
---
# auto-76-detect-probe-fail-closed

CI-repair round for #76: the Coverage gate (publish-set floor + diff coverage)
failed on the diff-coverage leg —

```
FAIL: 1 file(s) below the diff-coverage floor
  packages/maistro-core/src/maistro/sandbox/detect.py: 88.9% of 18 changed
  lines (need 90%); uncovered 198, 217
```

Both uncovered statements are fail-closed returns in the Kata-aware `_probe_vm`
(detect.py): line 198 — KVM usable, no `kata-runtime` on PATH, but a non-Kata
VMM (firecracker/cloud-hypervisor/qemu) *is* present, so the probe must refuse
the tier and name the missing supported deployment profile rather than claim
hardware virtualization it cannot launch; line 217 — `kata-runtime` and
`docker` both on PATH but `docker info` exits non-zero, so the daemon survey
failed and the tier reads absent-with-reason. The neighbors (probe timeout →
line 215, daemon without Kata runtimes → line 220) were already tested; these
two branches were the only changed lines nothing executed.

+2 node IDs in `packages/maistro-core/tests`
(`test_real_backend.py::test_the_vm_probe_refuses_a_non_kata_vmm_without_the_supported_profile`
and `...::test_the_vm_probe_refuses_a_docker_daemon_that_is_down`), both
following the file's existing `_probe_vm` pattern (monkeypatched `_kvm_usable`
/ `_which` / `subprocess.run`). No production code moved; every other gate
input is unchanged.

Local evidence at this revision: `coverage run --branch --source=
packages/maistro-core/src/maistro` over the sandbox suite leaves detect.py
missing only line 80; the audit arithmetic over the 18 changed lines vs
develop (`10f872fa7`) computes 100% line coverage (floor 90) and 8/8 branch
arcs (floor 80).
