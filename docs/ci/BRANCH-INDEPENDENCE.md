# Branch-independence contract

## Goal

An unrelated move of `develop` must not require an open pull request to rewrite
repository bookkeeping. Updating a branch may expose a real semantic regression,
but a valid change should be able to rerun CI without a new baseline, inventory,
or generated-state commit.

The collaboration invariant is:

```text
develop moves
    -> branch updates
    -> CI re-measures against the new trusted base
    -> no bookkeeping diff is required
```

This is a repository-throughput constraint, not merely a CI-runtime optimization.
A shared aggregate rewritten by every improving branch turns N independent changes
into repeated rebases and rebanks even when the underlying source changes do not
conflict.

## Registry

`quality/branch-independence.json` classifies every JSON state surface under
`quality/`. `scripts/check-branch-independence.py` requires each discovered JSON
file to match exactly one registered surface. The root test suite runs the checker,
so adding another quality-state file requires choosing its representation in the
same change without editing workflow YAML.

The representation classes are:

| Kind | Meaning |
| --- | --- |
| `base_derived` | State is measured from source at the trusted base and candidate; no collaboratively rewritten aggregate is authoritative. |
| `folded_notes` | Independent records are combined with a monotonic fold; one branch does not rewrite another branch's record. |
| `generated` | Reproducible observation belongs in CI evidence/artifacts/cache rather than a tracked shared aggregate. |
| `per_identity_policy` | Durable policy is keyed into independent records so unrelated decisions do not rewrite one array/object. |
| `specification` | The file itself is reviewed policy/specification; changing it is the substantive change rather than mechanical banking. |
| `retired_compat` | A non-authoritative compatibility file retained temporarily so branches predating a migration do not receive delete/modify conflicts. |
| `legacy_shared_aggregate` | Existing synchronization point awaiting migration. New instances are forbidden. |

## Frozen legacy set

The first version records the exact current `legacy_shared_aggregate` paths in
`frozen_legacy_paths`. Globs are forbidden for legacy entries. This is deliberate:
a rule such as `quality/*-baseline.json` would allow the repository to create new
serialization points while claiming the inventory had not changed.

The candidate registry must contain exactly the frozen legacy paths. A migration
removes a path from both the legacy surface and `frozen_legacy_paths`. Adding a
new legacy path fails.

When CI supplies `BRANCH_INDEPENDENCE_BASE_REV` or the existing
`RATCHET_BASE_REV`, the checker also reads this registry at the merge base and
refuses any candidate expansion of the frozen set. A candidate therefore cannot
make a new shared aggregate acceptable merely by adding it to its own freeze.
The initial landing is the bootstrap case because its base has no registry yet.

## Migration rule

A legacy surface should move to the representation that matches what the data
actually means:

1. **Generated observation**: measure it in CI and publish evidence; stop tracking
   the generated aggregate.
2. **Repository measurement / quality floor**: compare a measurement of the base
   tree with the candidate tree. An improvement becomes the next base by merging;
   it does not need a bank commit.
3. **Independent durable decisions**: use one stable identity per record instead
   of one shared array/object.
4. **Small monotonic numeric state**: use independent notes plus a safe monotonic
   fold when that representation is semantically valid, as AC-state already does.
5. **Actual policy/specification**: keep it as reviewed shared policy. Do not call
   an intentional policy edit a collaboration defect merely because it is shared.

A migration may leave the old aggregate as `retired_compat` for a compatibility
window. No checker may use that retired file as authority. Delete it after live
branches no longer predate the migration.

## AC-state: merge-time monotonicity, not review-time rebanking

AC-state has two different jobs and they must not share one synchronization
mechanism.

During pull-request review, the base-resolved fold still rejects regressions and
the touched-criterion mandate still requires new claims to be proven. An
improvement above that bound is informational: the author does not have to write
or refresh a branch note merely to make the measured value equal a number stored
in the branch.

At the merge serialization point, `scripts/check-ac-state.py` measures the actual
immutable base revision in a detached worktree and compares the exact merge
candidate against it. Any regression still fails. Any improvement becomes part
of the next base simply because the improved tree merged; the next candidate is
measured against that newer base and cannot spend the gain.

This ownership is deliberate. Live AC test execution can change the measured
`design_coverage` value between runs even when the source commit is identical.
Making review-time exact equality authoritative turns that measurement noise, or
an unrelated improvement that landed on `develop`, into a mandatory bookkeeping
commit on every open PR. The actual-base merge guard preserves monotonicity
without imposing that branch-wide re-bank tax.

Per-branch AC-state notes remain readable historical evidence and remain part of
the trusted regression fold during the transition. They are not a synchronization
requirement for recording every improvement observed during review.

## What this tranche does not do

This contract intentionally does not convert the eighteen existing legacy
aggregates. In particular it does not modify the direct-effect, vulture, radon,
enumeration, reachability, mutation, model-egress, public-route, or wiring-read
checkers. The trusted-base provenance work can therefore land independently.
Subsequent branch-independence PRs shrink the frozen set one surface at a time.

The success metric for those migrations is operational: after an unrelated merge
to `develop`, a semantically valid open PR should rerun its checks with a clean
working tree. A genuine regression may fail, but its remediation must be source or
policy work, not `--bank` churn.
