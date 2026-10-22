---
inventory-delta:
  tests/: +61
---

# Current-event Ruff ownership (#1610)

Refreshes #1610 on `develop@d0b942b9d7ab345ea6f1e50ce4e7a00de41cbfce`.
The earlier branch assumed both workflows received identical PR activities.
CI now also receives `edited` to recheck closure targets, while Quality keeps
GitHub's default `opened`, `reopened`, and `synchronize` activities. Retaining
CI's Ruff pair on `edited` closes that newly uncovered event without adding
whole Quality runs for metadata edits. CI also retains the existing
`merge/main-into-integration` push fallback. Common events use Quality alone.

The parsed CI workflow differs from current develop only in the two Ruff step
conditions. No tool pin, rule, source, setup, permission, job or required check
changes. Both owners use the candidate checkout, shared uv 0.12.5 setup, locked
Ruff 0.15.12, Python 3.12 and root configuration. Live rulesets 21421373 and
21701487 on 2026-10-07 still require both `lint-and-type-check` and the Quality
gate. Existing declared/live queue differences are not changed by this PR.

The ownership suite now has 96 cases, retaining the earlier 35 cases' coverage
and adding 61. Thirty-two cases evaluate the actual workflow triggers and
conditions for both Ruff commands across 16 event profiles. The remaining new
cases guard the edited fallback, overlapping push patterns, checkout/setup/sync
ordering, conditional or tolerated prerequisites, matrix/extra-job duplicates,
and CI's required status on both protected branches.

Negative controls demonstrate that the historical condition executes no Ruff
owner for `edited`, whereas the repaired condition selects CI. Twenty-four
isolated mutations are accepted by the previous guard and rejected by the new
one after adapting only its stale PR-trigger expectation and fallback constant;
both clean controls pass. This prevents unrelated assertion failures from
masquerading as mutation coverage. The shell mutation now uses
`bash -c "source {0}; true"`, which genuinely masks a failing script. The old
`bash {0} || true` mutation tested rejection of custom shells but would pass
`|| true` as literal arguments rather than execute a shell OR-list.

Local validation on the complete repository: 96 ownership cases and 398
combined workflow/gate cases pass; the parsed-workflow comparison and required
check, branch-protection, workflow-inventory, write-safety and uv-setup gates
pass. Full exact-head hosted checks and review remain merge prerequisites.

The concrete saving is one duplicate Ruff lint invocation and one duplicate
format invocation per common event, with no additional runner or environment
setup. CI loses the earlier duplicate fail-fast point, and the guard suite adds
work. No net runner-minute, wall-time or fleet-throughput gain is claimed.
