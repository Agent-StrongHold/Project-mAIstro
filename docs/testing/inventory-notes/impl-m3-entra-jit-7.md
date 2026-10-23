---
inventory-delta:
  packages/hive-conductor/backend/tests: +22
---

# impl-m3-entra-jit-7

Implementation record for one bounded M3 slice of issue #7 (job
`460d4f00fed94e50b8fa8d0ea175e709`, lane auto-7, starting head
`df227b0f211287971a79e3f8204e7529d2fc9957`). The prior round's NEEDS-DEEP-REVIEW
verdict (job `afb075beb2cb4d98afc80de77bb463b7`) split the M3 gap list into
program-scale absences (Goal layer, backlog control plane, release-pipeline
execution — not implementable in one round) and bounded, evidence-backed
repairs. This round implements the bounded set and declares the rest:

1. **#492 Entra group-gated JIT provisioning is now reachable.** The policy
   engine (`services/entra_entitlements.py`) had no call site outside its own
   tests. New `services/entra_jit.py` is the product transaction its docstring
   promised: settings-validated `EntraJitPolicy` activation, an authoritative
   Graph `transitiveMemberOf` resolver (outage ⇒ refusal, never "no groups"),
   and an `EntraJitProvisioner` wired into `OAuthLoginService.authenticate`
   for unlinked `entra` identities only. Accounts are created `role="user"`
   with an unusable password hash and exactly the mapped permissions; every
   admit/deny decision is audited with policy version and matched groups.
   Reconciliation of already-provisioned accounts is explicitly deferred and
   declared in KNOWN-GAPS.md (permission rows carry no SSO provenance; silent
   revocation could delete manual grants).
2. **#82 backlog gap is now declared.** KNOWN-GAPS.md carried no disposition
   for the generic Workspace backlog control plane (prior finding: "not
   declared anywhere"). It is now release-deferred with a Tracking line, per
   the exit condition's own "explicitly cut over or release-deferred" wording.
3. **#1047 user-model unreachability is now declared** (same file): modules
   and tests exist, no producer or wiring does — the specified-but-not-reached
   pattern, tracked under #1046 rather than counted as shipped.

## Tests added

`packages/hive-conductor/backend/tests/test_entra_jit_provisioning.py` (21
tests): first-login provisioning through the real route + service wiring
(account shape, permissions, durable link, session, audit record), second
login reuse, unknown-group refusal, directory-outage refusal, username
conflict fail-closed, JIT-off preserves prior behavior, fail-closed settings
validation (provider requirement, group UUID keys, case-variant duplicates,
permission ceiling at configuration time), Graph resolver paging/errors,
username derivation, and the concurrent-link race (rollback + canonical
account, no orphan).

## Validation executed

- `uv run pytest packages/hive-conductor/backend/tests/test_entra_jit_provisioning.py -q`
  — 21 passed.
- Adjacent regression suites (entra wiring ×5, oauth wiring ×2, auth routes,
  auth middleware) — 185 passed.
- `uv run ruff check packages/hive-conductor/` — clean;
  `uv run ruff format` applied to touched files.
- `uv run python scripts/check-release-consistency.py` — exit 0 (KNOWN-GAPS
  edits do not affect the version story).

## Follow-up validation round (job `0affa24dd4f14be3b7fcd80f64c0ac4b`)

Re-ran the suite at head `8211ee682` and found one reachability gap in the
tests rather than in the product: every boundary test injected a stub
resolver, so `build_entra_jit_provisioner` and the real `GraphMembershipResolver`
were never exercised through the login route. Added
`test_enabled_settings_build_the_real_graph_resolver_and_provision`, which
rebuilds `OAuthLoginService` from the validated `Settings` object exactly as
production does, lets the real resolver call the fake Graph
`transitiveMemberOf` endpoint with the login's access token, and asserts the
provisioned account receives only the configured permission and that the audit
records the resolver as the membership source. Suite is now 22 tests.

Executed in this round:

- `uv run pytest .../test_entra_jit_provisioning.py -q` — 22 passed.
- Adjacent auth/Entra/OAuth/username suites (9 files) — 170 passed.
- `uv run ruff check` / `uv run ruff format --check` on all touched files —
  clean.
- `uv run python scripts/check-release-consistency.py` — exit 0.
- `uv run python scripts/check-reachability.py` initially failed with
  `services.entra_entitlements` "newly REACHABLE — drop them from the
  baseline". It was listed as unreachable (and CONNECT-dispositioned) before
  this slice wired it; pruned the stale entry from
  `quality/reachability-baseline.json` and
  `quality/reachability-dispositions.json`. Reachability, dispositions, and
  provenance gates then exit 0 (188 → 187 unreachable modules).
- `scripts/check-suite-inventory.py`, `check-contract-markers.py`, and
  `check-backlog-consistency.py` — exit 0.

Residual risks: the Graph call itself is not exercised against a live tenant;
the deployment must grant the login application a delegated Graph scope that
can read transitive group membership, and the feature denies (rather than
provisions) if that scope is absent. Entitlement reconciliation after group
removal remains the declared KNOWN-GAPS deferral.

## Out of scope (recorded, not silently dropped)

Goal model / persistent Workspace Agent (#804), backlog implementation (#82),
release-workflow execution and RC soak (#19/#20), Home/session/attention
producers (#1048–#1051): program-scale work requiring decomposition per the
prior verdict; unchanged this round and tracked in issue #7's exit conditions.
