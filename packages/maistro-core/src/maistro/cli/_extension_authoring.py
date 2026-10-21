"""`maistro extension` — the authoring toolchain for extension developers.

The first command is `new` (M9-H1, #973): scaffold a complete, buildable,
out-of-tree extension package — manifest, family-shaped entrypoint, packaging
metadata, and self-contract tests — from the closed family vocabulary. Later
M9-H issues hang the rest of the authoring chain (test → validate → package →
sign) off the same group.

This group writes new projects; it is deliberately separate from
`maistro extensions`, which is the operator's read-only view of durable
install records — a scaffold command living there would break that promise.
The generated package imports nothing first-party: no repo-relative imports,
no product modules, no copied core source — the boundary
`scripts/check-extension-imports.py` enforces for every extension tree.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from rich.console import Console
from typer import Argument, Exit, Option, Typer

from maistro.extensions.scaffold import (
    FAMILIES,
    ScaffoldError,
    ScaffoldSpec,
    scaffold_project,
)

console = Console()
app = Typer(help="Scaffold and author extension packages (developer tooling).")


def _die(message: str) -> None:
    console.print(f"[red]{message}[/red]")
    raise Exit(code=1) from None


@app.command("new")
def extension_new(
    name: Annotated[str, Argument(help="Project name slug, e.g. 'my-weather-tool'.")],
    family: Annotated[
        str, Option(case_sensitive=False, help="Extension family (closed vocabulary).")
    ] = "tool",
    publisher: Annotated[
        str, Option(help="Publisher slug; the manifest id becomes 'publisher.name'.")
    ] = "example",
    target_dir: Annotated[
        Path | None, Option(help="Directory to create (default: ./NAME).")
    ] = None,
    title: Annotated[str | None, Option(help="Human-readable manifest title.")] = None,
    description: Annotated[str | None, Option(help="One-paragraph manifest description.")] = None,
    version: Annotated[str, Option(help="Initial MAJOR.MINOR.PATCH version.")] = "0.1.0",
    contract: Annotated[
        str, Option(help="Manifest-contract range; must pin exactly one major.")
    ] = ">=1.0.0,<2.0.0",
    force: Annotated[bool, Option(help="Write into a non-empty target directory.")] = False,
) -> None:
    """Scaffold an out-of-tree extension package: manifest, entrypoint, tests.

    The generated project builds and tests in a clean directory with zero
    dependencies — no MAIstro checkout, no product imports — and its manifest
    is validated against the documented public schema before anything is
    written. Family templates differ structurally: a tool ships a handler
    registry, a skill an instruction set, an mcp-gateway upstream server
    declarations, a capability-provider slot claims, a renderer-plugin
    artifact-kind renderers.
    """
    chosen = family.strip().lower()
    if chosen not in FAMILIES:
        _die(
            f"family '{family}' is not one of the closed families {list(FAMILIES)}; "
            "pass --family with one of them"
        )
    try:
        spec = ScaffoldSpec(
            name=name.strip(),
            publisher=publisher.strip(),
            family=chosen,
            version=version,
            contract=contract,
            title=title or "",
            description=description or "",
        )
        target = (target_dir or Path(".") / spec.name).resolve()
        written = scaffold_project(spec, target, force=force)
    except ScaffoldError as exc:
        _die(str(exc))
        return  # unreachable; keeps mypy's no-return path honest
    console.print(f"[green]Scaffolded {spec.manifest_id} ({spec.family}) in {target}[/green]")
    for path in sorted(written):
        console.print(f"  {path.relative_to(target)}")
    package = spec.package
    console.print()
    console.print("Next steps (all outside any MAIstro checkout):")
    console.print(f"  cd {target}")
    console.print("  uv build --wheel --out-dir dist")
    console.print(
        f"  uv venv .venv-isolated && uv pip install --python .venv-isolated/bin/python "
        f"dist/{package}-{spec.version}-py3-none-any.whl pytest"
    )
    console.print("  .venv-isolated/bin/python -m pytest tests -q")
    console.print()
    console.print(
        "Declare authority honestly in extension.json before you publish: "
        "capabilities, effects, and data scopes are closed vocabularies "
        "(docs/extensions/capabilities.md), and a host grants only what is declared."
    )
