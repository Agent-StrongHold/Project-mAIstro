"""The per-invocation extension context and its narrow authority seams (#950).

An extension receives exactly one :class:`ExtensionContext` per invocation.
The context is the complete authority surface: canonical identifiers, declared
configuration, granted services, the governed effect seam, cooperative
cancellation, and progress reporting. It holds no container, store, session,
or connection handle — anything the descriptor did not declare and the host
did not grant is refused with a typed error, never silently empty.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from maistro.extensions.errors import (
    ConfigurationKeyNotDeclared,
    EffectNotDeclared,
    ExtensionCancelled,
    ExtensionContractError,
    ExtensionContractUnavailableError,
    ServiceNotGranted,
)
from maistro.extensions.identity import ExtensionDescriptor, InvocationScope


class ExtensionConfigView(Mapping[str, Any]):
    """Read-only access to the configuration keys this extension declared.

    Values are snapshotted when the host builds the context; later mutation of
    the host-side mapping cannot reach a running extension. Undeclared keys
    raise :class:`ConfigurationKeyNotDeclared` on every access — including
    ``get`` — so an undeclared key reveals nothing, not even presence.
    """

    __slots__ = ("_declared", "_extension_id", "_values")

    def __init__(
        self,
        *,
        extension_id: str,
        declared: frozenset[str],
        values: Mapping[str, Any],
    ) -> None:
        self._extension_id = extension_id
        self._declared = declared
        self._values: Mapping[str, Any] = MappingProxyType(dict(values))

    def _require_declared(self, key: str) -> None:
        if key not in self._declared:
            raise ConfigurationKeyNotDeclared(
                f"configuration key {key!r} is not declared by extension "
                f"{self._extension_id!r}; declare it in the extension descriptor"
            )

    def __getitem__(self, key: str) -> Any:
        self._require_declared(key)
        return self._values.get(key)

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._declared))

    def __len__(self) -> int:
        return len(self._declared)

    def __contains__(self, key: object) -> bool:
        return key in self._declared

    def get(self, key: str, default: Any = None) -> Any:
        """Declared-key lookup; an undeclared key is a contract error."""
        self._require_declared(key)
        return self._values.get(key, default)

    def as_dict(self) -> dict[str, Any]:
        """A detached copy of the declared values."""
        return {key: self._values.get(key) for key in sorted(self._declared)}


class ExtensionCancellation:
    """Read-only cooperative-cancellation view over the owning execution.

    The authority behind this view is always the canonical execution fence:
    the host binds it to the ``asyncio.Task`` the ``ExecutionRuntime`` created
    for the Attempt (``of_current_task`` inside extension code), so
    ``runtime.cancel(attempt_id)`` — the one canonical cancellation path — is
    what makes this view report cancelled. This class never cancels anything
    and holds no lifecycle authority.
    """

    __slots__ = ("_is_cancelled",)

    def __init__(self, *, observe: Callable[[], bool]) -> None:
        self._is_cancelled = observe

    @classmethod
    def of_current_task(cls) -> ExtensionCancellation:
        """Observe the cancellation state of the calling ``asyncio`` task.

        The task is resolved when the view is asked, not when it is built:
        hosts build contexts before the ``ExecutionRuntime`` starts its work
        task, and the extension's code runs in that work task. Answering "am
        I, the code asking right now, being cancelled" is therefore correct
        wherever the extension calls it from. Inside an Attempt, that task is
        (a child of) the work the runtime launched for the Attempt's
        ``execution_id``; a canonical ``cancel`` marks it with a pending
        cancellation request that ``asyncio.Task.cancelling()`` reports
        before the error is delivered.
        """

        def observe() -> bool:
            task = asyncio.current_task()
            return task is not None and task.cancelling() > 0

        return cls(observe=observe)

    @classmethod
    def from_predicate(cls, observe: Callable[[], bool]) -> ExtensionCancellation:
        """Observe a host-supplied cancellation predicate (activation contexts)."""
        return cls(observe=observe)

    def cancelled(self) -> bool:
        """Whether the owning canonical execution has been asked to stop."""
        try:
            return self._is_cancelled()
        except Exception:  # pragma: no cover - a broken observer fails closed
            return True

    def check(self) -> None:
        """Raise :class:`ExtensionCancelled` when cancellation is pending."""
        if self.cancelled():
            raise ExtensionCancelled("the canonical execution owning this invocation was cancelled")

    async def wait(self, timeout_s: float | None = None) -> None:
        """Wait until cancellation is pending, then stop the caller.

        Extensions that cannot poll call this between units of work. Two
        outcomes are possible, and which one fires is not this class's
        choice: if the owning task itself was cancelled, the canonical
        ``CancelledError`` is delivered at the next suspension and propagates
        unchanged — this method never converts or absorbs it, or a cancelled
        Attempt would be recorded as an extension failure. If the observed
        cancellation comes from a host predicate instead (an activation stop
        flag with no pending task cancellation),
        :class:`ExtensionCancelled` is raised.

        A ``timeout_s`` that elapses without cancellation raises
        ``TimeoutError`` — an ordinary, retryable outcome, not a stop.
        """

        async def _poll() -> None:
            while True:
                if self.cancelled():
                    # Yield first so a pending canonical delivery keeps its
                    # precedence over this view's own error.
                    await asyncio.sleep(0)
                    self.check()
                    return
                await asyncio.sleep(0.01)

        if timeout_s is None:
            await _poll()
            return
        async with asyncio.timeout(timeout_s):
            await _poll()


@dataclass(frozen=True, slots=True)
class ExtensionProgress:
    """One progress report from one extension invocation."""

    message: str
    percent: float | None = None

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("progress message must be a non-empty string")
        if self.percent is not None and not 0.0 <= self.percent <= 100.0:
            raise ValueError("progress percent must be within [0, 100] or None")


@runtime_checkable
class ProgressReporter(Protocol):
    """The progress hook the host grants to one extension invocation."""

    async def report(self, progress: ExtensionProgress) -> None: ...


class UngrantedProgressReporter:
    """The reporter an invocation receives when the host granted no sink.

    Progress reporting is a granted capability, not an ambient one: without a
    host-provided sink the hook fails loudly instead of silently discarding
    the extension's reports.
    """

    __slots__ = ("_extension_id",)

    def __init__(self, extension_id: str) -> None:
        self._extension_id = extension_id

    async def report(self, progress: ExtensionProgress) -> None:
        raise ExtensionContractUnavailableError(
            f"extension {self._extension_id!r} reported progress but the host "
            "granted no progress sink"
        )


@dataclass(frozen=True, slots=True)
class EffectReceipt:
    """The canonical outcome of one governed effect, minus provider machinery.

    ``invocation_id`` is the canonical Invocation identity; ``result`` is the
    settled effect payload. The Binding, resolver, and executor that produced
    it are host-side and never travel back into extension code.
    """

    invocation_id: str
    binding_id: str
    capability: str
    effect_key: str
    status: str
    result: Any | None


EffectDispatcher = Callable[[str, Any], Any]
"""Host-wired ``(effect_key, request) -> EffectReceipt`` coroutine function."""


class ExtensionContext:
    """The complete authority one extension receives for one invocation.

    Hosts construct this; extensions only consume it. Every seam enforces the
    descriptor first and the host grant second, so importing SDK objects
    confers nothing undeclared:

    - ``config`` — declared configuration values only;
    - ``service(name)`` — declared *and* host-granted services;
    - ``invoke_effect`` — declared *and* host-routed effects, dispatched
      across the canonical governed Invocation seam;
    - ``cancellation`` / ``progress`` — read-only observation and reporting.
    """

    __slots__ = (
        "_dispatch_effect",
        "_services",
        "cancellation",
        "config",
        "descriptor",
        "identity",
        "progress",
        "scope",
    )

    def __init__(
        self,
        *,
        descriptor: ExtensionDescriptor,
        scope: InvocationScope,
        config: ExtensionConfigView,
        cancellation: ExtensionCancellation,
        progress: ProgressReporter,
        services: Mapping[str, object],
        dispatch_effect: EffectDispatcher,
    ) -> None:
        self.descriptor = descriptor
        self.identity = descriptor.identity
        self.scope = scope
        self.config = config
        self.cancellation = cancellation
        self.progress = progress
        self._services: Mapping[str, object] = MappingProxyType(dict(services))
        self._dispatch_effect = dispatch_effect

    def service(self, name: str) -> object:
        """Return the granted service for a declared name; refuse otherwise.

        A name the descriptor declared but the host did not grant is refused
        identically to an undeclared name: declaration alone is not authority.
        """
        if name not in self.descriptor.services:
            raise ServiceNotGranted(
                f"service {name!r} is not declared by extension {self.identity.extension_id!r}"
            )
        try:
            return self._services[name]
        except KeyError:
            raise ServiceNotGranted(
                f"service {name!r} is declared by extension "
                f"{self.identity.extension_id!r} but the host granted no instance"
            ) from None

    async def invoke_effect(self, effect_key: str, request: Any) -> EffectReceipt:
        """Cross the canonical governed seam for a declared, routed effect.

        This is the only authority-sensitive operation the context exposes.
        The route — Binding, provider resolution, executor, policy — is
        host-side, so the extension can never dispatch a provider call that
        bypasses the governed Invocation record. Pending cancellation is
        checked before dispatch: a cancelled invocation asks for no new
        effects.
        """
        if effect_key not in self.descriptor.effects:
            raise EffectNotDeclared(
                f"effect {effect_key!r} is not declared by extension {self.identity.extension_id!r}"
            )
        self.cancellation.check()
        receipt: Any = self._dispatch_effect(effect_key, request)
        if asyncio.iscoroutine(receipt):
            receipt = await receipt
        if isinstance(receipt, EffectReceipt):
            return receipt
        raise ExtensionContractError(
            "effect route returned a non-receipt outcome; the host wiring is invalid"
        )

    async def report_progress(
        self,
        message: str,
        *,
        percent: float | None = None,
    ) -> None:
        """Report progress through the host-granted hook."""
        await self.progress.report(ExtensionProgress(message=message, percent=percent))


__all__ = [
    "EffectDispatcher",
    "EffectReceipt",
    "ExtensionCancellation",
    "ExtensionConfigView",
    "ExtensionContext",
    "ExtensionContractUnavailableError",
    "ExtensionProgress",
    "ProgressReporter",
    "UngrantedProgressReporter",
]
