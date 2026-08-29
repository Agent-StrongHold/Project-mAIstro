---
inventory-delta:
  packages/maistro-core/tests: +28
---
# claude-m2-80-sandbox-conformance-6fe7

`test_real_backend.py` asserts which flags `bwrap` is given, because that is
this repository's security content and it can be checked on a machine with no
bubblewrap at all. **`packages/maistro-core/tests/sandbox/test_escape_conformance.py`
(+28)** asks the other question, the one #80 is about: with those flags, what
can a workload inside the sandbox actually reach?

Every expectation in it was measured against a live sandbox before it was
written down, and several corrected a guess. Grouped by the attack classes
ADR-093 and SPEC-190 name:

- **Filesystem** — the host's `/etc/passwd` and `/home` are not there to read;
  `/usr` is bound (an interpreter has to exist) but read-only; `/proc/1/root`
  is the sandbox's root, not the host's; a write to `/work` lands in the host
  workdir and a write to `/` does not outlive the sandbox.
- **Process and namespace** — fewer than ten PIDs are visible; `unshare -Ur`
  cannot map a uid, which is how a workload would try to get back what
  `--cap-drop ALL` took; `chroot` and `mount` are refused.
- **Device** — no block device, no `/dev/kvm`, and `mknod` refused. A visible
  disk is a filesystem escape needing no kernel bug.
- **Host sockets** — `/proc/net/unix` and `/proc/net/tcp` are empty and no
  container socket is reachable. A reachable `docker.sock` is root on the host
  with no exploit required.
- **Credentials** — the environment holds only what the config put in it.
  `--clearenv` is the flag; an inherited environment is how an API key reaches
  candidate code without anyone passing it.
- **Privilege** — `CapEff` is zero, and `NoNewPrivs` is 1. The `sudo` and `su`
  under the read-only `/usr` *are* visible, so the property worth asserting is
  the flag that neuters them rather than the absence of the files.

**Resource exhaustion is where this found a live defect.** `memory_mb` and
`cpu_cores` were declared on `SandboxConfig` and applied by nothing: a caller
could ask for 256 MB and watch the workload allocate two gigabytes. Four tests
pin the budgets as values (assertable on any host) and four more prove they
bite against the kernel — a 1 GB allocation raises `MemoryError`, `dd` stops at
the file ceiling, a busy loop is killed by the CPU budget *before* the
wall-clock timeout, and ordinary work still runs under all of them, which is
the test that keeps the limits from being a cure worse than the disease.

`max_processes` is set and deliberately **not** asserted to bite: the kernel
does not enforce `RLIMIT_NPROC` for a parent holding `CAP_SYS_ADMIN` or
`CAP_SYS_RESOURCE`, so an assertion would pass on an unprivileged CI runner and
fail on a root developer container. It is recorded as best-effort in the
support matrix instead, with the reason.

**Two assertions were about the host's wording, not the sandbox, and CI caught
them.** `unshare -Ur` is refused in a privileged container and *permitted* on an
unprivileged runner — nesting is what unprivileged user namespaces are for — so
asserting the refusal was asserting a property of the host. The test asserts
what the nested namespace can reach instead: `/etc/passwd` still absent, `/usr`
still read-only, which holds on both kinds of host and is the property this
sandbox actually owns. `mount` likewise says "permission denied" in one and
"must be superuser" in the other, so that test asserts a non-zero exit and an
unchanged `/proc/self/mounts` rather than a string. Both were then verified by
re-running the file as an unprivileged user, which reproduces the CI wording
exactly.

**Two cleanup assertions were vacuous and are fixed here.** They checked that
`tmp_path / instance.id` no longer existed — but the backend's workdir comes
from `mkdtemp(prefix=f"{id}-")`, so that path never existed in the first place
and the assertion held whether or not anything was deleted. `workdir_of()` now
globs for the real directory, and each cleanup test asserts the directory
existed before asserting it is gone.
