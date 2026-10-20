---
inventory-delta:
  tests/: +11
---

Pins the shape of every `RATCHET_BASE_REV` declaration in `.github/workflows/`, after three of the five had drifted into handing a topic-branch push `github.event.before`.

`ratchet_provenance._push_event_base` already draws the line: a protected-branch push replaces `before`, so that is its base; a topic-branch push does not, so its base is the integration branch its pull-request run uses. A workflow that names the base itself overrides that resolver, and three did so ref-blindly. On a topic branch `before` is the branch's own previous tip, which any rebase orphans — unreachable from every ref, so `fetch-depth: 0` cannot fetch it and the ratchet refuses with "base revision could not be resolved". The candidate reds on base provenance while its pull-request run passes on byte-identical content, and a re-run cannot clear it because `before` is fixed in the stored event payload.

Nothing pinned the expressions, so the two that were right and the three that were wrong drifted apart silently. `test_a_topic_push_never_falls_back_to_the_branchs_own_previous_tip` rejects `before` as the unguarded final alternative — the fall-through that is the bug — and `test_every_before_is_guarded_by_a_protected_ref` requires each use to sit behind a `github.ref ==` guard naming `develop`, `integration` or `main`. Both are parametrized per declaration, so a new workflow is covered the moment it declares one. A third case asserts the walk finds any declaration at all, so a rename fails loudly instead of passing vacuously.

Verified by running the exact pre-fix and post-fix expressions through the same predicates: the pre-fix text trips both assertions, the post-fix text trips neither.
