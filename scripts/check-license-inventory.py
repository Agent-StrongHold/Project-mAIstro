#!/usr/bin/env python3
"""Build a license inventory from final-artifact SBOMs.

The dependency environment is not the shipped product.  This gate consumes
CycloneDX SBOMs made from each final image and each frontend filesystem, then
keeps the component identity and the license evidence together.  It refuses a
component with no license unless a legal reviewer has recorded a resolution in
``quality/license-policy.json``.  Copyleft is reported for legal review; it is
not silently treated as either compatible or prohibited.

Example::

    python scripts/check-license-inventory.py \
      --policy quality/license-policy.json \
      --sbom maistro-engine=sboms/maistro-engine.json \
      --artifact maistro-engine=ghcr.io/agent-stronghold/maistro-engine@sha256:... \
      --output license-inventory.json
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "quality" / "license-policy.json"

# SPDX identifiers and common Syft names.  This is intentionally conservative:
# an unfamiliar expression is reviewable rather than being guessed permissive.
COPYLEFT_RE = re.compile(
    r"(?:^|[- /])(?:a?gpl|gpl|lgpl|mpl|epl|cddl|eucdl|sspl|osl)(?:[- /]|$)|"
    r"(?:^|[- ])(?:gnu|mozilla public|eclipse public|common development)",
    re.IGNORECASE,
)


class InventoryError(Exception):
    """A malformed or legally incomplete inventory input."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise InventoryError(f"{path}: top-level JSON value must be an object")
    return value


def _parse_pairs(values: list[str], label: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise InventoryError(f"--{label} expects SURFACE=PATH, got {value!r}")
        surface, raw_path = value.split("=", 1)
        if not surface or not raw_path or surface in result:
            raise InventoryError(f"invalid or duplicate --{label} value: {value!r}")
        result[surface] = Path(raw_path)
    return result


def _parse_artifacts(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise InventoryError(f"--artifact expects SURFACE=REFERENCE, got {value!r}")
        surface, reference = value.split("=", 1)
        if not surface or not reference or surface in result:
            raise InventoryError(f"invalid or duplicate --artifact value: {value!r}")
        result[surface] = reference
    return result


def _policy_surfaces(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = policy.get("surfaces")
    if not isinstance(raw, list) or not raw:
        raise InventoryError("policy `surfaces` must be a non-empty list")
    surfaces: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("id", "")).strip():
            raise InventoryError("every policy surface needs an id")
        ident = str(item["id"])
        if ident in surfaces:
            raise InventoryError(f"policy has duplicate surface {ident!r}")
        for field in ("kind", "classification", "source"):
            if not str(item.get(field, "")).strip():
                raise InventoryError(f"policy surface {ident!r} needs {field}")
        surfaces[ident] = item
    return surfaces


def _check_dependency_classes(policy: dict[str, Any]) -> set[str]:
    classes = policy.get("dependency_classes")
    if not isinstance(classes, dict):
        raise InventoryError("policy `dependency_classes` must be an object")
    required = {
        "runtime-distribution",
        "build-only-tooling",
        "external-cli-invocation",
        "source-only-development",
    }
    missing = required - set(classes)
    if missing:
        raise InventoryError(f"policy is missing dependency classes: {', '.join(sorted(missing))}")
    for name in required:
        item = classes[name]
        if not isinstance(item, dict):
            raise InventoryError(f"dependency class {name!r} must be an object")
        for field in ("description", "evidence", "review_owner"):
            if not str(item.get(field, "")).strip():
                raise InventoryError(f"dependency class {name!r} needs {field}")
    return set(classes)


def _check_policy(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    classes = _check_dependency_classes(policy)
    surfaces = _policy_surfaces(policy)
    for item in surfaces.values():
        if item["classification"] not in classes:
            raise InventoryError(
                f"surface {item['id']!r} uses unknown class {item['classification']!r}"
            )
        source = ROOT / str(item["source"])
        if not source.exists():
            raise InventoryError(f"surface {item['id']!r}: source does not exist: {source}")
    coverage = policy.get("coverage")
    required_coverage = {
        "transitive-packages",
        "extras",
        "vendored-code",
        "os-packages",
        "fonts-and-assets",
        "npm-trees",
    }
    if not isinstance(coverage, list) or not required_coverage <= set(coverage):
        raise InventoryError(
            "policy coverage must name transitive-packages, extras, vendored-code, "
            "os-packages, fonts-and-assets, and npm-trees"
        )
    for item in surfaces.values():
        if item["kind"] == "frontend-bundle" and not str(item.get("asset_evidence", "")).strip():
            raise InventoryError(f"frontend surface {item['id']!r} needs asset_evidence")
    legal = policy.get("legal")
    if not isinstance(legal, dict):
        raise InventoryError("policy `legal` must be an object")
    if legal.get("unknown_license_action") != "fail":
        raise InventoryError("legal.unknown_license_action must be `fail`")
    if legal.get("copyleft_action") not in {"review", "block", "allow"}:
        raise InventoryError("legal.copyleft_action must be review, block, or allow")
    return surfaces


def _resolution(identity: str, resolutions: list[Any]) -> dict[str, Any] | None:
    matches: list[dict[str, Any]] = []
    for item in resolutions:
        if not isinstance(item, dict):
            continue
        pattern = str(item.get("identity", ""))
        if pattern and fnmatch.fnmatchcase(identity, pattern):
            matches.append(item)
    if len(matches) > 1:
        raise InventoryError(f"multiple reviewed resolutions match {identity!r}")
    if not matches:
        return None
    item = matches[0]
    for field in ("license", "reason", "owner", "reviewed_on"):
        if not str(item.get(field, "")).strip():
            raise InventoryError(f"reviewed resolution for {identity!r} needs {field}")
    return item


def _license_values(component: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for item in component.get("licenses", []):
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("expression"), str) and item["expression"].strip():
            values.append(item["expression"].strip())
        value = item.get("value")
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
        license_data = item.get("license")
        if isinstance(license_data, dict):
            for field in ("id", "name", "url"):
                value = license_data.get(field)
                if isinstance(value, str) and value.strip():
                    values.append(value.strip())
    # Some CycloneDX producers put an expression at component level.
    expression = component.get("licenseExpression")
    if isinstance(expression, str) and expression.strip():
        values.append(expression.strip())
    return list(dict.fromkeys(values))


def _component_identity(component: dict[str, Any]) -> str:
    purl = component.get("purl")
    if isinstance(purl, str) and purl.strip():
        return purl.strip()
    name = str(component.get("name", "")).strip()
    version = str(component.get("version", "")).strip()
    if name and version:
        return f"{name}@{version}"
    if name:
        return name
    raise InventoryError("SBOM component has no purl or name")


def _kind(licenses: list[str]) -> str:
    if not licenses:
        return "unknown"
    if any(COPYLEFT_RE.search(value) for value in licenses):
        return "copyleft"
    return "other"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _components_for_sbom(path: Path) -> list[dict[str, Any]]:
    document = _load_json(path)
    if document.get("bomFormat") != "CycloneDX":
        raise InventoryError(f"{path}: expected a CycloneDX SBOM")
    components = document.get("components", [])
    # CycloneDX omits `components` for a bundle containing only unrecognised
    # files (for example a minified asset directory). The companion npm-tree
    # surface carries package/license identities; the empty bundle SBOM still
    # proves that the final filesystem was scanned.
    if components is None:
        components = []
    if not isinstance(components, list):
        raise InventoryError(f"{path}: CycloneDX `components` must be a list")
    return [item for item in components if isinstance(item, dict)]


def _component_record(
    surface_id: str,
    component: dict[str, Any],
    resolutions: list[Any],
    unknown: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = _component_identity(component)
    bom_ref = str(component.get("bom-ref", "")).strip()
    if not bom_ref:
        raise InventoryError(f"{surface_id}: {identity} has no CycloneDX bom-ref")
    # A file component (such as package-lock.json) is SBOM provenance rather
    # than a separately licensed dependency. Keep it in the reconciliation
    # evidence, but state that legal metadata is not applicable instead of
    # mistaking the absence of a package license for unknown metadata.
    if component.get("type") == "file":
        record = {
            "bom_ref": bom_ref,
            "identity": identity,
            "name": component.get("name"),
            "version": component.get("version"),
            "purl": component.get("purl"),
            "licenses": [],
            "license_status": "not-applicable",
            "legal_class": "not-applicable",
            "review": None,
        }
        return record, {"component_ref": bom_ref, "identity": identity, "licenses": []}
    licenses = _license_values(component)
    reviewed = _resolution(identity, resolutions)
    status = "known"
    if not licenses:
        if reviewed is None:
            unknown.append(f"{surface_id}: {identity} ({bom_ref})")
            status = "unresolved"
        else:
            licenses = [str(reviewed["license"])]
            status = "reviewed"
    elif reviewed is not None:
        status = "reviewed"
    record = {
        "bom_ref": bom_ref,
        "identity": identity,
        "name": component.get("name"),
        "version": component.get("version"),
        "purl": component.get("purl"),
        "licenses": licenses,
        "license_status": status,
        "legal_class": _kind(licenses),
        "review": reviewed,
    }
    evidence = {
        "component_ref": bom_ref,
        "identity": identity,
        "licenses": licenses,
    }
    return record, evidence


def _inventory_surface(
    surface_id: str,
    surface: dict[str, Any],
    sbom_path: Path,
    artifacts: dict[str, str],
    resolutions: list[Any],
    unknown: list[str],
) -> dict[str, Any]:
    if not sbom_path.is_file():
        raise InventoryError(f"SBOM for {surface_id!r} does not exist: {sbom_path}")
    components: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    for component in _components_for_sbom(sbom_path):
        record, evidence_record = _component_record(surface_id, component, resolutions, unknown)
        if record["bom_ref"] in seen_refs:
            raise InventoryError(f"{surface_id}: duplicate bom-ref {record['bom_ref']!r}")
        seen_refs.add(record["bom_ref"])
        components.append(record)
        evidence.append(evidence_record)
    if {item["bom_ref"] for item in components} != {item["component_ref"] for item in evidence}:
        raise InventoryError(f"{surface_id}: SBOM components and license evidence diverge")
    for item in evidence:
        item["source_sbom"] = str(sbom_path)
    return {
        "id": surface_id,
        "kind": surface["kind"],
        "classification": surface["classification"],
        "source": surface["source"],
        "artifact": artifacts.get(surface_id),
        "sbom": {"path": str(sbom_path), "sha256": _sha256(sbom_path)},
        "components": components,
        "license_evidence": evidence,
    }


def build_inventory(
    policy: dict[str, Any],
    sboms: dict[str, Path],
    artifacts: dict[str, str] | None = None,
    only: set[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    all_surfaces = _check_policy(policy)
    artifacts = artifacts or {}
    if only is not None:
        unknown_surfaces = only - set(all_surfaces)
        if unknown_surfaces:
            raise InventoryError(
                f"--only names unknown policy surfaces: {', '.join(sorted(unknown_surfaces))}"
            )
        surfaces = {name: item for name, item in all_surfaces.items() if name in only}
    else:
        surfaces = all_surfaces
    resolutions = policy.get("reviewed_resolutions", [])
    if not isinstance(resolutions, list):
        raise InventoryError("policy `reviewed_resolutions` must be a list")
    missing = {name for name, item in surfaces.items() if item.get("required", True)} - set(sboms)
    if missing:
        raise InventoryError(f"missing required SBOM surfaces: {', '.join(sorted(missing))}")
    unexpected = set(sboms) - set(surfaces)
    if unexpected:
        raise InventoryError(f"SBOM has no policy surface: {', '.join(sorted(unexpected))}")

    unknown: list[str] = []
    output_surfaces = [
        _inventory_surface(
            surface_id, surfaces[surface_id], sboms[surface_id], artifacts, resolutions, unknown
        )
        for surface_id in sorted(sboms)
    ]
    inventory = {
        "schema_version": 1,
        "policy": {
            "path": str(DEFAULT_POLICY.relative_to(ROOT)),
            "unknown_license_action": policy["legal"]["unknown_license_action"],
            "copyleft_action": policy["legal"]["copyleft_action"],
        },
        "surfaces": output_surfaces,
        "unresolved": unknown,
    }
    return inventory, unknown


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--sbom", action="append", default=[], metavar="SURFACE=PATH")
    parser.add_argument("--artifact", action="append", default=[], metavar="SURFACE=REFERENCE")
    parser.add_argument(
        "--only",
        action="append",
        default=None,
        metavar="SURFACE",
        help="limit this inventory to selected policy surfaces (for example published release images)",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        policy = _load_json(args.policy)
        sboms = _parse_pairs(args.sbom, "sbom")
        artifacts = _parse_artifacts(args.artifact)
        inventory, unknown = build_inventory(
            policy, sboms, artifacts, set(args.only) if args.only is not None else None
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except InventoryError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if unknown:
        print("FAIL: unknown or missing license metadata requires a reviewed resolution:")
        for item in unknown:
            print(f"  - {item}")
        return 1
    review = sum(
        1
        for surface in inventory["surfaces"]
        for component in surface["components"]
        if component["legal_class"] == "copyleft"
    )
    action = inventory["policy"]["copyleft_action"]
    print(
        f"OK: inventoried {len(inventory['surfaces'])} surface(s), "
        f"{sum(len(s['components']) for s in inventory['surfaces'])} component(s); "
        f"copyleft={review} (policy={action})"
    )
    if review and action == "block":
        print("FAIL: copyleft components are blocked by the legal policy", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
