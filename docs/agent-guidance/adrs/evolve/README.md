# Evolve ADRs

Progressive-disclosure index for ADRs governing experimental self-improvement, evaluation-driven optimization, genome/artifact evolution, and promotion of learned variants.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-088: maistro-evolve — experimental genome optimiser

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Keep the explicit experimental/no-stability contract, but revise the intended artifact vocabulary to match current architecture before other ADRs depend on it: identify the actual evolvable units (for example Persona/NodeTemplate/GraphTemplate prompts/config, harness/provider parameters, or other canonical versioned artifacts), current fitness/evidence sources, and the governed promotion path. Remove RecipeRegistry/release-channel assumptions that depend on ADR-006/075 successors.  
**Current state:** This ADR intentionally records direction rather than a stable API and explicitly promises no backward compatibility, which is appropriate before 1.0. Its original "genome = recipe/prompt variant promoted into RecipeRegistry" framing has aged as the canonical artifact model evolved, so the direction record should be refreshed without freezing the experimental package.  
**ADR:** [ADR-088: maistro-evolve — experimental genome optimiser](../../../adr/ADR-088-maistro-evolve-experimental.md)

## ADR-070126-6386: RSI code improvement as an evolve genome tournament

**Status:** Proposed  
**Last updated:** 2026-09-29  
**Next steps:** Rewrite the tournament execution path onto the current autonomous engineering substrate: isolated candidate workspaces, canonical Runs/NodeRuns/Attempts, current CI/eval/mutation evidence, and governed merge/promotion. Preserve competition across model/config/prompt strategies and verifier-gated selection, but do not promote through deprecated RecipeRegistry/Builders lifecycles or treat a container-only sandbox as sufficient where ADR-093 requires a stronger autonomous floor.  
**Current state:** The core research idea remains strong: make the improver itself an evolvable genome and select fixes using measured code-quality fitness rather than a single attempt. The proposal predates the current canonical execution, sandbox, and GitHub development architecture, so it should remain Proposed until those boundaries are rewritten.  
**ADR:** [ADR-070126-6386: RSI evolve genome tournament](../../../adr/ADR-070126-6386-rsi-evolve-genome-tournament.md)
