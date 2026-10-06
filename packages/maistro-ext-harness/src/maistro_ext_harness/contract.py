"""Public contract constants for the extension host harness (#974).

The harness validates and loads extensions against the **manifest contract**
documented in the repository's extension guides (`docs/extensions/
manifest-reference.md`): the versioned schema `extension.json` is written
against. The contract versions independently of the harness's own release
version — exactly the rule the M9 epic pins for the SDK package (`maistro-ext-sdk`,
M9-A1, #949, pending merge at the time this harness landed).

Reconciliation, recorded here so it is findable: the normative manifest
schema is code in the SDK package. Until that package merges, this module is
the harness's statement of contract 1.0.0 — the same contract the merged
reference extension (`extensions/reference-greeter`) pins as
`>=1.0.0,<2.0.0` — and the harness's tests validate the real reference
manifest to hold the two statements together. When the SDK package lands,
`maistro_ext_harness.manifest` becomes its delegation point rather than a
second schema authority.
"""

from __future__ import annotations

#: The manifest-contract major this harness enforces, as `MAJOR.MINOR.PATCH`.
#: A manifest whose contract range does not pin exactly this major is
#: rejected before any extension code loads — a host that rejects a manifest
#: names the contract version it enforces so an author can tell "malformed
#: manifest" from "manifest predates this host".
CONTRACT_VERSION = "1.0.0"

#: Contract major(s) this harness accepts. One entry: contract 1.x. A second
#: major appears here only when its schema lands behind a supported-majors
#: gate, never as a silent reinterpretation of old documents.
SUPPORTED_CONTRACT_MAJORS: tuple[int, ...] = (1,)

#: Version of the machine-readable report this harness emits. Bumped only for
#: a breaking change to the report's own shape; consumers parse it, so it
#: moves on its own schedule.
REPORT_SCHEMA = "maistro-ext-harness/report@1"

#: The closed extension families. An unknown family is a validation error,
#: never an ignored line — a misspelled family name must not quietly become
#: an unconformed extension.
FAMILIES: tuple[str, ...] = (
    "tool",
    "skill",
    "mcp-gateway",
    "capability-provider",
    "renderer-plugin",
)

#: The closed capability vocabulary — what a manifest may declare and what a
#: host may grant. Grant ⊆ declaration ⊆ vocabulary, in that order.
CAPABILITIES: tuple[str, ...] = (
    "workspace.read",
    "workspace.write",
    "agent.read",
    "run.read",
    "memory.read",
    "memory.write",
    "tool.invoke",
    "network.outbound",
    "filesystem.read",
    "filesystem.write",
    "secrets.read",
)

#: The closed effects vocabulary (reversibility classes, ADR-050 taxonomy).
EFFECTS: tuple[str, ...] = (
    "read-only",
    "mutating",
    "external-side-effect",
    "irreversible",
)

#: The closed data-scope vocabulary. Coarse by design; row-level scope is the
#: host's grant-time decision, not the manifest's.
DATA_SCOPES: tuple[str, ...] = (
    "workspace",
    "agent",
    "run",
    "memory",
    "messages",
    "artifacts",
)


class ContractError(RuntimeError):
    """Base class for every public-contract failure the harness raises."""
