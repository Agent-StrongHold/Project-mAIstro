"""Skill loader: filesystem -> SkillDefinition -> ToolDefinition.

Loads SKILL.md files from a directory, parses them, and merges
into the tool registry. Config-defined tools take priority over
skills (skills don't override existing tool names).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from maistro.skills.parser import parse_skill_file, security_scan
from maistro.types.tool import ToolDefinition

if TYPE_CHECKING:
    from maistro.types.skill import SkillDefinition

logger = logging.getLogger("maistro.skills.loader")


class FilesystemSkillLoader:
    """Loads skills from a directory of SKILL.md files."""

    def __init__(self, skills_dir: Path) -> None:
        self._skills_dir = skills_dir

    def _load_one(self, path: Path) -> SkillDefinition | None:
        """Load a single SKILL.md file: symlink guard, read, scan, parse.

        Every skill file is security-scanned before being made available —
        loading from disk is a trust boundary just like marketplace install.
        """
        if path.is_symlink():
            logger.warning("Skipping symlink in skills dir: %s", path)
            return None
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("Cannot read skill file: %s", path)
            return None

        safe, findings = security_scan(content)
        if not safe:
            logger.warning(
                "Skipping skill file (failed security scan): %s (%s)",
                path,
                ", ".join(f for f in findings if f.startswith("CRITICAL:")),
            )
            return None

        skill = parse_skill_file(content, source=str(path))
        if skill is None:
            logger.warning("Invalid skill file (parse failed): %s", path)
            return None

        return skill

    def load_all(self) -> list[SkillDefinition]:
        """Load all *.md files from the skills directory."""
        if not self._skills_dir.is_dir():
            logger.debug("Skills directory %s does not exist", self._skills_dir)
            return []

        skills: list[SkillDefinition] = []
        for path in sorted(self._skills_dir.glob("*.md")):
            skill = self._load_one(path)
            if skill is not None:
                skills.append(skill)
                logger.debug("Loaded skill: %s from %s", skill.name, path.name)

        community_dir = self._skills_dir / "community"
        if community_dir.is_dir():
            for path in sorted(community_dir.glob("*.md")):
                skill = self._load_one(path)
                if skill is not None:
                    skills.append(skill)

        logger.info("Loaded %d skills from %s", len(skills), self._skills_dir)
        return skills

    def merge_into_tools(
        self,
        skills: list[SkillDefinition],
        existing_tools: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        """Merge skill-defined tools into the tool list.

        Config-defined tools take priority.
        """
        existing_names = {t.name for t in existing_tools}
        merged = list(existing_tools)

        for skill in skills:
            if skill.name in existing_names:
                logger.debug(
                    "Skill '%s' skipped (tool already exists)",
                    skill.name,
                )
                continue

            tool = ToolDefinition(
                name=skill.name,
                description=skill.description,
                parameters=skill.parameters,
                groups=skill.groups,
                endpoint=skill.endpoint,
                auth_key_env=skill.auth_key_env,
            )
            merged.append(tool)
            existing_names.add(skill.name)

        return merged
