"""Secure product wiring for OIDC login through Hive's existing session model."""

from __future__ import annotations

import base64
import hmac
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import httpx
import stores
from config import (
    OAuthProviderSettings,
    Settings,
    get_settings,
    is_valid_oauth_provider_name,
)
from models.schemas import HiveUser
from routes.audit import log_audit

from maistro.auth.entra import build_entra_provider_config
from maistro.auth.oauth import (
    IdentityLinker,
    InMemoryStateStore,
    OAuth2Client,
    OAuthError,
    OAuthExchange,
    OAuthExchangeError,
    OAuthProviderConfig,
    OAuthStateError,
    OAuthTokenValidationError,
    StateStore,
    complete_login,
)
from maistro.http import get_shared_client
from services.entra_oauth import ProductIdTokenVerifier
from services.model_store import JsonStore
from services.secrets import resolve_secret

OAUTH_CALLBACK_BASE_PATH = "/v1/auth/oauth"
OAUTH_STATE_COOKIE_PREFIX = "__Host-hive_oauth_state_"
OAUTH_STATE_TTL_SECONDS = 300
OAUTH_STATE_MAX_LENGTH = 256
OAUTH_MAX_PENDING_STATES = 1024

OAuthFailureStage = Literal[
    "browser_state",
    "configuration",
    "exchange",
    "identity",
    "provider",
    "state",
    "token_validation",
]
OAuthFailureReason = Literal[
    "inactive_user",
    "invalid",
    "link_conflict",
    "missing",
    "provider_rejected",
    "secret_unavailable",
    "unknown_provider",
    "unknown_user",
    "unlinked_identity",
]

_IDENTITY_LINK_LOCK = threading.RLock()


class IdentityLinkConflictError(Exception):
    """A link is corrupt or an existing identity would be overwritten."""


class OAuthClientSecretUnavailableError(Exception):
    """A configured confidential client has no resolvable vault secret."""


class OAuthLoginDenied(Exception):
    """Sanitized product failure safe to classify in an audit record."""

    def __init__(
        self,
        *,
        stage: OAuthFailureStage,
        reason: OAuthFailureReason,
        subject: str | None = None,
        local_user_id: str | None = None,
    ) -> None:
        super().__init__("OAuth authentication failed")
        self.stage = stage
        self.reason = reason
        self.subject = subject
        self.local_user_id = local_user_id


def oauth_callback_path(provider: str) -> str:
    return f"{OAUTH_CALLBACK_BASE_PATH}/{provider}/callback"


def oauth_state_cookie_name(provider: str) -> str:
    return f"{OAUTH_STATE_COOKIE_PREFIX}{provider}"


def _validate_link_component(value: str, *, name: str, max_length: int) -> str:
    if not value or len(value) > max_length or any(ord(char) < 32 for char in value):
        raise IdentityLinkConflictError(f"invalid {name}")
    return value


def _validate_provider_name(value: str) -> str:
    if not is_valid_oauth_provider_name(value):
        raise IdentityLinkConflictError("invalid provider")
    return value


def _identity_link_key(provider: str, subject: str) -> str:
    encoded = json.dumps(
        [provider, subject],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode("ascii")


class HiveIdentityLinkStore:
    """Conflict-safe identity links backed by Hive's selected JsonStore."""

    def __init__(self, store: JsonStore | None = None) -> None:
        self._store = store if store is not None else stores.oauth_identity_links

    @staticmethod
    def _local_user_id(record: object, provider: str, sub: str) -> str:
        local_user_id = record.get("local_user_id") if isinstance(record, dict) else None
        if (
            not isinstance(record, dict)
            or set(record) != {"provider", "subject", "local_user_id"}
            or record.get("provider") != provider
            or record.get("subject") != sub
            or not isinstance(local_user_id, str)
        ):
            raise IdentityLinkConflictError("identity link record is invalid")
        return local_user_id

    async def resolve(self, provider: str, sub: str) -> str | None:
        provider = _validate_provider_name(provider)
        sub = _validate_link_component(sub, name="subject", max_length=512)
        key = _identity_link_key(provider, sub)
        with _IDENTITY_LINK_LOCK:
            record = self._store.get(key)
            if record is None:
                return None
            return self._local_user_id(record, provider, sub)

    async def link(self, provider: str, sub: str, user_id: str) -> None:
        """Create an idempotent link; never overwrite a different local user."""
        provider = _validate_provider_name(provider)
        sub = _validate_link_component(sub, name="subject", max_length=512)
        user_id = _validate_link_component(user_id, name="local user id", max_length=128)
        key = _identity_link_key(provider, sub)

        # SECURITY-REVIEW: The provider subject is untrusted identity data.
        # The injective key and locked compare-before-write reject collisions.
        with _IDENTITY_LINK_LOCK:
            existing = self._store.get(key)
            if existing is not None:
                resolved = self._local_user_id(existing, provider, sub)
                if resolved != user_id:
                    raise IdentityLinkConflictError("identity is already linked")
                return
            user = stores.users.get(user_id)
            if user is None or not user.is_active:
                raise IdentityLinkConflictError("identity target must be an active local user")
            record = {
                "provider": provider,
                "subject": sub,
                "local_user_id": user_id,
            }
            if self._store.put_if_absent(key, record):
                log_audit(
                    "auth.oauth.link",
                    user_id,
                    target=provider,
                    detail={
                        "provider": provider,
                        "stage": "identity",
                        "reason": "linked",
                        "subject": sub,
                        "local_user_id": user_id,
                    },
                )
                return
            durable_winner = self._store.get(key)
            resolved = self._local_user_id(durable_winner, provider, sub)
            if resolved != user_id:
                raise IdentityLinkConflictError("identity is already linked")


@dataclass(frozen=True)
class OAuthLoginResult:
    user: HiveUser
    provider: str
    subject: str


class OAuthLoginService:
    """Bind core OAuth authentication to durable links and active Hive users."""

    def __init__(
        self,
        settings: Settings,
        *,
        http: httpx.AsyncClient | None = None,
        state_store: StateStore | None = None,
        link_store: HiveIdentityLinkStore | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not settings.oauth_providers or settings.oauth_public_origin is None:
            raise OAuthLoginDenied(stage="configuration", reason="missing")
        self._settings = settings
        self._provider_settings = dict(settings.oauth_providers)
        self._http = http or get_shared_client(
            timeout=10.0,
            follow_redirects=False,
        )
        self._owns_http = False
        self._states = (
            state_store
            if state_store is not None
            else InMemoryStateStore(
                clock=clock,
                max_entries=OAUTH_MAX_PENDING_STATES,
            )
        )
        self._links = link_store or HiveIdentityLinkStore()
        self._linker = IdentityLinker(store=self._links, open_registration=False)

        providers = {
            name: self._core_provider(name, provider)
            for name, provider in self._provider_settings.items()
        }
        # SECURITY-REVIEW: OAuth2Client performs external provider I/O through
        # maistro.http's guarded transport; provider URLs are also registered
        # with core's outbound allowlist and JWKS verification is mandatory.
        # ProductIdTokenVerifier preserves the generic JWKS path for ordinary
        # OIDC providers and adds only Entra's verified tid/oid normalization.
        self._client = OAuth2Client(
            providers=providers,
            state_store=self._states,
            http=self._http,
            secret_resolver=self._resolve_client_secret,
            id_token_verifier=ProductIdTokenVerifier(),
            state_ttl_seconds=OAUTH_STATE_TTL_SECONDS,
            clock=clock,
        )

    @staticmethod
    def _core_provider(name: str, provider: OAuthProviderSettings) -> OAuthProviderConfig:
        if provider.entra_tenant_id is not None:
            # Tenant-specific Microsoft v2 endpoints, derived from the one
            # admitted directory UUID. `common`/`organizations` never reach
            # here: settings validation rejects them as non-UUID tenants.
            return build_entra_provider_config(
                tenant_id=provider.entra_tenant_id,
                client_id=provider.client_id,
                scopes=provider.scopes,
                name=name,
            )
        return OAuthProviderConfig(
            name=name,
            authorization_url=provider.authorization_url,
            token_url=provider.token_url,
            client_id=provider.client_id,
            jwks_url=provider.jwks_url,
            userinfo_url=provider.userinfo_url,
            issuer=provider.issuer,
            scopes=provider.scopes,
            require_id_token=True,
        )

    def _provider(self, provider: str) -> OAuthProviderSettings:
        configured = self._provider_settings.get(provider)
        if configured is None:
            raise OAuthLoginDenied(stage="provider", reason="unknown_provider")
        return configured

    def _resolve_client_secret(self, provider: str) -> str | None:
        configured = self._provider(provider)
        vault_key = configured.client_secret_vault_key
        if vault_key is None:
            return None
        # SECURITY-REVIEW: Client secrets are resolved from the canonical vault
        # service for each exchange and are never retained on configuration.
        secret = resolve_secret(vault_key)
        if secret is None:
            raise OAuthClientSecretUnavailableError
        return secret

    def callback_uri(self, provider: str) -> str:
        self._provider(provider)
        origin = self._settings.oauth_public_origin
        if origin is None:
            raise OAuthLoginDenied(stage="configuration", reason="missing")
        return f"{origin}{oauth_callback_path(provider)}"

    @property
    def success_path(self) -> str:
        return self._settings.oauth_success_path

    async def start(self, provider: str) -> tuple[str, str]:
        redirect_uri = self.callback_uri(provider)
        try:
            return await self._client.authorize_url(provider, redirect_uri)
        except OAuthError as exc:
            raise OAuthLoginDenied(stage="provider", reason="unknown_provider") from exc

    async def authenticate(
        self,
        *,
        provider: str,
        code: str,
        state: str,
        browser_state: str | None,
    ) -> OAuthLoginResult:
        self._provider(provider)
        self._validate_browser_state(state, browser_state)

        user_id, exchange = await self._complete_login(provider, code, state)
        return self._resolve_active_user(provider, user_id, exchange)

    async def link_authenticated_user(
        self,
        *,
        provider: str,
        code: str,
        state: str,
        browser_state: str | None,
        user_id: str,
    ) -> OAuthLoginResult:
        """Explicitly link a verified provider identity to the current Hive user."""
        self._provider(provider)
        self._validate_browser_state(state, browser_state)
        try:
            exchange = await self._client.exchange_code(
                provider,
                code,
                state,
                self.callback_uri(provider),
            )
            await self._links.link(provider, exchange.identity.sub, user_id)
        except OAuthClientSecretUnavailableError as exc:
            raise OAuthLoginDenied(
                stage="configuration",
                reason="secret_unavailable",
            ) from exc
        except OAuthStateError as exc:
            raise OAuthLoginDenied(stage="state", reason="invalid") from exc
        except OAuthTokenValidationError as exc:
            raise OAuthLoginDenied(stage="token_validation", reason="invalid") from exc
        except OAuthExchangeError as exc:
            raise OAuthLoginDenied(stage="exchange", reason="provider_rejected") from exc
        except IdentityLinkConflictError as exc:
            raise OAuthLoginDenied(stage="identity", reason="link_conflict") from exc
        except OAuthError as exc:
            raise OAuthLoginDenied(stage="provider", reason="provider_rejected") from exc
        except Exception as exc:
            raise OAuthLoginDenied(stage="provider", reason="provider_rejected") from exc
        return self._resolve_active_user(provider, user_id, exchange)

    @staticmethod
    def _validate_browser_state(state: str, browser_state: str | None) -> None:
        if browser_state is None:
            raise OAuthLoginDenied(stage="browser_state", reason="missing")
        if len(state) > OAUTH_STATE_MAX_LENGTH or len(browser_state) > OAUTH_STATE_MAX_LENGTH:
            raise OAuthLoginDenied(stage="browser_state", reason="invalid")
        if not hmac.compare_digest(browser_state, state):
            raise OAuthLoginDenied(stage="browser_state", reason="invalid")

    async def consume_failed_callback(
        self,
        *,
        provider: str,
        state: str,
        browser_state: str | None,
    ) -> None:
        """Consume a browser-bound state when the provider returns an error."""
        self._provider(provider)
        self._validate_browser_state(state, browser_state)
        entry = await self._states.consume(state)
        if (
            entry is None
            or entry.provider != provider
            or entry.redirect_uri != self.callback_uri(provider)
        ):
            raise OAuthLoginDenied(stage="state", reason="invalid")

    async def _complete_login(
        self,
        provider: str,
        code: str,
        state: str,
    ) -> tuple[str | None, OAuthExchange]:
        try:
            return await complete_login(
                self._client,
                self._linker,
                provider=provider,
                code=code,
                state=state,
                redirect_uri=self.callback_uri(provider),
            )
        except OAuthClientSecretUnavailableError as exc:
            raise OAuthLoginDenied(
                stage="configuration",
                reason="secret_unavailable",
            ) from exc
        except OAuthStateError as exc:
            raise OAuthLoginDenied(stage="state", reason="invalid") from exc
        except OAuthTokenValidationError as exc:
            raise OAuthLoginDenied(stage="token_validation", reason="invalid") from exc
        except OAuthExchangeError as exc:
            raise OAuthLoginDenied(stage="exchange", reason="provider_rejected") from exc
        except IdentityLinkConflictError as exc:
            raise OAuthLoginDenied(stage="identity", reason="link_conflict") from exc
        except OAuthError as exc:
            raise OAuthLoginDenied(stage="provider", reason="provider_rejected") from exc
        except Exception as exc:
            raise OAuthLoginDenied(stage="provider", reason="provider_rejected") from exc

    @staticmethod
    def _resolve_active_user(
        provider: str,
        user_id: str | None,
        exchange: OAuthExchange,
    ) -> OAuthLoginResult:
        subject = exchange.identity.sub
        if user_id is None:
            raise OAuthLoginDenied(
                stage="identity",
                reason="unlinked_identity",
                subject=subject,
            )
        user = stores.users.get(user_id)
        if user is None:
            raise OAuthLoginDenied(
                stage="identity",
                reason="unknown_user",
                subject=subject,
                local_user_id=user_id,
            )
        if not user.is_active:
            raise OAuthLoginDenied(
                stage="identity",
                reason="inactive_user",
                subject=subject,
                local_user_id=user_id,
            )

        # The exchange's access/id/refresh tokens deliberately leave scope
        # here. Human login needs only the verified identity and Hive session.
        return OAuthLoginResult(user=user, provider=provider, subject=subject)

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()


_service: OAuthLoginService | None = None


def get_oauth_login_service() -> OAuthLoginService:
    global _service
    if _service is None:
        _service = OAuthLoginService(get_settings())
    return _service


async def close_oauth_login_service() -> None:
    global _service
    if _service is not None:
        await _service.close()
        _service = None
