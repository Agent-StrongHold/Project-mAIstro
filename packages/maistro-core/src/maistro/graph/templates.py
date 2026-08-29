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

from typing import Protocol, TypeVar, runtime_checkable

from maistro.graph.definitions import GraphTemplate, NodeTemplate

TemplateT = TypeVar("TemplateT", GraphTemplate, NodeTemplate)


def revalidated(template: TemplateT) -> TemplateT:
    """Re-run the model's own validators against what is about to be stored.

    A template's validators run at construction. Every content field is a
    mutable `dict` or `list`, so a template can be built valid and then edited
    into an invalid one with nothing to notice:

        template = GraphTemplate(nodes=[node], edges=[edge])   # validated
        template.nodes.clear()                                 # no validator runs
        await store.put(template)                              # persisted

    `validate_assignment` does not close this -- it fires on rebinding a field,
    not on mutating the object a field already points at. The boundary that can
    is the one where content stops being a local object and becomes a record:
    every `put` revalidates, so no store can hold content its own model would
    have refused.

    Deliberately re-running the *model's* validators rather than any specific
    rule, so a rule added to the model later is enforced here without this
    function learning about it (#556; the case that prompted it is
    SPEC-081226-bb3a R12, live execution state in template content).
    """
    return type(template).model_validate(template.model_dump())


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
        self._templates[key] = revalidated(template).model_copy(deep=True)
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


class NodeTemplateNotFound(KeyError):
    """No NodeTemplate of that id — or no such version of it — exists."""


class NodeTemplateConflict(ValueError):
    """A version of this NodeTemplate already exists with different content."""


@runtime_checkable
class NodeTemplateStore(Protocol):
    """The half of AC-12 that had no home (#556).

    `GraphTemplateStore` has existed since #145 in all three backends;
    `NodeTemplate` had none, so a NodeTemplate could not survive a restart and
    "a template and its instantiated object resolve the same provenance after a
    reopen" could hold for only one of the two template families.

    Identity is `(template_id, version)`, exactly as for GraphTemplate: the
    content hash excludes `template_id`, `workspace_id` and `version`, so two
    versions are one template with different content.
    """

    async def put(self, template: NodeTemplate) -> NodeTemplate: ...

    async def get(self, template_id: str, *, version: int | None = None) -> NodeTemplate | None: ...

    async def list_for_workspace(self, workspace_id: str) -> list[NodeTemplate]: ...

    async def versions(self, template_id: str) -> list[int]: ...


async def require_node_template(
    store: NodeTemplateStore,
    template_id: str,
    *,
    version: int | None = None,
) -> NodeTemplate:
    """Resolve a NodeTemplate or say precisely what was missing.

    The same two failures `require_template` distinguishes, for the same
    reason: "no such template" is a configuration mistake and "no such version"
    is usually a rollback that removed one.
    """
    template = await store.get(template_id, version=version)
    if template is not None:
        return template
    if version is None:
        raise NodeTemplateNotFound(f"no NodeTemplate {template_id!r} is registered")
    known = await store.versions(template_id)
    if not known:
        raise NodeTemplateNotFound(f"no NodeTemplate {template_id!r} is registered")
    raise NodeTemplateNotFound(
        f"NodeTemplate {template_id!r} has no version {version}; "
        f"registered versions: {', '.join(str(item) for item in known)}"
    )


class InMemoryNodeTemplateStore:
    """Process-local NodeTemplate registry. The contract the durable twins meet."""

    def __init__(self) -> None:
        self._templates: dict[tuple[str, int], NodeTemplate] = {}

    async def put(self, template: NodeTemplate) -> NodeTemplate:
        """Register one version. Re-registering identical content is a no-op.

        Refusing a redefinition rather than overwriting is the same rule
        GraphTemplate keeps, and for the same reason: a Node's
        `source_template` records the version and the hash it was built from,
        so redefining a version in place would make every object that cites it
        cite something it never came from. That is AC-7 -- publishing T@2
        leaves T@1 addressable and unchanged.
        """
        key = (template.template_id, template.version)
        existing = self._templates.get(key)
        if existing is not None and existing.content_hash != template.content_hash:
            raise NodeTemplateConflict(
                f"NodeTemplate {template.template_id!r} version {template.version} already "
                "exists with different content; register a new version instead"
            )
        self._templates[key] = revalidated(template).model_copy(deep=True)
        return template

    async def get(self, template_id: str, *, version: int | None = None) -> NodeTemplate | None:
        if version is not None:
            found = self._templates.get((template_id, version))
            return found.model_copy(deep=True) if found is not None else None
        known = await self.versions(template_id)
        if not known:
            return None
        return self._templates[(template_id, known[-1])].model_copy(deep=True)

    async def list_for_workspace(self, workspace_id: str) -> list[NodeTemplate]:
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
    "InMemoryNodeTemplateStore",
    "NodeTemplateConflict",
    "NodeTemplateNotFound",
    "NodeTemplateStore",
    "require_node_template",
    "require_template",
    "revalidated",
]
