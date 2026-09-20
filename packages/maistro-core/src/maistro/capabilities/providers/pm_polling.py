"""Jira and Airtable Providers for governed polling Invocations.

These Providers own the vendor HTTP protocols. Nodes only submit business
parameters through the canonical Binding/Invocation egress; credentials are
attached by CredentialRouting immediately before the Provider call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.credential_routing import CredentialBackedProvider
from maistro.capabilities.invocation import EffectNotApplied
from maistro.capabilities.types import Unavailable
from maistro.http import shared_client

JIRA_POLL_CAPABILITY = "jira.search"
JIRA_SUBTASKS_CAPABILITY = "jira.subtasks"
AIRTABLE_POLL_CAPABILITY = "airtable.records"


class JiraPollRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    jql: str
    max_results: int = Field(ge=1, le=100)
    fields: tuple[str, ...] = ()


class JiraSubtasksRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    parent_key: str


class AirtablePollRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base_id: str
    table: str
    since_iso: str | None = None
    sort_field: str = "Last modified time"
    sort_direction: str = "desc"
    page_size: int = Field(default=20, ge=1, le=100)


class PollingHttpError(RuntimeError):
    """An HTTP response that reached the remote provider."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class JiraProvider:
    base_url: str
    flavor: str
    email: str | None
    capability: str

    @property
    def name(self) -> str:
        return "jira"

    @property
    def slot(self) -> str:
        return self.capability

    @property
    def trust_tier(self) -> str:
        return "t2"

    @property
    def credential_provider(self) -> str:
        return "jira"


@dataclass(frozen=True)
class AirtableProvider:
    base_url: str

    @property
    def name(self) -> str:
        return "airtable"

    @property
    def slot(self) -> str:
        return AIRTABLE_POLL_CAPABILITY

    @property
    def trust_tier(self) -> str:
        return "t2"

    @property
    def credential_provider(self) -> str:
        return "airtable"


def _config_string(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    return value.strip() if isinstance(value, str) else ""


async def resolve_jira_provider(
    binding: Binding,
) -> ResolvedCapabilityProvider | Unavailable:
    if binding.provider_name and binding.provider_name != "jira":
        return _unavailable(
            binding, f"Binding pins unsupported Jira provider {binding.provider_name!r}"
        )
    base_url = _config_string(binding.config, "base_url")
    flavor = _config_string(binding.config, "flavor") or "server"
    if not base_url:
        return _unavailable(binding, "Jira Binding config requires base_url")
    if flavor not in {"server", "cloud"}:
        return _unavailable(binding, f"unsupported Jira flavor {flavor!r}")
    email = _config_string(binding.config, "email") or None
    return JiraProvider(
        base_url=base_url.rstrip("/"),
        flavor=flavor,
        email=email,
        capability=binding.capability,
    )


async def resolve_airtable_provider(
    binding: Binding,
) -> ResolvedCapabilityProvider | Unavailable:
    if binding.provider_name and binding.provider_name != "airtable":
        return _unavailable(
            binding, f"Binding pins unsupported Airtable provider {binding.provider_name!r}"
        )
    base_url = _config_string(binding.config, "base_url") or "https://api.airtable.com"
    return AirtableProvider(base_url=base_url.rstrip("/"))


def _unavailable(binding: Binding, reason: str) -> Unavailable:
    return Unavailable(slot=binding.capability, reason=reason)


def _provider_and_credential(provider: Any, expected: type) -> tuple[Any, str]:
    if not isinstance(provider, CredentialBackedProvider):
        raise TypeError("polling Provider must be credential-routed before execution")
    if not isinstance(provider.base, expected):
        raise TypeError(f"polling Provider has unexpected implementation {type(provider.base)!r}")
    return provider.base, provider.credential.api_key


async def execute_jira(
    provider: ResolvedCapabilityProvider,
    request: object,
    *,
    timeout_s: float,
) -> dict[str, Any]:
    base, secret = _provider_and_credential(provider, JiraProvider)
    if isinstance(request, JiraPollRequest):
        path = "/rest/api/2/search" if base.flavor == "server" else "/rest/api/3/search"
        params: dict[str, str | int] = {
            "jql": request.jql,
            "maxResults": request.max_results,
            "fields": ",".join(request.fields),
        }
    elif isinstance(request, JiraSubtasksRequest):
        path = (
            f"/rest/api/2/issue/{request.parent_key}"
            if base.flavor == "server"
            else f"/rest/api/3/issue/{request.parent_key}"
        )
        params = {"fields": "subtasks"}
    else:
        raise TypeError(f"Jira Invocation received foreign request {type(request)!r}")

    headers = {"Accept": "application/json"}
    auth: tuple[str, str] | None = None
    if base.flavor == "server" or base.email is None:
        headers["Authorization"] = f"Bearer {secret}"
    else:
        auth = (base.email, secret)

    try:
        async with shared_client(timeout=timeout_s) as client:
            response = await client.get(
                f"{base.base_url}{path}", params=params, headers=headers, auth=auth
            )
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise EffectNotApplied(f"Jira unreachable, no effect occurred: {exc}") from exc
    _raise_http_error("jira", response.status_code)
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("Jira returned a non-object response body")
    return body


async def execute_airtable(
    provider: ResolvedCapabilityProvider,
    request: object,
    *,
    timeout_s: float,
) -> dict[str, Any]:
    base, secret = _provider_and_credential(provider, AirtableProvider)
    if not isinstance(request, AirtablePollRequest):
        raise TypeError(f"Airtable Invocation received foreign request {type(request)!r}")
    params: dict[str, Any] = {
        "pageSize": request.page_size,
        "sort[0][field]": request.sort_field,
        "sort[0][direction]": request.sort_direction,
    }
    if request.since_iso:
        params["filterByFormula"] = f"IS_AFTER(LAST_MODIFIED_TIME(), '{request.since_iso}')"
    try:
        async with shared_client(timeout=timeout_s) as client:
            response = await client.get(
                f"{base.base_url}/v0/{request.base_id}/{request.table}",
                headers={"Authorization": f"Bearer {secret}"},
                params=params,
            )
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise EffectNotApplied(f"Airtable unreachable, no effect occurred: {exc}") from exc
    _raise_http_error("airtable", response.status_code)
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("Airtable returned a non-object response body")
    return body


def _raise_http_error(service: str, status_code: int) -> None:
    if status_code < 400:
        return
    if status_code in {401, 403}:
        label = "auth_failed" if status_code == 401 else "forbidden"
        error = PermissionError(f"{service}_{label} status={status_code}")
        # CredentialRouting reads this status to block an invalid key after the
        # real provider response, while BaseNode retains the stable error type.
        error.status_code = status_code  # type: ignore[attr-defined]
        raise error
    raise PollingHttpError(f"{service}_http_error status={status_code}", status_code)


__all__ = [
    "AIRTABLE_POLL_CAPABILITY",
    "JIRA_POLL_CAPABILITY",
    "JIRA_SUBTASKS_CAPABILITY",
    "AirtablePollRequest",
    "AirtableProvider",
    "JiraPollRequest",
    "JiraProvider",
    "JiraSubtasksRequest",
    "PollingHttpError",
    "execute_airtable",
    "execute_jira",
    "resolve_airtable_provider",
    "resolve_jira_provider",
]
