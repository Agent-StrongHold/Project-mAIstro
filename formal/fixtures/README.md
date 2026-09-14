# Security oracle

`security_oracle.json` is the independently reviewed behavioral fixture for the
formal security gate. It is authored from the security claims in ADR-072,
ADR-073, and SPEC-190; it is not generated from `maistro-core` source and does
not import implementation constants.

The fixture records adversarial inputs that must be blocked, benign inputs that
must remain usable, and the expected number of effective command matches. The
match cardinality is intentional: the curl/wget cases exercise the specific
network-to-shell rules as well as the general pipe-to-shell rule. A rule
removal, weakening, shadowing, or unreachable detector changes a measured
behavior and fails the gate.

Changes to this directory require the CODEOWNER review configured in
`.github/CODEOWNERS`, and the formal workflow rejects a PR that changes the
oracle together with the security implementation or its conformance judge
once the oracle exists at the PR base (the one-time bootstrap is permitted
only when the trusted base has no oracle). Implementation authors must not
self-approve changes
to the oracle. Update the
one-to-one claim map in `formal/SECURITY-CONFORMANCE.md` when the governed
security claims change.
