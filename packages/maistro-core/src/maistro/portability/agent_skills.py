"""Inert Agent Skills directory portability, separate from legacy tool SKILL.md.

Agent Skills describes instructions/resources, not tool authorization. Parsing
never registers a skill, executes bundled scripts or creates a tool Binding.
The legacy maistro.skills.parser's parameter-bearing syntax is unaffected.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml
from yaml.events import AliasEvent

MAX_SKILL_BYTES = 256 * 1024
MAX_PACKAGE_BYTES = 8 * 1024 * 1024
MAX_PACKAGE_FILES = 256
_ALLOWED_FRONTMATTER = frozenset(
    {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
)


class AgentSkillValidationError(ValueError):
    """An Agent Skills bundle violates format or import safety constraints."""


class _StrictSkillLoader(yaml.SafeLoader):
    """Safe YAML with duplicate-key and alias rejection at the import edge."""

    def compose_node(self, parent: object, index: object) -> yaml.nodes.Node:
        if self.check_event(AliasEvent):
            raise AgentSkillValidationError("YAML aliases are not accepted")
        return super().compose_node(parent, index)

    def construct_mapping(self, node: yaml.nodes.MappingNode, deep: bool = False) -> dict:
        out: dict = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise AgentSkillValidationError("frontmatter keys must be strings")
            if key in out:
                raise AgentSkillValidationError(f"duplicate frontmatter key: {key}")
            out[key] = self.construct_object(value_node, deep=deep)
        return out


@dataclass(frozen=True)
class AgentSkillPackage:
    """Untrusted, inert file bundle. No runtime authority or internal tool name."""

    name: str
    description: str
    instructions: str
    files: tuple[tuple[str, bytes], ...]
    content_sha256: str
    license: str = ""
    compatibility: str = ""
    metadata: tuple[tuple[str, str], ...] = ()
    declared_allowed_tools: str = ""  # informational only; never a grant


def _valid_name(name: object) -> bool:
    if not isinstance(name, str) or not 1 <= len(name) <= 64:
        return False
    if name != unicodedata.normalize("NFKC", name) or name != name.lower():
        return False
    if name.startswith("-") or name.endswith("-") or "--" in name:
        return False
    return all(c.isalnum() or c == "-" for c in name)


def _parse_skill_md(raw: bytes, *, directory_name: str) -> tuple[dict, str]:
    if len(raw) > MAX_SKILL_BYTES:
        raise AgentSkillValidationError("SKILL.md exceeds size limit")
    try:
        source = raw.decode("utf-8").replace("\r\n", "\n")
    except UnicodeError as exc:
        raise AgentSkillValidationError("SKILL.md must be UTF-8") from exc
    if not source.startswith("---\n"):
        raise AgentSkillValidationError("SKILL.md must start with YAML frontmatter")
    separator = source.find("\n---\n", 4)
    closing_at_eof = separator == -1 and source.endswith("\n---")
    if separator == -1:
        if not closing_at_eof:
            raise AgentSkillValidationError("SKILL.md is missing the closing frontmatter delimiter")
        separator = len(source) - len("\n---")
    try:
        metadata = yaml.load(source[4:separator], Loader=_StrictSkillLoader)
    except yaml.YAMLError as exc:
        raise AgentSkillValidationError("invalid YAML frontmatter") from exc
    if not isinstance(metadata, dict):
        raise AgentSkillValidationError("frontmatter must be a mapping")
    unknown = set(metadata) - _ALLOWED_FRONTMATTER
    if unknown:
        raise AgentSkillValidationError("unknown Agent Skills frontmatter fields")
    name = metadata.get("name")
    if not _valid_name(name) or name != directory_name:
        raise AgentSkillValidationError("invalid skill name or directory/name mismatch")
    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise AgentSkillValidationError("description must be 1-1024 characters")
    for field, limit in (("license", 1024), ("compatibility", 500), ("allowed-tools", 4096)):
        value = metadata.get(field, "")
        if (not isinstance(value, str) or len(value) > limit or
                (field == "compatibility" and field in metadata and not value)):
            raise AgentSkillValidationError(f"invalid {field} metadata")
    extra = metadata.get("metadata", {})
    if not isinstance(extra, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in extra.items()
    ):
        raise AgentSkillValidationError("metadata must map strings to strings")
    return metadata, source[separator + (4 if closing_at_eof else 5) :]


def load_agent_skill_directory(directory: Path) -> AgentSkillPackage:
    """Inspect one standards-layout directory; do not admit it into the runtime.

    Rejects symlinks and caps bundled file count/size. Files are returned as
    inert bytes so export can round-trip without losing external identity.
    """
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise AgentSkillValidationError("skill directory missing or symlinked")
    skill_file = root / "SKILL.md"
    if skill_file.is_symlink() or not skill_file.is_file():
        raise AgentSkillValidationError("skill directory requires regular SKILL.md")
    files: list[tuple[str, bytes]] = []
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise AgentSkillValidationError("skill package cannot contain symlinks")
        if path.is_dir():
            continue
        if not path.is_file():
            raise AgentSkillValidationError("skill package contains a non-file resource")
        if len(files) >= MAX_PACKAGE_FILES:
            raise AgentSkillValidationError("skill package file count exceeds limit")
        size = path.stat().st_size
        if size > MAX_PACKAGE_BYTES or total_bytes + size > MAX_PACKAGE_BYTES:
            raise AgentSkillValidationError("skill package exceeds byte limit")
        data = path.read_bytes()
        total_bytes += len(data)
        if total_bytes > MAX_PACKAGE_BYTES:
            raise AgentSkillValidationError("skill package exceeds byte limit")
        files.append((path.relative_to(root).as_posix(), data))
    file_map = dict(files)
    if "SKILL.md" not in file_map:
        raise AgentSkillValidationError("SKILL.md not found")
    front, body = _parse_skill_md(file_map["SKILL.md"], directory_name=root.name)
    digest = hashlib.sha256()
    for relative_path, data in files:
        digest.update(len(relative_path.encode()).to_bytes(4, "big"))
        digest.update(relative_path.encode())
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return AgentSkillPackage(
        name=front["name"],
        description=front["description"],
        instructions=body,
        files=tuple(files),
        content_sha256=digest.hexdigest(),
        license=front.get("license", ""),
        compatibility=front.get("compatibility", ""),
        metadata=tuple(sorted(front.get("metadata", {}).items())),
        declared_allowed_tools=front.get("allowed-tools", ""),
    )


def export_agent_skill_directory(package: AgentSkillPackage, destination: Path) -> Path:
    """Write a fresh, non-overwriting external package to destination/name.

    The bundle is not trusted just because it came from a parsed object. Validate
    the paths and bytes again before writing; never execute bundled scripts.
    """
    if not _valid_name(package.name) or not package.files:
        raise AgentSkillValidationError("invalid export package")
    if len(package.files) > MAX_PACKAGE_FILES or sum(len(data) for _, data in package.files) > MAX_PACKAGE_BYTES:
        raise AgentSkillValidationError("export package exceeds resource bounds")
    if len(dict(package.files).get("SKILL.md", b"")) > MAX_SKILL_BYTES:
        raise AgentSkillValidationError("export SKILL.md exceeds size limit")
    filenames: set[str] = set()
    for relative, _data in package.files:
        path = Path(relative)
        if (path.is_absolute() or not path.parts or
                any(part in ("..", ".") for part in path.parts) or
                "\\" in relative or path.as_posix() != relative or relative in filenames):
            raise AgentSkillValidationError("unsafe or duplicate bundle resource path")
        filenames.add(relative)
    if "SKILL.md" not in filenames:
        raise AgentSkillValidationError("bundle has no SKILL.md")
    _parse_skill_md(dict(package.files)["SKILL.md"], directory_name=package.name)
    base = Path(destination)
    if base.is_symlink() or not base.is_dir():
        raise AgentSkillValidationError("export parent missing or symlinked")
    target = base / package.name
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"skill export already exists: {package.name}")
    target.mkdir()
    for relative, data in package.files:
        out = target / relative
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    return target
