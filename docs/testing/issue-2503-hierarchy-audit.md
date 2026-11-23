# GitHub Issue Hierarchy Integrity: Complete Native-Parent Census

**Owner:** [#2503](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2503)  
**Evidence:** [Machine-readable audit snapshot](issue-2503-native-hierarchy-audit.json)  
**Capture started:** 2026-11-23 04:48 UTC  
**Source:** GitHub REST issue-list endpoint, 26 pages, 100 results per page, state=all, created descending. Pull requests excluded.

## Executive finding

The repository's implementation descriptions frequently declare a canonical parent but the native GitHub issue relationship is absent. This is a real metadata-graph discrepancy, not inferred from missing labels or milestones.

| Measure | Count |
| --- | ---: |
| Issues inventoried | 898 |
| Issues with a recognized explicit Parent / Parent epic / Parent initiative / Parent program / Parent milestone tracker declaration | 745 |
| Explicit declarations matching native parent | 113 |
| Explicit parent declarations missing native link | **632** |
| Explicit declarations contradicting an existing native parent | **0** |
| Native-parented issues, including those without a matching declaration in prose | 119 |
| Missing-native-parent issues still open | **170** |
| Missing-native-parent issues closed | **462** |
| Distinct declared parents needing at least one native child | 137 |
| Completely unlabeled issues | 0 |
| Issues without GitHub milestone | 74 |

All 632 declared parent numbers resolve to an inventoried issue. The reconstructed intended graph has zero cycles and maximum depth of six edges. No parent exceeds GitHub's 100 direct-subissue limit when the proposed links are added to the observed native child count.

These counts apply to **recognized explicit Parent declarations only**, not arbitrary references, bullet-list-only relationships, or a full semantic review of later comments. Issue updates may occur between pages; this is a repeatable evidence snapshot, not an atomic GitHub transaction.

## Missing links by the child's native milestone

| Milestone | Missing native parent |
| --- | ---: |
| M0 | 34 |
| M1 | **175** |
| M2 | **125** |
| M3 | 81 |
| M4 | 53 |
| M5 | 27 |
| M6 | 26 |
| M8 | 52 |
| M9 | 44 |
| None | 15 |
| **Total** | **632** |

A missing milestone is not automatically a defect. For instance, #453 and cross-milestone program #160 intentionally have no single milestone. All issues with a single existing milestone:M-number label had a matching GitHub milestone at the end of the classification cleanup.

## Highest-volume missing parent groups

| Declared parent | Missing native children | Open missing children |
| --- | ---: | ---: |
| [#17](https://github.com/Agent-StrongHold/Project-mAIstro/issues/17) | 52 | 13 |
| [#450](https://github.com/Agent-StrongHold/Project-mAIstro/issues/450) | 31 | 11 |
| [#446](https://github.com/Agent-StrongHold/Project-mAIstro/issues/446) | 26 | 8 |
| [#452](https://github.com/Agent-StrongHold/Project-mAIstro/issues/452) | 23 | 1 |
| [#552](https://github.com/Agent-StrongHold/Project-mAIstro/issues/552) | 20 | 2 |
| [#20](https://github.com/Agent-StrongHold/Project-mAIstro/issues/20) | 19 | 3 |
| [#447](https://github.com/Agent-StrongHold/Project-mAIstro/issues/447) | 19 | 0 |
| [#880](https://github.com/Agent-StrongHold/Project-mAIstro/issues/880) | 16 | 3 |
| [#86](https://github.com/Agent-StrongHold/Project-mAIstro/issues/86) | 15 | 4 |
| [#448](https://github.com/Agent-StrongHold/Project-mAIstro/issues/448) | 15 | 6 |
| [#879](https://github.com/Agent-StrongHold/Project-mAIstro/issues/879) | 13 | 13 |
| [#160](https://github.com/Agent-StrongHold/Project-mAIstro/issues/160) | 12 | 2 |
| [#453](https://github.com/Agent-StrongHold/Project-mAIstro/issues/453) | 11 | 8 |

The master roadmap [#453](https://github.com/Agent-StrongHold/Project-mAIstro/issues/453) declares 12 direct children; only #787 is already a native child. The missing 11 root links are a high-impact first repair target. The five M1 epics declared by #446 likewise lack native links.

## Automatic-link eligibility

Of the **632** missing declared edges:

- **613** have exactly one issue reference on the entire parent-declaration line.
- **19** mention additional issue numbers on that same line, even where those may be dependencies or related work. They are conservatively withheld for review. Example: [#2398](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2398) identifies both #2311 and #52.
- **3** of the 613 single-reference edges have different parent/child native milestones and are withheld: [#614](https://github.com/Agent-StrongHold/Project-mAIstro/issues/614) (M4 child, M5 parent #305), [#564](https://github.com/Agent-StrongHold/Project-mAIstro/issues/564) (M3 child, M0 parent #162), and [#440](https://github.com/Agent-StrongHold/Project-mAIstro/issues/440) (M3 child, M1 parent #53).
- **610** are eligible for an operator-controlled native-link attempt, conditional on live revalidation. These are candidates, **not** already executed writes.

The fourth existing cross-milestone case, [#2310](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2310), is already natively parented to #16 and therefore does not appear in the missing-link application set.

## Backfill controls

The accompanying Python migration script is offline/read-only by default. Its write mode uses GitHub's documented sub-issue API with the immutable GitHub issue database ID, not the human-facing issue number as the sub_issue_id.

It applies parent-before-child order and checks the following before each POST:

1. Inventory membership, absence of cycles, and direct-child capacity.
2. Exactly one recognized parent reference in the source line.
3. No existing incompatible native parent, including changes since the snapshot.
4. Same child database ID, state, labels, native milestone, and unchanged full parent-declaration line.
5. Same parent database ID and milestone as the reviewed snapshot.
6. Successful read-after-write verification of both native child parent URL and the parent's sub-issue list.
7. Explicit operator confirmation, no more than 50 writes per invocation, with saved before/after outcome evidence.

Unknown POST outcomes are resolved by re-reading the child; the script does not blindly resubmit a potentially committed link.

The workflow is manual-only and restricted to the canonical develop branch. There is no automatic write trigger and no issue state changes. It must not run until review, CI, and merge complete.

## Closure integrity and residual work

[PR #2504](https://github.com/Agent-StrongHold/Project-mAIstro/pull/2504) is a separate companion guard. It closes the immediate false-closure loophole whereby a parent declares open children in its description while GitHub reports an empty native sub-issue list.

The complete [#2503](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2503) remains open until native backfill is actually executed, verified against a refreshed census, the 22 review-only cases are dispositioned, and the issue-creation/dispatch integrity gate prevents new drift. This evidence document is not a completion claim.
