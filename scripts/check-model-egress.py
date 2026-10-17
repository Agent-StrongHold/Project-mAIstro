#!/usr/bin/env python3
"""Freeze direct model-egress modules against a trusted base revision (#542, #319).

A candidate may not add a direct model caller and approve that escape by adding
the same module to quality/model-egress.json. Expansions are judged against the
merge-base inventory and require a separately landed authorization. Candidate
bookkeeping is checked independently so migrated callers must still be pruned.

A module move that carries already-reviewed egress verbatim to a new home is
not an expansion when the trusted base records the predecessor and the
candidate prunes it; CANDIDATE_MIGRATIONS is that operator-approved record,
scoped per move so it can never authorize a caller that did not exist before.

Metric v2 (#1089) -- reachable physical egress, not syntactic source matches.
A finding is now a physical model HTTP call: an effect-method call whose own
URL argument carries a model endpoint fragment, resolved through string
bindings, exactly the curated boundary `check_direct_effects.py` enforces.
Endpoint prose, a route table, or an unrelated ``.post(...)`` elsewhere in the
file no longer classify a module -- `maistro_server.api.chat_completions` was
recorded that way and is gone. Each finding is joined with the repository
reachability model (`check-reachability.py` baseline and the reviewed
dispositions) and labeled:

- APPROVED_PROVIDER_BOUNDARY -- the named terminal Provider implementation(s);
  recognition only, never an authorization path (the ratchet below does not
  consult this label);
- UNREACHABLE_LIBRARY -- the module sits on the reviewed reachability
  baseline, so it cannot be a shipped escape; the reviewed CONNECT/LIBRARY/
  RETIRE group is attached when one exists;
- REACHABLE_ESCAPE -- reachable from a shipped process entry point and not the
  Provider boundary: the count #56/#35 closeout must drive to zero.

Dispositions are derived, never stored in a candidate-editable ledger: the
inputs are separately gated files, so a disposition cannot go stale and a
candidate cannot relabel its own escape. Staleness is enforced where state is
actually stored -- a ledger entry whose physical egress disappeared fails the
candidate check until pruned. The reachability vocabulary has no fourth
"downstream/deferred owner" class because no governed artifact records one;
inventing an unauditable label would put adjudication inside the measurement.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "quality" / "model-egress.json"
DIRECT_EFFECTS_SOURCE = ROOT / "scripts" / "check_direct_effects.py"
DIRECT_EFFECTS_TOOL = "check_direct_effects"
REACHABILITY = ROOT / "scripts" / "check-reachability.py"
REACHABILITY_BASELINE = ROOT / "quality" / "reachability-baseline.json"
REACHABILITY_DISPOSITIONS = ROOT / "quality" / "reachability-dispositions.json"
_PROVENANCE_SOURCE = ROOT / "scripts" / "ratchet_provenance.py"
RATCHET = "model-egress"
# v2: physical call-site detection with the reachability join (#1089). v1 was
# the module-level endpoint-text + any-.post heuristic that recorded
# maistro_server.api.chat_completions without a physical call.
METRIC_DEFINITION_VERSION = "2"

# An operator-approved record of a direct caller whose egress moved verbatim
# to a new module in a convergence PR, judged against the trusted base. This
#: mirrors the CANDIDATE_AUTHORED design in check-ratchet-provenance.py: the
#: mapping is scoped to exactly one reviewed move and lands atomically with
#: the code that performs it. It is NOT an authorization to grow the set:
#: `_migration_predecessor` honors it only while the predecessor is recorded
#: in the trusted base AND has been pruned from the candidate inventory, so a
#: rename can relocate a caller but never add one (#835: graph_runner's
#: compatibility helpers moved into the legacy_dag_node adapter; #56:
#: llm_summarize's model HTTP moved into the approved llm_gateway Provider).
CANDIDATE_MIGRATIONS: dict[str, str] = {
    "services.legacy_dag_node": "services.graph_runner",
    "maistro.capabilities.providers.llm_gateway": "maistro.graph.nodes.llm_summarize",
}

# The terminal model Provider boundary #56 built: the one implementation
# allowed to perform physical model HTTP as a product design decision. Naming
# a module here only labels the report; it is not and can never be the
# ratchet's authorization path, which reads quality/ratchet-authorizations.json
# from the merge base (load_authorizations below). A candidate that adds its
# own escape here gets a friendlier label and the same FAIL.
APPROVED_PROVIDER_BOUNDARIES: frozenset[str] = frozenset(
    {
        "maistro.capabilities.providers.llm_gateway",
    }
)

# Curated MODEL_EFFECT rows that are NOT this ledger's population. The census
# counts image-model HTTP (images/generations and the image-worker endpoints)
# at exact call sites with image-specific entry-point names; those sites are
# dispositioned in quality/direct-effect-call-sites.json and the trusted base
# here never recorded their modules. Folding them into this ratchet is a floor
# raise, not a precision fix: it needs a separately landed authorization under
# the two-merge rule. The carve-out is fail-closed in the right direction --
# any new non-image model-effect entry point enters the population below and
# fails the gate until its module is reviewed into (or out of) the ledger.
# The chat-endpoint URL match itself never recognises image endpoints, so
# v1 (the endpoint-text heuristic this metric replaces) never counted them
# either; the population below stays exactly the one the trusted base measured.
_IMAGE_HTTP_ENTRY_POINTS = frozenset(
    {
        "cloudflare-image-http",
        "azure-openai-image-http",
        "gemini-image-http",
        "openai-compatible-image-http",
    }
)

# The reachability classes a physical caller can carry. REACHABLE_ESCAPE is
# the #56/#35 closeout population: zero is the goal, and only zero for this
# class -- not for the whole inventory -- is the honest closeout claim.
PROVIDER_BOUNDARY = "APPROVED_PROVIDER_BOUNDARY"
UNREACHABLE_LIBRARY = "UNREACHABLE_LIBRARY"
REACHABLE_ESCAPE = "REACHABLE_ESCAPE"


def _load_direct_effects() -> ModuleType:
    """Load the sibling gate when this file is imported outside ``scripts/``."""
    name = DIRECT_EFFECTS_TOOL
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(name, DIRECT_EFFECTS_SOURCE)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {DIRECT_EFFECTS_SOURCE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


check_direct_effects = _load_direct_effects()
Site = check_direct_effects.Site


def _provenance() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_ratchet_provenance", _PROVENANCE_SOURCE)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {_PROVENANCE_SOURCE}")
    cached = sys.modules.get(spec.name)
    if cached is not None:
        return cached
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[spec.name]
        raise
    return module


def _load_reachability() -> object:
    spec = importlib.util.spec_from_file_location("_reachability", REACHABILITY)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {REACHABILITY}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_reachability"] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class EgressFinding:
    """One physical model-egress caller and its call-site evidence.

    `module` is the display identity the ledger is written in; `identity` is
    the reachability-graph spelling (`@flat/<app>/<module>` or the dotted
    package path) the reachability baseline and dispositions are keyed by.
    """

    module: str
    identity: str
    sites: tuple[Site, ...]


def find_egress_sites(source: str, *, path: str = "<module>") -> tuple[Site, ...]:
    """The physical completions-family model-egress call sites in one module.

    Delegates to the curated direct-effect census: a finding is an AST ``Call``
    at an HTTP effect boundary whose own URL argument (constant, binding,
    f-string, concatenation, or env default) carries a model endpoint
    fragment, or one of the census's exact triples for callers whose ``_post``
    seam hides the URL. Endpoint text anywhere else in the file -- docstrings,
    route tables, response shapes -- belongs to no call and finds nothing.
    Image-model HTTP is a separate curated population (see
    _IMAGE_HTTP_ENTRY_POINTS) and is not reported here.
    """
    return tuple(
        site
        for site in check_direct_effects.analyze_source(source, path)
        if site.category == "MODEL_EFFECT" and site.entry_point not in _IMAGE_HTTP_ENTRY_POINTS
    )


def performs_egress(source: str) -> bool:
    """Whether the module performs physical model HTTP anywhere in its code."""
    return bool(find_egress_sites(source))


def discover_sites() -> dict[str, EgressFinding]:
    """Every production module performing physical model egress, with evidence.

    Keyed by the display identity the ledger is written in, so the ratchet set
    and the report stay one vocabulary.
    """
    reach = _load_reachability()
    findings: dict[str, EgressFinding] = {}
    for key, path in reach._collect_modules().items():  # type: ignore[attr-defined]
        display = reach._display_name(key, reach.FLAT_APPS)  # type: ignore[attr-defined]
        if display in findings:  # pragma: no cover - universe guard, not expectation
            raise RuntimeError(f"duplicate module display identity: {display}")
        rel = path.relative_to(ROOT).as_posix()
        sites = find_egress_sites(path.read_text(errors="replace"), path=rel)
        if sites:
            findings[display] = EgressFinding(module=display, identity=key, sites=sites)
    return findings


def discover() -> set[str]:
    """The display identities performing physical model egress."""
    return set(discover_sites())


def _unreachable_identities(path: Path = REACHABILITY_BASELINE) -> frozenset[str]:
    """The reviewed unreachable module identities, spelled as the graph spells them.

    Read from the reviewed baseline, not recomputed: `check-reachability.py`
    ratchets that file against the live graph, so this join consumes the
    reviewed truth and never disagrees with the gate that owns it. An absent
    or malformed oracle fails closed -- an unreadable join would silently
    label every unreachable caller a shipped escape.
    """
    if not path.exists():
        raise RuntimeError(
            f"{path} is missing: the reachability join refuses to classify "
            "without the reviewed baseline"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("unreachable") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise RuntimeError(f"{path} has no 'unreachable' list: malformed reachability baseline")
    return frozenset(str(entry) for entry in entries)


def _reviewed_dispositions(
    path: Path = REACHABILITY_DISPOSITIONS,
) -> dict[str, dict[str, str]]:
    """The reviewed CONNECT/LIBRARY/RETIRE group per unreachable identity."""
    if not path.exists():
        raise RuntimeError(
            f"{path} is missing: the reachability join refuses to classify "
            "without the reviewed dispositions"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    groups = payload.get("groups") if isinstance(payload, dict) else None
    if not isinstance(groups, list):
        raise RuntimeError(f"{path} has no 'groups' list: malformed reachability dispositions")
    reviewed: dict[str, dict[str, str]] = {}
    for group in groups:
        if not isinstance(group, dict):  # pragma: no cover - malformed, not expectation
            continue
        for module in group.get("modules", ()):
            reviewed[str(module)] = {
                "disposition": str(group.get("disposition", "")),
                "subsystem": str(group.get("subsystem", "")),
                "root": str(group.get("root", "")),
            }
    return reviewed


def classify(finding: EgressFinding, *, unreachable: frozenset[str]) -> str:
    """The current reachability disposition of one physical caller.

    Boundary recognition first (it is a design status, not a reachability
    fact), then the reviewed unreachable baseline, then the shipped-escape
    default. Derived from gated artifacts only, so no candidate edit can move
    a caller between classes.
    """
    if finding.module in APPROVED_PROVIDER_BOUNDARIES:
        return PROVIDER_BOUNDARY
    if finding.identity in unreachable:
        return UNREACHABLE_LIBRARY
    return REACHABLE_ESCAPE


def _report_rows(
    findings: dict[str, EgressFinding],
    *,
    unreachable: frozenset[str],
    reviewed: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """Sorted per-caller evidence rows for the report (stable output order)."""
    rows: list[dict[str, Any]] = []
    for module in sorted(findings):
        finding = findings[module]
        disposition = classify(finding, unreachable=unreachable)
        rows.append(
            {
                "module": finding.module,
                "identity": finding.identity,
                "disposition": disposition,
                "reviewed_disposition": reviewed.get(finding.identity),
                "sites": [
                    {
                        "path": site.path,
                        "qualname": site.qualname,
                        "line": site.line,
                        "callee": site.callee,
                        "entry_point": site.entry_point,
                    }
                    for site in finding.sites
                ],
            }
        )
    return rows


def _render_report(rows: list[dict[str, Any]]) -> list[str]:
    """The human-readable per-caller table: one line per caller and call site."""
    lines = ["physical model egress by caller:"]
    for row in rows:
        note = ""
        reviewed = row["reviewed_disposition"]
        if isinstance(reviewed, dict) and reviewed.get("disposition"):
            note = f" [reviewed {reviewed['disposition']} -- {reviewed['subsystem']}]"
        lines.append(f"  {row['disposition']} {row['module']}{note}")
        for site in row["sites"]:
            lines.append(
                f"    {site['path']}:{site['line']} in {site['qualname']}: "
                f"{site['callee']} ({site['entry_point']})"
            )
    counts = _counts(rows)
    lines.append(
        "reachability summary: "
        f"{counts[REACHABLE_ESCAPE]} reachable escape(s) awaiting #56 migration, "
        f"{counts[UNREACHABLE_LIBRARY]} unreachable library/diagnostic caller(s), "
        f"{counts[PROVIDER_BOUNDARY]} approved Provider boundary"
    )
    return lines


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {PROVIDER_BOUNDARY: 0, UNREACHABLE_LIBRARY: 0, REACHABLE_ESCAPE: 0}
    for row in rows:
        counts[str(row["disposition"])] += 1
    return counts


def _write_report(rows: list[dict[str, Any]], path: Path, candidate_sha: str | None) -> None:
    counts = _counts(rows)
    payload = {
        "ratchet": RATCHET,
        "metric_definition_version": METRIC_DEFINITION_VERSION,
        "candidate_sha": candidate_sha,
        "counts": {**counts, "total": len(rows)},
        "callers": rows,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def audit(recorded: set[str], found: set[str]) -> list[str]:
    failures: list[str] = []
    for module in sorted(found - recorded):
        failures.append(
            f"{module}: calls a model endpoint directly and is not in the inventory. "
            "The set of direct callers may not grow while #56 builds the one egress."
        )
    for module in sorted(recorded - found):
        failures.append(
            f"{module}: recorded as calling a model endpoint but no longer does; prune it "
            "so the inventory shrinks with the migration"
        )
    return failures


def _migration_predecessor(module: str, *, trusted: set[str], candidate: set[str]) -> str | None:
    """The trusted-base module whose egress moved into `module`, or None.

    The exception fires only when both ratchet halves stay intact: the
    predecessor performed direct egress in the trusted base (it is recorded
    there), and the candidate pruned it (it is absent from the candidate
    inventory -- the same requirement `candidate_stale` enforces). Any other
    shape -- no recorded predecessor, an unpruned predecessor, a module with
    no mapping at all -- is not a migration and still requires an
    already-landed authorization.
    """
    predecessor = CANDIDATE_MIGRATIONS.get(module)
    if predecessor is None:
        return None
    if predecessor not in trusted:
        return None
    if predecessor in candidate:
        return None
    return predecessor


def _modules(loaded: object) -> set[str]:
    if not isinstance(loaded, dict):
        return set()
    modules = loaded.get("modules")
    return {str(module) for module in modules} if isinstance(modules, list) else set()


def main(argv: list[str] | None = None) -> int:
    args = [str(arg) for arg in (sys.argv[1:] if argv is None else argv)]
    report: Path | None = None
    if "--report" in args:
        index = args.index("--report")
        if index + 1 >= len(args):
            print("FAIL: --report requires a destination path", file=sys.stderr)
            return 2
        report = Path(args[index + 1])

    if not INVENTORY.exists():
        print(f"FAIL: {INVENTORY} is missing", file=sys.stderr)
        return 1
    candidate = _modules(json.loads(INVENTORY.read_text()))
    findings = discover_sites()
    found = set(findings)

    prov = _provenance()
    try:
        trusted_ref = prov.resolve_baseline(INVENTORY, root=ROOT)
        trusted_payload = trusted_ref.loads(default={"modules": []})
        trusted = _modules(trusted_payload)
        prov.require_measurement(found, ratchet=RATCHET, what="direct model-egress modules")
        recorded_version = (
            trusted_payload.get("metric_definition_version")
            if isinstance(trusted_payload, dict)
            else None
        )
        prov.require_metric_version(
            METRIC_DEFINITION_VERSION,
            recorded=recorded_version,
            ratchet=RATCHET,
            baseline=trusted_ref,
        )
        authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    added = sorted(found - trusted)
    migrated = {
        module: predecessor
        for module in added
        if (predecessor := _migration_predecessor(module, trusted=trusted, candidate=candidate))
    }
    unauthorized = [
        module for module in added if module not in authorized and module not in migrated
    ]
    unbanked_authorized = [
        module for module in added if module in authorized and module not in candidate
    ]
    candidate_new = sorted(found - candidate)
    candidate_stale = sorted(candidate - found)

    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=trusted_ref,
            tool="python ast (direct-effect census)",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(trusted)} recorded direct callers",
            new_value=f"{len(found)} physical model callers",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(
                [f"{module}: {authorized[module]}" for module in added if module in authorized]
                + [
                    f"{module}: operator-approved migration from {predecessor} "
                    "(predecessor pruned from the candidate inventory; not an expansion)"
                    for module, predecessor in migrated.items()
                ]
            ),
        ).render()
    )

    rows = _report_rows(
        findings,
        unreachable=_unreachable_identities(),
        reviewed=_reviewed_dispositions(),
    )
    for line in _render_report(rows):
        print(line)
    if report is not None:
        _write_report(rows, report, prov.head_sha(ROOT))
        print(f"wrote {report} ({len(rows)} caller(s))")

    failures: list[str] = []
    failures.extend(
        f"{module}: NEW direct model egress is absent from the trusted base and has no "
        "already-landed authorization"
        for module in unauthorized
    )
    failures.extend(
        f"{module}: authorized expansion is not recorded in the candidate inventory"
        for module in unbanked_authorized
    )
    failures.extend(
        f"{module}: current direct caller is missing from the candidate inventory"
        for module in candidate_new
    )
    failures.extend(
        f"{module}: candidate inventory is stale; this module no longer performs direct egress"
        for module in candidate_stale
    )

    if failures:
        print("FAIL: the direct-model-egress inventory does not match trusted policy\n")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    counts = _counts(rows)
    print(
        f"OK: {len(found)} physical model caller(s) "
        f"({counts[REACHABLE_ESCAPE]} reachable escape(s), "
        f"{counts[UNREACHABLE_LIBRARY]} unreachable library/diagnostic, "
        f"{counts[PROVIDER_BOUNDARY]} approved Provider boundary), "
        "no candidate-approved expansion"
    )
    return check_direct_effects.main([])


if __name__ == "__main__":
    raise SystemExit(main())
