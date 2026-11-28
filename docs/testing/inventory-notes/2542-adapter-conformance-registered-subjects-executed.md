---
inventory-delta:
  packages/maistro-core/tests: +3
---

# #2542 adapter conformance: no registered supported adapter silently escapes the shared suite

Three tests added to
`packages/maistro-core/tests/testing/test_conformance_claim_contract.py`; no
test removed or renamed.

## What the tests pin

The issue's adapter clause ("prove no registered supported adapter silently
escapes the suite") held at the production seam `run_registered_subjects`,
which before these tests had no pin that binds *registration* to *execution*:

- `test_every_registered_subject_is_executed_with_a_valid_claim` — a subject
  registered under the canonical `maistro.conformance` entry-point group is
  executed by `run_registered_subjects`, and only claim-valid, conformant
  reports come back. Registration alone is not evidence.
- `test_a_registered_nonconforming_subject_fails_the_run` — a registered
  adapter that breaks a semantic (uncancellable effect) fails the run, naming
  that subject; being registered buys no pass.
- `test_a_registered_subject_cannot_skip_its_way_to_a_claim` — a registered
  adapter whose real-backend leg skips produces a claim-less report, and the
  run refuses it: marker-only proof and never-run paths buy nothing.

Together with the existing pins (registration-refusal for nonconforming
provider adapters at `ProviderAdapterCatalog.register`, per-family executable
suites for tools and connectors, and the claim-contract rules for skipped
legs and version mismatch), the enforced contract is: registration ⇒
execution ⇒ valid claim, for provider/tool/connector families alike.
Unsupported and expressly test-only providers need no external service calls:
the tests use the in-repo reference/violator subjects, whose real-backend leg
is a loopback audit socket.

Existing in-repo subjects are deliberately test-only (`testing/
conformance_subjects.py`), so the canonical group stays empty in a base
checkout — `run_registered_subjects` fails closed on an empty group by
design, and these tests exercise the binding with installed-style entry
points rather than registering production surface (which would add
production modules and ledger debt outside this issue's scope).

## Unverified here (environmental)

`scripts/check-suite-inventory.py` cannot complete in this worktree
(`maistro_ext_harness` not installed; pre-existing, unrelated to this
change). Collection of the touched file is clean: 20 passed locally (+3).
