# ghas-mop-residue-ace4

Follow-up after #2357 (DevSkim allowlist + CodeQL on develop) merged ahead of
the queued self-hosted runner matrix.

- Update `tests/test_codeql_scan_scope.py` so the wired-workflow assertion
  expects `develop` on push/PR (matches `.github/workflows/codeql.yml`).
- Dependabot alerts #50 (ecdsa) and #56 (nltk) dismissed as `tolerable_risk`
  — no patched release; still allowlisted in `scripts/pip_audit_gate.py`.
- Remaining open CodeQL/DevSkim alerts wait on the tip analyses queued for
  `44cb5ee97` (self-hosted runners); most are expected to auto-close once
  SARIF uploads (noise roots out of DevSkim allowlist; CodeQL tip already
  holds path/stack-trace/re.escape/`isSafeObjectKey` fixes +
  `**/third_party/**` paths-ignore for BFCL ReDoS).

- Add `workflow_dispatch` to DevSkim so a cancelled tip analysis can be re-uploaded without another product commit.
