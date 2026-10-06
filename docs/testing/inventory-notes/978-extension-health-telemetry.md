---
inventory-delta:
  packages/maistro-core/tests: +44
  packages/maistro-server/tests: +12
---

# #978 (M9-I3) — truthful extension health, dependency status, error
# taxonomy, and SLO/usage views

Implements the M9-I3 operational-evidence layer over the M9-B/M9-C
extension substrate: the truthful operational status projection
(`maistro/extensions/health.py`), the durable health/telemetry store twin
(`maistro/extensions/sqlite_health_store.py`), the scope-enumeration seam on
the install store, and the operator HTTP views
(`maistro_server/api/extensions.py`: `/extensions/health`,
`/extensions/health/{id}`, `/extensions/usage`, `/extensions/telemetry/export`,
`POST /extensions/health/{id}/operator`).

**+44 `packages/maistro-core/tests/extensions/`**:

- `test_container_wiring.py` (+1) — the health facade is lazily built and
  cached, and reads lifecycle evidence from the SAME install-store instance
  the install service owns (the fork-the-canonical-record regression is
  pinned by identity, not by behavior).

- `test_health.py` (34) — each refusal path names its acceptance
  criterion: installed-but-incompatible (platform API re-derived now, not
  the install-day verdict), unauthorized (terminal refusal), and unhealthy
  (non-dependency failure) extensions cannot report ready; an unmeasured
  extension reports `unmeasured` while staying ready (absent is not
  healthy); a transient dependency failure projects DEGRADED — live but not
  ready — structurally distinct from the durable QUARANTINED/DISABLED
  operator holds; superseded versions stay attributable (`active=False`)
  and never report active; telemetry for a never-installed version projects
  NOT_INSTALLED; a recoverable FAILED activation reports INSTALL_FAILING;
  liveness vs readiness are separate axes (dependency upgrade past the
  declared range leaves the extension live, not ready); the projection has
  no extension-supplied health input (introspected) and observations enter
  only through the host seam with their taxonomy invariants (failed ⇒
  classified error, dependency-kind ⇒ dependency provenance, enforced at
  construction); health windowing (dependency-only failures degrade,
  non-dependency fail unhealthy, window bounded, no evidence = unmeasured);
  ranking by each metric with unmeasured sorting last (never read as zero)
  and deterministic tie-breaks; SLO error-budget math including the exact
  boundary and the absent-data contract (no position, no alarm); digest
  absent-metrics are `None`, not zero; service views (unknown extension →
  no fabricated status; refused candidates surface UNAUTHORIZED; export
  carries exactly what the views serve).
- `test_health_store_conformance.py` (9) — the in-memory and SQLite twins
  agree on observation/error/decision reads under every filter (scope
  containment included), with `limit` selecting the newest rows; a failed
  observation files its error in both twins; restart survival is proven by
  close/reopen of one SQLite database with identical reads and an identical
  projection; corrupted durable evidence (forged outcome value) fails
  closed on read; timezone-naive evidence timestamps are refused at the
  write; full-field round-trip equality; identical evidence sequences
  produce identical health verdicts through either twin.

**+11 `packages/maistro-server/tests/api/test_extensions_health_api.py`** —
drives the real router over the real services: reads are authenticated like
the install-lifecycle reads; Workspace-scoped operator decisions require
ADMINISTER (a non-member gets the containment 404 and no decision is
recorded) and a recorded reason; the baseline ready view; a quarantine
issued through the API flips the view to QUARANTINED with actor/reason on
the decision; a host-recorded dependency failure shows DEGRADED with
provenance in `recent_errors` and an exhausted SLO budget; unknown extension
detail is 404 (no fabricated status); a historical version projects
SUPERSEDED while the active version stays ready; usage ranking orders by
measured cost with the unmeasured extension last and rejects unknown
metrics with 422; the export matches the views; a container without health wiring
answers 503 rather than improvising a view.
