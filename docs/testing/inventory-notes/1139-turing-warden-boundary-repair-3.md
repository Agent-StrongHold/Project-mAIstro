# Issue #1139 repair - reconcile AuditEntry with the canonical persisted type

Third repair pass, after merging develop (411a2185) into `auto-1139`.

Develop moved the persisted security types: `maistro.security._types.AuditEntry`
became a re-export of `maistro.types.security.AuditEntry`, which carries the
durable audit columns (timestamp, org_id, trace_id, request_id). The #1139
correlation fields (route, action, policy_version, workspace_id, project_id,
run_id, invocation_id, content_sha256, content_length) lived only on the old
inline `_types` class, so the merge conflicted.

Resolution: keep develop's canonical location and re-export, and carry the
#1139 correlation fields onto the canonical `maistro.types.security.AuditEntry`
dataclass. The Turing backend audit record therefore remains the one canonical
shape exchanged with Sentinel and the durable audit stores — no Turing-local
audit vocabulary was introduced, and every #1139 seam (middleware scan, direct
execution-plane scan, deferred chat Run correlation, runtime model-result
audit) still constructs the canonical record.

No tests were added or removed in this pass; the existing #1139 suites
(`packages/maistro-turing` 255 passed, `packages/maistro-core/tests/security`
plus `tests/persistence` 1722 passed) cover the reconciled shape, including
`test_composed_audit_sink_records_correlation_without_content` in
`packages/maistro-core/tests/security/test_composition.py`.
