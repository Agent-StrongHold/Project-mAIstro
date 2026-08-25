---
id: SPEC-062126-d421
title: "Medley import sanitization pipeline — scan, salvage-or-block, register, re-scan-on-use"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-21
substrate:
  - maistro-engine#ADR-072
  - maistro-engine#ADR-073
  - maistro-engine#ADR-083
implements:
  - maistro-engine#ADR-083
related:
  - maistro-engine#SPEC-005
  - maistro-engine#ADR-050
  - maistro-engine#ADR-069
  - maistro-engine#ADR-070
  - maistro-engine#ADR-074
  - maistro-engine#ADR-093
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/skills/test_import_pipeline.py
layer: Tools
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-062126-d421: Medley import sanitization pipeline

## Context

A user can bring a skill into the engine from many places: the Medley/ClawHub registry, an
arbitrary **URL**, a **file upload**, or **pasted text**. The supply-chain threat is live and at
scale — OpenClaw's ClawHavoc campaign put 1,184 malicious skills (~1 in 5 packages at peak) on its
registry, 341+ shipping the AMOS infostealer (see `docs/security/AGENT-FRAMEWORK-FLAWS-LEDGER.md`
entry 13). ADR-072 names malicious third-party code as the #1 adversary; ADR-083 says skills must be
signed, trust-tiered, and sandboxed; SPEC-005 specifies the *publisher VC / signing / revocation*
trust chain.

What is **not** yet specified is the **content-safety pipeline** that every import — signed or not,
registry or pasted — must pass before it can become a usable tool, and the **per-use re-scan** that
catches a skill which is benign at import but rug-pulls later. The primitives exist in
`maistro.skills` but are not composed into one fail-closed gate:

- `skills.parser.security_scan(content) -> (is_clean, issues)` — dangerous-pattern scan.
- `skills.fixer.fix_content(content) -> (fixed_content, fixes_applied, unfixable_issues)` —
  NFKD-normalize, strip hidden direction/zero-width markers, remove dangerous constructs (e.g.
  `exec()`).
- `skills.forge` — LLM-assisted normalization/improvement; forged skills start at trust tier **T3
  (sandboxed)**.
- `skills.canary` — staged rollout (canary → partial → majority → full) with auto-rollback.
- `skills.marketplace` — URL fetch that already blocks SSRF targets
  (`_BLOCKED_HOSTNAME_PREFIXES`: `metadata.`, `localhost`, …) and installs at T2 by default.

This SPEC composes them into a single import boundary and adds the two missing pieces: the
**salvage-or-block decision with a structured report**, and the **re-scan-on-use** binding.

## Goals

- One import boundary for **all** sources (registry/URL/upload/paste) with identical safety
  semantics — provenance changes the *trust tier*, never whether the content is scanned.
- **Salvage-or-block, fail-closed:** attempt automated sanitization; if unsalvageable, refuse and
  emit a structured report rather than installing a "mostly fixed" artifact.
- Register a salvaged import as **tools + prompts** (`SkillDefinition`) at a **sandboxed tier (T3)**,
  rolled out via canary.
- **Re-scan the payload on every use**, so a post-import mutation / rug-pull is caught at execution.
- Make the *block* the guarantee and the *salvage* a convenience — the design must not depend on the
  LLM "improve" step to make malicious content safe.

## Non-goals

- Publisher signing, Verifiable-Credential trust chain, and revocation — **SPEC-005** (this pipeline
  runs regardless of, and in addition to, signing).
- The sandbox substrate / microVM selection — **ADR-093 / SPEC-190**.
- The LLM-judge model and prompt used in the escalation tier of scanning — a tuning follow-up
  (ADR-073 keeps detector mechanism in code).
- Trust-tier *promotion* policy beyond "imports start at T3" — separate skills-trust work (ADR-083).

## Decision

### Import boundary and flow

Every import is a `SkillImportRequest` that runs the pipeline below; the gate returns a
`SkillImportVerdict` and never installs on a non-`registered` outcome.

```python
class ImportSource(StrEnum):
    REGISTRY = "registry"     # Medley/ClawHub
    URL = "url"
    UPLOAD = "upload"
    PASTE = "paste"

@dataclass(frozen=True)
class SkillImportRequest:
    source: ImportSource
    raw: str | None = None        # paste/upload body
    url: str | None = None        # URL import
    importer: Principal           # who is importing (authority bound, ADR-068)

@dataclass(frozen=True)
class SkillImportReport:
    blocked: bool
    scan_issues: tuple[str, ...]          # security_scan issues
    fixes_applied: tuple[str, ...]        # what salvage changed
    unfixable_issues: tuple[str, ...]     # why it was refused (empty if registered)
    content_hash: str
    source: ImportSource
    source_ref: str | None                # URL/registry id for abuse escalation

@dataclass(frozen=True)
class SkillImportVerdict:
    outcome: Literal["registered", "blocked"]
    skill: SkillDefinition | None         # set iff registered
    trust_tier: Literal["T3"] | None      # imports always start sandboxed
    report: SkillImportReport
```

**Pipeline (fail-closed at every stage):**

1. **Fetch + bound.** For `URL`, fetch via `skills.marketplace` (SSRF host-denylist enforced);
   for `upload`/`paste`, take the raw body. Enforce `MAX_SKILL_BODY_LENGTH` (prompt-stuffing
   guard) before any parsing.
2. **Scan for malicious intent.** Run `parser.security_scan()` **and** a Warden pass
   (`boundary="skill_import"`). Collect issues; do not short-circuit yet (salvage may clear them).
3. **Sanitize / salvage.** Run `fixer.fix_content()`. If `unfixable_issues` is non-empty → **BLOCK**:
   return `outcome="blocked"` with a `SkillImportReport` (this is the "it was only a scam/attack"
   path). No partial install.
4. **Re-scan the salvaged content.** Run `security_scan()` again on `fixed_content`; any remaining
   issue is treated as `unfixable` → **BLOCK** (salvage must produce a clean artifact, not a quieter
   one).
5. **Improve + parse.** Normalize/improve via `skills.forge`, then `parser.parse_skill_file()` into a
   `SkillDefinition` (tools + system prompts). Forge output is itself re-scanned (step 4 invariant
   applies to anything forge emits — the LLM step is never trusted to be safe).
6. **Register sandboxed + canary.** Persist at **trust tier T3 (sandboxed)** regardless of source;
   roll out via `skills.canary` with auto-rollback. Registry/`signed` provenance may raise the tier
   *only* through the SPEC-005 signing path — never this pipeline.
7. **Bind re-scan-on-use.** Record `content_hash`; the per-call Warden/Sentinel boundary
   (ADR-073) re-scans the actual payload at execution and re-checks the hash, so a post-import
   mutation/rug-pull (ledger entry 6) is caught at use, and a tier-T3 skill always executes in the
   ADR-093 sandbox.

### Block + report contract

On `outcome="blocked"` the gate returns a `SkillImportReport` with the concrete `unfixable_issues`
and the `source_ref`, surfaced to the importer so they can escalate to the source's abuse/report
channel if one exists. The report is also emitted as a `security.violation` event (ADR-073) and is
admin-readable; an agent principal cannot suppress it.

### Authority + audit

The importing `Principal` is authority-bound (ADR-068): importing is itself a gated action, and a
registered skill inherits no authority beyond its importer. Every import verdict (registered or
blocked) is a signed decision record (ADR-073).

## Acceptance criteria

- [x] A single `import_skill(request) -> SkillImportVerdict` entrypoint handles all four
      `ImportSource` values with identical scan/salvage semantics.
- [x] `unfixable_issues` non-empty ⇒ `outcome="blocked"`, `skill is None`, and a populated
      `SkillImportReport` — **no partial/"mostly fixed" install path exists** (property test).
- [x] A salvaged import is re-scanned post-`fix_content`; any residual `security_scan` issue blocks
      (salvage produces a clean artifact or nothing). *Deviation:* residual **CRITICAL** findings
      block; WARNING-level findings (e.g. `external_url`) are recorded in the report but do not
      block, matching existing marketplace semantics — otherwise any skill mentioning a URL would
      be uninstallable.
- [x] URL imports reject SSRF targets at fetch (`metadata.`, `localhost`, link-local) before any
      parsing — regression test over `marketplace._BLOCKED_HOSTNAME_PREFIXES`.
- [x] Registered imports persist at trust tier **T3**; no source value can raise the tier through
      this pipeline (only the SPEC-005 signing path can).
- [x] The per-use boundary re-scans payload and verifies `content_hash`; a mutated payload is denied
      at execution, not just at import (rug-pull test). Implemented as
      `verify_skill_payload(skill_id, payload)` over a `PolicyAttachmentStore` (Sentinel policy
      attachment per the decided open question).
- [ ] Every verdict emits a signed decision record; a block emits `security.violation`; the report
      is admin-readable and not agent-suppressible. *Partial:* blocks emit `security.violation`
      via an injected emit callable and the report is the return value; **signing** of decision
      records and the admin delivery surface (`GET /admin/import-reports/{id}`) are follow-ups.
- [x] The LLM `forge` "improve" output is subject to the same step-4 re-scan as any other content
      (the improve step is never the trusted control).

### Implementation notes / deviations

- Module: `packages/maistro-core/src/maistro/skills/import_pipeline.py`; tests:
  `packages/maistro-core/tests/skills/test_import_pipeline.py`.
- The Warden pass (step 2) is an injected `warden_scan(content, boundary)` callable (e.g.
  `Warden.scan`), not a hard dependency; flags are folded into `report.scan_issues` prefixed
  `warden:`. Container wiring is a follow-up (container.py untouched per scope).
- The forge "improve" step is an injected `improve(content) -> content` callable, since
  `SkillForge` exposes only `forge(request)`/`mutate(...)` and no content-improvement API; forge
  output is always re-scanned (CRITICAL residuals block, prefixed `forge_output:`).
- The pipeline imports `marketplace._block_ssrf` (private); exposing it publicly from
  `skills.marketplace` would be a tidy follow-up (marketplace.py untouched per scope).
- Canary rollout (step 6) is optional via an injected `CanaryManager`; registration also does not
  write skill files to disk (registry-only) — persistence is the caller's concern.

## Testing

- Unit: `packages/maistro-core/tests/skills/test_import_pipeline.py` (new) — per-source flow,
  salvage-vs-block branching on `fixer` output, post-salvage re-scan, T3 tier assignment, report
  shape, SSRF host-block on URL import.
- Property (Hypothesis): "no partial install" — for any input where `fix_content` reports
  `unfixable_issues`, the verdict is always `blocked` with `skill is None`.
- Integration: a benign-then-mutated skill is registered, then denied at use when its payload hash
  changes (rug-pull regression), exercising the per-use re-scan binding.
- Existing primitive coverage to reuse: `tests/skills/test_fixer.py` (already asserts `exec()` is
  stripped), parser `security_scan` tests, marketplace SSRF-block tests.

## Open questions

- **Hash/binding storage** (DECIDED): store on Sentinel policy attachment. Provides audit trail,
  per-skill policies, fits ADR-073 security model.
- **Salvage vs. improve order** (DECIDED): salvage first, improve optional and always re-scanned.
  Keeps trusted path minimal; forge output is re-scanned same as salvage output.
- **Report delivery surface** (DEFERRED to Phase 2): start with API endpoint (`GET /admin/import-reports/{id}`),
  CLI output, and dashboard follow-up. Auto-format abuse endpoint discovery deferred.

## References

- `docs/security/AGENT-FRAMEWORK-FLAWS-LEDGER.md` — entries 6 (rug-pull) and 13 (supply chain).
- `packages/maistro-core/src/maistro/skills/parser.py` (`security_scan`),
  `skills/fixer.py` (`fix_content`), `skills/forge.py`, `skills/canary.py`, `skills/marketplace.py`.
- [ADR-083: Skills and MCP Gateway Trust](../adr/ADR-083-skills-mcp-trust.md);
  [ADR-073: Warden + Sentinel](../adr/ADR-073-warden-sentinel.md);
  [ADR-072: Threat Model](../adr/ADR-072-threat-model.md);
  [ADR-050: Tool reversibility taxonomy](../adr/ADR-050-tool-reversibility-taxonomy.md);
  [ADR-093: Sandbox isolation model](../adr/ADR-093-sandbox-isolation-model.md).
- [SPEC-005: Medley full](SPEC-005-clawhub-full.md) — publisher VC / signing / revocation.
