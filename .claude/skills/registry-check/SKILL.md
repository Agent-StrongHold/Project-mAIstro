---
name: registry-check
description: Validate ADR/spec docs with the maistro-registry CLI — front-matter validation, dependency-DAG cycle check, and local link check. Mirrors the registry.yml CI gate. Use after editing docs/adr/ or docs/specs/, before pushing. Optional path argument scopes the walk.
---

The user wants to verify ADR/spec documentation passes the registry gate. The argument is $ARGUMENTS (an optional path to walk; default `.`).

Run the full lint (walk + front-matter validation + DAG cycle check + local link check):

```bash
PYTHONPATH=packages/maistro-registry/src python3 -m maistro_registry.cli lint ${ARGUMENTS:-.}
```

Notes:
- This is exactly what `.github/workflows/registry.yml` runs, so a clean local run means the registry CI job will pass.
- `lint` = `walk` + `validate` + DAG cycle check + link check. Use `validate <file>` to check a single file, or `walk <root>` for validation only without the DAG/link passes.
- Add `--strict` to treat warnings as errors (post-rollout mode); add `--quiet` to print only failures.
- To regenerate the registry index after docs change: `... cli generate .` (writes registry.json + registry.md).

After the run:
1. Report pass/fail and the count of docs walked.
2. For each failure, name the file and the specific problem (missing/invalid front-matter field, broken cross-reference, or a cycle in the substrate/blocks DAG) and propose the fix.
3. If a cross-reference points at a non-existent ADR/SPEC, surface it — it usually means a typo'd id or a doc that hasn't been created yet.
