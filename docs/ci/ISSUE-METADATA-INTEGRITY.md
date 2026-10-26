# Issue hierarchy and metadata integrity

The canonical roadmap is GitHub #453. Parentage is decomposition, never an
execution dependency. Existing closure protection reads native sub-issues, so
prose-only links bypass that part of its evidence model.

`scripts/issue-metadata-integrity.py` inventories open and closed issues through
all pages, excludes pull requests, reads native sub-issues, checks declarations,
detects cycles, and reports classification gaps. `Parent milestone tracker:` is
included. Quoted/fenced examples and `Depends on:` are not parent declarations.
Issues with several declared parents, unknown references, conflicting native
parents or no placement remain exceptions. #453 is the explicit root exception.
#1134 is held because its body and reclassification comment disagree.

## Read-only checks

```sh
GITHUB_REPOSITORY=Agent-StrongHold/Project-mAIstro \
  python3 scripts/issue-metadata-integrity.py --check
python3 scripts/issue-metadata-integrity.py --repo Agent-StrongHold/Project-mAIstro --issue 1884 --check
python3 scripts/issue-metadata-integrity.py --snapshot inventory.json
```

Live commands require `GITHUB_TOKEN`. `--with-comments` includes complete issue
comment history for human review and costs additional API calls. The normal
audit uses complete same-repository sub-issue collections; before any repair,
the direct parent endpoint also detects and refuses cross-repository parents.
API errors are failures, never evidence that a parent does not exist.

The workflow checks newly opened/edited/reclassified issues and runs a daily
full audit. The targeted check judges that issue, independently of old backlog
debt, while traversing ancestors to detect cycles. Missing labels, missing
milestones in a milestone-owned family and milestone/label conflicts fail the
check. Cross-milestone programs need not have a native milestone. These checks
report readiness; the external factory must consume the verdict before dispatch.

## Reviewed hierarchy repair

`quality/issue-hierarchy-links.json` contains 611 source-supported missing links
from the October 19, 2026 Chicago-time investigation. This is a one-time repair
manifest, not a second roadmap. Twelve multiple-declaration cases and #1134 are
excluded. New findings require another review; the workflow does not turn a
new report into authority to mutate issues automatically.

The manifest pins child database identity, complete child and parent bodies, and
potential ownership decisions in their comments. Any changed contract or
ownership discussion stops that batch for fresh review. Operational comments
without ownership/reclassification language do not invalidate its fingerprints.
Comment interpretation beyond this conservative fingerprint remains human work.

Manual workflow dispatch with `apply_links=true` applies up to 25 remaining
links. Existing correct links are verified in the fresh native inventory and
skipped; a different parent is never replaced. Both the child's parent endpoint
and the parent's complete sub-issue list must confirm each new write. The
before/after inventories, exception report and intent/verification journal are
uploaded even when a batch fails. A subsequent invocation resumes without
repeating successful writes. Batches limit API and content-creation load.

No implementation contract, issue state, priority, provenance, assignee, label
or milestone is changed by the hierarchy script. Label/milestone corrections
remain separately reviewed metadata changes.

The investigation applied and independently verified metadata changes on 28
issues; it did not apply the 611 native links. The recurring workflow becomes
active only after this change lands on `develop`, the default branch. Existing
backlog exceptions will keep the full audit red until repaired or explicitly
dispositioned. Do not add this backlog-wide verdict as a required PR status
while that debt remains.

## Verification and remaining acceptance

Sixteen root-suite tests cover parser boundaries, live-parent refusal, source
and ownership drift, graph cycles, native forward/reverse read-back, pagination,
transport failure, classification and second-run idempotence. An offline
simulation applies all 611 proposed links and proves a repeat pass makes zero
writes; this does not certify live GitHub mutations.

Still required: execute and verify native batches; disposition the 12 duplicate
parent declarations and #1134; place or exempt 128 issues without explicit or
native parentage; resolve remaining classification gaps, including #1195's
M1 label/body versus M6 milestone; connect dispatch admission to the verdict;
and verify a full live second run makes no changes. A missing milestone alone
does not prove a defect for intentionally cross-milestone programs.
