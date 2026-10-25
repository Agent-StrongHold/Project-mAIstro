---
inventory-delta:
  packages/maistro-core/tests: +106
  packages/maistro-server/tests: +12
---
# 953 — Extension install lifecycle: inspect → authorize → install (#953, M9-B2)

Adds the governed extension install state machine
(`packages/maistro-core/src/maistro/extensions/`), its HTTP operator surface
(`maistro_server/api/extensions.py`), and the tests that pin the issue's
acceptance criteria against reachable behavior.

## packages/maistro-core/tests (+106)

- `extensions/test_install_lifecycle.py` (30 cases) — the state machine end to
  end. The load-bearing one is `test_inspection_and_authorization_never_reach_
  the_loader`: the host loader is the platform's only extension-code-execution
  seam, and a recording spy proves inspect + authorize (approve *and* deny)
  complete without touching it. Also pinned: denied/expired requests leave no
  active extension; permissions display re-verifies the manifest snapshot's
  SHA-256 before showing anything; a crashed loader records FAILED with the
  reason and the same bound artifact recovers on retry; retries neither
  duplicate the (scope, extension, version) record nor widen the frozen grant;
  every transition carries actor, org/workspace scope, extension version and a
  reason; install ids are opaque across scopes.
- `extensions/test_manifest_inspection.py` (43 cases) — the byte-level trust
  boundary: unknown keys/versions, malformed ids/permissions/semver, duplicate
  permissions, artifact claim mismatches and snapshot tampering all fail
  closed with typed rejections.
- `extensions/test_compatibility_trust_authority.py` (30 cases) — the pure
  evaluators: semver major compatibility, dependency range resolution
  (exact/caret/star, unknown grammar unsatisfiable), fail-closed trust (empty
  allowlist trusts nobody, publisher mismatch is a tamper signal), and
  authority deltas that name only genuinely new permissions.
- `extensions/test_container_wiring.py` (3 cases) — the Container builds the
  service lazily and cached, over the in-memory store, with the fail-closed
  `UnwiredExtensionLoader`: a deployment without an activation substrate can
  inspect and decide but can never improvise code execution.

## packages/maistro-server/tests (+12)

`api/test_extensions_api.py` drives the real router and service over HTTP:
the full inspect → authorize → install flow, rejection as a truthful 201,
422s for malformed manifests/payloads, denial refusing install, 404-without-
existence-leak across scopes, Workspace ADMINISTER as the operator authority,
permissions displayed through the snapshot integrity check, the audit-trail
endpoint, the expired-authorization sweep, and the fail-closed default loader
answering 409 with a FAILED record and no active extension.
