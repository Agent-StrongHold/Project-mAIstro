"""`maistro portability` subcommand — foreign-format agent/skill import/export.

The CLI face of ADR-101 §3 ("import wide, export narrow") and
SPEC-070226-c4f8 §3-4. The adapters themselves live in `maistro.portability`;
until this subcommand existed they were reachable only from their own tests —
the reachability gate counted all four modules unreachable, and the
disposition ledger named exactly this root ("a maistro.cli export/import
subcommand") as the wiring they waited on (#34 tranche, #62).

Read-only towards the Conductor API: these commands convert files the user
names and write only where the user points them, so the CLI keeps its
no-local-lifecycle shape — there is no store behind this subcommand.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table
from typer import Typer

from maistro.agents.catalog import AgentCard
from maistro.portability import (
    AgentImporterRegistry,
    SkillImporterRegistry,
    export_agent,
)
from maistro.types.skill import SkillDefinition

console = Console()
#: ``stderr=True`` (not ``file=sys.stderr``): the stream resolves at print time,
# so runners that redirect ``sys.stderr`` — CliRunner in the tests — capture it.
err_console = Console(stderr=True)
app = Typer(help="Import foreign agent/skill definitions; export to MCP manifest + SKILL.md.")

_agent_importers = AgentImporterRegistry()
_skill_importers = SkillImporterRegistry()


def _read_source(
    source: Annotated[Path, typer.Argument(help="File to read, or `-` for stdin.")],
) -> str:
    """Read the source document as text; JSON detection happens in the adapters."""
    try:
        if str(source) == "-":
            return sys.stdin.read()
        return source.read_text(encoding="utf-8")
    except OSError as exc:
        err_console.print(f"[red]cannot read {source}: {exc.strerror or exc}[/red]")
        raise typer.Exit(1) from exc


def _write_or_print(output: Path | None, payload: str) -> None:
    if output is None:
        # Raw echo, not rich: a machine-readable payload must not be word-wrapped
        # to the console width.
        typer.echo(payload)
        return
    try:
        output.write_text(payload, encoding="utf-8")
    except OSError as exc:
        err_console.print(f"[red]cannot write {output}: {exc.strerror or exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"wrote [bold]{output}[/bold]")


@app.command("formats")
def formats() -> None:
    """List the foreign formats the importers detect."""
    table = Table("kind", "format")
    for name in _agent_importers.formats():
        table.add_row("agent", name)
    for name in _skill_importers.formats():
        table.add_row("skill", name)
    console.print(table)


@app.command("import-agent")
def import_agent(
    source: Annotated[
        Path, typer.Argument(help="Foreign agent definition (file, or `-` for stdin).")
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the AgentCard JSON here instead of stdout."),
    ] = None,
) -> None:
    """Detect the foreign format and emit the imported AgentCard as JSON."""
    text = _read_source(source)
    card = _agent_importers.import_agent(text)
    if card is None:
        err_console.print(
            f"[red]no agent importer recognizes {source}.[/red] "
            f"Known formats: {', '.join(_agent_importers.formats())}"
        )
        raise typer.Exit(1)
    _write_or_print(output, json.dumps(dataclasses.asdict(card), indent=2))


@app.command("import-skills")
def import_skills(
    source: Annotated[
        Path, typer.Argument(help="SKILL.md or MCP manifest (file, or `-` for stdin).")
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the SkillDefinition JSON array here."),
    ] = None,
) -> None:
    """Detect the skill format and emit the imported SkillDefinitions as JSON."""
    text = _read_source(source)
    if not _skill_importers.detect(text):
        err_console.print(
            f"[red]no skill importer recognizes {source}.[/red] "
            f"Known formats: {', '.join(_skill_importers.formats())}"
        )
        raise typer.Exit(1)
    skills = _skill_importers.import_skills(text)
    payload = json.dumps([dataclasses.asdict(skill) for skill in skills], indent=2)
    _write_or_print(output, payload)


def _required_fields(cls: type) -> list[str]:
    """Dataclass fields with neither a default nor a default_factory."""
    return [
        field.name
        for field in dataclasses.fields(cls)
        if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
    ]


def _agent_from_json(data: dict[str, Any]) -> AgentCard:
    """Build an AgentCard from parsed JSON, naming rejected keys."""
    known = {field.name for field in dataclasses.fields(AgentCard)}
    unknown = sorted(set(data) - known)
    if unknown:
        err_console.print(
            f"[red]unknown AgentCard field(s): {', '.join(unknown)}.[/red] "
            f"Accepted fields: {', '.join(sorted(known))}"
        )
        raise typer.Exit(1)
    missing = [name for name in _required_fields(AgentCard) if name not in data]
    if missing:
        err_console.print(f"[red]missing required AgentCard field(s): {', '.join(missing)}[/red]")
        raise typer.Exit(1)
    return AgentCard(**data)


def _skills_from_json(data: Any) -> list[SkillDefinition]:
    if not isinstance(data, list):
        err_console.print("[red]skills file must be a JSON array of SkillDefinition objects.[/red]")
        raise typer.Exit(1)
    known = {field.name for field in dataclasses.fields(SkillDefinition)}
    skills: list[SkillDefinition] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            err_console.print(f"[red]skills[{index}] is not a JSON object.[/red]")
            raise typer.Exit(1)
        unknown = sorted(set(item) - known)
        if unknown:
            err_console.print(
                f"[red]skills[{index}] has unknown SkillDefinition field(s): "
                f"{', '.join(unknown)}[/red]"
            )
            raise typer.Exit(1)
        missing = [name for name in _required_fields(SkillDefinition) if name not in item]
        if missing:
            err_console.print(
                f"[red]skills[{index}] is missing required field(s): {', '.join(missing)}[/red]"
            )
            raise typer.Exit(1)
        skills.append(SkillDefinition(**item))
    return skills


@app.command("export")
def export(
    agent_json: Annotated[Path, typer.Argument(help="AgentCard JSON file (or `-` for stdin).")],
    skills_json: Annotated[
        Path | None,
        typer.Option("--skills", "-s", help="Optional JSON array of SkillDefinitions to expose."),
    ] = None,
    out_dir: Annotated[
        Path,
        typer.Option("--out-dir", "-d", help="Directory to write the bundle into."),
    ] = Path("."),
) -> None:
    """Export an agent as an MCP manifest plus SKILL.md (the one export target)."""
    text = _read_source(agent_json)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        err_console.print(f"[red]{agent_json} is not valid JSON: {exc}[/red]")
        raise typer.Exit(1) from exc
    if not isinstance(data, dict):
        err_console.print(f"[red]{agent_json} must contain a JSON object.[/red]")
        raise typer.Exit(1)
    agent = _agent_from_json(data)

    skills: list[SkillDefinition] = []
    if skills_json is not None:
        try:
            skill_data = json.loads(_read_source(skills_json))
        except json.JSONDecodeError as exc:
            err_console.print(f"[red]{skills_json} is not valid JSON: {exc}[/red]")
            raise typer.Exit(1) from exc
        skills = _skills_from_json(skill_data)

    bundle = export_agent(agent, skills)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = out_dir / "mcp-manifest.json"
        skill_path = out_dir / "SKILL.md"
        manifest_path.write_text(json.dumps(bundle.mcp_manifest, indent=2), encoding="utf-8")
        skill_path.write_text(bundle.skill_md, encoding="utf-8")
    except OSError as exc:
        err_console.print(f"[red]cannot write bundle: {exc.strerror or exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"wrote [bold]{manifest_path}[/bold] and [bold]{skill_path}[/bold]")
