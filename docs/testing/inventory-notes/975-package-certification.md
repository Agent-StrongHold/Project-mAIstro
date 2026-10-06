---
inventory-delta:
  packages/maistro-core/tests: +60
---
# 975-package-certification

Sixty maistro-core node IDs arrive with the M9-H3 pre-publication
certification workflow (issue #975): `test_certification.py` (46) pins the
certification module, `test_cli_certification.py` (14) pins the
`maistro extensions certify` / `verify-certification` commands.

The split follows the issue's acceptance criteria. The truthfulness contract
gets the structural tests: claims are earned only by checks that executed and
passed (skipped, not-applicable and failed checks earn nothing, and their
declared claims never reach the report or its JSON), and a publication-profile
run without executed conformance suites refuses certification while the
declared-but-never-invoked suite is proven to have run zero times. The
signature contract gets real Ed25519 keys: the seal verifies over the report
digest, the report digest covers the framed bundle digest, one flipped byte in
manifest, artifact, or packaged sources is refused — by naming its layer — and
a report edited after sealing fails verification. Subject/environment recording
(extension id, version, publisher, API contract version, SDK/certifier
versions, host, backend, Python, platform, timestamp) is pinned through the
JSON roundtrip, including the refusal of a hand-edited `certified` field that
disagrees with its own recorded results. The install-lifecycle criterion is
pinned end to end: a sealed certification mints the `TrustClaim` the inspect
step consumes, `evaluate_trust` accepts it under a policy pinning the signer's
key, and the record lands in `AWAITING_AUTHORIZATION` — certification is
evidence, and the operator decision is still required — while unbacked trust
evidence fails inspection closed.

The CLI tests pin the CI-facing contract the command help promises:
manifest-profile certification of a well-formed package exits zero and writes
report/seal JSON; publication-profile truthfully refuses (the refusal names the
skipped conformance check, because suites are host-supplied objects a command
line cannot carry); verification round-trips and prints the trust claim, and
exits non-zero for a mutated package, an untrusted key, an unsigned seal, and
an edited report. The remainder covers the scans' degenerate subjects and the
error paths: source-less bundles answer not-applicable and prove nothing,
unparseable sources and manifests are named rather than silently passed,
subscript and non-literal call shapes neither trip nor hide behind the static
rules, a stale `__pycache__` never becomes packaged source, and malformed key
material, policy files, and reports are refused with named errors.

One production bug surfaced on the way and is fixed here: the seal signed with
`Encoding`/`PublicFormat` classes instead of their `Raw` members, so every
`sign_certification` call raised `TypeError` — the first signing test caught
it, which is the test-suite-as-acceptance-evidence case working as intended.
