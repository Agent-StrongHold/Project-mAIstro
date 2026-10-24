---
inventory-delta:
  packages/maistro-core/tests: +23
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
shrank 153 → 149 (the four `maistro.portability*` rows left the baseline) and
the `portability` disposition group was removed; the convergence-matrix
Portability row moved CONNECT → KEEP and the README "Known non-features" list
dropped `portability`.

## Tests added

`packages/maistro-core/tests/cli/test_portability.py` (+23) drives the shipped
Typer app through CliRunner: format listing, OpenAI-assistant JSON and
Claude-Code markdown agent imports, stdin source, the SKILL.md-is-not-an-agent
rejection, MCP-manifest skill import with name sanitizing, the
detected-but-empty manifest (not an error), the import → export → re-import
round trip through the written `mcp-manifest.json` + `SKILL.md`, and the
export input validation that names unknown/missing AgentCard and
SkillDefinition fields instead of silently dropping them — plus the error
surfaces for an unwritable output path, non-object export input, invalid or
non-object `--skills` payloads, a skill missing `name`, and an unwritable
`--out-dir`.

`AgentImporterRegistry.detect` / `SkillImporterRegistry.detect` were added so
the command can distinguish "no format matches" from "matched, zero skills
imported" — a distinction `import_skills`' `[]` return cannot make on its own.

Repair round (CI citation-status + convergence + diff-coverage gates):
`AgentImporterRegistry.detect` was removed again — the `import-agent` command
distinguishes "no format matches" through `import_agent`'s `None` return, so
the agent-side `detect` had no caller (a public method kept alive only by its
own definition is exactly the keep-alive shape #34 burns down). Only
`SkillImporterRegistry.detect` remains, and only because `import-skills` needs
it for the detected-but-empty-manifest case. Six more command tests cover the
shipped error paths the first tranche left unmeasured: unwritable `--output`
path, export input that is JSON but not an object, invalid `--skills` JSON,
a skills-array entry that is not an object, a skill missing its required
`name`, and an unwritable `--out-dir`.
