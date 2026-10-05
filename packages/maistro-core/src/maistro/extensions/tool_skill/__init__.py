"""Canonical third-party tool and Skill contracts (M9-E3, issue #964).

The published host-side contract for out-of-tree ``tool`` and ``skill``
extension packages:

* :mod:`.contracts` — manifest parsing against the published closed
  vocabularies, and the host-owned capability/effect classification (the
  effect floor an extension cannot talk down at runtime).
* :mod:`.registration` — data-driven registration into the host tool catalog
  and Skill surface under Agent/Workspace allowlists and manifest
  permissions; the canonical ``extension.tool:*`` Binding factory.
* :mod:`.execution` — one governed dispatch path: every extension tool call
  crosses ``Capability -> Provider -> Binding -> Invocation``, producing
  canonical, attributable outcomes (results, errors, cancellation).
* :mod:`.conformance` — the shared protocol suite built-in and external tools
  both pass where semantics overlap.

Nothing here imports extension code during validation; entrypoint modules are
loaded by the host only after a manifest was accepted (data about the code
before the code — the M9-A3 posture this package extends to execution).
Operators inspect a package's contract and host classification with
``maistro extensions contract <manifest.json>``.
"""

from maistro.extensions.tool_skill.conformance import (
    DEFAULT_CHECKS,
    CheckResult,
    ConformanceReport,
    ConformantTool,
    run_conformance,
)
from maistro.extensions.tool_skill.contracts import (
    CAPABILITY_VOCABULARY,
    DATA_SCOPE_VOCABULARY,
    FAMILY_VOCABULARY,
    ContractError,
    EffectClass,
    EffectDowngradeRefused,
    EntrypointSpec,
    ExtensionContract,
    ExtensionFamily,
    ManifestContractError,
    SkillContract,
    SkillEntrypoint,
    ToolEntrypoint,
    effect_risk,
    highest_risk,
    max_effect,
    to_reversibility,
    validate_effect_claim,
)
from maistro.extensions.tool_skill.execution import (
    ERROR_CODE_APPROVAL,
    ERROR_CODE_CANCELLED,
    ERROR_CODE_DENIAL,
    ERROR_CODE_DOWNGRADE_REFUSED,
    ERROR_CODE_HANDLER_ERROR,
    ERROR_CODE_TIMEOUT,
    ERROR_CODE_UNAVAILABLE,
    ERROR_CODE_UNKNOWN,
    ExtensionToolCancellation,
    ExtensionToolOutcome,
    ExtensionToolRunner,
    UnknownToolError,
    effect_key_for,
    invoke_extension_tool,
)
from maistro.extensions.tool_skill.registration import (
    TOOL_CAPABILITY_PREFIX,
    ExtensionToolCatalog,
    RegistrationError,
    ToolAccessPolicy,
    ToolNotAllowlisted,
    TrustTierError,
    composition_denials,
    load_entrypoint_handler,
    register_extension_skill,
)

__all__ = [
    "CAPABILITY_VOCABULARY",
    "DATA_SCOPE_VOCABULARY",
    "DEFAULT_CHECKS",
    "ERROR_CODE_APPROVAL",
    "ERROR_CODE_CANCELLED",
    "ERROR_CODE_DENIAL",
    "ERROR_CODE_DOWNGRADE_REFUSED",
    "ERROR_CODE_HANDLER_ERROR",
    "ERROR_CODE_TIMEOUT",
    "ERROR_CODE_UNAVAILABLE",
    "ERROR_CODE_UNKNOWN",
    "FAMILY_VOCABULARY",
    "TOOL_CAPABILITY_PREFIX",
    "CheckResult",
    "ConformanceReport",
    "ConformantTool",
    "ContractError",
    "EffectClass",
    "EffectDowngradeRefused",
    "EntrypointSpec",
    "ExtensionContract",
    "ExtensionFamily",
    "ExtensionToolCancellation",
    "ExtensionToolCatalog",
    "ExtensionToolOutcome",
    "ExtensionToolRunner",
    "ManifestContractError",
    "RegistrationError",
    "SkillContract",
    "SkillEntrypoint",
    "ToolAccessPolicy",
    "ToolEntrypoint",
    "ToolNotAllowlisted",
    "TrustTierError",
    "UnknownToolError",
    "composition_denials",
    "effect_key_for",
    "effect_risk",
    "highest_risk",
    "invoke_extension_tool",
    "load_entrypoint_handler",
    "max_effect",
    "register_extension_skill",
    "run_conformance",
    "to_reversibility",
    "tool_capability",
    "validate_effect_claim",
]


def tool_capability(tool_id: str) -> str:
    """The canonical capability name for one registered third-party tool."""
    return f"{TOOL_CAPABILITY_PREFIX}:{tool_id}"
