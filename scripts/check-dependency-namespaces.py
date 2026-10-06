#!/usr/bin/env python3
"""Gate: dependency wheels install no unreviewed top-level namespace (#406).

Why this exists
---------------
The locked identity stack (``maistro-core[identity]`` -> ``bip-utils`` ->
``pytoniq-core-fork``) installs a generic top-level ``examples`` namespace
package into every environment that resolves it. A top-level name from a
dependency is an import-boundary problem in both directions:

- **Shadowing.** If a first-party tree ever ships a module with the same
  top-level name, the two meet on ``sys.path`` — and when both land in the
  *same* site-packages (two wheels, one directory) the later install silently
  overwrites the earlier one's files. Neither direction fails loudly.
- **Import-surface sprawl.** ``pytoniq_core_fork-0.1.48`` ships
  ``examples/boc/*``, ``examples/hashmaps/dict.py`` (a module literally named
  ``dict``), ``examples/tl/*`` and ``examples/tlb/*`` — tens of importable
  modules no production code path uses, offered to every ``import`` in the
  process (including agent-authored code in the RSI runner).

Nothing else in the repo watches this surface. ``verify-wheel-imports.py``
checks what *our* wheels contain; ``pip-audit`` checks CVEs, not namespace
collisions; the suite inventory checks tests. This gate closes the remaining
half: it inventories every top-level importable name each installed
distribution contributes, and rejects the ones nothing has reviewed.

What it rejects
---------------
- **Generic names** from a dependency (``examples``, ``tests``, ``utils``,
  ``common``, ``core``, ...) unless an entry in ``REVIEWED_NAMESPACES`` names
  exactly that (distribution, name) pair with a written mitigation. A review
  is keyed to the distribution: if a *different* distribution starts shipping
  ``examples``, the entry does not cover it and the gate fails.
- **Multi-owner names**: two distributions contributing the same top-level
  name. This is a file-level collision in a shared site-packages even when
  both are namespaces, so it is rejected unless the split is deliberate and
  reviewed (``MULTI_OWNER_REVIEWED`` — e.g. the ``jaraco`` PEP 420 split) and
  no contributor makes it a regular package.
- **First-party shadowing**: any non-first-party distribution contributing a
  name in ``FIRST_PARTY_TOP_LEVEL_NAMES``. There is no review escape here —
  that name is ours, and the gate's job is to keep it that way.
- **Unscannable distributions**: a ``*.dist-info`` with no readable RECORD
  cannot be inventoried, and an uninventorable distribution reads exactly like
  a safe one. It fails until it can be scanned.

Production is stricter
----------------------
``--production`` additionally demands that every name in
``PRUNED_IN_PRODUCTION`` is *absent*: reviewed-and-present is a dev/CI
disposition, not a shipped-artifact one. The shipped images run the prune
(``scripts/prune-dependency-namespaces.py``) and then this gate in
``--production`` mode inside the same build layer, so a prune that silently
stopped pruning fails the image build rather than the next audit.

How the inventory is computed
-----------------------------
From each ``*.dist-info/RECORD`` under the scanned site-packages: the first
path component of every row, minus non-importable prefixes (``bin``,
``share``, ``*.dist-info``, ``*.data``, ``__pycache__``, ``..`` escapes,
top-level ``.pth`` config files). RECORD is scanned rather than
``top_level.txt`` because RECORD is what the installer actually wrote —
``top_level.txt`` is a setuptools courtesy that goes stale the moment a wheel
is post-processed.

The decision record (#406's "determine")
----------------------------------------
``pytoniq-core-fork`` cannot be upgraded past the ``examples`` payload: both
releases on PyPI (0.1.47, 0.1.48) ship it, bip-utils pins ``<0.2.0``, and the
clean upstream ``pytoniq-core`` (no ``examples``) is a different distribution
that bip-utils does not accept. pip/uv cannot exclude a subpath at install
time, and the shipped images pip-install from PyPI without reading uv.lock, so
a lock-level override cannot reach them either. Isolation is already maximal:
``bip-utils`` sits behind maistro-core's optional ``identity`` extra — but the
shipped images genuinely need ``identity``, so isolation alone leaves the
namespace in production. The remaining lever, taken here: prune the payload at
image build time and hold every environment to the reviewed registry. This
extends the supply-chain controls of ADR-039 to the namespace surface.

SBOM provenance: syft catalogs Python distributions from ``dist-info``, so the
CycloneDX SBOM of a shipped image records ``pkg:pypi/pytoniq-core-fork@0.1.48``
— the *fork* provenance, by name — and, after the prune rewrites RECORD, a
file inventory that shows exactly what the patch removed.

Usage
-----
    python scripts/check-dependency-namespaces.py                  # this env
    python scripts/check-dependency-namespaces.py --production     # shipped env
    python scripts/check-dependency-namespaces.py --site-packages /app/venv/lib/python3.13/site-packages
    python scripts/check-dependency-namespaces.py --json           # machine inventory
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import sysconfig
from dataclasses import dataclass, field
from pathlib import Path

#: Stem of the companion prune tool, ``scripts/prune-dependency-namespaces.py``.
#
#: Named at runtime, not imported: both are standalone entry points, and the
#: remediation for a ``pruned-present`` finding (reported below) is to run that
#: tool on the shipped environment and re-scan with ``--production``. Holding
#: the stem here also keeps the tool reachable for ``scripts/check-reachability.py``:
#: it roots tooling from workflow text, and the places the prune actually runs
#: (the shipped-image Dockerfiles) are not workflow text — without this
#: reference the live tool re-banks as an unreachable identity and the
#: reachability ratchet fails. Sibling scripts the images run must stay named
#: by a script CI runs.
PRUNE_TOOL_STEM = "prune-dependency-namespaces"

#: Top-level names so generic that a dependency shipping one unreviewed is a
#: collision waiting for a victim: they are the names a first-party tree, a
#: script, or a vendored module would plausibly choose. Not an exhaustive
#: blocklist — an unusual name nobody reviewed is still caught by a human
#: reading the gate's inventory diff — but these are the ones that must never
#: arrive by accident.
GENERIC_TOP_LEVEL_NAMES = frozenset(
    {
        "app",
        "assets",
        "bench",
        "benchmarks",
        "bin",
        "build",
        "common",
        "config",
        "content",
        "core",
        "demo",
        "demos",
        "dist",
        "doc",
        "docs",
        "examples",
        "helper",
        "helpers",
        "lib",
        "main",
        "misc",
        "sample",
        "samples",
        "script",
        "scripts",
        "setup",
        "src",
        "temp",
        "templates",
        "test",
        "testing",
        "tests",
        "tool",
        "tools",
        "tmp",
        "util",
        "utils",
    }
)

#: Top-level importable names first-party distributions ship, mapped to the
#: ONLY distributions entitled to contribute them (wheel names, since a
#: scanned environment sees wheels, not source trees). The gate fails any
#: other distribution contributing one of these — that is the "first-party
#: cannot be shadowed" half of #406, and it has no review escape.
#:
#: ``tests/`` holds this map against the actual ``packages/*/src`` trees (and
#: hive-conductor's remapped flat-layout wheel), so it cannot silently drift
#: from what the workspace really builds. ``_vulture_whitelist`` is excluded
#: from the maistro-core wheel by hatch config but is first-party source; a
#: dependency shipping a module of that name would still be an impostor.
FIRST_PARTY_OWNERS: dict[str, set[str]] = {
    "_vulture_whitelist": {"maistro-core"},
    "hive_conductor": {"hive-conductor"},
    "maistro": {"maistro-core"},
    "maistro_bootstrap": {"maistro-bootstrap"},
    "maistro_canvas": {"maistro-canvas"},
    "maistro_design": {"maistro-design"},
    "maistro_evolve": {"maistro-evolve"},
    "maistro_ext_harness": {"maistro-ext-harness"},
    "maistro_ext_sdk": {"maistro-ext-sdk"},
    "maistro_registry": {"maistro-registry"},
    "maistro_rsi": {"maistro-rsi"},
    "maistro_server": {"maistro-server"},
    "maistro_turing": {"maistro-turing"},
}

#: Convenience view for the multi-owner/shadow checks; keep in sync via the
#: map above (derived, so it cannot drift).
FIRST_PARTY_TOP_LEVEL_NAMES = frozenset(FIRST_PARTY_OWNERS)

#: RECORD path prefixes that are not importable Python surface. ``.data`` and
#: ``.dist-info`` suffixes cover installer metadata and wheel data trees
#: (``foo-1.0.data/scripts/...``); the bare names cover scheme directories
#: some installers record alongside the package payload.
NON_IMPORTABLE_PREFIXES = frozenset(
    {
        "__pycache__",
        "bin",
        "etc",
        "include",
        "lib",
        "lib32",
        "lib64",
        "man",
        "share",
        "usr",
    }
)


@dataclass(frozen=True)
class Reviewed:
    """One deliberately accepted (namespace, distribution) pair."""

    distribution: str
    """The only distribution the review covers (PEP 503 normalized)."""

    environments: str
    """Where the presence is accepted, stated so it cannot over-extend."""

    mitigation: str
    """What keeps the name out of the environments where it is not accepted."""


#: Reviews are keyed by the top-level NAME, and each names exactly one
#: distribution. A second distribution shipping the same name is a new,
#: unreviewed event — which is the failure mode a shared allowlist would hide.
REVIEWED_NAMESPACES: dict[str, Reviewed] = {
    "examples": Reviewed(
        distribution="pytoniq-core-fork",
        environments=(
            "dev and CI sync environments only (uv.lock installs maistro-core[tui,identity] "
            "at the workspace root, pulling bip-utils -> pytoniq-core-fork)"
        ),
        mitigation=(
            "both PyPI releases of the fork (0.1.47, 0.1.48) ship the namespace and bip-utils "
            "pins <0.2.0, so it cannot be upgraded away; shipped images prune it at build time "
            "via scripts/prune-dependency-namespaces.py (Dockerfile, "
            "packages/hive-conductor/Dockerfile, Dockerfile.rsi-runner) and then run this gate "
            "with --production, which fails if the namespace is importable"
        ),
    ),
}


@dataclass(frozen=True)
class MultiOwnerReview:
    """One deliberately accepted multi-contributor top-level name."""

    reason: str
    """Who contributes, why it is safe (or accepted), and who owns the debt."""

    allow_regular_package: bool = False
    """Whether a contributor shipping ``<top>/__init__.py`` is part of the
    review. Deliberately False for every coordinated namespace split — there,
    the absence of a regular package IS the safety argument — and True only
    for an explicitly owned debt where the shadowing is known and bounded."""


#: Deliberate multi-contributor top-level names. Reviewed by name because a
#: reviewed split is a real packaging decision, and an unreviewed one is the
#: collision this gate exists to catch. Each excuse is void beyond its terms:
#: a namespace-split review fails the moment any contributor ships a regular
#: package at the namespace root — then files can overwrite files — and an
#: accepted-collision review fails if a third contributor appears.
MULTI_OWNER_REVIEWED: dict[str, MultiOwnerReview] = {
    "jaraco": MultiOwnerReview(
        reason=(
            "upstream-coordinated PEP 420 split (jaraco.classes / jaraco.context / "
            "jaraco.functools ship disjoint subpackages, no __init__.py anywhere)"
        )
    ),
    "google": MultiOwnerReview(
        reason=(
            "upstream-coordinated PEP 420 split (protobuf ships google/protobuf/, "
            "googleapis-common-protos ships google/api|rpc|type/; neither ships "
            "google/__init__.py — verified against the pinned wheels for #406)"
        )
    ),
    "opentelemetry": MultiOwnerReview(
        reason=(
            "upstream-coordinated PEP 420 split (the opentelemetry-api/sdk/exporter "
            "family ships disjoint opentelemetry/ subpackages, no __init__.py "
            "anywhere — verified against the pinned wheels for #406)"
        )
    ),
    "py": MultiOwnerReview(
        reason=(
            "KNOWN pre-existing collision, owned by #348's tool pinning: pytest >=9 "
            "ships a bare py.py compatibility shim while the legacy py 1.11.0 "
            "distribution (pulled by the rsi-runner's deliberately unpinned fitness "
            "tools, uv pip install coverage bandit radon interrogate vulture pylint) "
            "installs a real py/ package into the same site-packages, where the "
            "package shadows the shim. Not a coordinated split; reviewed as accepted "
            "debt with an owner so the collision cannot GROW unnoticed — a third "
            "contributor still fails"
        ),
        allow_regular_package=True,
    ),
}

#: Names that must be ABSENT from a production scan (--production), mapped to
#: the distribution whose payload is pruned. This is the machine-readable half
#: of the mitigation text above; scripts/prune-dependency-namespaces.py loads
#: this exact mapping, so the prune and the strict check cannot disagree.
PRUNED_IN_PRODUCTION: dict[str, str] = {
    "examples": "pytoniq-core-fork",
}


@dataclass
class Distribution:
    """What one installed distribution contributes to the namespace surface."""

    name: str
    """Distribution name from METADATA (PEP 503 normalized)."""

    dist_info: Path
    """The *.dist-info directory the inventory was read from."""

    top_levels: set[str] = field(default_factory=set)
    """Top-level importable names contributed, from RECORD."""

    skipped_rows: list[str] = field(default_factory=list)
    """RECORD rows excluded from the inventory, each with its reason.

    Informational (installer metadata, scheme directories, ``.pth`` config),
    never a finding — a wheel that records its own dist-info files is normal.
    """

    problems: list[str] = field(default_factory=list)
    """Why the distribution could not be inventoried at all (empty = scannable).

    Only a missing RECORD lands here: a distribution whose payload cannot be
    listed is indistinguishable from a safe one, and that is a finding."""


@dataclass(frozen=True)
class Finding:
    """One rejection, with the evidence a reviewer needs to act on it."""

    kind: str
    """unreviewed-generic | multi-owner | first-party-shadow | unscannable | pruned-present."""

    top_level: str
    distribution: str
    detail: str


def normalize(name: str) -> str:
    """PEP 503 name normalization, so registry keys match METADATA spellings."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _first_component(path: str) -> str | None:
    """First path component of a RECORD row, or None when it escapes upward."""
    if path.startswith(".."):
        return None
    return path.split("/", 1)[0]


def _record_rows(dist_info: Path) -> list[list[str]] | None:
    """RECORD rows, or None when the dist-info carries no readable RECORD."""
    record = dist_info / "RECORD"
    if not record.is_file():
        return None
    with record.open(newline="", encoding="utf-8") as fh:
        return [row for row in csv.reader(fh) if row and row[0]]


def _record_top_levels(dist_info: Path) -> tuple[set[str], list[str], list[str]]:
    """(top-level names, skipped-row notes, hard problems) from one RECORD.

    A row counts when it is importable content: a package directory
    (``pkg/__init__.py``), a namespace portion (``examples/boc/address.py`` —
    no ``__init__`` required), a bare module (``foo.py``) or a top-level
    extension (``foo.so``), all keyed by IMPORT name (extensions stripped) so
    comparisons line up with what ``import`` sees. Everything else —
    dist-info metadata, wheel ``*.data`` trees, scheme directories, ``..``
    escapes out of site-packages, top-level ``.pth`` config, and extensionless
    non-Python files — is skipped and named, so a skimmer can see what was
    excluded and why. Only a missing RECORD is a hard problem: a payload that
    cannot be listed cannot be trusted.
    """
    rows = _record_rows(dist_info)
    if rows is None:
        return set(), [], [f"no RECORD in {dist_info.name}"]
    tops: set[str] = set()
    skipped: list[str] = []
    for row in rows:
        path = row[0]
        first = _first_component(path)
        if first is None:
            skipped.append(f"{path} (escapes site-packages)")
        elif first.endswith(".dist-info") or first.endswith(".data"):
            skipped.append(f"{path} (installer metadata/data tree)")
        elif first in NON_IMPORTABLE_PREFIXES:
            skipped.append(f"{path} (scheme directory, not importable)")
        elif "/" not in path and path.endswith(".pth"):
            skipped.append(f"{path} (path configuration, not a module)")
        elif "/" not in path and (import_name := _bare_module_name(path)) is None:
            skipped.append(f"{path} (top-level non-Python file, not importable)")
        elif "/" not in path:
            tops.add(import_name)
        else:
            tops.add(first)
    return tops, skipped, []


def _bare_module_name(path: str) -> str | None:
    """Import name of a site-packages-root module file, or None if not code.

    ``curio.py`` -> ``curio``; ``foo.cpython-312-x86_64-linux-gnu.so`` ->
    ``foo``. An extensionless root file (a stray LICENSE, a README) is data,
    not an import surface, and must not enter the inventory.
    """
    for suffix in (".py", ".pyd", ".pyi"):
        if path.endswith(suffix):
            return path[: -len(suffix)]
    if ".so" in path:
        return path.split(".")[0]
    return None


def _metadata_name(dist_info: Path) -> str | None:
    """Distribution name from METADATA, tolerating a missing file."""
    meta = dist_info / "METADATA"
    if not meta.is_file():
        return None
    for line in meta.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("Name:"):
            return line.split(":", 1)[1].strip()
        if not line.strip():
            break
    return None


def scan_site_packages(site: Path) -> list[Distribution]:
    """Inventory every *.dist-info under one site-packages directory."""
    dists: list[Distribution] = []
    for dist_info in sorted(site.glob("*.dist-info")):
        if not dist_info.is_dir():
            continue
        raw = _metadata_name(dist_info)
        name = normalize(raw if raw else dist_info.name.split("-")[0])
        tops, skipped, problems = _record_top_levels(dist_info)
        dists.append(
            Distribution(
                name=name,
                dist_info=dist_info,
                top_levels=tops,
                skipped_rows=skipped,
                problems=problems,
            )
        )
    return dists


def default_site_packages() -> list[Path]:
    """The running interpreter's package directories (purelib, and platlib when distinct)."""
    paths = sysconfig.get_paths()
    sites = [Path(paths["purelib"])]
    platlib = paths.get("platlib")
    if platlib and Path(platlib) != sites[0]:
        sites.append(Path(platlib))
    return sites


def _owners_by_name(dists: list[Distribution]) -> dict[str, list[Distribution]]:
    owners: dict[str, list[Distribution]] = {}
    for dist in dists:
        for top in dist.top_levels:
            owners.setdefault(top, []).append(dist)
    return owners


def _is_first_party_dist(dist: Distribution, top: str) -> bool:
    """Whether this distribution is one entitled to contribute `top`.

    First-party names arrive in a scanned dev environment through editable
    installs (no dist-info rows), so the usual case is that the name was
    contributed by someone else entirely. Entitlement is an explicit map
    (``FIRST_PARTY_OWNERS``), not a spelling heuristic — ``not-maistro`` must
    not pass for ``maistro``.
    """
    owners = FIRST_PARTY_OWNERS.get(top, set())
    return dist.name in {normalize(o) for o in owners}


def _ships_regular_package(dist: Distribution, top: str) -> bool:
    """Whether the distribution's RECORD lists `<top>/__init__.py`."""
    rows = _record_rows(dist.dist_info)
    if rows is None:
        return False
    return any(row[0] == f"{top}/__init__.py" for row in rows)


def evaluate(dists: list[Distribution], production: bool) -> list[Finding]:
    """Every rejection in the scanned inventory, with evidence.

    Deterministic order (kind, name, distribution) so two runs of the same
    environment produce byte-identical reports — a gate whose output shuffles
    trains people to ignore it.
    """
    findings: list[Finding] = []

    for dist in dists:
        for problem in dist.problems:
            findings.append(
                Finding(
                    kind="unscannable",
                    top_level="-",
                    distribution=dist.name,
                    detail=f"{problem}; an uninventorable distribution reads the same as a safe one",
                )
            )

    owners = _owners_by_name(dists)
    for top, contributing in sorted(owners.items()):
        if len(contributing) > 1:
            _evaluate_multi_owner(top, contributing, findings)
        else:
            _evaluate_single_owner(top, contributing[0], production, findings)

    findings.sort(key=lambda f: (f.kind, f.top_level, f.distribution))
    return findings


def _evaluate_multi_owner(
    top: str, contributing: list[Distribution], findings: list[Finding]
) -> None:
    """Reject a name contributed by two+ distributions unless the split is reviewed."""
    any_regular = any(_ships_regular_package(d, top) for d in contributing)
    review = MULTI_OWNER_REVIEWED.get(top)
    if review is not None and (
        not any_regular or (review.allow_regular_package and len(contributing) == 2)
    ):
        return
    first_party_involved = top in FIRST_PARTY_TOP_LEVEL_NAMES and any(
        _is_first_party_dist(d, top) for d in contributing
    )
    detail = (
        "a first-party top-level name is shared with a dependency wheel; the "
        "dependency's files can overwrite ours in a shared site-packages"
        if first_party_involved
        else review.reason
        if review is not None
        else (
            "no reviewed split: even namespace portions merge silently, and one "
            "regular package among them overwrites the others' files in a shared "
            "site-packages"
        )
    )
    findings.append(
        Finding(
            kind="first-party-shadow" if first_party_involved else "multi-owner",
            top_level=top,
            distribution=",".join(sorted(d.name for d in contributing)),
            detail=detail,
        )
    )


def _evaluate_single_owner(
    top: str,
    owner: Distribution,
    production: bool,
    findings: list[Finding],
) -> None:
    """Reject one distribution's claim on a name it may not own."""
    if top in FIRST_PARTY_TOP_LEVEL_NAMES:
        if not _is_first_party_dist(owner, top):
            findings.append(
                Finding(
                    kind="first-party-shadow",
                    top_level=top,
                    distribution=owner.name,
                    detail=(
                        f"{top} is a first-party top-level name; a dependency wheel "
                        "contributing it is a shadowing/collision hazard and has no review escape"
                    ),
                )
            )
        return
    if top in GENERIC_TOP_LEVEL_NAMES:
        review = REVIEWED_NAMESPACES.get(top)
        if review is None:
            findings.append(
                Finding(
                    kind="unreviewed-generic",
                    top_level=top,
                    distribution=owner.name,
                    detail=(
                        "generic top-level name with no entry in REVIEWED_NAMESPACES; "
                        "review it (with a mitigation) or stop shipping it"
                    ),
                )
            )
        elif review.distribution != owner.name:
            findings.append(
                Finding(
                    kind="unreviewed-generic",
                    top_level=top,
                    distribution=owner.name,
                    detail=(
                        f"the REVIEWED_NAMESPACES entry for {top!r} names "
                        f"{review.distribution!r}, not {owner.name!r}; a new distribution "
                        "shipping a reviewed name is a new, unreviewed event"
                    ),
                )
            )
    if production and top in PRUNED_IN_PRODUCTION:
        findings.append(
            Finding(
                kind="pruned-present",
                top_level=top,
                distribution=owner.name,
                detail=(
                    f"production scan: {top!r} is in PRUNED_IN_PRODUCTION (prune via "
                    f"scripts/{PRUNE_TOOL_STEM}.py) and must be absent from "
                    "shipped environments, reviewed or not"
                ),
            )
        )


def _render(
    dists: list[Distribution], findings: list[Finding], sites: list[Path], production: bool
) -> str:
    """Human report: the inventory (criterion 1) plus every rejection."""
    lines: list[str] = []
    scope = "production" if production else "dev/CI"
    lines.append(f"{scope} scan of {len(dists)} distribution(s) across:")
    for s in sites:
        lines.append(f"  {s}")
    present_reviewed = sorted(top for top in _owners_by_name(dists) if top in REVIEWED_NAMESPACES)
    for top in present_reviewed:
        r = REVIEWED_NAMESPACES[top]
        lines.append(f"reviewed: {top} <- {r.distribution} ({r.environments})")
    if findings:
        lines.append(f"REJECTED — {len(findings)} namespace finding(s):")
        for f in findings:
            lines.append(f"  [{f.kind}] {f.top_level} <- {f.distribution}: {f.detail}")
        if production and any(f.kind == "pruned-present" for f in findings):
            lines.append(
                f"Remediate a pruned-present finding: run scripts/{PRUNE_TOOL_STEM}.py "
                "on the shipped environment, then re-run this gate with --production."
            )
        lines.append(
            "Fix by removing the payload (prune/patch), pinning past it, or adding a "
            "REVIEWED_NAMESPACES entry that names exactly this distribution and the "
            "mitigation — never by widening the generic-name set."
        )
    else:
        lines.append("no unreviewed top-level namespaces.")
    return "\n".join(lines)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else None,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--site-packages",
        type=Path,
        action="append",
        default=[],
        help="site-packages directory to scan (repeatable; default: this interpreter's)",
    )
    ap.add_argument(
        "--production",
        action="store_true",
        help="additionally require PRUNED_IN_PRODUCTION names to be absent (shipped images)",
    )
    ap.add_argument("--json", action="store_true", help="emit the inventory and findings as JSON")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    sites = args.site_packages or default_site_packages()
    missing = [s for s in sites if not s.is_dir()]
    if missing:
        print(f"error: site-packages directory not found: {missing}", file=sys.stderr)
        return 2

    dists: list[Distribution] = []
    for site in sites:
        dists.extend(scan_site_packages(site))
    findings = evaluate(dists, production=args.production)

    if args.json:
        print(
            json.dumps(
                {
                    "sites": [str(s) for s in sites],
                    "production": args.production,
                    "distributions": {
                        d.name: sorted(d.top_levels) for d in sorted(dists, key=lambda x: x.name)
                    },
                    "non_importable_rows": {
                        d.name: len(d.skipped_rows)
                        for d in sorted(dists, key=lambda x: x.name)
                        if d.skipped_rows
                    },
                    "findings": [f.__dict__ for f in findings],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(_render(dists, findings, sites, production=args.production))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
