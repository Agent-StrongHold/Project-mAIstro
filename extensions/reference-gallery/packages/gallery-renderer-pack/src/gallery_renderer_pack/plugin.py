"""The gallery renderer pack's entrypoint module (renderer-plugin family, #980).

A UI pack: pure renderers over read-only product projections. A renderer
receives host-provided data and returns display text — it never mutates
state, never reaches the network, and never sees more than the
``workspace.read`` projection the host grants. This is the extension
family an external UI author ships; the runtime binds it to renderer
surfaces the same way every other family binds to its seam.
"""

from __future__ import annotations

from collections.abc import Callable

PLUGIN: dict[str, object] = {
    "kind": "renderer-plugin",
    "name": "gallery.renderer_pack",
    "version": "1.0.0",
    "capabilities": ["workspace.read"],
    "handlers": ["render_run_summary", "render_extension_badge"],
}

#: The renderer surfaces this pack claims, so a host can match declared
#: surfaces against the slots it actually offers.
SURFACES: tuple[str, ...] = ("run-summary", "extension-badge")


def render_run_summary(run: dict[str, object]) -> str:
    """Render the read-only Run projection into a display summary.

    Pure formatting over host-provided data. Absent fields render as
    "unknown" — a renderer shows what it was given, it never fabricates.
    """
    name = run.get("name") if isinstance(run.get("name"), str) else "unknown"
    state = run.get("state") if isinstance(run.get("state"), str) else "unknown"
    nodes = run.get("node_count")
    node_part = f", {nodes} nodes" if isinstance(nodes, int) and not isinstance(nodes, bool) else ""
    return f"Run {name!r} — {state}{node_part}"


def render_extension_badge(extension: dict[str, object]) -> str:
    """Render an installed extension's identity into a badge line."""
    name = extension.get("name") if isinstance(extension.get("name"), str) else "unknown"
    version = extension.get("version") if isinstance(extension.get("version"), str) else "unknown"
    publisher = (
        extension.get("publisher") if isinstance(extension.get("publisher"), str) else "unknown"
    )
    return f"[{name} v{version} by {publisher}]"


HANDLERS: dict[str, Callable[[dict[str, object]], str]] = {
    "render_run_summary": render_run_summary,
    "render_extension_badge": render_extension_badge,
}
