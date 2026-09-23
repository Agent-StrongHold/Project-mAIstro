---
inventory-delta:
  packages/maistro-rsi/tests: +35
---
# Issue #1138 Warden harvest boundary

Adds collected cases covering recursive RSI harvest admission: ordinary and
structured payload forms, model-call refusal, unavailable-policy fail-closed
behavior, audit correlation/redaction, canonical event persistence, digest
evidence, nested keys, synchronous active-loop refusal, and saved-patch resume
refusal for hostile or unavailable Warden policy.

The repair pass adds `test_non_production_reachability.py` (13 node IDs):
RSI's activation defaults stay pinned to disabled/non-production-reachable
until #552's M5 containment gates. No engine product package may import the
`maistro_rsi` surface; the only product references are the Conductor's two
execution-policy-gated seams; the HTTP run gate stays literally fail-closed
(`IN_PROCESS_ISOLATION_AVAILABLE is False`, and `start_run` resolves
`require_isolation()` before dispatch). Scanner-sensitivity cases prove the
static scans flag every import form (including dynamic `import_module` /
`__import__`) and the activation flips, so a green run is evidence rather
than a vacuous pass.

The second repair pass adds 6 more node IDs closing the residual audit-
correlation and adversarial-probe gaps: the real maistro-evolve swebench
seam is pinned as guarded by the cycle-installed wrapper (plus a control
proving the seam itself does not scan, so the wrapper is load-bearing);
hostile builder system prompts, scout sources, judge diffs, and proposer
hypotheses are each refused before their model callable with durable,
campaign-correlated audit records; resume refusals now also assert the
audit trail carries campaign/repository/base correlation. Mutation
validation executed: disabling the runner guard, the scout scan, the
builder system-prompt admission, or the resume admission each fails the
adversarial tests (2/1/1/2 failures respectively).

Revalidated at merge head `11b1a55ea` (develop base `84d937add`, no test
delta): the develop merge touched no `maistro-rsi`/`maistro-evolve` file and
left `WardenVerdict` unchanged (only `Violation`/`AuditEntry` moved to
canonical types). Full battery re-executed: 756 rsi + 645 evolve tests pass,
ruff check/format clean, suite-inventory/security-inventory/reachability
(+dispositions, provenance) gates pass. Mutation checks re-executed at this
head: removing the runner guard fails 2 tests; ignoring the resume-patch
admission fails 2 tests; both mutations reverted with the tree byte-verified
clean. One unrelated pre-existing upstream failure
(`maistro-core/tests/security/test_log_redaction.py::test_install_is_idempotent`)
reproduces on canonical develop and is out of scope for this lane.
