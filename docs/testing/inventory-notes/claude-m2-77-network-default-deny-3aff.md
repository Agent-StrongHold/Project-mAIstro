---
inventory-delta:
  packages/maistro-core/tests: +25
---
# claude-m2-77-network-default-deny

Unattended sandboxes get no network, grants are explicit and reasoned, and a
backend refuses egress it cannot enforce (#77, ADR-093).

**`tests/sandbox/test_network_default_deny.py` (+24)**

The distinction the suite rests on: `maistro.security.ssrf` guards the engine's
*own* outbound calls and is worth nothing against candidate code, which is not
obliged to go through Python at all. A model-authored script can open a socket.
So "no network" has to mean the kernel never gave the sandbox an interface —
a claim about a namespace, checked against the namespace. The real-kernel tests
open raw sockets to cloud metadata (`169.254.169.254`), a private address and
host loopback, and resolve a hostname; none of them reach.

The rest is the grant model. A grant without a reason is refused, so one cannot
be made by accident and an audit line always has a subject. `HOST` plus an
allowlist reads as "these destinations only" and means the opposite, so it is
refused rather than silently ignored. Both the granted and the denied case are
logged, because "auditable" is not satisfied by recording only the interesting
one — a reader needs to tell "denied" from "never asked".

The sharpest case is `SCOPED` on a backend that cannot filter. Bubblewrap has
two network states: an empty namespace, or the host's shared whole. Reading
"scoped" as "on" would hand over unrestricted egress while the audit line said
scoped, so the grant is refused — before a workdir exists, which the test also
asserts.

ADR-093 decision 6's execution-mode floors had no implementation at all.
Interactive may stand on Tier 3; autonomous may not; an unstated mode gets the
autonomous floor, because treating an unattended run as supervised is the
failure that matters and the converse only costs a refusal on a weak host. The
refusal names which rule raised the requirement.

Decision 3 is enforced just as explicitly in the other direction: first-party
workloads carry `untrusted=False` and are not floored by mode. Applying the
autonomous floor to a Jira call would refuse it on every host without gVisor,
which is not a security gain — it is the ADR being read past its own scope.

**`tests/sandbox/test_real_backend.py` (+1 net)** — one test split in two. A
bare `network=True` no longer grants anything; an explicit `HOST` grant is what
shares the namespace. The old test asserted the boolean was sufficient, which
is precisely what stopped being true.
