"""The SDK's own console entry point: validate and scaffold without this repo.

``maistro-ext-sdk validate <dir>`` runs the same no-import validation the
library exposes, from any shell — the author-facing face of "manifest can be
parsed and rejected before importing extension code".
``maistro-ext-sdk new`` scaffolds a complete, valid, buildable extension
project (M9-H1, #973). This module is also the reachability root for the SDK
inside the monorepo graph (the ``maistro_registry.cli`` precedent for a
standalone package's CLI entry).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from maistro_ext_sdk import (
    ExtensionManifestError,
    contract_version,
    public_json_schema,
    validate_extension_dir,
)
from maistro_ext_sdk.scaffold import SCAFFOLD_FAMILIES, ScaffoldError, scaffold_extension

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="maistro-ext-sdk",
        description=(
            "Validate a MAIstro extension package against the extension SDK "
            "(no extension code is imported during validation)."
        ),
    )
    parser.add_argument(
        "--contract-version",
        action="store_true",
        help="print the extension contract version this SDK publishes and exit",
    )
    sub = parser.add_subparsers(dest="command")

    validate = sub.add_parser(
        "validate", help="validate an extension package directory; exit 0 iff it validates"
    )
    validate.add_argument("directory", help="extension package directory carrying extension.json")

    schema = sub.add_parser("schema", help="print the manifest JSON Schema (2020-12)")
    schema.add_argument("--out", default="-", help="output file for the schema (default: stdout)")

    new = sub.add_parser(
        "new",
        help="scaffold a new extension project (buildable and validatable out of tree)",
    )
    new.add_argument("name", help="extension name slug; the id becomes <publisher>.<name>")
    new.add_argument(
        "--publisher",
        required=True,
        help="publisher slug; must match the id's first segment",
    )
    new.add_argument(
        "--family",
        choices=SCAFFOLD_FAMILIES,
        default="tool",
        help="extension family template (default: tool)",
    )
    new.add_argument(
        "--out",
        type=Path,
        default=None,
        help="target directory (default: ./<publisher>-<name>)",
    )
    new.add_argument("--version", default="0.1.0", help="extension version (default: 0.1.0)")
    new.add_argument(
        "--title", default=None, help="single-line human-readable title (default: derived)"
    )
    new.add_argument(
        "--description",
        default=None,
        help="single-line manifest description (default: derived)",
    )
    new.add_argument(
        "--force",
        action="store_true",
        help="write into an existing non-empty directory",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.contract_version:
        print(contract_version())
        return 0

    if args.command == "schema":
        schema = json.dumps(public_json_schema(), indent=2, sort_keys=True)
        if args.out == "-":
            print(schema)
        else:
            Path(args.out).write_text(schema + "\n", encoding="utf-8")
        return 0

    if args.command == "validate":
        try:
            ext = validate_extension_dir(args.directory)
        except ExtensionManifestError as exc:
            print(f"REJECTED: {exc}", file=sys.stderr)
            return 1
        print(
            json.dumps(
                {
                    "id": ext.manifest.id,
                    "version": ext.manifest.version,
                    "family": ext.manifest.family,
                    "contract": ext.manifest.contract,
                    "entrypoint": ext.entrypoint_target(),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "new":
        try:
            root = scaffold_extension(
                name=args.name,
                publisher=args.publisher,
                family=args.family,
                out_dir=args.out,
                version=args.version,
                title=args.title,
                description=args.description,
                force=args.force,
            )
        except ScaffoldError as exc:
            print(f"SCAFFOLD-REJECTED: {exc}", file=sys.stderr)
            return 1
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        print(
            json.dumps(
                {
                    "scaffolded": str(root),
                    "id": manifest["id"],
                    "family": manifest["family"],
                    "contract": manifest["contract"],
                    "entrypoint": manifest["entrypoint"]["module"],
                    "next": [
                        f"pip install -e {root}",
                        f"maistro-ext-sdk validate {root}",
                        f"maistro-ext-harness run --path {root}",
                    ],
                },
                indent=2,
            )
        )
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover - python -m convenience
    sys.exit(main())
