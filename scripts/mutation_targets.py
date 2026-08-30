#!/usr/bin/env python3
"""Map changed source files to the tests that should kill their mutants.

Mutation testing asks a narrow question — *do this file's tests catch changes
to this file?* — so both halves must be scoped to the file. The PR job used to
scope neither: `module-path` was the whole 126k-line package and the test
command ran all 5600+ core tests per mutant, which is why it hit the 30-minute
wall and reported "cancelled" on every PR that triggered it.

Resolution order for a source file's tests:

1. the mirror path — ``src/maistro/router/scorer.py`` → ``tests/router/test_scorer.py``
2. the nearest ancestor test directory — ``tests/router/``, then ``tests/``

Emits one ``<src>\\t<test-path>`` line per resolvable file. Files whose tests
resolve only to the whole suite are reported on stderr and SKIPPED rather than
silently mutated against everything: a per-file budget that quietly widens to
the full suite is how the 30-minute timeout happened in the first place.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORE_SRC = Path("packages/maistro-core/src/maistro")
CORE_TESTS = Path("packages/maistro-core/tests")
PACKAGES = Path("packages")
#: The repository's own gate scripts. `scripts/<name>.py` -> `tests/test_<name>.py`,
#: the convention every gate here already follows.
#:
#: They were unresolvable until #419, so the code that decides whether anything
#: else may merge was the one body of Python mutation could not reach -- the
#: same blind spot #257 closed for diff coverage, one instrument later.
SCRIPTS = Path("scripts")
ROOT_TESTS = Path("tests")

EXTERNAL_TEST_ROOTS = {
    # The package's own tests/ directory is external browser E2E coverage.
    # Unit tests for its non-backend Python modules live at the repository root.
    "hive-conductor": Path("tests/hive_conductor"),
    "maistro-registry": Path("tests/tools/registry"),
}


def resolve_tests(src: str) -> Path | None:
    """Return the most specific existing test path for ``src``, or None."""
    path = Path(src)
    try:
        rel = path.relative_to(CORE_SRC)
    except ValueError:
        return None

    if not (REPO / path).is_file():
        return None

    mirror = CORE_TESTS / rel.parent / f"test_{rel.stem}.py"
    if (REPO / mirror).is_file():
        return mirror

    parent = rel.parent
    while parent != Path("."):
        candidate = CORE_TESTS / parent
        if (REPO / candidate).is_dir():
            return candidate
        parent = parent.parent
    return None


def resolve_script_tests(src: str) -> Path | None:
    """Resolve a repository gate script to its own test file.

    Mirror path only, deliberately. There is no ancestor directory to widen to
    -- `tests/` is the whole root suite, and mutating one script against all
    1,400 root tests is exactly the unbounded scope that produced the original
    30-minute timeout. A script without `tests/test_<name>.py` is skipped and
    reported, not silently mutated against everything.
    """
    path = Path(src)
    if path.suffix != ".py" or not (REPO / path).is_file():
        return None
    if path.parent != SCRIPTS:
        return None
    mirror = ROOT_TESTS / f"test_{path.stem.replace('-', '_')}.py"
    return mirror if (REPO / mirror).is_file() else None


def resolve_package_tests(src: str) -> Path | None:
    """Resolve every production package file to its closest package test scope."""
    path = Path(src)
    if not (REPO / path).is_file() or path.suffix != ".py" or "tests" in path.parts:
        return None
    try:
        path.relative_to(PACKAGES)
    except ValueError:
        return None

    package = Path(*path.parts[:2])
    test_root = _package_test_root(path, package)
    if not (REPO / test_root).is_dir():
        return None

    rel = path.relative_to(_source_root(path, package))
    mirror = test_root / rel.parent / f"test_{rel.stem}.py"
    if (REPO / mirror).is_file():
        return mirror

    return _nearest_test_scope(test_root, rel)


def _package_test_root(path: Path, package: Path) -> Path:
    backend_tests = package / "backend" / "tests"
    if "backend" in path.parts and (REPO / backend_tests).is_dir():
        return backend_tests
    return EXTERNAL_TEST_ROOTS.get(package.name, package / "tests")


def _source_root(path: Path, package: Path) -> Path:
    if "src" in path.parts:
        index = path.parts.index("src")
        if len(path.parts) > index + 1:
            return Path(*path.parts[: index + 2])
    if "backend" in path.parts:
        return package / "backend"
    if "frontend" in path.parts and "server" in path.parts:
        return package / "frontend" / "server"
    return package


def _nearest_test_scope(test_root: Path, rel: Path) -> Path:
    parent = rel.parent
    while True:
        candidate = test_root / parent
        if (REPO / candidate).is_dir():
            return candidate
        if parent == Path("."):
            return test_root
        parent = parent.parent


def production_sources() -> list[str]:
    """All executable package Python files, excluding tests and caches."""
    return sorted(
        path.relative_to(REPO).as_posix()
        for path in (REPO / PACKAGES).rglob("*.py")
        if "tests" not in path.parts and "__pycache__" not in path.parts
    )


def _script_source_for_test(path: Path) -> str | None:
    """Return the exact gate script whose canonical root test is ``path``."""
    if path.parent != ROOT_TESTS or path.suffix != ".py":
        return None

    for candidate in (REPO / SCRIPTS).glob("*.py"):
        source = candidate.relative_to(REPO).as_posix()
        if resolve_script_tests(source) == path:
            return source
    return None


def sources_for_test(test_path: str) -> list[str]:
    """Map a changed TEST path back to the source files it covers.

    This inverse mapping exists for test-only PRs whose purpose is to kill
    surviving mutants. When a PR also changes production code, ``expand``
    deliberately does not widen from its supporting tests: the blocking PR
    gate measures every changed production source and uses the mapped tests as
    the kill scope. Test-to-source inference is only necessary when there are
    no changed production sources at all.
    """
    path = Path(test_path)

    script_source = _script_source_for_test(path)
    if script_source is not None:
        return [script_source]

    try:
        rel = path.relative_to(CORE_TESTS)
    except ValueError:
        return []

    if path.suffix == ".py" and path.stem.startswith("test_"):
        mirror = CORE_SRC / rel.parent / f"{path.stem.removeprefix('test_')}.py"
        if (REPO / mirror).is_file():
            return [str(mirror)]

    src_dir = CORE_SRC / (rel.parent if path.suffix else rel)
    if not (REPO / src_dir).is_dir():
        return []
    return sorted(
        str(src_dir / p.name) for p in (REPO / src_dir).glob("*.py") if p.name != "__init__.py"
    )


def _is_test_path(path: str) -> bool:
    parts = Path(path).parts
    return "tests" in parts or any(part.startswith("test_") for part in parts[-1:])


def expand(paths: list[str]) -> list[str]:
    """Resolve changed paths to the production sources the PR gate must mutate.

    If any production source changed, mutate exactly those changed production
    sources. Supporting test edits affect the tests used to kill mutants, not
    the set of production files under review. This prevents a focused source
    change plus broad characterization tests from expanding into an unrelated
    package-wide mutation sweep.

    For a test-only PR, preserve inverse mapping so new mutant-killing tests are
    still measured against the source files they cover.
    """
    explicit_sources = [p for p in paths if p and not _is_test_path(p)]
    if explicit_sources:
        return list(dict.fromkeys(explicit_sources))

    out: list[str] = []
    for p in paths:
        for item in sources_for_test(p):
            if item not in out:
                out.append(item)
    return out


_PRIORITY = (
    "src/maistro/security/",
    "src/maistro/policy/",
    "src/maistro/router/",
    "src/maistro/graph/",
)


def priority(src: str) -> int:
    for rank, prefix in enumerate(_PRIORITY):
        if prefix in src:
            return rank
    return len(_PRIORITY)


def _parse_args(argv: list[str]) -> tuple[int, list[str]]:
    limit = 0
    args = list(argv)
    if args and args[0] == "--limit":
        limit = int(args[1])
        args = args[2:]
    return limit, args


def _requested_files(args: list[str]) -> list[str]:
    if args == ["--all"]:
        return production_sources()
    return [line.strip() for line in (args[0].splitlines() if args else sys.stdin) if line.strip()]


def _resolve_targets(files: list[str]) -> tuple[list[tuple[str, Path]], list[str]]:
    files = expand(files)
    targets: list[tuple[str, Path]] = []
    unresolved: list[str] = []
    for src in files:
        if not src:
            continue
        # Gate scripts first: they live outside `packages/`, so
        # `resolve_package_tests` returns None for every one of them (#419).
        script_tests = resolve_script_tests(src)
        if script_tests is not None:
            # Keep the two directions one contract. This makes a test-only
            # mutation-fix PR observable by the same mapping that targets the
            # script when production changes, and makes drift fail closed.
            if sources_for_test(str(script_tests)) != [src]:
                unresolved.append(src)
                continue
            tests = script_tests
        else:
            tests = resolve_package_tests(src)

        if tests is None:
            unresolved.append(src)
        else:
            targets.append((src, tests))
    return targets, unresolved


def _apply_limit(targets: list[tuple[str, Path]], limit: int) -> list[tuple[str, Path]]:
    if not limit or len(targets) <= limit:
        return targets

    dropped = targets[limit:]
    targets = targets[:limit]
    print(
        f"::warning::mutation budget limit={limit}; "
        f"{len(dropped)} changed file(s) NOT mutated in this run "
        "(full sweep runs on the develop -> main gate and nightly):",
        file=sys.stderr,
    )
    for src, _ in dropped:
        print(f"  not mutated: {src}", file=sys.stderr)
    return targets


def main(argv: list[str]) -> int:
    limit, args = _parse_args(argv)
    files = _requested_files(args)
    targets, unresolved = _resolve_targets(files)

    if unresolved:
        print("::error::mutation target(s) have no package test scope:", file=sys.stderr)
        for src in unresolved:
            print(f"  unresolvable: {src}", file=sys.stderr)
        return 1

    targets.sort(key=lambda t: (priority(t[0]), t[0]))
    targets = _apply_limit(targets, limit)

    for src, tests in targets:
        print(f"{src}\t{tests}")
    if not targets:
        print("no changed file resolved to a scoped test path", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
