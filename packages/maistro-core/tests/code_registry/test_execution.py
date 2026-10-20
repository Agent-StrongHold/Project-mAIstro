"""Tests for the governed execution harness (ADR-069): Sentinel gating.

Covers the P1 review findings on #59:

- an ``authorized=True`` decision with an outstanding approval
  (``needs != "none"``) must NOT clear the sandbox — the required approval has
  to be granted first;
- a Warden verdict that is merely suspicious (``clean=False, blocked=False`` —
  heuristic/semantic-poisoning/configured-LLM findings) must refuse the
  payload: ``blocked`` is reserved for reject-pattern hits, so gating on it
  alone would wave suspicious payloads into the signed-code sandbox.
"""

from __future__ import annotations

import hashlib
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from maistro.code_registry.execution import CodeInvoker, CodeResult, CodeSandboxOutcome
from maistro.code_registry.registry import CodeRegistry
from maistro.code_registry.types import CodeEntry, CodeKind
from maistro.code_registry.verify import Ed25519Verifier
from maistro.security.sentinel.authz_types import AuthzDecision, Principal, Tier


def _make_signed_entry(signer: Ed25519PrivateKey) -> CodeEntry:
    code_sha256 = hashlib.sha256(b"body").hexdigest()
    payload = f"my_compensator@1.0.0:{CodeKind.COMPENSATOR.value}:{code_sha256}".encode()
    return CodeEntry(
        name="my_compensator",
        version="1.0.0",
        kind=CodeKind.COMPENSATOR,
        code_sha256=code_sha256,
        signature=signer.sign(payload),
    )


class _FakeSentinel:
    def __init__(self, decision: AuthzDecision) -> None:
        self._decision = decision

    async def authorize(self, action: str, principal: Principal, **_: Any) -> AuthzDecision:
        return self._decision


class _RecordingSandbox:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, entry: CodeEntry, payload: Any) -> CodeSandboxOutcome:
        self.calls.append(entry.name)
        return CodeSandboxOutcome(label="test_vm", result="ran")


def _decision(*, authorized: bool, needs: str) -> AuthzDecision:
    return AuthzDecision(
        tier=Tier.SELF_ELEVATION,
        authorized=authorized,
        needs=needs,  # type: ignore[arg-type]
        approver_scope=None,
        within_budget=True,
        rlphd=None,
        reason="table decision",
    )


class _FakeWarden:
    """Stands in for Warden's detector: returns a canned verdict."""

    def __init__(self, verdict: Any) -> None:
        self._verdict = verdict
        self.scanned: list[str] = []

    async def __call__(self, content: str, _boundary: str) -> Any:
        self.scanned.append(content)
        return self._verdict


def _invoker(
    decision: AuthzDecision,
    sandbox: _RecordingSandbox,
    warden: _FakeWarden | None = None,
) -> CodeInvoker:
    signer = Ed25519PrivateKey.generate()
    registry = CodeRegistry()
    registry.register(
        _make_signed_entry(signer), verifier=Ed25519Verifier(signer.public_key().public_bytes_raw())
    )
    return CodeInvoker(
        registry,
        sentinel=_FakeSentinel(decision),
        warden_scan=warden,
        sandbox=sandbox,
    )


_PRINCIPAL = Principal(id="agent-1", kind="agent", owner="human-1")


async def test_outstanding_approval_blocks_execution() -> None:
    for needs in ("self_elevation", "scoped_2fa", "delegated", "admin"):
        sandbox = _RecordingSandbox()
        result = await _invoker(_decision(authorized=True, needs=needs), sandbox).invoke(
            "my_compensator@1.0.0", {}, _PRINCIPAL
        )
        assert result == CodeResult(
            ref="my_compensator@1.0.0",
            ok=False,
            isolation="refused",
            reason=f"authorization pending approval ({needs}); refusing to execute before it is granted",
        )
        assert sandbox.calls == []


async def test_non_clean_warden_verdict_refuses_payload() -> None:
    # Warden's heuristic/semantic/LLM findings are clean=False, blocked=False
    # (blocked is reserved for reject patterns). The untrusted-execution gate
    # must refuse on not clean, not only on blocked.
    class _Verdict:
        clean = False
        blocked = False
        flags = ("heuristic: obfuscation markers",)

    warden = _FakeWarden(_Verdict())
    sandbox = _RecordingSandbox()
    result = await _invoker(_decision(authorized=True, needs="none"), sandbox, warden).invoke(
        "my_compensator@1.0.0", {"q": "hi"}, _PRINCIPAL
    )
    assert result == CodeResult(
        ref="my_compensator@1.0.0",
        ok=False,
        isolation="refused",
        reason="warden flagged payload: heuristic: obfuscation markers",
    )
    assert sandbox.calls == []
    assert warden.scanned == ['{"q": "hi"}']


async def test_clean_warden_verdict_executes() -> None:
    class _Verdict:
        clean = True
        blocked = False
        flags = ()

    sandbox = _RecordingSandbox()
    result = await _invoker(
        _decision(authorized=True, needs="none"), sandbox, _FakeWarden(_Verdict())
    ).invoke("my_compensator@1.0.0", {}, _PRINCIPAL)
    assert result.ok is True
    assert sandbox.calls == ["my_compensator"]


async def test_cleared_decision_executes() -> None:
    sandbox = _RecordingSandbox()
    result = await _invoker(_decision(authorized=True, needs="none"), sandbox).invoke(
        "my_compensator@1.0.0", {}, _PRINCIPAL
    )
    assert result.ok is True
    assert result.isolation == "test_vm"
    assert sandbox.calls == ["my_compensator"]


async def test_sandbox_failure_after_start_is_unknown_not_refused() -> None:
    # A sandbox exception after admission (timeout kill, OOM, result-collection
    # error) may mean the code partially ran: the result must NOT carry
    # isolation="refused" (which asserts nothing ran in audit evidence) but
    # the honest "unknown" label (ADR-069 failure table).
    class _ExplodingSandbox:
        async def execute(self, entry: CodeEntry, payload: Any) -> CodeSandboxOutcome:
            raise TimeoutError("microVM over budget: killed after start")

    sandbox = _ExplodingSandbox()
    result = await _invoker(_decision(authorized=True, needs="none"), sandbox).invoke(
        "my_compensator@1.0.0", {}, _PRINCIPAL
    )
    assert result == CodeResult(
        ref="my_compensator@1.0.0",
        ok=False,
        isolation="unknown",
        reason="microVM over budget: killed after start",
    )
