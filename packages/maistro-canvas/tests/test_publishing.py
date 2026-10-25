"""Governed Design Studio publish/export (M3-B4, #94) — capability-owner tests.

Covers the publishing module end to end with the *real* invocation lifecycle
(InMemoryInvocationStore) so the assertions exercise the actual governed
Boundary -> Invocation contract, not a shadow of it:

- state pinning: same state → same digest; any edit → new digest
- provider truthfulness: pdf/svg explicitly unsupported; png/webp/jpg/html
  real bytes; pptx honest about its optional dependency
- governed export: COMPLETED invocation + append-only ExportVersion with full
  provenance (Run/NodeRun/Attempt ids, invocation_id, binding_id)
- idempotent same-state re-export; edit-then-re-export creates a NEW version
  while the historical version stays byte-identical
- truthful failure: provider error → FAILED/UNKNOWN invocation, NO version
- policy: DENY refuses the effect through GovernedInvocationExecutionService
- isolation: an in-flight export does not block an unrelated export
"""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime

import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.governed_invocation import (
    GovernedInvocationExecutionService,
    InvocationDenied,
)
from maistro.capabilities.invocation import (
    EffectNotApplied,
    InMemoryInvocationStore,
    InvocationExecutionService,
    InvocationStatus,
    InvocationStore,
)
from maistro.events.envelope import InMemoryEventStore
from maistro.policy.types import Decision, PolicyVerdict
from maistro_canvas.canvas.publishing import (
    DesignExportProvider,
    ExportFormatUnsupported,
    ExportVersion,
    ExportVersionExistsError,
    GovernedCanvasExporter,
    InMemoryExportStore,
    canvas_state_digest,
    export_media_type,
)
from maistro_canvas.export import ExporterDependencyError
from maistro_canvas.types import (
    CanvasRecord,
    CompositeResult,
    LayerRecord,
    TextConfig,
)

# A minimal valid 1x1 PNG (mirrors test_export.py's fixture).
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6360000002000154a24f5f0000000049454e44ae426082"
)


def _canvas(org_id: str = "org-1") -> CanvasRecord:
    return CanvasRecord(id="canvas-1", name="Poster", width=800, height=600, org_id=org_id)


def _layers(**overrides: object) -> list[LayerRecord]:
    layer = LayerRecord(
        id="layer-1",
        canvas_id="canvas-1",
        name="title",
        layer_type="text",
        text_config=TextConfig(content="Hello", size=48, color="#111111"),
    )
    for key, value in overrides.items():
        setattr(layer, key, value)
    return [layer]


def _composite(png: bytes = _PNG) -> CompositeResult:
    return CompositeResult(canvas_id="canvas-1", image_bytes=png, width=800, height=600)


class StubCompositor:
    """Composite/encode double with controllable behavior."""

    def __init__(self, png: bytes = _PNG, *, gate: asyncio.Event | None = None) -> None:
        self.png = png
        self.gate = gate
        self.composite_calls = 0
        self.encode_calls: list[str] = []

    async def composite(self, canvas: object, layers: list[LayerRecord]) -> CompositeResult:
        self.composite_calls += 1
        if self.gate is not None:
            await self.gate.wait()
        return _composite(self.png)

    async def encode(self, image_bytes: bytes, *, fmt: str = "png", quality: int = 90) -> bytes:
        self.encode_calls.append(f"{fmt}:{quality}")
        return b"encoded<" + fmt.encode() + b">" + image_bytes[:4]


def _binding() -> Binding:
    return Binding(workspace_id="ws-1", project_id="proj-1", capability="design.export")


class RecordingInvocationStore:
    """Delegating InvocationStore that keeps every row for assertions."""

    def __init__(self, inner: InvocationStore) -> None:
        self._inner = inner
        self.rows: list[object] = []

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    async def create(self, invocation):
        self.rows.append(invocation)
        return await self._inner.create(invocation)

    async def save(self, invocation):
        self.rows.append(invocation)
        return await self._inner.save(invocation)

    async def get(self, invocation_id: str):
        return await self._inner.get(invocation_id)

    async def claim(self, invocation):
        self.rows.append(invocation)
        return await self._inner.claim(invocation)

    async def list_effect(self, *, run_id, node_run_id, binding_id, effect_key, effect_scope=None):
        return await self._inner.list_effect(
            run_id=run_id,
            node_run_id=node_run_id,
            binding_id=binding_id,
            effect_key=effect_key,
            effect_scope=effect_scope,
        )

    async def list_ambiguous(self, *, stale_before):
        return await self._inner.list_ambiguous(stale_before=stale_before)


def _resolver(provider: DesignExportProvider):
    async def resolve(binding: Binding):
        return provider

    return resolve


def _make_exporter(
    *,
    provider: DesignExportProvider | None = None,
    compositor: StubCompositor | None = None,
    invocation_service: InvocationExecutionService | None = None,
    invocation_store: RecordingInvocationStore | None = None,
    policy=None,
    event_store: InMemoryEventStore | None = None,
) -> tuple[GovernedCanvasExporter, RecordingInvocationStore, InMemoryExportStore]:
    provider = provider or DesignExportProvider(compositor or StubCompositor())
    store = invocation_store or RecordingInvocationStore(InMemoryInvocationStore())
    service = invocation_service or InvocationExecutionService(store=store)
    if policy is not None:
        service = GovernedInvocationExecutionService(
            invocation_service=service,
            event_store=event_store or InMemoryEventStore(),
            policy_evaluator=policy,
        )
    exports = InMemoryExportStore()
    exporter = GovernedCanvasExporter(
        provider=provider,
        invocation_service=service,
        export_store=exports,
        binding=_binding(),
        resolver=_resolver(provider),
    )
    return exporter, store, exports


# ── State pinning ────────────────────────────────────────────────────────


class TestCanvasStateDigest:
    def test_same_state_same_digest(self) -> None:
        assert canvas_state_digest(_canvas(), _layers()) == canvas_state_digest(
            _canvas(), _layers()
        )

    def test_layer_edit_changes_digest(self) -> None:
        before = canvas_state_digest(_canvas(), _layers())
        after = canvas_state_digest(_canvas(), _layers(x=12.0))
        assert before != after

    def test_text_edit_changes_digest(self) -> None:
        edited_cfg = TextConfig(content="Changed", size=48, color="#111111")
        edited = _layers(text_config=edited_cfg)
        assert canvas_state_digest(_canvas(), _layers()) != canvas_state_digest(_canvas(), edited)

    def test_canvas_edit_changes_digest(self) -> None:
        renamed = _canvas()
        renamed.name = "Renamed"
        assert canvas_state_digest(_canvas(), _layers()) != canvas_state_digest(renamed, _layers())

    def test_timestamp_only_touch_does_not_change_digest(self) -> None:
        """Audit timestamps are volatile, not state: touching them must not
        fork export versions without a real edit."""
        touched = _canvas()
        touched.updated_at = datetime.now(UTC)
        assert canvas_state_digest(_canvas(), _layers()) == canvas_state_digest(touched, _layers())


# ── Provider truthfulness ────────────────────────────────────────────────


class TestDesignExportProvider:
    async def test_pdf_is_explicitly_unsupported(self) -> None:
        provider = DesignExportProvider(StubCompositor())
        with pytest.raises(ExportFormatUnsupported) as excinfo:
            await provider.export(_request("pdf"), _canvas(), _layers(), _composite())
        assert excinfo.value.code == "EXPORT_FORMAT_UNSUPPORTED"
        assert "pdf" in str(excinfo.value)

    async def test_svg_is_explicitly_unsupported(self) -> None:
        provider = DesignExportProvider(StubCompositor())
        with pytest.raises(ExportFormatUnsupported):
            await provider.export(_request("svg"), _canvas(), _layers(), _composite())

    async def test_png_passthrough_of_pinned_composite(self) -> None:
        provider = DesignExportProvider(StubCompositor())
        result = await provider.export(_request("png"), _canvas(), _layers(), _composite(_PNG))
        assert result.content == _PNG
        assert result.media_type == "image/png"
        assert result.sha256

    async def test_webp_and_jpg_use_compositor_encode(self) -> None:
        compositor = StubCompositor()
        provider = DesignExportProvider(compositor)
        webp = await provider.export(_request("webp"), _canvas(), _layers(), _composite())
        assert webp.content.startswith(b"encoded<webp>")
        jpg = await provider.export(_request("jpg", quality=42), _canvas(), _layers(), _composite())
        assert jpg.content.startswith(b"encoded<jpg>")
        assert compositor.encode_calls == ["webp:90", "jpg:42"]

    async def test_html_serialization_stays_text(self) -> None:
        provider = DesignExportProvider(StubCompositor())
        result = await provider.export(_request("html"), _canvas(), _layers(), _composite())
        assert result.media_type.startswith("text/html")
        assert b"Hello" in result.content
        assert result.content.startswith(b"<!doctype html>")

    async def test_html_export_embeds_image_layers_from_composite(self) -> None:
        """Visible image layers must render as <img> carrying the pinned
        composite PNG, not be silently dropped."""
        image_layer = LayerRecord(
            id="layer-img",
            canvas_id="canvas-1",
            name="hero",
            layer_type="character",
            image_path="images/hero.png",
            z_index=2,
        )
        provider = DesignExportProvider(StubCompositor())
        result = await provider.export(
            _request("html"),
            _canvas(),
            [image_layer, _layers()[0]],
            _composite(_PNG),
        )
        assert b"<img" in result.content
        assert base64.b64encode(_PNG) in result.content

    async def test_pptx_is_honest_about_missing_dependency(self) -> None:
        provider = DesignExportProvider(StubCompositor())
        try:  # behavior depends on whether python-pptx is installed
            import pptx  # noqa: F401

            pptx_installed = True
        except ImportError:
            pptx_installed = False

        if pptx_installed:
            result = await provider.export(_request("pptx"), _canvas(), _layers(), _composite())
            assert result.content[:2] == b"PK"  # zip container
        else:
            with pytest.raises(ExporterDependencyError):
                await provider.export(_request("pptx"), _canvas(), _layers(), _composite())

    async def test_encode_absent_on_non_png_is_truthful(self) -> None:
        class PngOnly:
            pass  # no encode()

        provider = DesignExportProvider(PngOnly())
        with pytest.raises(EffectNotApplied):
            await provider.export(_request("webp"), _canvas(), _layers(), _composite())


def _request(fmt: str, quality: int = 90, state: str = "s1", composite: str = "c1"):
    from maistro_canvas.canvas.publishing import ExportRequest

    return ExportRequest(
        canvas_id="canvas-1",
        format=fmt,
        quality=quality,
        state_digest=state,
        composite_digest=composite,
    )


# ── Governed export: success + provenance + versioning ──────────────────


class TestGovernedExportVersions:
    async def test_success_appends_version_with_full_provenance(self) -> None:
        exporter, invocations, _unused = _make_exporter()
        version = await exporter.export_canvas(
            _canvas(), _layers(), _composite(), fmt="png", actor_principal_id="alice"
        )

        assert version.content == _PNG
        assert version.export_id
        assert version.invocation_id
        assert version.binding_id == exporter.binding.binding_id
        assert version.run_id.startswith("canvas-export:")
        assert version.node_run_id
        assert version.attempt_id
        assert version.state_digest == canvas_state_digest(_canvas(), _layers())
        assert version.sha256
        assert version.published is False

        stored = await invocations.get(version.invocation_id)
        assert stored is not None
        assert stored.status is InvocationStatus.COMPLETED
        assert stored.binding.capability == "design.export"
        assert stored.binding.provider_name == "canvas-fixed-page-exporter"
        assert stored.workspace_id == "ws-1"
        assert stored.project_id == "proj-1"

    async def test_same_state_reexport_is_idempotent(self) -> None:
        exporter, _invocations, exports = _make_exporter()
        first = await exporter.export_canvas(_canvas(), _layers(), _composite(), fmt="png")
        second = await exporter.export_canvas(_canvas(), _layers(), _composite(), fmt="png")
        assert first.export_id == second.export_id
        assert first.invocation_id == second.invocation_id
        assert len(await exports.list_for_canvas("canvas-1", org_id="org-1")) == 1

    async def test_edit_then_reexport_creates_new_version(self) -> None:
        exporter, _invocations, exports = _make_exporter()
        first = await exporter.export_canvas(_canvas(), _layers(), _composite(), fmt="png")
        first_snapshot = (first.export_id, first.sha256, first.state_digest, first.invocation_id)

        # Later manual/AI edit: same canvas, changed layer state.
        edited = _layers(x=55.0)
        second = await exporter.export_canvas(_canvas(), edited, _composite(), fmt="png")

        assert second.export_id != first_snapshot[0]
        assert second.state_digest != first_snapshot[2]
        assert second.invocation_id != first_snapshot[3]
        # Historical provenance untouched: the old version is byte-identical.
        history = await exports.list_for_canvas("canvas-1", org_id="org-1")
        assert len(history) == 2
        old = next(v for v in history if v.export_id == first_snapshot[0])
        assert (old.export_id, old.sha256, old.state_digest, old.invocation_id) == first_snapshot
        assert old.content == _PNG

    async def test_publish_flags_version_and_records_project(self) -> None:
        exporter, _, _unused = _make_exporter()
        version = await exporter.export_canvas(
            _canvas(),
            _layers(),
            _composite(),
            fmt="png",
            published=True,
            design_project_id="design-project-9",
        )
        assert version.published is True
        assert version.design_project_id == "design-project-9"

    async def test_append_only_store_refuses_duplicate_ids(self) -> None:
        store = InMemoryExportStore()
        version = ExportVersion(
            export_id="fixed",
            canvas_id="c",
            org_id="o",
            format="png",
            media_type="image/png",
            byte_size=1,
            sha256="x",
            state_digest="s",
            composite_digest="c",
            width=1,
            height=1,
            run_id="r",
            node_run_id="n",
            attempt_id="a",
            invocation_id="i",
            binding_id="b",
        )
        await store.save(version)
        with pytest.raises(ExportVersionExistsError):
            await store.save(version)

    async def test_store_scopes_versions_to_org(self) -> None:
        exporter, _, exports = _make_exporter()
        await exporter.export_canvas(_canvas(org_id="org-A"), _layers(), _composite(), fmt="png")
        assert await exports.list_for_canvas("canvas-1", org_id="org-B") == []
        assert await exports.get("canvas-1", "nope", org_id="org-A") is None


# ── Truthful failures ───────────────────────────────────────────────────


class TestGovernedExportFailures:
    async def test_provider_crash_records_unknown_and_saves_no_version(self) -> None:
        class ExplodingCompositor(StubCompositor):
            async def encode(
                self, image_bytes: bytes, *, fmt: str = "png", quality: int = 90
            ) -> bytes:
                raise ValueError("libwebp vanished")

        exporter, invocations, exports = _make_exporter(
            provider=DesignExportProvider(ExplodingCompositor())
        )
        with pytest.raises(ValueError, match="libwebp vanished"):
            await exporter.export_canvas(_canvas(), _layers(), _composite(), fmt="webp")

        assert await exports.list_for_canvas("canvas-1", org_id="org-1") == []
        ambiguous = [row for row in invocations.rows if row.status is InvocationStatus.UNKNOWN]  # type: ignore[attr-defined]
        assert len(ambiguous) == 1
        assert ambiguous[0].error  # type: ignore[attr-defined]

    async def test_provable_non_effect_records_failed(self) -> None:
        class NoEncodeCompositor:
            pass  # no encode(): provider proves the effect never applied

        exporter, invocations, exports = _make_exporter(
            provider=DesignExportProvider(NoEncodeCompositor())
        )
        with pytest.raises(EffectNotApplied):
            await exporter.export_canvas(_canvas(), _layers(), _composite(), fmt="webp")

        assert await exports.list_for_canvas("canvas-1", org_id="org-1") == []
        terminal = [
            row
            for row in invocations.rows
            if row.status is InvocationStatus.FAILED  # type: ignore[attr-defined]
        ]
        assert terminal, "expected a FAILED invocation row"
        assert terminal[-1].error  # type: ignore[attr-defined]

    async def test_unsupported_format_never_creates_invocation(self) -> None:
        exporter, invocations, exports = _make_exporter()
        with pytest.raises(ExportFormatUnsupported):
            await exporter.export_canvas(_canvas(), _layers(), _composite(), fmt="pdf")
        assert await exports.list_for_canvas("canvas-1", org_id="org-1") == []
        assert invocations.rows == []  # type: ignore[attr-defined]


# ── Policy enforcement ──────────────────────────────────────────────────


class TestGovernedPolicy:
    async def test_policy_deny_refuses_export_and_records_decision(self) -> None:
        events = InMemoryEventStore()
        calls: list[str] = []

        async def deny_policy(binding: Binding, request: object, context: object) -> PolicyVerdict:
            calls.append(context.effect_key)
            return PolicyVerdict(Decision.DENY, reason="export not approved", rule="t3-block")

        exporter, _invocations, exports = _make_exporter(policy=deny_policy, event_store=events)
        with pytest.raises(InvocationDenied, match="export not approved"):
            await exporter.export_canvas(_canvas(), _layers(), _composite(), fmt="png")

        assert await exports.list_for_canvas("canvas-1", org_id="org-1") == []
        assert calls, "policy evaluator never consulted"
        # InMemoryEventStore keeps per-stream deques; flatten for the assertion.
        event_types = [envelope.type for stream in events._streams.values() for envelope in stream]
        assert "capability.invocation.policy_decision" in event_types

    async def test_permissive_policy_allows_export(self) -> None:
        async def allow_policy(binding: Binding, request: object, context: object) -> PolicyVerdict:
            return PolicyVerdict(Decision.ALLOW, reason="ok", rule="default-allow")

        exporter, invocations, _unused = _make_exporter(
            policy=allow_policy, event_store=InMemoryEventStore()
        )
        version = await exporter.export_canvas(_canvas(), _layers(), _composite(), fmt="png")
        assert version.content == _PNG
        stored = await invocations.get(version.invocation_id)
        assert stored is not None and stored.status is InvocationStatus.COMPLETED


# ── Isolation from unrelated work ───────────────────────────────────────


class GatedExportProvider(DesignExportProvider):
    """Export provider whose dispatch blocks on a gate (isolation test)."""

    def __init__(self, compositor: object, gate: asyncio.Event) -> None:
        super().__init__(compositor)
        self._gate = gate
        self.started = 0

    async def export(self, request, canvas, layers, composite):  # type: ignore[override]
        self.started += 1
        await self._gate.wait()
        return await super().export(request, canvas, layers, composite)


class TestExportIsolation:
    async def test_inflight_export_does_not_block_unrelated_export(self) -> None:
        """A user exports one artifact while an unrelated branch keeps working.

        Two independent bindings/effects: the first blocks inside its provider
        (simulating a slow compositor); the second must complete meanwhile —
        the invocation service only serializes admission, never dispatch.
        """
        gate = asyncio.Event()
        slow_provider = GatedExportProvider(StubCompositor(), gate)
        exporter_slow, _invocations, _unused = _make_exporter(provider=slow_provider)
        fast = StubCompositor(png=_PNG + b"fast")
        other_canvas = _canvas()
        other_canvas.id = "canvas-2"

        # A second exporter with a distinct binding so effect scopes differ.
        provider_fast = DesignExportProvider(fast)
        exports_fast = InMemoryExportStore()
        exporter_fast = GovernedCanvasExporter(
            provider=provider_fast,
            invocation_service=InvocationExecutionService(store=InMemoryInvocationStore()),
            export_store=exports_fast,
            binding=Binding(workspace_id="ws-1", project_id="proj-1", capability="design.export"),
            resolver=_resolver(provider_fast),
        )

        slow_task = asyncio.create_task(
            exporter_slow.export_canvas(_canvas(), _layers(), _composite(), fmt="png")
        )
        await asyncio.sleep(0)  # let the slow export reach its provider gate
        fast_version = await exporter_fast.export_canvas(
            other_canvas, _layers(), _composite(fast.png), fmt="png"
        )
        assert fast_version.content == fast.png

        gate.set()
        slow_version = await asyncio.wait_for(slow_task, timeout=5)
        assert slow_version.content == _PNG
        assert slow_provider.started == 1
        assert fast.composite_calls == 0  # composite handed in, not re-composited

    async def test_run_spine_identity_lands_on_version(self) -> None:
        recorded: dict[str, str] = {}

        class FakeSpine:
            async def execute_export(self, *, canvas_id, actor_principal_id, executor):
                run_id, node_run_id, attempt_id = (
                    "run-canonical-1",
                    "node-canonical-1",
                    "attempt-canonical-1",
                )
                invocation, _ = await executor(run_id, node_run_id, attempt_id)
                recorded["invocation"] = invocation.invocation_id
                return run_id, node_run_id, attempt_id

        exporter, _invocations, _unused = _make_exporter()
        exporter._run_spine = FakeSpine()
        version = await exporter.export_canvas(_canvas(), _layers(), _composite(), fmt="png")
        assert version.run_id == "run-canonical-1"
        assert version.node_run_id == "node-canonical-1"
        assert version.attempt_id == "attempt-canonical-1"
        assert version.invocation_id == recorded["invocation"]


# ── Media type table ────────────────────────────────────────────────────


def test_export_media_type_table() -> None:
    assert export_media_type("png") == "image/png"
    assert export_media_type("jpg") == "image/jpeg"
    assert export_media_type("jpeg") == "image/jpeg"  # legacy alias of jpg
    assert export_media_type("webp") == "image/webp"
    assert export_media_type("html").startswith("text/html")
    assert "presentationml" in export_media_type("pptx")
    assert export_media_type("pdf") == ""
    assert export_media_type("svg") == ""
