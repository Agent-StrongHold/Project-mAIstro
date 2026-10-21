---
inventory-delta:
  packages/maistro-core/tests: +17
---
# Issue #34 Portability CONNECT tranche — `maistro portability` CLI

Issue: #34
Parent: #446

## Claim

The #34 CONNECT tranche for the `portability` subsystem wires the four
`maistro.portability` modules (ADR-101 §3 import-wide / export-narrow adapters)
to the production entry point the disposition ledger named: a
`maistro.cli` subcommand. The new `maistro portability` commands (`formats`,
`import-agent`, `import-skills`, `export`) are real file-conversion behavior —
no store, no lifecycle, no fake keep-alive import. The reachability baseline
shrank 178 → 174 and the `portability` disposition group was removed; the
convergence-matrix Portability row moved CONNECT → KEEP and the README
"Known non-features" list dropped `portability`.

## Tests added

`packages/maistro-core/tests/cli/test_portability.py` (+17) drives the shipped
Typer app through CliRunner: format listing, OpenAI-assistant JSON and
Claude-Code markdown agent imports, stdin source, the SKILL.md-is-not-an-agent
rejection, MCP-manifest skill import with name sanitizing, the
detected-but-empty manifest (not an error), the import → export → re-import
round trip through the written `mcp-manifest.json` + `SKILL.md`, and the
export input validation that names unknown/missing AgentCard and
SkillDefinition fields instead of silently dropping them.

`AgentImporterRegistry.detect` / `SkillImporterRegistry.detect` were added so
the command can distinguish "no format matches" from "matched, zero skills
imported" — a distinction `import_skills`' `[]` return cannot make on its own.
