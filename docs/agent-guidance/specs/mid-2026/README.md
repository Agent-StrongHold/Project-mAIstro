# Mid-2026 Memory, Design, Evolve, and Quality Specs

## SPEC-062126-5d56: Memory dynamics follow-up

**Status:** Accepted  
**Next steps:** Verify the pluggable decay and contradiction-resolution implementation is actually reached by durable memory dynamics, not only unit tests. Reconcile any RLPHD-derived threshold coupling with current authorization terminology.  
**Current state:** Focused follow-up to implemented SPEC-240/241 mechanics; likely close to completion but production scheduling/reachability remains the ADR-080 question.  
**SPEC:** [SPEC-062126-5d56](../../../specs/SPEC-062126-5d56-memory-dynamics-decay-consolidation.md)

## SPEC-062126-6a31: Memory exposure enforcement

**Status:** Accepted  
**Next steps:** Replace Recipe/overlay declaration with current Persona/NodeTemplate/agent configuration, then wire mandatory exposure mode into concrete durable stores/read paths with denial events. No implicit compatibility default.  
**Current state:** Pure enforcement exists; store/agent integration remains the missing contract.  
**SPEC:** [SPEC-062126-6a31](../../../specs/SPEC-062126-6a31-memory-exposure-mode-enforcement.md)

## SPEC-062126-757a: Canvas tool action contracts

**Status:** Proposed  
**Next steps:** Reassess whether the legacy `execute_canvas` tool survives the direct pre-1.0 AssetInstance/canvas_asset cutover. If not, move useful upload/action correctness tests into the canonical Canvas capability and delete the old dispatcher instead of refactoring it.  
**Current state:** This is the canonical renamed copy; SPEC-070126-a3f1 is superseded. Its target may itself be legacy.  
**SPEC:** [SPEC-062126-757a](../../../specs/SPEC-062126-757a-canvas-tool-action-contracts.md)

## SPEC-062126-7853: Skill fixer rule pipeline

**Status:** Proposed  
**Next steps:** First prove the fixer remains a reachable supported capability. If yes, make repair rules explicit/tested; if no, delete the dead API instead of preserving it.  
**Current state:** Canonical renamed copy; SPEC-070126-c5d7 is superseded.  
**SPEC:** [SPEC-062126-7853](../../../specs/SPEC-062126-7853-skill-fixer-rule-pipeline.md)

## SPEC-062126-971d: Shared widget/chat tool-call cache

**Status:** In Progress  
**Next steps:** Converge shared provider/cache primitives onto the canonical Capability Binding/Invocation and credential path as Hive becomes a client. Preserve request coalescing/TTL/defensive-copy behavior only where the upstream provider benefits from caching.  
**Current state:** Real partial implementation exists for Airtable, but the ownership boundary predates the one governed tool surface. SPEC-070126-b2e4 is superseded.  
**SPEC:** [SPEC-062126-971d](../../../specs/SPEC-062126-971d-shared-tool-call-cache.md)

## SPEC-062126-a05f: SuperPlanner validation gate

**Status:** Accepted  
**Next steps:** Do not preserve MasterOrchestrator as a separate DAG executor. Port useful pre-execution validation findings into canonical Graph/Run planning/admission and retire the independent Builders planner lifecycle.  
**Current state:** Tests may prove the validator, but its explicit claim that the two DAG executors should not merge conflicts with current execution convergence.  
**SPEC:** [SPEC-062126-a05f](../../../specs/SPEC-062126-a05f-superplanner-master-orchestrator-validation-gate.md)

## SPEC-062126-d421: Medley import sanitization

**Status:** Proposed  
**Next steps:** Keep scan/salvage/block provenance requirements, but express imported skills as explicitly installed Capability Providers with current sandbox/outbound/Warden/Sentinel policy. Do not depend on Proposed DID/VC/CodeRegistry architecture as shipped authority.  
**Current state:** The spec already corrected its lifecycle for exactly this authority problem and has useful import-pipeline tests.  
**SPEC:** [SPEC-062126-d421](../../../specs/SPEC-062126-d421-medley-import-sanitization-pipeline.md)

## SPEC-062226-fb23: ConfigStore

**Status:** Accepted  
**Next steps:** Implement/verify the DB store, cache invalidation, canonical-principal authorization, API/CLI, explicit export/restore, and actual migration of selected hot tunables. Avoid turning every numeric constant into runtime config by default.  
**Current state:** This remains the concrete missing half of ADR-078; the document itself says no ConfigStore existed when specified.  
**SPEC:** [SPEC-062226-fb23](../../../specs/SPEC-062226-fb23-config-store-db-cli-api.md)

## SPEC-062326-7dcb: Artifact hierarchy and output scanning

**Status:** Accepted  
**Next steps:** Remeasure the listed tests and ensure generated executable/code artifacts are not merely scanned but executed only through the current sandbox/capability boundary. Promote if the narrow ArtifactNode/scanning contract is fully evidenced.  
**Current state:** Documents shipped ArtifactNode/output-scan behavior and is likely near completion.  
**SPEC:** [SPEC-062326-7dcb](../../../specs/SPEC-062326-7dcb-artifact-node-hierarchy-and-output-scanning.md)

## SPEC-062326-e9c6: React/TSX design output

**Status:** Accepted  
**Next steps:** Re-evidence the 12 AC modules after M0 rollback; keep code generation separate from safe execution/preview. Promote only on strict evidence.  
**Current state:** Implementation history exists, but M0 correctly rolled it back for insufficient completion evidence.  
**SPEC:** [SPEC-062326-e9c6](../../../specs/SPEC-062326-e9c6-design-skills-react-tsx-output-format.md)

## SPEC-062826-1924: Test hardening

**Status:** Accepted  
**Next steps:** Keep adversarial/state×IO/property testing as living quality policy and update its target list as legacy subsystems retire. Do not count tests of dead execution paths as production assurance.  
**Current state:** Large test body exists; M0 rollback means its overall completion claim needs current reachability-aware evidence.  
**SPEC:** [SPEC-062826-1924](../../../specs/SPEC-062826-1924-test-hardening-adversarial-matrix-exploratory.md)

## SPEC-062826-8982: Exploratory testing program

**Status:** Accepted  
**Next steps:** Keep the session-log → issue/regression-test escalation process lightweight and ensure findings land in current issue tracking rather than stale BACKLOG-only workflow.  
**Current state:** Ongoing process policy rather than a finite runtime feature.  
**SPEC:** [SPEC-062826-8982](../../../specs/SPEC-062826-8982-exploratory-testing-program.md)

## SPEC-062926-8ec5: Evolve mutation bounds

**Status:** Proposed  
**Next steps:** Integrate bounded edits and strict held-out improvement into the current Evolve genome/candidate pipeline, using measured variance and canonical candidate validation. Prevent configuration from weakening a mathematically strict gate below its evidence floor.  
**Current state:** Useful optimization discipline; not yet a current canonical implementation contract.  
**SPEC:** [SPEC-062926-8ec5](../../../specs/SPEC-062926-8ec5-skillopt-inspired-mutation-bounds.md)

## SPEC-070126-9d37: RSI tournament contracts

**Status:** Proposed  
**Next steps:** Rewrite execution onto current isolated candidate workspaces, canonical Runs, current model/provider routing, and CI/mutation/eval evidence. Preserve scout/compete/select semantics without Builders/legacy LiteLLM ownership.  
**Current state:** Substantial tests exist, but the governing ADR remains Proposed and the execution substrate has changed.  
**SPEC:** [SPEC-070126-9d37](../../../specs/SPEC-070126-9d37-rsi-evolve-tournament-contracts.md)

## Superseded duplicate specs

- **SPEC-070126-a3f1** → SPEC-062126-757a.  
- **SPEC-070126-b2e4** → SPEC-062126-971d.  
- **SPEC-070126-c5d7** → SPEC-062126-7853.  

These are stale copies accidentally reintroduced after date-based renaming and should remain historical only.
