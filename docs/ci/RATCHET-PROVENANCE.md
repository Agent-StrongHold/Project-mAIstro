# Ratchet provenance policy

Issue #542 finishes #319 by making the comparison oracle for quality/security
ratchets independent of the candidate tree. The shared resolver is
`scripts/ratchet_provenance.py` from #534.

A file under `quality/` is not automatically a ratchet ledger. The governing
question is whether a candidate is being judged against an accepted prior state,
or whether the file is itself the specification or generated evidence the
candidate is intentionally changing.

## Trusted-base ratchets

These files record tolerated debt or an externally/security-relevant allowlist.
Their comparison state MUST be resolved from the trusted merge base through
`ratchet_provenance.py`. Candidate bookkeeping may remove stale entries, but a
candidate edit cannot authorize new debt or a newly allowed surface.

| Checker | Ledger | Class | Enforcement |
| --- | --- | --- | --- |
| `check-wiring-reads.py` | `wiring-reads-baseline.json` | tolerance | direct; converted by #534 |
| `check-vulture-baseline.py` | `vulture-baseline.json` | tolerance | direct; trusted rules and identities |
| `check-radon-baseline.py` | `radon-baseline.json` | tolerance | direct; raises authorized at exact resulting complexity |
| `check-citation-status.py` | `citation-baseline.json` | governance tolerance | delegated to `check-citation-status-provenance.py` |
| `check-promotion-surface.py` | `promotion-surface-baseline.json` | security tolerance | delegated to `check-promotion-surface-provenance.py`; a newly unprotected promotion-path module needs prior authorization |
| `check-shell-execution.py` | `shell-execution.json` | security allowlist | delegated to `check-shell-execution-provenance.py`; a new `shell=` execution identity needs prior authorization |
| `check_contract_markers_impl.py` | `contract-markers-baseline.json` | evidence-debt tolerance | delegated to `check-contract-markers-provenance.py` |
| `check_enumerations.py` | `enumeration-baseline.json` | tolerance | delegated to `check-enumerations-provenance.py` so mature discovery stays untouched |
| `check-execution-lifecycles.py` | `execution-lifecycles.json` | lifecycle debt | direct; a new enum identity needs prior authorization |
| `check-reachability.py` | `reachability-baseline.json` | tolerance | delegated to `check-reachability-provenance.py` |
| `check-reachability-dispositions.py` | `reachability-baseline.json`, `reachability-dispositions.json` | tolerance | delegated; the same prior module authorization covers the baseline entry and its required disposition |
| `check_mutation_baseline.py` | `mutation-baseline.json`, `mutation-history.json` | tolerance/history | direct; quality floor and runtime-history evidence both come from base; generated candidates start from that trusted baseline |
| `check-model-egress.py` | `model-egress.json` | security allowlist | direct; a new direct caller requires prior authorization |
| `check-public-routes.py` | `public-routes.json` | security allowlist | direct; a new unauthenticated path requires prior authorization |

`mutation-history.json` is trusted evidence, not an authorization channel. It
changes runtime-regression/new-survivor reporting; it never grants permission to
weaken mutation quality.

## Deliberate candidate-authored specifications and derived evidence

These are not independent tolerance oracles. A candidate may intentionally
change the specification, or the file is generated output. Their dedicated
validators still check structure/consistency, and any trusted input they depend
on remains protected by its owning ratchet.

| Checker | File | Decision |
| --- | --- | --- |
| `check-retired-guidance.py` | `retired-guidance.json` | candidate-authored specification: retiring or restoring guidance is the reviewed change itself |
| `check-image-inventory.py` | `image-inventory.json` | candidate-authored current-tree specification: every Dockerfile must have a reviewed disposition and shipped images must name live build/scan jobs; this checker does not compare against tolerated prior state |
| `ac_state_notes.py` / AC-state fold | per-branch AC notes and bounds | already base-folded through `ratchet_provenance`; candidate note is explicit branch evidence, not the comparison oracle |
| `check_ac_state_impl.py` | `ac-state.json` | generated report output, not an oracle |
| `check_ac_state_impl.py` | `reachability-baseline.json` | measurement input; a candidate cannot self-promote by deleting an unreachable module because the separately required trusted reachability ratchet rejects that deletion while the module remains unreachable |
| `pip_audit_gate.py` | `direct-dependency-exceptions.json` | candidate-authored exception specification; changes require ordinary review and the dependency/audit gate |
| `check-convergence-matrix.py` | `reachability-baseline.json` read for census attribution | informational input at this call site; the blocking reachability ratchet owns trusted-base debt comparison |

## Delegated enforcement

A large measurement checker does not have to be rewritten merely to change where
its comparison oracle comes from. `scripts/check-ratchet-provenance.py` permits a
consumer→adapter mapping only when the adapter exists and uses the shared trusted
resolver. It then executes each live delegated adapter in CI. This preserves the
mature discovery implementation while making the monotonicity verdict
independent of the candidate ledger.

Delegation is enforcement, not documentation: a missing adapter, an adapter that
does not use `ratchet_provenance`, or an adapter returning non-zero fails the
repository provenance test.

## CI inventory contract

`scripts/check-ratchet-provenance.py` is the enforcement owner for this table.
It structurally inventories Python scripts reading `quality/*.json`. A consumer
must be directly base-resolved, delegated to an executed trusted adapter, or
recorded as a deliberate candidate-authored/derived exception with a reason.
The lightweight `Vulture Ratchet` job runs `--inventory-only`, making that
inventory script itself a real workflow-rooted tool and catching an unclassified
consumer before analyzer installation. The required repository test supplies the
deeper proof below.

`tests/test_ratchet_provenance_repository.py` runs that inventory and every live
delegated adapter in the required root test suite. Adding a new ratchet therefore
requires choosing and enforcing its provenance model in the same change rather
than inheriting candidate-controlled comparison by accident.

A trusted-base ratchet must fail closed when the base revision or ledger cannot
be read, identify the base and candidate revisions in its provenance record, and
must not let its normal update/banking path authorize the increase it just
measured. Authorization lives separately in
`quality/ratchet-authorizations.json`, which is itself read from the trusted
base, so a new authorization takes effect only after it has already merged.

Developer runs without a base revision remain possible and are explicitly
labelled worktree-judged by the shared resolver; required monotonicity CI supplies
a trusted base or fails closed.
