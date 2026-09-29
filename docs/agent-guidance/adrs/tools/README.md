# Tools ADRs

Progressive-disclosure index for ADRs governing tool-layer contracts, structured transformations, tool execution surfaces, and related utility boundaries.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-008: StructuredOutputParser

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Strengthen the validation-error retry-context test to assert the Pydantic error type as well as the field name, run the focused StructuredOutputParser suite, then transition ADR-008 to `Implemented` if the full acceptance set passes. Audit SPEC-210 separately because its checked criteria and prose say the design is implemented while its lifecycle status remains `Accepted`.  
**Current state:** StructuredOutputParser is implemented and exercises schema injection, pure/fenced/embedded JSON extraction, shape validation, and retry-context formatting. SPEC-210 records all eight criteria as satisfied, but the current validation-error test only asserts the field name even though the accepted ADR requires both field name and error type, so promotion is held until that evidence gap is closed.  
**ADR:** [ADR-008: StructuredOutputParser](../../../adr/ADR-008-structured-output-parser.md)
