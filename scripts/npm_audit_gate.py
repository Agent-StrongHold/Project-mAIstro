#!/usr/bin/env python3
"""Gate the npm supply chain against triaged advisories (canvas frontend).

The ci.yml ``test`` job used to run bare ``npm audit --audit-level=high`` over
``packages/maistro-canvas/frontend``. That step became unsatisfiable on every
tree when GHSA-fc5q-39xc-vjpf (picomatch ReDoS, published 2026-10-19) landed:
the advisory lists *every published picomatch* as vulnerable (range
``<=4.0.7``; 4.0.7 is the newest release) with **no patched version**, and
picomatch is a hard dependency of the frontend's dev toolchain — vite@8.3.8
depends on ``picomatch ^4.0.7`` directly and tinyglobby 0.2.17 depends on it —
so no lock refresh, override, or upgrade can produce a report without it.

This is the same shape the Python supply chain hit with ``ecdsa`` /
PYSEC-2026-1325 ("upstream states there is no planned fix"), which
``scripts/pip_audit_gate.py`` already solved with a triaged allowlist. This
module mirrors that design for npm: one list, one verdict.

Waiver ledger: that advisory was waived here from 2026-10-19 (#1450, round 9).
On 2026-11-18 npm's advisory database stopped reporting it — ``npm audit
--json`` returned **zero** advisories against the identical lock (picomatch
still pinned at 4.0.7, no new release) — and the two-way ratchet below
consumed the waiver (#2375): a waiver whose advisory stops being reported must
go with it. ALLOWED is empty again; the gate stays so the next unpatchable
advisory gets the same triaged treatment, and if the advisory resurfaces it
blocks again until it is re-triaged on its own merits.

Contract
--------
The workflow step writes the JSON report and this gate owns the verdict::

    npm audit --json > /tmp/npm-audit.json || true
    python scripts/npm_audit_gate.py /tmp/npm-audit.json

Nothing is weakened silently:

- Every advisory the report lists at severity **high or critical** fails the
  job unless its ID is in ``ALLOWED`` — including advisories that only reach
  the tree transitively through npm's "Depends on vulnerable versions of X"
  cascade, which this gate resolves to the root advisory ID.
- A waiver is accepted only for an advisory with **no available fix**, with a
  rationale specific enough to re-audit. A future advisory on the same package
  has a different ID and blocks until it is triaged on its own merits.
- Two-way ratchet: an ``ALLOWED`` entry whose advisory is no longer reported
  (upstream shipped the patch and the lock was refreshed) fails as stale, so
  waivers cannot accumulate past the advisories that justify them.

Exit codes (mirroring pip_audit_gate.py): 0 = pass; 1 = real finding
(unwaived high/critical advisory, stale waiver); 2 = usage error; 3 = the
audit produced no usable report (empty, unparseable, or an npm registry error
payload). That last case means the ``npm audit`` subprocess crashed or could
not reach the registry and ``|| true`` papered over it — an infrastructure
failure to retry, never a clean verdict.

Usage:  npm audit --json > npm-audit.json || true
        python scripts/npm_audit_gate.py npm-audit.json
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

BLOCKING_SEVERITIES = frozenset({"high", "critical"})

# Advisory ID -> why it is accepted. Keyed by the advisory ID, not the
# package: npm cascades one root advisory through every package that depends
# on it, and exempting a package name would silently pass every FUTURE
# advisory on it too. Each entry must name an advisory with no available fix
# and say why the tree is acceptable anyway, specifically enough to re-audit.
# An entry whose advisory stops being reported fails as stale — delete it.
# (Empty since 2026-11-18 (#2375): the picomatch waiver GHSA-fc5q-39xc-vjpf
# was consumed by the two-way ratchet — npm's advisory database stopped
# reporting the advisory against the unchanged lock. History in the module
# docstring and REPAIR-NOTES-1450-round9-picomatch-audit-gate.md.)
ALLOWED: dict[str, str] = {}


@dataclass(frozen=True)
class Advisory:
    """One npm advisory and the packages it affects in this tree."""

    identifier: str
    package: str
    title: str
    severity: str
    url: str
    vulnerable_range: str
    affected: frozenset[str]
    fix_available: Any

    @property
    def fix_hint(self) -> str:
        if isinstance(self.fix_available, dict):
            breaking = " (breaking)" if self.fix_available.get("isSemVerMajor") else ""
            return f"fix available: {self.fix_available.get('name')}@{self.fix_available.get('version')}{breaking}"
        if self.fix_available is True:
            return "fix available via `npm audit fix`"
        return "NO FIX AVAILABLE — needs triage"


def _advisory_from_via(package: str, via: dict[str, Any], fix_available: Any) -> Advisory:
    """Build one Advisory from an npm audit ``via`` object."""
    url = via.get("url") if isinstance(via.get("url"), str) else ""
    source = via.get("source")
    identifier = url.rsplit("/", 1)[-1] if url else str(source)
    return Advisory(
        identifier=identifier,
        package=via.get("name", package) if isinstance(via.get("name"), str) else package,
        title=via.get("title", "") if isinstance(via.get("title"), str) else "",
        severity=via.get("severity", "unknown")
        if isinstance(via.get("severity"), str)
        else "unknown",
        url=url,
        vulnerable_range=via.get("range", "") if isinstance(via.get("range"), str) else "",
        affected=frozenset({package}),
        fix_available=fix_available,
    )


def _index_via(
    vulnerabilities: dict[str, dict[str, Any]],
) -> tuple[dict[str, Advisory], dict[str, set[str]], dict[str, set[str]]]:
    """Split each package's ``via`` list into advisories, cascades, and roots."""
    advisories: dict[str, Advisory] = {}
    direct: dict[str, set[str]] = {}
    refers: dict[str, set[str]] = {}
    for package, entry in vulnerabilities.items():
        fix_available = entry.get("fixAvailable")
        for via in entry.get("via", []):
            if isinstance(via, dict):
                advisory = _advisory_from_via(package, via, fix_available)
                existing = advisories.get(advisory.identifier)
                advisories[advisory.identifier] = (
                    replace(existing, affected=existing.affected | {package})
                    if existing is not None
                    else advisory
                )
                direct.setdefault(package, set()).add(advisory.identifier)
            elif isinstance(via, str):
                refers.setdefault(package, set()).add(via)
    return advisories, direct, refers


def _resolve_transitively(
    packages: Iterable[str],
    direct: dict[str, set[str]],
    refers: dict[str, set[str]],
) -> dict[str, set[str]]:
    """Give every package the advisory IDs it carries directly or inherits."""
    resolved: dict[str, set[str]] = {}

    def resolve(package: str, seen: frozenset[str]) -> set[str]:
        if package in resolved:
            return resolved[package]
        if package in seen:  # npm has produced dependency cycles before
            return set()
        found = set(direct.get(package, ()))
        for reference in sorted(refers.get(package, ())):
            found |= resolve(reference, seen | {package})
        resolved[package] = found
        return found

    for package in packages:
        resolve(package, frozenset())
    return resolved


def collect_advisories(report: dict[str, Any]) -> list[Advisory]:
    """Resolve the report's advisory objects and npm's cascade references.

    ``vulnerabilities[name].via`` mixes real advisory objects (with a GHSA
    URL) with bare strings naming the package that carries the advisory —
    npm's "Depends on vulnerable versions of X" cascade. A cascade entry is
    resolved transitively so the verdict names the root advisory ID, not the
    intermediate package names.
    """
    vulnerabilities = report.get("vulnerabilities")
    if not isinstance(vulnerabilities, dict) or not all(
        isinstance(entry, dict) for entry in vulnerabilities.values()
    ):
        raise ValueError("report has no well-formed vulnerabilities object")

    advisories, direct, refers = _index_via(vulnerabilities)
    by_id: dict[str, set[str]] = {}
    for package, identifiers in _resolve_transitively(vulnerabilities, direct, refers).items():
        for identifier in identifiers:
            by_id.setdefault(identifier, set()).add(package)

    return [
        replace(
            advisory, affected=advisory.affected | frozenset(by_id.get(advisory.identifier, ()))
        )
        for advisory in (advisories[identifier] for identifier in sorted(advisories))
    ]


def load_report(path: str) -> dict[str, Any]:
    """Read one npm audit JSON report, failing on unusable output."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("report is not a JSON object")
    if "error" in data:
        detail = data["error"]
        if isinstance(detail, dict):
            message = detail.get("summary") or detail.get("message") or detail.get("detail") or ""
        else:
            message = str(detail)
        raise ValueError(f"npm audit reported an error payload: {message}")
    collect_advisories(data)  # validates the shape before any verdict
    return data


def audit_report(path: str) -> int:
    """Gate one npm audit JSON report against the triaged ALLOWED list.

    Returns 3 — never 0 — when the report is empty, unparseable, or an npm
    registry error payload: the audit subprocess crashed before writing a
    verdict (e.g. a registry read timeout), which is an infrastructure
    failure to retry, never a clean supply-chain verdict.
    """
    try:
        report = load_report(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            f"::error::npm audit report {path!r} is not usable ({exc}). The audit subprocess "
            "crashed before writing a verdict — likely a transient registry/network outage. "
            "This is an infrastructure failure (exit 3): retry the audit; do not treat the "
            "dependency set as clean."
        )
        return 3

    advisories = collect_advisories(report)
    blocking = [
        advisory
        for advisory in advisories
        if advisory.severity in BLOCKING_SEVERITIES and advisory.identifier not in ALLOWED
    ]

    if blocking:
        print("::error::npm audit found advisories outside the triaged allowlist:")
        for advisory in blocking:
            affected = ", ".join(sorted(advisory.affected))
            print(
                f"  {advisory.identifier} ({advisory.severity}) {advisory.package} "
                f"[affects: {affected}] -> {advisory.fix_hint}"
            )
            print(f"    {advisory.title} {advisory.url}")
        print(
            "\nFix by upgrading the affected dependency. Only add an advisory ID "
            "to ALLOWED in scripts/npm_audit_gate.py when no fixed version exists, "
            "and say why, specifically enough to re-audit — the comment block "
            "above ALLOWED spells out the bar."
        )
        return 1

    allowed_present = [a for a in advisories if a.identifier in ALLOWED]
    for advisory in allowed_present:
        print(
            f"allowed: {advisory.identifier} ({advisory.severity}) "
            f"affects {', '.join(sorted(advisory.affected))}"
        )
    stale = sorted(set(ALLOWED) - {a.identifier for a in advisories})
    if stale:
        print("::error::npm audit waivers are stale — the advisories are no longer reported:")
        for identifier in stale:
            print(f"  {identifier} — delete it from ALLOWED in scripts/npm_audit_gate.py")
        print(
            "\nUpstream shipped a fix (or the dependency left the tree) and the lock "
            "was refreshed: the waiver must go with it, not linger."
        )
        return 1

    print(f"npm audit OK ({len(advisories)} advisories reported, all triaged in ALLOWED)")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <npm-audit.json>", file=sys.stderr)
        return 2
    return audit_report(argv[1])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
