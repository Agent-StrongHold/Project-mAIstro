---
inventory-delta:
  packages/maistro-core/tests: +33
---
# 972-extension-quarantine

Lands the M9-G4 quarantine/disable flow for misbehaving extensions
(`packages/maistro-core/src/maistro/extensions/quarantine.py`): canonical
security/sandbox/health evidence with threshold-driven suspension, the
M9-G2 → M9-G4 bridge the sandbox violation log's escalation names, three
distinct responses (version disable, package quarantine, publisher-wide
action), immediate admission refusal after the authoritative state change,
in-flight drain/terminate disposition, and an append-only ledger no
extension actor can write or clear. Thirty-three node IDs in
`packages/maistro-core/tests/extensions/test_extension_quarantine.py`.

Per-criterion mapping (issue #972 acceptance):

- **extension cannot write or clear its own quarantine/security state** —
  `test_extension_actor_cannot_mutate_governance_state` refuses an
  `ActorKind.EXTENSION` actor on every mutating method and asserts no state
  and no ledger rows resulted;
  `test_extension_actor_cannot_clear_an_administrator_quarantine` proves a
  refused self-clear leaves the suspension in force. Structurally, no
  method accepts an `ExtensionContext`.
- **quarantined extension receives no new Invocations even if clients still
  request it** — `test_no_admission_after_the_authoritative_state_change`
  schedules 25 concurrent admissions against a quarantine under
  `asyncio.gather` and asserts (from a shared ordering log, not timing)
  that no allowed admission follows the state change;
  `test_begin_invocation_raises_when_suspended` proves the combined
  admit-and-open step fails closed; `test_disabled_version_refuses_begin_and_naming_is_accurate`
  checks the disabled reason path.
- **historical Runs/Invocations remain queryable** — governance history is
  append-only and never rewritten:
  `test_history_is_append_only_and_narrowable` (prefix stability across
  later events, per-version narrowing, actor attribution),
  `test_re_enable_preserves_strikes_and_history`,
  `test_audit_rows_carry_evidence_digests`. Canonical Run evidence stays
  with the Run/NodeRun/Attempt chain; this module only refuses new work.
- **re-enable requires canonical authorized action and does not erase
  strike/violation evidence** — `test_re_enable_preserves_strikes_and_history`
  proves strikes survive re-enable and the next violation re-quarantines
  from lifetime strikes; `test_authorized_actors_can_mutate` pins the
  admin-actor requirement;
  `test_package_lift_under_quarantined_publisher_reports_effective_state`
  pins the develop-sync repair: lifting a package quarantine under a still
  quarantined publisher audits `state_after=QUARANTINED` (the effective
  governing state, not the package layer alone), keeps admission refused,
  and stays on the ledger.
- **one bad version disabled without condemning unrelated signed versions,
  unless policy chooses publisher-wide action** —
  `test_version_disable_does_not_condemn_sibling_versions`,
  `test_package_quarantine_blocks_all_versions_but_not_other_packages`,
  `test_publisher_quarantine_is_an_explicit_action`, and
  `test_publisher_wide_policy_quarantines_the_publisher_on_trigger` (off by
  default, on by explicit policy).
- **distinction between package quarantine, version disable, and transient
  health failure** — the response taxonomy above plus
  `test_transient_health_failures_change_no_state` (below-threshold health
  evidence records but never suspends) and
  `test_health_failures_at_the_threshold_quarantine`.
- **security violations attributable to identity/version** —
  `test_evidence_is_attributed_and_digested` (stable digests, full
  attribution), `test_evidence_requires_full_attribution` (degenerate
  path), `test_sandbox_bridge_feeds_boundary_events_into_governance` and
  `test_sandbox_bridge_kinds_round_trip` for the M9-G2 seam the sandbox
  log's candidate-for-quarantine warning names.
- **threshold/instant behavior and degenerate paths** —
  `test_security_violation_quarantines_immediately`,
  `test_sandbox_violations_accumulate_to_the_threshold`,
  `test_sandbox_threshold_matches_the_m9g2_escalation_point`,
  `test_thresholds_are_deployment_configurable`,
  `test_policy_rejects_nonpositive_thresholds`,
  `test_governance_actor_requires_an_id`,
  `test_unknown_identity_admits_until_evidence_says_otherwise`.
- **in-flight disposition** — `test_in_flight_work_drains_by_default`,
  `test_in_flight_work_terminates_when_policy_chooses_it`,
  `test_disposition_is_a_pure_query`.
- **degenerate paths and single-state authority** —
  `test_re_enable_paths_work_on_never_governed_identities`,
  `test_strikes_for_unknown_identity_is_zero`,
  `test_evidence_on_governed_identities_reports_the_effective_state`
  (below-threshold evidence rows report the identity's actual governing
  state — disabled version, quarantined package, quarantined publisher —
  through the same `_governing` authority admission and disposition use).
