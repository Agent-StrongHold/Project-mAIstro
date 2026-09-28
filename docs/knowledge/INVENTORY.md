# Repository Guidance Inventory

Working inventory for the pre-1.0 knowledge-architecture normalization. This file records source ownership and conflicts while the corpus is reconciled. It is not an always-loaded rule source.

## Authority model

| Source | Current role | Target role |
|---|---|---|
| `AGENTS.md` | Compact static agent briefing | L0 bootstrap pointer into progressive disclosure |
| `.cursor/rules/core/always.mdc` | Tiny always-loaded Cursor rules | L0 bootstrap pointer, no domain detail |
| `CLAUDE.md` | Large architecture + workflow briefing | Migration source; route stable content to canonical domain indexes/docs |
| `CONTRIBUTING.md` | Declared rules of record for contribution mechanics | Canonical repository/contribution standards, referenced by routing layer |
| `docs/WAYS-OF-WORKING.md` | Practical field guide; explicitly subordinate to CONTRIBUTING | Practical derived guide only; must not contradict canonical standards |
| `docs/adr/*` | Architectural decisions | Canonical ADR documents, referenced in place through categorized indexes |
| `docs/specs/*` | Requirements/acceptance criteria | Canonical specs, referenced in place through categorized indexes |
| `docs/ci/*`, `docs/quality-gates.md` | CI/quality operational material | Evidence for later CI topology audit; canonical CI docs after deduplication |

## Confirmed conflicts / stale guidance

### ADR/spec numbering

- `docs/WAYS-OF-WORKING.md` §5 instructs agents to allocate the next free sequential `ADR-NNN` / `SPEC-NNN` number.
- `CONTRIBUTING.md` says sequential IDs are frozen and new records use `ADR-MMDDYY-xxxx` / `SPEC-MMDDYY-xxxx` per `ADR-062026-9b30`.
- Resolution authority today: `WAYS-OF-WORKING.md` itself declares `CONTRIBUTING.md` authoritative when they disagree, therefore the sequential-number instruction is stale and must be removed or rewritten.

### Pre-1.0 compatibility pressure

- `CLAUDE.md` documents backwards-compatibility aliases such as `MaistroConfig`, `MaistroError`, and `StrongholdError`.
- New pre-1.0 operating policy assigns no preservation value to backwards compatibility unless the compatibility surface independently belongs in the target 1.0 architecture.
- These aliases therefore require target-architecture review; their existence is not by itself a reason to preserve them.

## Inventory rules

For each source, determine:
1. Is the guidance currently true?
2. What canonical source owns the rule/fact?
3. What applicability trigger should cause an agent to retrieve it?
4. Is the source canonical, derived, historical, or stale?
5. Does it conflict with the intended 1.0 architecture or pre-1.0 operating policy?

Do not duplicate canonical prose into indexes. Indexes carry only routing metadata and concise current-state summaries.