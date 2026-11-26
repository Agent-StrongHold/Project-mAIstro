---
inventory-delta:
  packages/maistro-rsi/tests: +34
---
# 302-rsi-promotion-quarantine-approval

#302 — require quarantine and signed approval before RSI promotion — adds 34
node IDs to `packages/maistro-rsi/tests`: 29 in the new `test_promotion_gate.py`
and 5 in `test_local_loop.py`. No tests were removed or renamed.

The defect: `LocalRsiLoop._run_cycle` fast-forwarded `rsi-baseline` on
`accepted=True` alone — the internal promotion path never consulted
`quarantine_scan` or `matches_sensitive_pattern` (the guards existed only on the
selfbranch/PR/export paths), so a candidate could mutate the baseline on a green
test command by itself.

What the new tests pin:

- `test_promotion_gate.py` (29, new): the gate's fail-closed contract — a
  Warden-flagged diff never clears; a sensitive-surface diff with no reviewer
  and no approval source parks (default posture); a review denial, an
  unavailable (crashing) approval source, a missing record, an expired
  approval, a malformed record (every field), a wrong policy version, a wrong
  signature, and a binding mismatch (other candidate/diff/scope) each refuse;
  the HMAC payload excludes the signature itself; an ordinary clean diff
  clears with no approval even when a source exists (approval is required
  only where the deterministic classifier says so — never a candidate- or
  model-populated boolean); `DirectoryApprovalStore` treats absent and
  malformed files as no evidence; and the dict-shaped (JSON) record path — a
  badly-shaped one is malformed evidence, never approval.
- `test_local_loop.py` (5): loop-level proof that the direct `--ff-only` path
  cannot execute without the gate — an ordinary green change still promotes
  and its trace note carries the quarantine evidence; a sensitive candidate
  (edits `maistro_rsi/local_loop.py`) that passes the test command is refused
  with the baseline HEAD unchanged; a valid-but-unbound approval does not
  authorize; a reviewer approval plus a pre-signed, correctly bound approval
  is the only path that promotes, and the promotion's durable git-note record
  then carries the full approval provenance; and the #109-style adversarial
  case — a candidate that rewrites the fitness evaluator and a test file
  (both sensitive paths) cannot self-score into promotion.
