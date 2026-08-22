"""Resolving a `graph_template_id` to the GraphTemplate it names (#145).

`GraphTemplate` and `GraphTemplate.instantiate` have existed since the graph
layer was written, and `Schedule.graph_template_id` has always been the field a
firing was supposed to resolve. Nothing ever resolved it, because there was
nowhere to look it up — which is the whole reason a schedule could not produce a
Run.

Identity is `(template_id, version)`, not `template_id` alone. `GraphTemplate`
already treats version as a separate axis: `_reusable_content` excludes
`template_id`, `workspace_id` and `version` from the content hash, so two
versions of one template are the same template with different topology, and
resolving without a version means "whatever is current".
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from maistro.graph.definitions import GraphTemplate


class GraphTemplateNotFound(KeyError):
    """No template of that id — or no such version of it — exists."""


class GraphTemplateConflict(ValueError):
    """A version of this template already exists with different content."""


@runtime_checkable
class GraphTemplateStore(Protocol):
    async def put(self, template: GraphTemplate) -> GraphTemplate: ...

    async def get(
        self, template_id: str, *, version: int | None = None
    ) -> GraphTemplate | None: ...

    async def list_for_workspace(self, workspace_id: str) -> list[GraphTemplate]: ...

    async def versions(self, template_id: str) -> list[int]: ...


async def require_template(
    store: GraphTemplateStore,
    template_id: str,
    *,
    version: int | None = None,
) -> GraphTemplate:
    """Resolve a template or say precisely what was missing.

    A schedule that names a template nobody registered must fail loudly at the
    fire, not produce a Run over an empty Graph. The two failures read
    differently on purpose — "no such template" is a configuration mistake,
    "no such version" is usually a rollback that removed one.
    """
    template = await store.get(template_id, version=version)
    if template is not None:
        return template
    if version is None:
        raise GraphTemplateNotFound(f"no GraphTemplate {template_id!r} is registered")
    known = await store.versions(template_id)
    if not known:
        raise GraphTemplateNotFound(f"no GraphTemplate {template_id!r} is registered")
    raise GraphTemplateNotFound(
        f"GraphTemplate {template_id!r} has no version {version}; "
        f"registered versions: {', '.join(str(item) for item in known)}"
    )


class InMemoryGraphTemplateStore:
    """Process-local template store. Tests, and any process with no database."""

    def __init__(self) -> None:
        self._templates: dict[tuple[str, int], GraphTemplate] = {}

    async def put(self, template: GraphTemplate) -> GraphTemplate:
        """Register one version. Re-registering identical content is a no-op.

        Re-registering *different* content under a version that already exists
        is refused rather than overwritten: a Run's `source_template` records
        the version and the content hash, so silently redefining a version
        would make every Run that already cited it cite something else.
        """
        key = (template.template_id, template.version)
        existing = self._templates.get(key)
        if existing is not None and existing.content_hash != template.content_hash:
            raise GraphTemplateConflict(
                f"GraphTemplate {template.template_id!r} version {template.version} already "
                "exists with different content; register a new version instead"
            )
        self._templates[key] = template.model_copy(deep=True)
        return template

    async def get(self, template_id: str, *, version: int | None = None) -> GraphTemplate | None:
        if version is not None:
            found = self._templates.get((template_id, version))
            return found.model_copy(deep=True) if found is not None else None
        known = await self.versions(template_id)
        if not known:
            return None
        latest = self._templates[(template_id, known[-1])]
        return latest.model_copy(deep=True)

    async def list_for_workspace(self, workspace_id: str) -> list[GraphTemplate]:
        found = [
            template.model_copy(deep=True)
            for template in self._templates.values()
            if template.workspace_id == workspace_id
        ]
        found.sort(key=lambda template: (template.name, template.template_id, template.version))
        return found

    async def versions(self, template_id: str) -> list[int]:
        return sorted(version for (found_id, version) in self._templates if found_id == template_id)


__all__ = [
    "GraphTemplateConflict",
    "GraphTemplateNotFound",
    "GraphTemplateStore",
    "InMemoryGraphTemplateStore",
    "require_template",
]
