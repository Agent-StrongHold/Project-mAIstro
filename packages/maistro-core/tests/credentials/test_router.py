"""Tests for maistro.credentials.router — scoped selection and outcome rotation.

The rotation scenarios ADR-063 described around ``execute_with_pool`` (#AC-10
through #AC-16, #AC-19) are proven here against the surface #58 put them on:
selection happens at Provider-resolution time under a Binding's authorized
scope, and cooldown/blocking is driven by ``record_outcome`` folding a *real*
provider-call exception through the IMP-001 classifier. No detached retry loop
is involved — that machinery was removed with #58.
"""

from __future__ import annotations

import time

import pytest

from maistro.credentials.pool import CredentialPool
from maistro.credentials.router import (
    CredentialRouter,
    CredentialScopeError,
    cooldown_for_failure,
)
from maistro.credentials.types import (
    CredentialRecord,
    PoolExhaustedError,
    SelectionStrategy,
)
from maistro.resilience.classifier import ClassifiedError, ErrorCategory

WS = "ws-1"
PROJECT = "project-1"
PROVIDER = "openai"


class _HttpError(Exception):
    def __init__(self, message: str, status_code: int, headers: dict | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = type("Resp", (), {"status_code": status_code, "headers": headers or {}})


def _rec(key_id: str, provider: str = PROVIDER, **kwargs) -> CredentialRecord:
    return CredentialRecord(key_id=key_id, provider=provider, api_key=f"sk-{key_id}", **kwargs)


def _router(keys: list[str], strategy: SelectionStrategy = SelectionStrategy.ROUND_ROBIN):
    router = CredentialRouter(strategy=strategy)
    for key in keys:
        router.add(workspace_id=WS, project_id=PROJECT, record=_rec(key))
    return router


async def _acquire(router: CredentialRouter, refs: tuple[str, ...] = ("a", "b", "c")):
    return await router.acquire(
        workspace_id=WS,
        project_id=PROJECT,
        provider=PROVIDER,
        credential_refs=refs,
    )


def _entry(router: CredentialRouter, key_id: str) -> CredentialRecord:
    pool = router.pool_for(workspace_id=WS, project_id=PROJECT, provider=PROVIDER)
    assert isinstance(pool, CredentialPool)
    return next(e for e in pool._entries if e.key_id == key_id)


class TestScopedAcquisition:
    async def test_acquire_selects_within_the_binding_authorized_refs(self):
        router = _router(["a", "b"])

        first = await _acquire(router, refs=("a", "b"))
        second = await _acquire(router, refs=("a", "b"))

        assert (first.key_id, second.key_id) == ("a", "b")  # round-robin over refs

    async def test_acquire_never_returns_a_credential_the_binding_did_not_name(self):
        router = _router(["a", "b"])

        selection = await _acquire(router, refs=("b",))

        assert selection.key_id == "b"

    async def test_acquire_without_refs_fails_closed(self):
        router = _router(["a"])

        with pytest.raises(CredentialScopeError, match="credential_refs is empty"):
            await _acquire(router, refs=())

    async def test_acquire_for_refs_absent_from_scope_is_denied(self):
        router = _router(["a"])

        with pytest.raises(CredentialScopeError, match="authorizes credentials"):
            await _acquire(router, refs=("not-configured",))

    async def test_acquire_in_a_workspace_with_no_pool_is_denied(self):
        router = _router(["a"])

        with pytest.raises(CredentialScopeError, match="no credentials configured"):
            await router.acquire(
                workspace_id="ws-other",
                project_id=PROJECT,
                provider=PROVIDER,
                credential_refs=("a",),
            )

    async def test_one_workspace_cannot_acquire_another_workspaces_key(self):
        router = CredentialRouter()
        router.add(workspace_id="ws-1", project_id=PROJECT, record=_rec("a"))

        with pytest.raises(CredentialScopeError, match="no credentials configured"):
            await router.acquire(
                workspace_id="ws-2",
                project_id=PROJECT,
                provider=PROVIDER,
                credential_refs=("a",),
            )

    async def test_one_project_cannot_acquire_a_sibling_projects_key(self):
        router = CredentialRouter()
        router.add(workspace_id=WS, project_id="project-1", record=_rec("a"))

        with pytest.raises(CredentialScopeError):
            await router.acquire(
                workspace_id=WS,
                project_id="project-2",
                provider=PROVIDER,
                credential_refs=("a",),
            )

    async def test_re_registering_a_key_id_replaces_rather_than_duplicates(self):
        router = _router(["a"])
        router.add(workspace_id=WS, project_id=PROJECT, record=_rec("a"))

        stats = router.stats(workspace_id=WS, project_id=PROJECT, provider=PROVIDER)
        assert stats is not None and stats.total_keys == 1

    def test_router_reports_its_default_strategy(self):
        router = _router(["a"])

        assert router.strategy is SelectionStrategy.ROUND_ROBIN


class TestOutcomeRotation:
    """Rotation as a reaction to real provider outcomes (#58)."""

    @pytest.mark.ac("ADR-063/AC-30")
    async def test_success_outcome_clears_error_state_and_counts_use(self):
        router = _router(["a"])
        await router.record_outcome(
            workspace_id=WS, project_id=PROJECT, provider=PROVIDER, key_id="a", error=None
        )

        entry = _entry(router, "a")
        assert entry.use_count == 1
        assert entry.last_status == 200
        assert entry.last_error_code is None

    @pytest.mark.ac("ADR-063/AC-10")
    async def test_429_outcome_cools_first_key_and_next_acquire_rotates(self):
        router = _router(["a", "b"], strategy=SelectionStrategy.FILL_FIRST)

        first = await _acquire(router)
        await router.record_outcome(
            workspace_id=WS,
            project_id=PROJECT,
            provider=PROVIDER,
            key_id=first.key_id,
            error=_HttpError("Rate limit exceeded", 429),
        )
        second = await _acquire(router)

        assert first.key_id == "a"
        assert second.key_id == "b"
        assert _entry(router, "a").cooldown_until is not None
        assert _entry(router, "b").is_available

    @pytest.mark.ac("ADR-063/AC-11")
    async def test_429_with_retry_after_sets_that_cooldown(self):
        router = _router(["a", "b"])

        await router.record_outcome(
            workspace_id=WS,
            project_id=PROJECT,
            provider=PROVIDER,
            key_id="a",
            error=_HttpError("Slow down", 429, headers={"retry-after": "30"}),
        )

        remaining = _entry(router, "a").cooldown_until - time.monotonic()
        assert 25 < remaining <= 30

    @pytest.mark.ac("ADR-063/AC-12")
    @pytest.mark.ac("ADR-063/AC-26")
    async def test_429_without_retry_after_defaults_to_60_seconds(self):
        router = _router(["a", "b"])

        await router.record_outcome(
            workspace_id=WS,
            project_id=PROJECT,
            provider=PROVIDER,
            key_id="a",
            error=_HttpError("Rate limit exceeded", 429),
        )

        remaining = _entry(router, "a").cooldown_until - time.monotonic()
        assert 55 < remaining <= 60

    @pytest.mark.ac("ADR-063/AC-27")
    async def test_429_retry_after_is_capped_at_60_seconds(self):
        router = _router(["a", "b"])

        await router.record_outcome(
            workspace_id=WS,
            project_id=PROJECT,
            provider=PROVIDER,
            key_id="a",
            error=_HttpError("Slow down", 429, headers={"retry-after": "300"}),
        )

        remaining = _entry(router, "a").cooldown_until - time.monotonic()
        assert 55 < remaining <= 60

    @pytest.mark.ac("ADR-063/AC-15")
    async def test_402_outcome_rotates_to_next_key_with_hour_cooldown(self):
        router = _router(["a", "b"], strategy=SelectionStrategy.FILL_FIRST)

        await router.record_outcome(
            workspace_id=WS,
            project_id=PROJECT,
            provider=PROVIDER,
            key_id="a",
            error=_HttpError("Insufficient credits", 402),
        )

        remaining = _entry(router, "a").cooldown_until - time.monotonic()
        assert 3500 < remaining <= 3600
        assert (await _acquire(router)).key_id == "b"

    @pytest.mark.ac("ADR-063/AC-16")
    async def test_402_on_all_keys_exhausts_the_pool(self):
        router = _router(["a", "b"])

        for key in ("a", "b"):
            await router.record_outcome(
                workspace_id=WS,
                project_id=PROJECT,
                provider=PROVIDER,
                key_id=key,
                error=_HttpError("Insufficient credits", 402),
            )

        with pytest.raises(PoolExhaustedError) as exc_info:
            await _acquire(router)
        err = exc_info.value
        assert err.total_keys == 2
        assert err.wait_seconds <= 3600

    @pytest.mark.ac("ADR-063/AC-13")
    async def test_transient_outcome_does_not_rotate_the_key(self):
        router = _router(["a", "b"], strategy=SelectionStrategy.FILL_FIRST)

        await router.record_outcome(
            workspace_id=WS,
            project_id=PROJECT,
            provider=PROVIDER,
            key_id="a",
            error=_HttpError("Internal Server Error", 500),
        )
        again = await _acquire(router)

        assert again.key_id == "a"

    @pytest.mark.ac("ADR-063/AC-14")
    async def test_transient_outcome_sets_no_cooldown(self):
        router = _router(["a"])

        await router.record_outcome(
            workspace_id=WS,
            project_id=PROJECT,
            provider=PROVIDER,
            key_id="a",
            error=_HttpError("Bad Gateway", 502),
        )

        assert _entry(router, "a").cooldown_until is None
        assert _entry(router, "a").is_available

    @pytest.mark.ac("ADR-063/AC-24")
    async def test_401_outcome_blocks_the_key_permanently(self):
        router = _router(["a", "b"])

        await router.record_outcome(
            workspace_id=WS,
            project_id=PROJECT,
            provider=PROVIDER,
            key_id="a",
            error=_HttpError("Unauthorized", 401),
        )

        assert _entry(router, "a").blocked is True
        assert _entry(router, "a").is_available is False

    @pytest.mark.ac("ADR-063/AC-25")
    async def test_403_outcome_blocks_the_key_permanently(self):
        router = _router(["a", "b"])

        await router.record_outcome(
            workspace_id=WS,
            project_id=PROJECT,
            provider=PROVIDER,
            key_id="a",
            error=_HttpError("Forbidden", 403),
        )

        assert _entry(router, "a").blocked is True

    @pytest.mark.ac("ADR-063/AC-31")
    async def test_error_outcome_increments_error_count(self):
        router = _router(["a"])

        await router.record_outcome(
            workspace_id=WS,
            project_id=PROJECT,
            provider=PROVIDER,
            key_id="a",
            error=_HttpError("Rate limit exceeded", 429),
        )

        assert _entry(router, "a").error_count == 1

    @pytest.mark.ac("ADR-063/AC-19")
    async def test_single_key_429_then_acquire_reports_exhaustion(self):
        router = _router(["a"])

        await router.record_outcome(
            workspace_id=WS,
            project_id=PROJECT,
            provider=PROVIDER,
            key_id="a",
            error=_HttpError("Rate limit exceeded", 429),
        )

        with pytest.raises(PoolExhaustedError) as exc_info:
            await _acquire(router)
        assert exc_info.value.total_keys == 1

    @pytest.mark.ac("ADR-063/AC-20")
    async def test_exhaustion_error_names_the_provider(self):
        router = CredentialRouter()
        router.add(workspace_id=WS, project_id=PROJECT, record=_rec("x", provider="anthropic"))

        await router.record_outcome(
            workspace_id=WS,
            project_id=PROJECT,
            provider="anthropic",
            key_id="x",
            error=_HttpError("Rate limit exceeded", 429),
        )

        with pytest.raises(PoolExhaustedError) as exc_info:
            await router.acquire(
                workspace_id=WS,
                project_id=PROJECT,
                provider="anthropic",
                credential_refs=("x",),
            )
        assert exc_info.value.provider == "anthropic"

    async def test_outcome_for_an_unknown_scope_is_ignored(self):
        router = _router(["a"])

        await router.record_outcome(
            workspace_id="ws-none",
            project_id=PROJECT,
            provider=PROVIDER,
            key_id="a",
            error=_HttpError("Rate limit exceeded", 429),
        )

        assert _entry(router, "a").is_available


class TestCooldownMapping:
    """The ADR-063 table, folded from classified errors."""

    def test_status_is_read_from_the_error_response_object(self):
        class _ResponseOnly(Exception):
            def __init__(self) -> None:
                super().__init__("transport said so")
                self.response = type("Resp", (), {"status_code": 403, "headers": {}})

        from maistro.credentials.router import _status_from_error

        assert _status_from_error(_ResponseOnly()) == 403

    def test_status_falls_back_to_zero_without_any_status_attribute(self):
        from maistro.credentials.router import _status_from_error

        assert _status_from_error(ValueError("no status at all")) == 0

    def test_non_integer_status_attribute_falls_through_to_response(self):
        from maistro.credentials.router import _status_from_error

        class _StringyStatus(Exception):
            def __init__(self) -> None:
                super().__init__("string status")
                self.status_code = "429"
                self.response = type("Resp", (), {"status_code": 429, "headers": {}})

        assert _status_from_error(_StringyStatus()) == 429

    def test_none_detail_yields_no_status(self):
        classified = ClassifiedError(
            category=ErrorCategory.UNKNOWN,
            original=ValueError("no detail"),
            detail=None,
        )

        cooldown, block = cooldown_for_failure(classified)

        assert cooldown == 0.0
        assert block is False

    def test_non_integer_detail_status_is_ignored(self):
        classified = ClassifiedError(
            category=ErrorCategory.UNKNOWN,
            original=ValueError("weird"),
            detail={"status_code": "not-a-number"},
        )

        cooldown, block = cooldown_for_failure(classified)

        assert cooldown == 0.0
        assert block is False

    def test_rate_limit_classification_without_status_code_still_cools(self):
        # The classifier itself only produces RATE_LIMIT for status 429 (and
        # 402-with-usage-message), both of which earlier branches handle. This
        # pins the table's remaining arm: a rate_limit classification carrying
        # no status at all still earns the default cooldown.
        classified = ClassifiedError(
            category=ErrorCategory.RATE_LIMIT,
            original=ValueError("quota"),
        )

        cooldown, block = cooldown_for_failure(classified)

        assert cooldown == 60.0
        assert block is False

    def test_429_classification_with_retry_after_cools_for_that_value(self):
        classified = ClassifiedError(
            category=ErrorCategory.RATE_LIMIT,
            original=ValueError("quota"),
            retry_after_seconds=17.0,
        )

        cooldown, block = cooldown_for_failure(classified)

        assert cooldown == 17.0
        assert block is False

    def test_unknown_error_sets_no_cooldown_and_does_not_block(self):
        classified = ClassifiedError(
            category=ErrorCategory.UNKNOWN,
            original=ValueError("boom"),
        )

        cooldown, block = cooldown_for_failure(classified)

        assert cooldown == 0.0
        assert block is False
