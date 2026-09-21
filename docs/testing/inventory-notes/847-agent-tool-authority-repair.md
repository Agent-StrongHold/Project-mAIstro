---
inventory-delta:
  packages/maistro-core/tests: -1
  packages/maistro-evolve/tests: +1
---

# Issue 847 gate-repair coverage

Repair pass over the rebased branch: the strategy no longer carries decorative
compatibility stubs, so the 14 stub-projection tests (repository recon, failure
patterns, PR diagnostics, learning stores, utc_now) are removed with the five
dead methods they exercised and replaced by one structural regression guard
asserting the strategy owns no tool-execution surface. The Docker `_shell_quote`
passthrough test is replaced by real `parse_command` contract tests
(tokenization, shell-operator rejection, interpreter rejection, malformed argv).
The Agent-level narrowing test now composes the invocation-time seam
(`_authority_for(...).wrap(_sentinel_governed_executor(...))`) that
`Agent._run_strategy` actually builds, instead of a dead `__init__` attribute.
Adds branch/ref option-injection denial coverage for `github_create_pr`
(branch/base), `github_get_pr`, and `github_list_issues`, non-object JSON
argument denial in Artificer, and shell-operator/interpreter refusal at the
`sandbox_exec` MCP boundary. In maistro-evolve, corpus rows with an empty
`repo_state`/`task_id` are refused by the loader (digest pins bytes, not
shape), with a tamper-and-repin test.
