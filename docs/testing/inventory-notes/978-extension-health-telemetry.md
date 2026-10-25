---
inventory-delta:
  packages/maistro-core/tests: +55
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

- `test_container_wiring.py` (+4) — the health facade is lazily built and
  cached, and reads lifecycle evidence from the SAME install-store instance
  the install service owns (the fork-the-canonical-record regression is
  pinned by identity, not by behavior); a host that prewires
  `extension_install_service` over its own store without mirroring the
  `extension_install_store` field gets the field backfilled from the
  service and a health facade reading that same store (never a forked
  empty one); and `create_container` itself selects the health store from
  the configured backend — the SQLite twin whenever it owns a SQLite
  connection (operator holds are durable-admission state and must survive
  restart), the in-memory twin only for the deliberate `memory://`
  configuration.

- `test_health.py` (39) — each refusal path names its acceptance
  criterion: installed-but-incompatible (platform API re-derived now, not
  the install-day verdict), unauthorized (terminal refusal), and unhealthy
  (non-dependency failure) extensions cannot report ready; an unmeasured
  extension reports `unmeasured` while staying ready (absent is not
  healthy); a transient dependency failure projects DEGRADED — live but not
  ready — structurally distinct from the durable QUARANTINED/DISABLED
  operator holds; superseded versions stay attributable (`active=False`)
  and never report active; telemetry for a never-installed version projects
  NOT_INSTALLED through the service's detail, overview, and export views
  (with the requested identity kept verbatim; only an identity with no
  recorded evidence at all answers None); a failed observation rejects an
  embedded error whose org/workspace/extension/version provenance does not
  match the observation's own identity, and telemetry metrics must be
  finite and non-negative at construction (negative/NaN latency or cost
  would fabricate rankings and break the JSON response); a recoverable FAILED activation
  reports INSTALL_FAILING;
  liveness vs readiness are separate axes (dependency upgrade past the
  declared range leaves the extension live, not ready); the projection has
  no extension-supplied health input (introspected) and observations enter
  only through the host seam with their taxonomy invariants (failed ⇒
  classified error, dependency-kind ⇒ dependency provenance, enforced at
  construction); health windowing (dependency-only failures degrade,
  non-dependency fail unhealthy, window bounded, no evidence = unmeasured);
  ranking by each metric with unmeasured sorting last (never read as zero)
  and deterministic tie-breaks; every status-projection read requests only
  the newest HEALTH_WINDOW rows, so projection latency does not stream the
  store's whole retained history; SLO error-budget math including the exact
  boundary and the absent-data contract (no position, no alarm); digest
  absent-metrics are `None`, not zero; service views (unknown extension →
  no fabricated status; refused candidates surface UNAUTHORIZED; export
  carries exactly what the views serve); and the service feeds the readiness
  gate each declared dependency's OWN health — evaluated from that
  dependency's active version's host-recorded evidence, so a failing
  provider marks an otherwise-clean dependent not ready, while a failure
  recorded against a superseded dependency version does not condemn the
  upgraded one.
- `test_health_store_conformance.py` (12) — the in-memory and SQLite twins
  agree on observation/error/decision reads under every filter (scope
  containment included), with `limit` selecting the newest rows; a failed
  observation files its error in both twins; restart survival is proven by
  close/reopen of one SQLite database with identical reads and an identical
  projection; corrupted durable evidence (forged outcome value) fails
  closed on read; timezone-naive evidence timestamps are refused in the
  shared evidence model (both twins inherit the rule) with the SQLite
  write-time check kept as the constructor-bypass backstop; full-field
  round-trip equality; identical evidence sequences
  produce identical health verdicts through either twin; and two store
  instances writing one database concurrently allocate distinct sequences
  (each append opens with BEGIN IMMEDIATE, so the write lock is held across
  the MAX(seq) read — no lost or duplicated append); and both twins agree
  on the read-limit contract (limit counts down from the newest row, 0
  selects nothing, negative is refused — Python's rows[-0:] would return
  every row while SQLite's LIMIT 0 returns none).

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
