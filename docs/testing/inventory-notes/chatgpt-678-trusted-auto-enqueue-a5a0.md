---
inventory-delta:
  tests/: +28
---
# Trusted merge queue admission regression coverage

Issue #678 expands the root tool suite for the repository-owned merge-queue controller from 6 to 34 collected node IDs on this branch.

The additional coverage proves the human-only trust boundary, fetched-base prospective-merge-tree policy evaluation, exact-head object evidence, base-movement refusal before queue mutation, NUL-delimited pathname handling, non-UTF-8 fail-closed behavior, idempotent queue requests, diagnostic Git/GitHub failures, and fail-closed behavior when gates, policy evidence, or queue transport are unavailable.

Three more node IDs answer the final Codex review round's P1 (bind the loaded
policy to the fetched base): a fetched base that advanced past the workflow's
own checkout may carry a tightened policy this controller process never
loaded, so assessing that base with the older policy could classify a
newly-sensitive path green. Two pin the `controller_revision` guard directly
-- a mismatched revision refuses assessment with a loud RuntimeError before
the policy ever runs, and a matching one assesses normally -- and the third
pins `main()` refusing to start without `GITHUB_SHA` at all, because an
unverifiable policy-to-base binding is a refusal, not a default.
