# CI Operating Standards

Status: Active.

## Organize by invariant
CI should be organized around explicit invariants rather than historical tools, scripts, or workflow names. Prefer one invariant, one canonical owner, and one authoritative result. Tools are evidence producers.

## No hidden checks
A named check must accurately represent its contract. Umbrella checks must expose their constituent assertions in a discoverable, machine-readable form. Do not hide unrelated blocking checks behind misleading names.

## No duplicate invariant ownership
Do not independently enforce the same invariant in multiple blocking locations. Reuse canonical evidence when inputs and toolchain are equivalent. One underlying defect should not unnecessarily create several independent blocking failures.

## Merge readiness is an aggregator
The final merge-readiness decision should aggregate authoritative results for the exact candidate or merge-group artifact. It should not introduce a second hidden set of validators.

## Candidate owns candidate delta
Ratchets should normally charge a candidate only for regressions it introduces relative to its trusted base. If trusted base has X debt and candidate has X debt, the candidate passes that ratchet. If candidate introduces X+1, it fails unless that increase is appropriately authorized.

## Baseline health is not candidate debt
Repository-wide baseline inconsistency is a CI/repository-health problem. Report it separately rather than attributing unrelated global drift to whichever candidate encounters it.

## No authorization serialization chains
Do not require a legitimate candidate to merge a separate authorization PR before the candidate can become eligible to pass. Authorized exceptions or dispositions should be evaluable atomically with the candidate whenever possible while still preventing silent unauthorized policy weakening.

## Autonomous remediation
Failures must identify the actual invariant violated and provide enough precise evidence for an authorized agent to remediate the problem without reverse-engineering umbrella workflows or relying on tribal knowledge.

## Concurrency
Evaluate CI architecture for merge-queue throughput, unnecessary reruns, shared mutable state, global baseline churn, migration collisions, duplicated computation, cross-PR serialization, and long-lived branch sensitivity. A mechanism that works for a few contributors but collapses under many autonomous lanes is inadequate for this repository.

## Strong verification over manual friction
Preserve useful rigor. Prefer better provenance, deterministic evidence, precise authorization, and artifact verification over manual ceremony or human-only repository operations.
