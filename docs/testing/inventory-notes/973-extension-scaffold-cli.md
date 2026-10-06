---
inventory-delta:
  packages/maistro-core/tests: +90
---
# 973-extension-scaffold-cli

[M9-H1](https://github.com/Agent-StrongHold/Project-mAIstro/issues/973): the
`maistro extension new` scaffold CLI and its engine. All +90 node IDs are one
new file, `packages/maistro-core/tests/extensions/test_extension_scaffold.py`
(the `extensions` suite had no scaffold coverage before — this is an addition,
no compensating removals):

- **Schema validation (~45 IDs)** — the manifest validator every generated
  project must pass, tested against the documented contract
  (`docs/extensions/manifest-reference.md`): the reference extension's real
  manifest validates; a rejection matrix covers every required key, the
  closed vocabularies (families, capabilities, effects, data scopes),
  publisher-prefixed ids, strict semver, contract ranges that must pin
  exactly one major, entrypoint shapes, sandbox-relative filesystem paths,
  secret references that may never carry values, and one-pass reporting of
  every violation. One grounding test pins the vocabularies to the
  documented ones so the matrix cannot drift into testing an invention.
- **Rendering/structure (~15 IDs, parametrized over the 5 families)** — each
  family renders a schema-clean project whose Python parses, whose templates
  are structurally distinct (tool → `HANDLERS`/`"handler"`, skill →
  `SKILL_INSTRUCTIONS`/`"skills"`, mcp-gateway → `"upstreams"`,
  capability-provider → `"providers"`, renderer-plugin → `"renderers"`), whose
  generated code imports nothing first-party or third-party, and whose
  pyproject ships the manifest in the wheel.
- **create/refusal + CLI (~25 IDs)** — `scaffold_project` refusal semantics
  (non-empty target, file target, `--force`), and the full `maistro` app
  exercised through its real registration: `extension new` scaffolds,
  defaults to the tool family and `./NAME`, rejects unknown families and
  non-slug names, matches family case-insensitively, honors
  title/description/version, and refuses an occupied target until `--force`.
- **End-to-end (5 IDs, env-gated)** — one per family, skipped unless
  `MAISTRO_TEST_EXTENSION_SCAFFOLD_E2E=1` (the ordinary suite stays offline,
  mirroring the isolation fixture's `MAISTRO_TEST_EXTENSION_ISOLATION`
  precedent): scaffold outside the repo, `uv build --wheel`, install wheel +
  pytest into a fresh venv, run the generated suite there, and assert
  `import maistro` fails in that venv. CI and acceptance runs set the flag;
  the offline suite's count is unchanged by them (skip, not collection).

No other suite moved.
