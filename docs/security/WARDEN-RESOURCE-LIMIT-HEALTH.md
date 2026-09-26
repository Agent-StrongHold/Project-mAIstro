# Warden resource-limit health evidence

## Operational meaning

Warden's scan-window and per-pattern timeout controls protect the output
security boundary from pathological input. They are not a `/health/ready`
metric: readiness reports process and deployment dependencies, while a
constant or a healthy process cannot demonstrate that regex work is bounded.

The operational claim is therefore supported by executable product-path
evidence, not by the configured values alone. The canonical evidence runs the
real Warden behind `build_output_security_gate` through
`MasterOrchestrator.execute`:

```sh
uv run pytest \
  packages/maistro-core/tests/orchestrator/test_output_security_gate.py \
  packages/maistro-core/tests/security/test_sentinel_policy.py \
  packages/maistro-core/tests/security/test_warden_regex_equivalence.py -q -x
```

Those tests prove a catastrophic reject pattern fails closed under the
per-search timeout, reject/heuristic/semantic fallback searches receive no
more than one scan window, the canonical Run/NodeRun/Attempt projection keeps
only the static refusal, and accelerated and stdlib fallback engines produce
the same Warden verdict corpus. The output-gate tests also pin the
capture-to-full-conversation ordering regression, so an earlier benign object
phrase cannot hide a later attack pair.

PII handling is separately exercised at the production governed-executor
boundary in `packages/maistro-core/tests/agents/test_base.py`; it verifies that
a raw credential is masked before it reaches model context or the user-facing
response, and that an unavailable filter blocks output fail-closed.

For the control inventory and its detailed test references, see
[SECURITY.md](../../SECURITY.md#product-path-evidence-for-scanner-limits).
The non-release compliance claims and matching product-path evidence are in
[COMPLIANCE.md](../../COMPLIANCE.md#product-path-evidence-for-security-claims).
