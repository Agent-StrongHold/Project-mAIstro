---
name: code-health
description: Deep "better than a linter" quality scan that the regular CI ruff/mypy pass does not catch — cyclomatic complexity + maintainability (radon/xenon), dead code (vulture), god functions/files (lizard + AST), copy-paste (pylint R0801), security (bandit), and optionally architecture boundaries (import-linter), dep hygiene (deptry), docstring coverage (interrogate). Argument-driven: pass a path/package, or omit to scan files changed vs the base branch. Use before opening a PR, or when reviewing a chunk of work.
---

The user wants a deep quality scan. The argument is $ARGUMENTS (an optional path or package dir to scan). This runs the analyzers that are intentionally NOT in the per-commit CI loop — the ones too slow or too noisy to gate every push, but valuable on demand.

## 1. Determine the target set

- If $ARGUMENTS is given, scan that path (file, dir, or package, e.g. `packages/maistro-core/src/maistro/capabilities`).
- If $ARGUMENTS is empty, scan only Python files changed vs the base branch (topic branches base off `develop`):

  ```bash
  base=$(git merge-base HEAD origin/develop 2>/dev/null || git merge-base HEAD origin/main 2>/dev/null || echo HEAD~1)
  git diff --name-only "$base"...HEAD -- '*.py'; git diff --name-only -- '*.py'  # committed + uncommitted
  ```

  De-duplicate the list. If it is empty, tell the user there is nothing to scan and stop. Set `TARGETS` to the space-separated list (or the single path from $ARGUMENTS).

Each tool below is optional — if the binary/module is missing, note "skipped (not installed: pip install X)" and continue. Do not fail the whole scan because one tool is absent.

## 2. Run the analyzers

**Cyclomatic complexity + maintainability — radon / xenon** (installed):
```bash
radon cc -s -n C $TARGETS          # functions graded C or worse (CC > 10), with scores
radon mi -s $TARGETS               # maintainability index per file (flag anything below B)
xenon --max-absolute C --max-modules B --max-average A $TARGETS || true   # gate view; B-cap mirrors a reasonable bar
```

**Dead code — vulture** (installed):
```bash
vulture $TARGETS --min-confidence 70
```
Treat high-confidence (≥90) hits as real; flag 70–89 as "review". Watch for false positives on dynamically-referenced names (FastAPI routes, pydantic validators, event handlers) — call those out rather than recommending deletion.

**God functions — lizard** (in requirements-dev-tools.txt; `pip install lizard` if missing):
```bash
lizard -w -T nloc=60 -T cyclomatic_complexity=10 -T parameter_count=5 $TARGETS
```
`-w` prints only the functions that breach a threshold (long, complex, or too many params). These are the god-function candidates.

**Copy-paste / duplication — pylint R0801** (in requirements-dev-tools.txt):
```bash
pylint --disable=all --enable=duplicate-code --ignore-patterns='.*_test\.py,test_.*\.py' $TARGETS 2>/dev/null || true
```

**Security — bandit** (installed):
```bash
bandit -ll -r $TARGETS 2>/dev/null
```
`-ll` = medium+ severity & confidence only (matches the user's global step-11 bar and security.yml).

**God files + god functions — hand-rolled AST pass** (no deps; authoritative for file size, which no tool above reports):
```bash
python3 - "$@" <<'PY'
import ast, sys, pathlib
FILE_LINES, FUNC_LINES, PARAMS = 500, 60, 5
paths = []
for a in sys.argv[1:]:
    p = pathlib.Path(a)
    paths += list(p.rglob("*.py")) if p.is_dir() else ([p] if p.suffix == ".py" else [])
flagged = False
for f in sorted(set(paths)):
    try:
        src = f.read_text(); tree = ast.parse(src)
    except (OSError, SyntaxError):
        continue
    nlines = src.count("\n") + 1
    if nlines > FILE_LINES:
        print(f"GOD FILE   {f}: {nlines} lines (> {FILE_LINES})"); flagged = True
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            span = (node.end_lineno or node.lineno) - node.lineno + 1
            nargs = len(node.args.posonlyargs) + len(node.args.args) + len(node.args.kwonlyargs)
            if span > FUNC_LINES:
                print(f"LONG FUNC  {f}:{node.lineno} {node.name}() = {span} lines (> {FUNC_LINES})"); flagged = True
            if nargs > PARAMS:
                print(f"MANY PARMS {f}:{node.lineno} {node.name}() = {nargs} params (> {PARAMS})"); flagged = True
if not flagged:
    print("no god files/functions over thresholds")
PY
```
(Pass the same `$TARGETS` as positional args. Thresholds: 500-line file, 60-line function, 5 params — tune per the user's preference.)

**Optional, run only if installed** — these reward this codebase's architecture but aren't required:
```bash
command -v lint-imports >/dev/null && lint-imports || echo "skipped import-linter (pip install import-linter; needs an [importlinter] contract in setup.cfg/pyproject — enforces 'core must not import stronghold', 'logic depends on protocols not impls')"
command -v deptry     >/dev/null && deptry .   || echo "skipped deptry (pip install deptry — unused/missing/transitive deps)"
command -v interrogate>/dev/null && interrogate -v $TARGETS || echo "skipped interrogate (pip install interrogate — docstring coverage)"
```

## 3. Synthesize a report

Do NOT just dump tool output. Produce a ranked summary:

1. **Headline counts** per category (complexity hotspots, dead-code hits, god files/functions, duplication blocks, security findings).
2. **Top offenders** — the worst few items with `file:line`, the metric, and a one-line "why it matters / suggested fix".
3. **Likely false positives** flagged separately (dynamic dispatch for vulture; test fixtures; intentional complexity).
4. **Skipped tools** and the one-line install command for each.
5. A short verdict: is this change PR-ready on the health axis, or are there must-fix items first?

Map findings to the user's 12-step workflow: complexity/god-objects → step 10 (code smells), bandit → step 11 (security). Keep it actionable — every finding should have a next step or an explicit "acceptable, here's why".
