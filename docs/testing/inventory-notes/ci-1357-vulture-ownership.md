---
inventory-delta:
  tests/: +80
---

# Vulture event-preserving ownership (#1357)

Focused partial recovery from `develop@08febc2bcc9cbd263ce59afff5782b59d25c3719`.
The original #1357 branch and its unrelated rollback history remain intact.
Only Quality's Vulture step gains an event condition: topic pushes retain their
existing owner; shared default PR activities, merge groups and protected pushes
use the already-required `Vulture Ratchet / exact-debt-ledger` owner.

## Equivalence and boundaries

Both invocations use the same root candidate checkout, Python 3.12, shared uv
setup, root `uv sync --locked --all-extras`, locked Vulture 2.16 and exact command:

```sh
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
```

Vulture statically reads those source paths; it does not import the workspace
or depend on Quality's PostgreSQL service, extra analyzers or evolve install.
Both jobs already name the same trusted base: current PR target ref, merge-group
base SHA, protected push's previous SHA, otherwise `origin/develop` for topic
pushes. Candidate ledger changes cannot authorize debt. No scan, provenance,
shipped-surface policy, grant, ledger or baseline implementation is changed.

PR `edited`, reusable `workflow_call`, manual dispatch, unsupported/nested topic
branches and `merge/main-into-integration` pushes do not trigger either existing
Vulture workflow. Tests preserve these explicit boundaries rather than claim
new coverage. Ruff's separate CI edited-event fallback from #1610 is untouched.
No reusable workflow is introduced; #1609's resolver work remains independent.

## Verification

The ownership suite adds 80 cases: deployed contract, 23 event profiles,
50 independent owner mutations, four missing/overbroad fallback controls and
two prerequisite-order regressions.
Cases inspect actual repository YAML across all workflows, exact scan arguments,
checkout scope/history, setup ordering, Python/locked environment, trusted base,
job matrix duplication, shell failure propagation and required status names.
Independent review approved the bounded behavior and identified guard gaps for
skipped-job dependencies, prerequisite ordering and `.yaml` discovery. All three
are hardened; regressions reject a skipped dependency and prerequisites moved
after the scan even when a trailing step masks their old positional check.

The pre-change Quality condition is rejected because it repeats Vulture on the
shared profiles; removing the dedicated owner is also rejected, not accepted
as a skipped or successful replacement.

Local validation: 337 focused ownership/provenance/workflow cases pass; the
exact Vulture scan matches 1,328 reviewed identities; provenance and shipped
surface gates pass. Actionlint, required-check, branch-protection, workflow
write-safety, uv-setup and repository-wide Ruff lint/format checks pass. The
root test inventory matches 5,066 cases. A parsed-workflow comparison proves
that the sole semantic workflow delta is the Vulture condition; the original
workflow fails the new ownership guard.

Live ruleset read-back on 2026-10-07 confirms `exact-debt-ledger` and the Quality
gate remain required in rulesets 21421373 (develop) and 21701487 (main).
No ruleset change is part of this slice. Full exact-head hosted CI and fresh
independent review remain merge prerequisites.

## Residual scope

This does not close #1357, #160 or #1605. Resolved-environment pip-audit
comparison, test/coverage coalescing, serial collector removal, equivalent
artifact sharing, publisher-cost attribution and whole-battery measurements
remain open. The concrete reduction is one repeated Vulture scan per shared
event, with no new runner/setup. Lost duplicate fail-fast coverage and added
contract tests are costs; no net runner-minute or wall-time gain is claimed.
