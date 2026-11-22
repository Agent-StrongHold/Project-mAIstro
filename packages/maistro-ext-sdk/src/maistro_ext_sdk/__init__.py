"""maistro-ext-sdk: the public MAIstro extension SDK (M9-A1, #949).

Standalone and installable out of tree: the only runtime dependency is
pydantic, and nothing here imports a ``maistro`` product module (enforced by
this package's own import-hygiene test). Extension authors depend on this
package; the product depends on the *contract* it publishes, never the other
way around (ADR-081226-034b: core discovers specialized behavior through
public extension contracts).

Two versions live here, on purpose:

- ``__version__`` — the package, in lockstep with the monorepo VERSION file
  (ADR-073126-c4e1).
- :func:`contract_version` — the extension manifest contract, versioned
  independently of the application.
"""

from __future__ import annotations

import importlib.metadata

from maistro_ext_sdk.contract import (
    EXTENSION_CONTRACT_VERSION,
    ContractVersion,
    contract_version,
)
from maistro_ext_sdk.manifest import (
    AuthorityError,
    DataAuthority,
    DependencyRef,
    EntrypointMetadata,
    ExtensionIdentity,
    ExtensionManifest,
    ExtensionManifestError,
    FilesystemAuthority,
    NetworkAuthority,
    SecretRequirement,
    validate_manifest,
)
from maistro_ext_sdk.validation import (
    MANIFEST_FILENAME,
    ValidatedExtension,
    manifest_from_dict,
    manifest_from_json,
    manifest_from_yaml,
    public_json_schema,
    validate_extension_dir,
)

__all__ = [
    "EXTENSION_CONTRACT_VERSION",
    "MANIFEST_FILENAME",
    "AuthorityError",
    "ContractVersion",
    "DataAuthority",
    "DependencyRef",
    "EntrypointMetadata",
    "ExtensionIdentity",
    "ExtensionManifest",
    "ExtensionManifestError",
    "FilesystemAuthority",
    "NetworkAuthority",
    "SecretRequirement",
    "ValidatedExtension",
    "contract_version",
    "manifest_from_dict",
    "manifest_from_json",
    "manifest_from_yaml",
    "public_json_schema",
    "validate_extension_dir",
    "validate_manifest",
]

# Single source of truth for version — read from installed package metadata.
# The lockstep fallback string is a bump_version.py site (ADR-073126-c4e1);
# it is the PACKAGE version. The extension CONTRACT version lives in
# contract.py and is deliberately not derived from it.
try:
    __version__ = importlib.metadata.version("maistro-ext-sdk")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover - editable/unbuilt checkout
    __version__ = "0.9.0-dev"
