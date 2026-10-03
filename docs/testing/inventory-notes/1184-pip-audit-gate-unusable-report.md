---
inventory-delta:
  tests/: +4
---
# pip-audit gate fails closed on an unusable report (security-gate repair)

The 2026-10-01 `security` CI failure (run 36840245122, job 110297395562) was not
an advisory finding: pip-audit crashed on a PyPI read timeout, the shell
redirect left an empty `pip-audit.json` for `|| true` to paper over, and
`scripts/pip_audit_gate.py` died on a raw `JSONDecodeError` traceback.

The repair makes that state explicit and retryable instead of opaque:

- `audit_pip_report` returns **3** (documented in the module docstring) when the
  report is empty, unparseable, or missing, with a `::error::` message naming it
  an infrastructure failure to retry — never a clean audit verdict.
- `security.yml`'s supply-chain job and `ci.yml`'s `security` job retry the
  audit (3 attempts, 15s apart) only while the report is unusable; a complete
  report is final regardless of pip-audit's exit status so the gate's allowlist
  verdict always decides.

Four tests in `tests/test_check_direct_dependencies.py` (+4): the empty-report
case pins the exact CI failure mode and asserts the retry diagnosis; truncated
and missing reports take the same exit-3 path; `main` propagates 3 without
running the direct-dependency gate on an unusable report. No existing cases
were removed and no baseline or skip policy changed.
