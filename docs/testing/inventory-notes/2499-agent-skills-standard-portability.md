---
inventory-delta:
  packages/maistro-core/tests: +25
---

# #2499 — Agent Skills standards-layout directory portability

**Scope:** Added `maistro.portability.agent_skills` as a separate, inert import/export
boundary for `<skill-name>/SKILL.md` packages. Legacy `maistro.skills.parser`
and `export_agent` format remain unchanged.

**Why the split matters:** Upstream Agent Skills requires only `name` and
`description` and permits hyphenated 1–64 character names; the existing
MAIstro parser requires internal `parameters` and snake_case names. It
is unsafe to silently translate those identifiers into tool authority.

**25 collected test cases** in
`packages/maistro-core/tests/portability/test_agent_skills_standard.py`:
roundtrip with inert script/resources and stable content digest; `allowed-tools`
is informational only; malformed frontmatter, unknown keys, duplicate YAML keys,
aliases, invalid names, directory/name mismatches, symlinks, size caps, export
traversal and overwrite refusal; legacy format remains accepted; CRLF preserved
in bundle bytes.

The API does **not** register imported skills into a Workspace, dispatch
bundled scripts, grant tool permissions or enable remote fetch. Any future
runtime consumer must enter existing Warden/Sentinel/Binding/Invocation
boundaries. Conformance against the pinned upstream `skills-ref` validator
and production activation remain outstanding before issue #2499 closes.

Local standalone parser tests were run in an isolated Python harness, but
**the repository's full suite and CI have not yet been run**. This note is
an inventory record, not proof of production acceptance.
