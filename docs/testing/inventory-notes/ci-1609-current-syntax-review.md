---
inventory-delta:
  tests/: +24
---

# Current reusable-workflow syntax and conditional caller review (#1609)

The exact-head review of `61c4c17d` found three additional compatibility gaps:

- Both `./` and `$/` identify same-repository workflows at the running commit.
  Normalize either prefix through the existing repository-root path handling;
  external paths, traversal, nested directories, refs and escaping symlinks
  remain refused. No production workflow is migrated.
- Disable the implicit YAML timestamp resolver in the local SafeLoader, so
  date-shaped caller/callee names and literal string inputs/defaults remain
  text. Global PyYAML behavior and safe constructors are unchanged. This is
  not a complete YAML 1.2 schema implementation.
- Refuse conditional or dependency-bound reusable callers. A skipped reusable call need not emit
  its composed callee contexts, so discovering those contexts unconditionally
  would guess names that may not report. A skipped dependency can skip the
  caller transitively even without an explicit caller condition. Caller matrices and conditional
  callee jobs remain unsupported. Direct-job scope behavior is unchanged.

Twenty-four additional cases cover both local prefixes, containment, seven raw-YAML
date/timestamp cases, conditional caller refusals, and string/list dependency
forms with direct/transitive skipped predecessors. The former conditional
caller base-scope case is corrected to require refusal; a separate case retains
proof that workflow-level PR-base filters propagate to composed names. No
existing test coverage is removed. Nineteen cases fail before these repairs;
the other cases retain negative path and scope-preservation coverage.

References:
- https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_iduses
- https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idif
- https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idneeds
- https://yaml.org/spec/1.2.2/ext/changes/
