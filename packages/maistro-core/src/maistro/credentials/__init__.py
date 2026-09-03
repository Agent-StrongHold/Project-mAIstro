"""Per-user encrypted credentials for PM integrations."""

from maistro.credentials.providers import PM_CREDENTIAL_PROVIDERS, CredentialProvider, get_provider
from maistro.credentials.router import (
    CredentialRouter,
    CredentialScopeError,
    cooldown_for_failure,
)
from maistro.credentials.store import (
    CredentialNotFound,
    CredentialStoreError,
    CredentialStoreUnavailable,
    MasterKeyRotationResult,
    UserCredentialStore,
    generate_master_key,
    repair_interrupted_rotation,
)

__all__ = [
    "PM_CREDENTIAL_PROVIDERS",
    "CredentialNotFound",
    "CredentialProvider",
    "CredentialRouter",
    "CredentialScopeError",
    "CredentialStoreError",
    "CredentialStoreUnavailable",
    "MasterKeyRotationResult",
    "UserCredentialStore",
    "cooldown_for_failure",
    "generate_master_key",
    "get_provider",
    "repair_interrupted_rotation",
]
