"""Deployment optional-module state (#2549).

Setup (``/v1/setup/complete``) persists the operator's ``optional_modules``
list into the durable setup record — the same record ``identity_health``
reads for ``crypto_identity``. This module is the one interpretive seam for
"gating a surface on one of those choices", so no consumer restates the
lookup against the setup record.

The raw store read lives in ``identity_health.setup_state`` — that module is
the retiring ``sessions`` store's ledger-listed consumer, and
``quality/workspace-retirement.json`` forbids a retiring surface from
gaining new ones, so gating code must read through that seam rather than
``import stores`` itself.

The first consumer is the UAT product direction in #2549: the PM-demo
heritage (the ``pm_fleet`` workspace persona and its Jira-first tooling) is
no longer a default, first-class surface. The persona moves behind the
explicit ``pm_tooling`` optional module — off by default, selected in the
setup wizard's module step exactly like ``crypto_identity`` — instead of
being offered in every workspace-creation dialog. Existing workspaces whose
``persona_template_id`` is already ``pm_fleet`` keep working: the gate is a
picker filter, never a resolution or membership check.
"""

from __future__ import annotations

from typing import Any

#: Persona templates an optional module gates. A template listed here is
#: hidden from the workspace-creation picker unless every gating module is
#: enabled. (A template may list under several modules; all must be on.)
PERSONA_MODULE_GATES: dict[str, frozenset[str]] = {
    "pm_tooling": frozenset({"pm_fleet"}),
}


def _setup_config() -> dict[str, Any] | None:
    """The setup record via ``identity_health.setup_state``, or ``None``.

    ``None`` covers both pre-setup (no record) and an unreadable store.
    """
    from services.identity_health import setup_state

    try:
        config = setup_state()
    except Exception:
        # An unreadable store hides the gated personas (fails closed) rather
        # than advertising a surface the deployment did not choose.
        return None
    return config if isinstance(config, dict) else None


def enabled_modules() -> list[str]:
    """The ``optional_modules`` list setup persisted, or [] before setup."""
    config = _setup_config()
    if config is None:
        return []
    modules = config.get("optional_modules")
    if not isinstance(modules, list):
        return []
    return [m for m in modules if isinstance(m, str)]


def module_enabled(module: str) -> bool:
    return module in enabled_modules()


def picker_hidden_template_ids() -> frozenset[str]:
    """Template ids the workspace-creation picker must not offer."""
    hidden: set[str] = set()
    for module, template_ids in PERSONA_MODULE_GATES.items():
        if not module_enabled(module):
            hidden |= template_ids
    return frozenset(hidden)
