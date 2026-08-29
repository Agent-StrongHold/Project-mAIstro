# Ratchet provenance policy

Issue #542 finishes #319 by making the comparison oracle for quality/security
ratchets independent of the candidate tree. The shared resolver is
`scripts/ratchet_provenance.py` from #534.

A file under `quality/` is not automatically a ratchet ledger. The governing
question is whether a candidate is being judged against an accepted prior state,
or whether the file is itself the specification the candidate is intentionally
changing.

## Trusted-base ratchets

These files record tolerated debt or an externally/security-relevant allowlist.
Their comparison state MUST be resolved from the trusted merge base through
`ratchet_provenance.py`. Candidate bookkeeping may remove stale entries, but a
candidate edit cannot authorize new debt or a newly allowed surface.

| Checker | Ledger | Class | Policy |
| --- | --- | --- | --- |
| `check-wiring-reads.py` | `wiring-reads-baseline.json` | tolerance | converted by #534 |
| `check-vulture-baseline.py` | `vulture-baseline.json` | tolerance | trusted base |
| `check-radon-baseline.py` | `radon-baseline.json` | tolerance | trusted base |
| `check_enumerations.py` | `enumeration-baseline.json` | tolerance | trusted base |
| `check-execution-lifecycles.py` | `execution-lifecycles.json` | tolerance | trusted base |
| `check-reachability.py` | `reachability-baseline.json` | tolerance | trusted base |
| `check-reachability-dispositions.py` | `reachability-baseline.json`, `reachability-dispositions.json` | tolerance | trusted base |
| `check_mutation_baseline.py` | `mutation-baseline.json`, `mutation-history.json` | tolerance/history | trusted base for the accepted floor; history is evidence, not authorization |
| `check-model-egress.py` | `model-egress.json` | security allowlist | trusted base |
| `check-public-routes.py` | `public-routes.json` | security allowlist | trusted base |

## Deliberate candidate-authored specifications

These are not tolerance ledgers. A candidate may intentionally change the
specification, so forcing the previous revision to remain authoritative would
make the documented workflow impossible or would answer a different question.
They remain candidate-authored, and their dedicated validators must continue to
check structure, consistency, and any separate trusted inputs they consume.

| Checker | File | Decision |
| --- | --- | --- |
| `check-retired-guidance.py` | `retired-guidance.json` | candidate-authored specification: retiring or restoring guidance is the reviewed change itself |
| `check-ac-state.py` | `ac-state-notes/` and generated AC state | AC bounds already fold per-branch notes from the base via `ratchet_provenance`; the candidate note is explicit branch evidence, not the comparison oracle |
| `pip_audit_gate.py` | `direct-dependency-exceptions.json` | candidate-authored exception specification; changes require ordinary review and the dependency/audit gate, rather than pretending the old exception set is the only valid future set |
| `check-convergence-matrix.py` | `reachability-baseline.json` read for census attribution | informational/specification input at this call site; the blocking reachability ratchet owns trusted-base debt comparison |

## CI inventory contract

`scripts/check-ratchet-provenance.py` is the enforcement owner for this table.
It must fail when a checker reads a `quality/` JSON ledger that is neither
base-resolved nor listed here as a deliberate candidate-authored exception.
Adding a new ratchet therefore requires choosing its provenance model in the
same change rather than inheriting candidate-controlled comparison by accident.

A trusted-base ratchet must fail closed when the base revision or ledger cannot
be read, must identify the base and candidate revisions in its provenance
record, and must not let `--update` authorize the increase it just measured.
Developer runs without a base may remain worktree-judged when they label that
fact explicitly; required CI always supplies the trusted base.
