---
inventory-delta:
  packages/maistro-bootstrap/tests: +6
  tests/: +12
---
# claude-m2-81-installer-preflight-ae66

`DEPLOYMENT-STANCE.md` listed a `maistro-sandbox-worker` in all four supported
profiles, assigned sandbox execution to it, said "official installs always
include a sandbox worker", and claimed the installer verifies it is "configured
and reachable". **There is no such package, no such compose service, and no
such check.** It also named Kata Containers as the "recommended first backend"
and offered gVisor as a fallback; neither is implemented, and bubblewrap is the
only backend that ships.

**`tests/test_check_deployment_claims.py` (+12)** covers the gate that stops
this recurring. The first test is the literal row that shipped for months — if
it ever stops failing, the gate has stopped doing the one thing it exists for.
The rest establish that a component resolving to a package or to a compose
service passes, that the capability words (`persistence`, `Hive`, `UI`) are
exempt by an explicit list rather than by a silent hole, and that the
services-block parser leaves the block when the indent returns to column zero,
so a `volumes:` key is not read as a service.

The tier table's `Ships?` column is what makes the backend claim checkable: a
row saying **Yes** must name a module that exists, a row saying **No backend**
is the honest state and is not checked, and a row claiming to ship while naming
nothing fails. Two more cover the reporting path — each claim printed with the
remedy, and a missing document failing rather than passing vacuously.

**`packages/maistro-bootstrap/tests/test_sandbox_preflight.py` (+6)** covers
the installer half. `environment_report()` reported `kvm_device: bool` under a
heading called "Virtualization", which to an operator reads as "this host can
isolate untrusted code" — and #76 established that a visible `/dev/kvm` is not
Tier 1, quite apart from the engine shipping no VM backend at all.

The installer runs before the engine is installed and cannot import the
engine's detector, so the fix is not a better probe here. The tests pin what it
says instead: a host without `bubblewrap` is told the engine will *refuse* work
rather than fall back, and told what to type; a host with it is still told to
confirm with `maistro sandbox status`, because `which bwrap` is not the answer
either — a host can have it on PATH and be unable to build the namespace, which
is what taught #76 to probe functionally. A KVM node is reported under a key
that says a device node was *seen*, beside a sentence saying the stronger tiers
have no backend, so it cannot be read as capability.

One test asserts the sandbox section is separate from `virtualization` in the
report. Conflating the host's hypervisor inventory with the sandbox ladder is
what made the old output misleading, and keeping them apart is the fix.
