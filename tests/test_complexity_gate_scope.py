"""The complexity gates watch every shipped package, and agree with each other (#1682).

Until #1682 the radon ratchet scanned only ``packages/maistro-core/src`` while
xenon counted the same single tree and interrogate floored only core paths: the
other eight shipped packages carried every D and E block in production code and
nothing was looking. The widening landed with the scan set, the xenon ceiling
and the eight new docstring floors — but the ceiling is a hand-maintained count
next to a per-identity ledger, and after the landing it drifted (145 against a
ledger that had followed its improvements down to 143) while a comment still
claimed the two numbers were the same.

These tests pin the widened scope structurally, so the failure modes #1682
closed stay closed:

- a tenth shipped package added without widening the gates fails here instead
  of shipping unmeasured;
- the xenon block ceiling cannot drift away from the radon ledger it mirrors —
  an improvement must lower both in the same PR, exactly like the ledger's own
  banking rule;
- the vendored ``third_party`` trees stay excluded from both scanners;
- xenon keeps enforcing all three of its axes (block count, module rank,
  project average), not just the one the old step counted.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "quality.yml"
RADON_SCRIPT = ROOT / "scripts" / "check-radon-baseline.py"
RADON_LEDGER = ROOT / "quality" / "radon-baseline.json"


#: Packages under packages/ that carry a src/ tree but are tooling, not shipped
#: product source, so the complexity/docstring gates do not watch them. The
#: harness is the stdlib-only conformance runner a third-party CI installs; it
#: loads extension code and is never imported by the product. Listed by name so
#: an exclusion is a reviewed decision, not a side effect of a filename filter.
_DEV_ONLY_PACKAGES = frozenset({"maistro-ext-harness"})


def _shipped_src_roots() -> set[str]:
    """Every shipped package's ``src/`` root, discovered from the tree."""
    return {
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "packages").glob("*/src")
        if p.parent.name not in _DEV_ONLY_PACKAGES
    }


def _radon_module() -> Any:
    spec = importlib.util.spec_from_file_location("_coverage_radon_scan_scope", RADON_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _radon_scan() -> tuple[set[str], list[str]]:
    """DEFAULT_SCAN as (scan roots, raw argument list)."""
    args = list(_radon_module().DEFAULT_SCAN)
    roots = {a for a in args if a.startswith("packages/")}
    return roots, args


def _quality_steps() -> list[dict[str, Any]]:
    doc = yaml.safe_load(WORKFLOW.read_text())
    return [
        step
        for job in doc["jobs"].values()
        for step in job.get("steps", [])
        if isinstance(step, dict) and step.get("name")
    ]


def _xenon_step() -> dict[str, Any]:
    hits = [s for s in _quality_steps() if str(s["name"]).startswith("xenon ")]
    assert len(hits) == 1, f"expected exactly one xenon step, found {len(hits)}"
    return hits[0]


def _interrogate_run_lines() -> list[str]:
    hits = [s for s in _quality_steps() if "interrogate" in str(s["name"])]
    assert len(hits) == 1, f"expected exactly one interrogate step, found {len(hits)}"
    run = hits[0]["run"]
    assert isinstance(run, str)
    # Join backslash continuations BEFORE filtering: the Evolve floor spans two
    # lines and its real target (`packages/maistro-evolve/src`) sits on the
    # continuation line, which a per-line filter would drop.
    lines: list[str] = []
    pending = ""
    for raw in run.splitlines():
        line = (pending + " " + raw).strip() if pending else raw.strip()
        if line.endswith("\\"):
            pending = line[:-1].rstrip()
            continue
        pending = ""
        if "interrogate " in line:
            lines.append(line)
    assert not pending, "the interrogate step ends in a dangling line continuation"
    return lines


def _interrogate_targets() -> list[str]:
    """Positional scan targets of each interrogate invocation.

    Option operands (``-f`` floors, ``-e`` excludes) are consumed as values, so
    an explicitly excluded directory is never mistaken for covered ground.
    """
    option_flags = {"-e", "--exclude", "-f", "--fail-under"}
    targets: list[str] = []
    for line in _interrogate_run_lines():
        skip_next = False
        for token in shlex.split(line):
            if skip_next:
                skip_next = False
                continue
            if token in option_flags:
                skip_next = True
            elif token.startswith("packages/"):
                targets.append(token)
    return targets


def _xenon_run() -> str:
    run = _xenon_step()["run"]
    assert isinstance(run, str)
    return run


# --- the scan scope ---------------------------------------------------------


def test_radon_ratchet_scans_every_shipped_package_and_excludes_vendored_code() -> None:
    roots, args = _radon_scan()
    assert roots == _shipped_src_roots(), (
        "check-radon-baseline.py DEFAULT_SCAN must cover every shipped src/ root; "
        "a package missing here ships unmeasured by the complexity ratchet"
    )
    # Vendored third-party source is kept byte-faithful on purpose and is not
    # this repository's complexity to ratchet (the same exclusion the xenon
    # step uses below).
    assert "third_party" in args and args[args.index("third_party") - 1] == "-i"


def test_xenon_scans_the_same_roots_as_the_radon_ratchet() -> None:
    run = _xenon_run()
    xenon_roots = set(re.findall(r"packages/[\w-]+/src\b", run))
    radon_roots, _ = _radon_scan()
    assert xenon_roots == radon_roots, (
        "xenon and the radon ratchet must measure the same trees, or one of them "
        "stopped looking (#1682)"
    )
    assert "-i third_party" in run, "xenon must exclude vendored third_party too"


# --- the ceiling ------------------------------------------------------------


def test_xenon_block_ceiling_equals_the_radon_ledger_length() -> None:
    env = _xenon_step().get("env", {})
    assert "XENON_BASELINE" in env, "the xenon step must carry its ceiling in env"
    ceiling = int(env["XENON_BASELINE"])
    ledger = json.loads(RADON_LEDGER.read_text())["entries"]
    assert ceiling == len(ledger), (
        f"XENON_BASELINE ({ceiling}) diverges from the radon ledger's length "
        f"({len(ledger)}). The two tools measure the same blocks over the same "
        "scope, so the numbers only agree while both are green. An improvement "
        "must bank the ledger row AND lower this ceiling in the same PR; a "
        "regression needs a grant and raises both."
    )


# --- the other two xenon axes -----------------------------------------------


def test_xenon_enforces_module_rank_and_project_average_not_just_block_count() -> None:
    run = _xenon_run()
    # All three axes requested from the tool.
    assert "--max-absolute B" in run
    assert "--max-modules B" in run
    assert "--max-average A" in run
    # The old step ran `|| true` and counted only block errors, discarding the
    # other two axes. All three must be counted and judged. Module violations
    # are piped into the identity ledger compare; the average is counted.
    assert "grep '^ERROR:xenon:module' xenon.log" in run
    assert re.search(r"grep -c '\^ERROR:xenon:average'", run)
    assert '[ "$average" -gt 0 ]' in run, (
        "a project average below rank A must fail the step, not be printed and dropped"
    )
    # The condition text alone doesn't prove enforcement: deleting `fail=1` from
    # that branch, or the final `exit "$fail"`, would restore the historical
    # print-an-average-violation-and-pass behavior while the assertion above
    # stayed green. Pin the branch body and the status propagation too.
    assert re.search(r'if \[ "\$average" -gt 0 \]; then\n.*?\n\s*fail=1\n\s*fi', run, re.DOTALL), (
        "the average branch must raise the shared `fail` flag, not just print an error annotation"
    )
    assert run.rstrip().endswith('exit "$fail"'), (
        "the step must exit on the accumulated `fail` flag, or no counted "
        "violation (block, module, or average) ever fails the job"
    )
    # Module rank is compared by identity in both directions — a new violation
    # fails, and a fixed one must leave the ledger in the same PR.
    assert "comm -23 xenon-modules.now xenon-modules.ledger" in run
    assert "comm -13 xenon-modules.now xenon-modules.ledger" in run


# --- docstring floors -------------------------------------------------------


def test_interrogate_floors_every_shipped_package() -> None:
    """Every shipped src root sits under at least one interrogate floor."""
    floored = _interrogate_targets()
    assert floored, "the interrogate step must floor at least one tree"
    for root in _shipped_src_roots():
        covered = any(path == root or path.startswith(root.rstrip("/") + "/") for path in floored)
        assert covered, (
            f"{root} is not covered by any interrogate floor; docstring coverage "
            "there is unmeasured (core is covered by its four per-path floors, "
            "including the whole-package floor)"
        )
