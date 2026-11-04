"""Bounded Canvas layer scale before image allocation (#393).

At the parent commit, a layer's ``scale`` reached ``PIL.resize`` unbounded:
``scale=1e6`` on a 1024px layer computed a ~1.024e9-px-wide target and
attempted a ~4e18-byte allocation (memory/CPU denial of service), NaN was
silently accepted, and ``float('inf')`` crashed with a raw ``OverflowError``.

These tests pin the fix contract:

- every numeric boundary (NaN, ±inf, zero, negative, overflow-scale,
  string-encoded values, wrong types) is rejected with a typed
  :class:`LayerScaleLimitError` *before* any pixel allocation;
- computed resize targets are bounded by server-configured per-side,
  per-image and cumulative per-request pixel caps
  (:class:`LayerPixelBudgetError`);
- decode/resize runs in a worker bounded by a configured timeout
  (:class:`CompositeTimeoutError`);
- a rejected composite produces no output and nothing is persisted;
- the limits are server-configurable via environment variables and
  observable (logged, pinned onto Pillow's decompression guard).

The property tests drive the validator with arbitrary IEEE-754 floats
(including NaN and both infinities) and arbitrary JSON scalars, asserting
the total contract: a valid finite float inside the cap, or a typed
rejection — never a crash, never a silent acceptance.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from PIL import Image

from maistro_canvas.canvas.compositor import PilCompositorService, _transform_layer_image
from maistro_canvas.canvas.limits import (
    CanvasImageLimits,
    PixelBudget,
    configure_pillow_decompression_limit,
    load_image_limits,
    rotated_dimensions,
    run_with_resize_timeout,
    scaled_dimensions,
    validate_scale,
)
from maistro_canvas.canvas.routes import _make_canvas_router
from maistro_canvas.types import (
    CanvasRecord,
    CompositeTimeoutError,
    LayerPixelBudgetError,
    LayerRecord,
    LayerScaleLimitError,
)

RED = (255, 0, 0, 255)

SMALL_LIMITS = CanvasImageLimits(
    max_scale=64.0,
    max_layer_pixels=10_000,
    max_request_pixels=25_000,
    max_dimension=1_000,
    resize_timeout_s=5.0,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _png(size: tuple[int, int], color: tuple[int, int, int, int] = RED) -> bytes:
    img = Image.new("RGBA", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class _RecordingResize:
    """Patch target that records every ``Image.resize`` call site request."""

    def __init__(self) -> None:
        self.requested: list[tuple[int, int]] = []

    def __call__(self, pil_resize: Any) -> Any:
        def wrapper(image: Image.Image, size: tuple[int, int], *args: Any, **kwargs: Any) -> Any:
            self.requested.append(tuple(size))
            return pil_resize(image, size, *args, **kwargs)

        return wrapper


class _DictImageStore:
    """An ImageStore over in-memory PNG bytes (per-layer path -> bytes)."""

    def __init__(self, images: dict[str, bytes]) -> None:
        self._images = images
        self.fetch_count = 0

    async def fetch(self, url: str) -> Image.Image:
        self.fetch_count += 1
        return Image.open(io.BytesIO(self._images[url]))


class _RecordingStore:
    """Fake CanvasStore that records whether a composite was persisted."""

    def __init__(self) -> None:
        self.saved: list[Any] = []

    async def latest_composite(self, canvas_id: str, *, org_id: str) -> None:
        return None

    async def save_composite(self, comp: Any, *, org_id: str) -> Any:
        self.saved.append(comp)
        return comp


class _RecordingRotate:
    """Patch target that records every ``Image.rotate`` call site request."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, pil_rotate: Any) -> Any:
        def wrapper(image: Image.Image, angle: float, *args: Any, **kwargs: Any) -> Any:
            self.calls.append({"angle": angle, "size": image.size, "kwargs": kwargs})
            return pil_rotate(image, angle, *args, **kwargs)

        return wrapper


class _RecordingOpen:
    """Patch target that records every ``Image.open`` decode request."""

    def __init__(self, pil_open: Any) -> None:
        self._open = pil_open
        self.calls: list[bytes] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(b"<open>")
        return self._open(*args, **kwargs)


def _canvas(width: int = 1024, height: int = 1024) -> CanvasRecord:
    return CanvasRecord(id="c1", name="c", width=width, height=height)


def _layer(
    layer_id: str,
    image_path: str,
    *,
    scale: float,
    z_index: int = 0,
) -> LayerRecord:
    return LayerRecord(
        id=layer_id,
        canvas_id="c1",
        name=layer_id,
        image_path=image_path,
        scale=scale,
        z_index=z_index,
    )


@pytest.fixture
def recording_resize(monkeypatch: pytest.MonkeyPatch) -> Iterator[_RecordingResize]:
    recorder = _RecordingResize()
    monkeypatch.setattr(Image.Image, "resize", recorder(Image.Image.resize))
    yield recorder


# ---------------------------------------------------------------------------
# validate_scale — numeric boundaries (fuzz + table)
# ---------------------------------------------------------------------------


class TestValidateScaleBoundaries:
    @pytest.mark.parametrize(
        ("bad_scale", "reason"),
        [
            (float("nan"), "NaN"),
            (float("inf"), "+infinity"),
            (float("-inf"), "-infinity"),
            (0.0, "zero"),
            (-0.0, "negative zero"),
            (-1.0, "negative"),
            (1e6, "demonstrated DoS payload"),
            (1e300, "overflow-scale"),
            (65.0, "above max_scale"),
            ("1e6", "string-encoded number"),
            ("nan", "string-encoded NaN"),
            ("inf", "string-encoded infinity"),
            (True, "bool is not a scale"),
            (False, "bool is not a scale"),
            (None, "null"),
            ([2.0], "list"),
            ({"scale": 2.0}, "object"),
        ],
    )
    def test_rejected_scales(self, bad_scale: Any, reason: str) -> None:
        with pytest.raises(LayerScaleLimitError, match="scale"):
            validate_scale(bad_scale, SMALL_LIMITS)

    @pytest.mark.parametrize("good_scale", [1.0, 2, 0.001, 0.5, 64.0, 63.999])
    def test_accepted_scales_pass_through_as_float(self, good_scale: Any) -> None:
        assert validate_scale(good_scale, SMALL_LIMITS) == float(good_scale)

    @settings(max_examples=500, deadline=None)
    @given(scale=st.floats(allow_nan=True, allow_infinity=True))
    def test_any_float_is_valid_or_typed_rejected(self, scale: float) -> None:
        """Total contract: no float input can crash or silently pass."""
        try:
            value = validate_scale(scale, SMALL_LIMITS)
        except LayerScaleLimitError:
            return
        assert value == scale
        assert 0.0 < value <= SMALL_LIMITS.max_scale

    @settings(max_examples=300, deadline=None)
    @given(scale=st.one_of(st.text(), st.booleans(), st.none(), st.integers()))
    def test_any_json_scalar_is_valid_or_typed_rejected(self, scale: Any) -> None:
        """Encoded (string) and non-numeric JSON scalars never parse into a scale."""
        try:
            value = validate_scale(scale, SMALL_LIMITS)
        except LayerScaleLimitError:
            return
        assert isinstance(scale, int) and not isinstance(scale, bool)
        assert 0.0 < value <= SMALL_LIMITS.max_scale

    @settings(max_examples=300, deadline=None)
    @given(
        scale=st.floats(min_value=0.001, max_value=64.0, allow_nan=False),
        src=st.integers(min_value=1, max_value=1_000_000),
    )
    def test_accepted_scale_yields_bounded_target_or_budget_error(
        self, scale: float, src: int
    ) -> None:
        """For any accepted scale, the target is either bounded or typed-rejected."""
        try:
            w, h = scaled_dimensions(src, src, scale, SMALL_LIMITS)
        except LayerPixelBudgetError:
            return
        assert 1 <= w <= SMALL_LIMITS.max_dimension
        assert 1 <= h <= SMALL_LIMITS.max_dimension
        assert w * h <= SMALL_LIMITS.max_layer_pixels


# ---------------------------------------------------------------------------
# scaled_dimensions — computed target bounds before allocation
# ---------------------------------------------------------------------------


class TestScaledDimensions:
    def test_demonstrated_payload_is_rejected_before_allocation(
        self, recording_resize: _RecordingResize
    ) -> None:
        """scale=1e6 on a 1024px layer once targeted ~1.024e9 px per side."""
        img = Image.new("RGBA", (1024, 1024), RED)
        with pytest.raises(LayerScaleLimitError, match="maximum"):
            _transform_layer_image(
                img,
                canvas_w=1024,
                canvas_h=1024,
                x=0,
                y=0,
                scale=1e6,
                rotation=0.0,
                opacity=1.0,
                limits=SMALL_LIMITS,
            )
        assert recording_resize.requested == []

    def test_extreme_aspect_target_is_rejected(self) -> None:
        """A 500000x1 target violates the per-side cap even at legal scale."""
        with pytest.raises(LayerPixelBudgetError, match="per-side"):
            scaled_dimensions(500_000, 1, 1.0, SMALL_LIMITS)

    def test_pixel_overflow_is_rejected_even_at_small_scale(self) -> None:
        """A target past the per-image pixel cap is rejected before resize."""
        with pytest.raises(LayerPixelBudgetError, match="per-image"):
            scaled_dimensions(90, 90, 3.0, SMALL_LIMITS)

    def test_downscale_of_large_source_is_allowed(self) -> None:
        w, h = scaled_dimensions(1_000, 1_000, 0.1, SMALL_LIMITS)
        assert (w, h) == (100, 100)


# ---------------------------------------------------------------------------
# Cumulative multi-layer budget
# ---------------------------------------------------------------------------


class TestPixelBudget:
    def test_charges_accumulate(self) -> None:
        budget = PixelBudget(SMALL_LIMITS)
        budget.charge(100, 100)
        budget.charge(100, 100)
        assert budget.remaining == SMALL_LIMITS.max_request_pixels - 20_000

    def test_exhaustion_is_typed_and_leaves_remaining_untouched(self) -> None:
        budget = PixelBudget(SMALL_LIMITS)
        budget.charge(100, 100)
        with pytest.raises(LayerPixelBudgetError, match="per-request budget"):
            budget.charge(200, 200)
        assert budget.remaining == SMALL_LIMITS.max_request_pixels - 10_000

    def test_cumulative_multi_layer_abuse_rejected_in_composite(self) -> None:
        """Three 100x100px resizes fit; the 4th exceeds the 25000px request budget."""
        store = _DictImageStore({f"l{i}": _png((10, 10)) for i in range(4)})
        compositor = PilCompositorService(store)
        limits = CanvasImageLimits(
            max_scale=64.0,
            max_layer_pixels=10_000,
            max_request_pixels=25_000,
            max_dimension=1_000,
            resize_timeout_s=5.0,
        )
        compositor._limits = limits  # test injection of the server config
        layers = [_layer(f"l{i}", f"l{i}", scale=10.0, z_index=i) for i in range(4)]
        with pytest.raises(LayerPixelBudgetError, match="per-request budget"):
            _run(compositor.composite(_canvas(), layers))


def _run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# End-to-end compositor: rejection before allocation, no partial persistence
# ---------------------------------------------------------------------------


class TestCompositorScaleEnforcement:
    def test_scale_payload_rejected_before_pil_allocation(self) -> None:
        """The demonstrated 1e6 payload never reaches PIL.resize (#393 DoD)."""
        store = _DictImageStore({"big": _png((1024, 1024))})
        persist = _RecordingStore()
        compositor = PilCompositorService(store)
        compositor._limits = SMALL_LIMITS
        recording = _RecordingResize()
        original = Image.Image.resize
        Image.Image.resize = recording(original)
        try:
            with pytest.raises(LayerScaleLimitError, match="maximum"):
                _run(compositor.composite(_canvas(), [_layer("big", "big", scale=1e6)]))
        finally:
            Image.Image.resize = original
        assert recording.requested == []
        assert persist.saved == []

    def test_valid_layers_still_composite(self) -> None:
        store = _DictImageStore({"a": _png((10, 10))})
        compositor = PilCompositorService(store)
        compositor._limits = SMALL_LIMITS
        result = _run(compositor.composite(_canvas(), [_layer("a", "a", scale=2.0)]))
        img = Image.open(io.BytesIO(result.image_bytes))
        assert img.size == (1024, 1024)

    def test_pillow_decompression_guard_is_pinned_to_per_image_cap(self) -> None:
        limit = configure_pillow_decompression_limit(SMALL_LIMITS)
        assert limit == SMALL_LIMITS.max_layer_pixels
        assert SMALL_LIMITS.max_layer_pixels == Image.MAX_IMAGE_PIXELS

    def test_worker_timeout_is_typed(self) -> None:
        import asyncio

        async def slow() -> None:
            await asyncio.sleep(5.0)

        tight = CanvasImageLimits(resize_timeout_s=0.05)
        with pytest.raises(CompositeTimeoutError, match="timeout"):
            _run(run_with_resize_timeout(slow(), tight))


# ---------------------------------------------------------------------------
# HTTP surface: explicit 422, nothing persisted
# ---------------------------------------------------------------------------


class _FakeStore:
    """In-memory CanvasStore exposing add/get/update layer for route tests."""

    def __init__(self) -> None:
        self._canvases: dict[str, CanvasRecord] = {}
        self._layers: dict[str, LayerRecord] = {}
        self.updates: list[LayerRecord] = []

    async def create_canvas(
        self,
        *,
        name: str,
        width: int,
        height: int,
        background_color: str = "#FFFFFF",
        org_id: str = "",
    ) -> CanvasRecord:
        rec = CanvasRecord(
            id="c1",
            name=name,
            width=width,
            height=height,
            background_color=background_color,
            org_id=org_id,
        )
        self._canvases[rec.id] = rec
        return rec

    async def get_canvas(self, canvas_id: str, *, org_id: str = "") -> CanvasRecord | None:
        rec = self._canvases.get(canvas_id)
        if rec is not None and org_id and rec.org_id != org_id:
            return None
        return rec

    async def list_layers(self, canvas_id: str, *, org_id: str = "") -> list[LayerRecord]:
        return [lyr for lyr in self._layers.values() if lyr.canvas_id == canvas_id]

    async def add_layer(
        self,
        canvas_id: str,
        *,
        org_id: str,
        name: str,
        layer_type: str,
        z_index: int | None = None,
        x: float = 0.0,
        y: float = 0.0,
        scale: float = 1.0,
        rotation: float = 0.0,
        opacity: float = 1.0,
        blend_mode: str = "normal",
        visible: bool = True,
        locked: bool = False,
    ) -> LayerRecord:
        rec = LayerRecord(
            id=f"layer-{len(self._layers) + 1}",
            canvas_id=canvas_id,
            name=name,
            layer_type=layer_type,
            z_index=z_index or 0,
            x=x,
            y=y,
            scale=scale,
            rotation=rotation,
            opacity=opacity,
            blend_mode=blend_mode,
            visible=visible,
            locked=locked,
        )
        self._layers[rec.id] = rec
        return rec

    async def get_layer(self, layer_id: str, *, org_id: str) -> LayerRecord | None:
        return self._layers.get(layer_id)

    async def update_layer(self, layer: LayerRecord, *, org_id: str) -> LayerRecord:
        self._layers[layer.id] = layer
        self.updates.append(layer)
        return layer


TEST_TOKEN = "test-canvas-token"


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("CANVAS_API_TOKEN", TEST_TOKEN)
    store = _FakeStore()
    app = FastAPI()
    app.include_router(
        _make_canvas_router(
            store=store,  # type: ignore[arg-type]
            executor=object(),  # type: ignore[arg-type]
            compositor=object(),  # type: ignore[arg-type]
        ),
        prefix="/api/canvas",
    )
    client = TestClient(
        app,
        raise_server_exceptions=True,
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    )
    client.post("/api/canvas", json={"name": "c", "width": 1024, "height": 1024})
    client._store = store  # type: ignore[attr-defined]
    return client


class TestRouteScaleValidation:
    @pytest.mark.parametrize(
        "bad_scale",
        [1e6, "1e6", "nan", 0.0, -2.0, 1e300, True],
    )
    def test_add_layer_rejects_bad_scales_with_422(
        self, monkeypatch: pytest.MonkeyPatch, bad_scale: Any
    ) -> None:
        client = _client(monkeypatch)
        r = client.post("/api/canvas/c1/layers", json={"name": "l", "scale": bad_scale})
        assert r.status_code == 422, (bad_scale, r.text)
        assert "scale" in r.json()["detail"].lower()

    def test_add_layer_valid_scale_is_stored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client(monkeypatch)
        r = client.post("/api/canvas/c1/layers", json={"name": "l", "scale": 2.0})
        assert r.status_code == 201, r.text
        assert r.json()["scale"] == 2.0

    @pytest.mark.parametrize("bad_scale", [1e6, "1e6", 0.0, -1.0])
    def test_update_layer_rejects_bad_scales_without_persisting(
        self, monkeypatch: pytest.MonkeyPatch, bad_scale: Any
    ) -> None:
        client = _client(monkeypatch)
        created = client.post("/api/canvas/c1/layers", json={"name": "l", "scale": 1.0})
        layer_id = created.json()["id"]
        r = client.patch(f"/api/canvas/c1/layers/{layer_id}", json={"scale": bad_scale})
        assert r.status_code == 422, (bad_scale, r.text)
        assert client._store.updates == []  # type: ignore[attr-defined]
        assert client.get("/api/canvas/c1/layers").json()[0]["scale"] == 1.0

    def test_update_layer_rejects_encoded_string_scale(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client(monkeypatch)
        created = client.post("/api/canvas/c1/layers", json={"name": "l"})
        layer_id = created.json()["id"]
        r = client.patch(
            f"/api/canvas/c1/layers/{layer_id}",
            content=b'{"scale": "1e6"}',
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# HTTP surface: the typed #393 limit errors through the composite/export routes
# ---------------------------------------------------------------------------


class _ExplodingCompositor:
    """Compositor stub whose composite() raises the given typed error."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def composite(self, canvas: Any, layers: list[Any]) -> Any:
        raise self._exc


class _SavingStore(_FakeStore):
    """_FakeStore plus the composite-persistence calls the export/composite routes use."""

    def __init__(self) -> None:
        super().__init__()
        self.saved: list[tuple[Any, str]] = []
        self._stored: dict[str, Any] = {}

    async def latest_composite(self, canvas_id: str, *, org_id: str = "") -> Any:
        return self._stored.get(canvas_id)  # export composites on demand when empty

    async def save_composite(self, comp: Any, *, org_id: str = "") -> Any:
        self.saved.append((comp, org_id))
        self._stored[comp.canvas_id] = comp
        return comp


_TYPED_LIMIT_ERRORS = [
    (LayerScaleLimitError("scale 1e6 above the server-configured maximum of 64.0"), 422),
    (LayerPixelBudgetError("computed resize target exceeded the per-request pixel budget"), 422),
    (CompositeTimeoutError("decode/resize worker exceeded the configured timeout of 5s"), 504),
]


class TestRouteTypedRejection:
    """A layer violating the image limits yields an explicit typed HTTP error (#393)."""

    @staticmethod
    def _client(monkeypatch: pytest.MonkeyPatch, compositor: Any) -> TestClient:
        monkeypatch.setenv("CANVAS_API_TOKEN", TEST_TOKEN)
        store = _SavingStore()
        app = FastAPI()
        app.include_router(
            _make_canvas_router(
                store=store,  # type: ignore[arg-type]
                executor=object(),  # type: ignore[arg-type]
                compositor=compositor,  # type: ignore[arg-type]
            ),
            prefix="/api/canvas",
        )
        client = TestClient(
            app,
            raise_server_exceptions=True,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        client.post("/api/canvas", json={"name": "c", "width": 1024, "height": 1024})
        client._store = store  # type: ignore[attr-defined]
        return client

    @pytest.mark.parametrize(("exc", "status"), _TYPED_LIMIT_ERRORS)
    def test_composite_route_rejects_typed_limit_errors_explicitly(
        self, monkeypatch: pytest.MonkeyPatch, exc: Exception, status: int
    ) -> None:
        client = self._client(monkeypatch, _ExplodingCompositor(exc))
        r = client.post("/api/canvas/c1/composite")
        assert r.status_code == status, r.text
        body = r.json()
        assert body["code"]
        assert body["detail"]
        assert client._store.saved == []  # type: ignore[attr-defined]

    @pytest.mark.parametrize(("exc", "status"), _TYPED_LIMIT_ERRORS)
    def test_export_route_rejects_typed_limit_errors_and_persists_nothing(
        self, monkeypatch: pytest.MonkeyPatch, exc: Exception, status: int
    ) -> None:
        client = self._client(monkeypatch, _ExplodingCompositor(exc))
        r = client.get("/api/canvas/c1/export")
        assert r.status_code == status, r.text
        assert client._store.saved == []  # type: ignore[attr-defined]

    def test_export_route_returns_a_stored_composite_without_recompositing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stored composite is served as-is — the compositor is never invoked."""
        from maistro_canvas.types import CompositeResult

        compositor = _ExplodingCompositor(LayerScaleLimitError("must never be reached"))
        client = self._client(monkeypatch, compositor)
        client._store._stored["c1"] = CompositeResult(  # type: ignore[attr-defined]
            canvas_id="c1",
            image_bytes=b"\x89PNG-stored",
            width=1024,
            height=1024,
            layer_snapshot=[],
        )
        r = client.get("/api/canvas/c1/export")
        assert r.status_code == 200, r.text
        assert r.content == b"\x89PNG-stored"
        assert client._store.saved == []  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Server configuration is observable
# ---------------------------------------------------------------------------


class TestServerConfig:
    def test_limits_read_from_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAISTRO_CANVAS_MAX_SCALE", "8")
        monkeypatch.setenv("MAISTRO_CANVAS_MAX_LAYER_PIXELS", "1000")
        monkeypatch.setenv("MAISTRO_CANVAS_MAX_REQUEST_PIXELS", "2000")
        monkeypatch.setenv("MAISTRO_CANVAS_RESIZE_TIMEOUT_S", "1.5")
        limits = load_image_limits()
        assert limits.max_scale == 8.0
        assert limits.max_layer_pixels == 1000
        assert limits.max_request_pixels == 2000
        assert limits.resize_timeout_s == 1.5

    def test_malformed_overrides_fall_back_to_safe_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bad env value never *disables* a limit."""
        monkeypatch.setenv("MAISTRO_CANVAS_MAX_SCALE", "not-a-number")
        monkeypatch.setenv("MAISTRO_CANVAS_MAX_LAYER_PIXELS", "-5")
        monkeypatch.setenv("MAISTRO_CANVAS_MAX_SCALE2", "ignored")
        limits = load_image_limits()
        assert limits.max_scale == CanvasImageLimits().max_scale
        assert limits.max_layer_pixels == CanvasImageLimits().max_layer_pixels

    def test_env_disabled_zero_scale_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAISTRO_CANVAS_MAX_SCALE", "0")
        limits = load_image_limits()
        assert limits.max_scale == CanvasImageLimits().max_scale


# ---------------------------------------------------------------------------
# Repair round 3: decode/rotation allocation boundaries (#393 deep-review)
# ---------------------------------------------------------------------------


class TestScaleValidatedBeforeDecode:
    """A rejected scale never pays for a decode — the review found the
    ``convert("RGBA")`` (which forces the full pixel decode) running before
    ``validate_scale`` in both transform paths."""

    def test_scale_is_validated_before_the_source_is_fetched(self) -> None:
        """The compositor rejects the scale before the image store is hit."""
        store = _DictImageStore({"a": _png((10, 10))})
        compositor = PilCompositorService(store)
        compositor._limits = SMALL_LIMITS
        with pytest.raises(LayerScaleLimitError, match="maximum"):
            _run(compositor.composite(_canvas(), [_layer("a", "a", scale=1e6)]))
        assert store.fetch_count == 0  # no fetch, so no decode was ever forced


class TestDecodedPixelCap:
    """Pillow warns at ``MAX_IMAGE_PIXELS`` and raises only at 2x, so the
    ``[cap, 2*cap)`` window decoded above the configured per-image cap; the
    explicit post-decode check enforces the cap exactly."""

    def test_decoded_source_above_per_image_cap_is_rejected(self) -> None:
        """A 200x200 source (40k px) at a valid downscale is rejected — the
        decode itself exceeded the 10k-px per-image cap."""
        store = _DictImageStore({"big": _png((200, 200))})
        compositor = PilCompositorService(store)
        compositor._limits = SMALL_LIMITS
        recording = _RecordingResize()
        original = Image.Image.resize
        Image.Image.resize = recording(original)
        try:
            with pytest.raises(LayerPixelBudgetError, match="per-image maximum"):
                _run(compositor.composite(_canvas(), [_layer("big", "big", scale=0.5)]))
        finally:
            Image.Image.resize = original
        assert recording.requested == []


class TestRotationBoundingBox:
    """``rotate(expand=True)`` allocates the rotated bounding box — up to
    sqrt(2)x the area — which the resize-time checks never saw; the box is
    now computed, capped, and charged *before* the rotation."""

    def test_rotated_dimensions_math(self) -> None:
        generous = CanvasImageLimits(
            max_scale=64.0,
            max_layer_pixels=10_000_000,
            max_request_pixels=40_000_000,
            max_dimension=10_000,
            resize_timeout_s=5.0,
        )
        assert rotated_dimensions(100, 60, 0.0, generous) == (100, 60)
        assert rotated_dimensions(100, 60, 90.0, generous) == (60, 100)
        # 45deg on a square: each side grows by sqrt(2) (141.42 -> 142)
        assert rotated_dimensions(100, 100, 45.0, generous) == (142, 142)
        assert rotated_dimensions(100, 100, -45.0, generous) == (142, 142)

    def test_rotated_box_above_per_side_cap_is_rejected(self) -> None:
        tall = CanvasImageLimits(
            max_scale=64.0,
            max_layer_pixels=10_000_000,
            max_request_pixels=40_000_000,
            max_dimension=1_000,
            resize_timeout_s=5.0,
        )
        with pytest.raises(LayerPixelBudgetError, match="per-side maximum"):
            rotated_dimensions(900, 900, 45.0, tall)  # 1273 > 1000

    def test_rotated_box_above_per_image_cap_is_rejected_before_rotate(self) -> None:
        """A full-cap layer rotated 45deg would allocate ~2x the cap."""
        store = _DictImageStore({"r": _png((100, 100))})
        compositor = PilCompositorService(store)
        compositor._limits = SMALL_LIMITS  # per-image cap 10_000 == 100x100
        recording = _RecordingRotate()
        original = Image.Image.rotate
        Image.Image.rotate = recording(original)
        try:
            layer = _layer("r", "r", scale=1.0)
            layer.rotation = 45.0
            with pytest.raises(LayerPixelBudgetError, match="per-image maximum"):
                _run(compositor.composite(_canvas(), [layer]))
        finally:
            Image.Image.rotate = original
        assert recording.calls == []  # the rotation was never attempted

    def test_rotation_expansion_is_charged_to_the_request_budget(self) -> None:
        """The rotated box is charged too: 10k charged for the resize leaves
        5k, and the ~20k rotated box exhausts the 15k request budget."""
        store = _DictImageStore({"r": _png((100, 100))})
        compositor = PilCompositorService(store)
        compositor._limits = CanvasImageLimits(
            max_scale=64.0,
            max_layer_pixels=30_000,  # the rotated box fits the per-image cap
            max_request_pixels=15_000,  # but not the request budget
            max_dimension=1_000,
            resize_timeout_s=5.0,
        )
        layer = _layer("r", "r", scale=1.0)
        layer.rotation = 45.0
        with pytest.raises(LayerPixelBudgetError, match="per-request budget"):
            _run(compositor.composite(_canvas(), [layer]))

    def test_modest_rotation_still_composites(self) -> None:
        """A rotation whose bounding box stays inside every cap still renders."""
        store = _DictImageStore({"r": _png((10, 10))})
        compositor = PilCompositorService(store)
        compositor._limits = SMALL_LIMITS
        layer = _layer("r", "r", scale=2.0)
        layer.rotation = 45.0  # 20x20 -> 29x29 box, well inside the caps
        result = _run(compositor.composite(_canvas(), [layer]))
        assert Image.open(io.BytesIO(result.image_bytes)).size == (1024, 1024)
