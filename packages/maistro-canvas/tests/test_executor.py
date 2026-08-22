"""Tests for the canvas job executor (#171).

`canvas/executor.py` had **0% coverage** and is live code — `canvas/routes.py`
and `canvas/runner.py` both import it. It was invisible to the coverage report
rather than reported at zero, because `canvas/` has no `__init__.py`; see
`test_compositor.py` for the mechanism.

The module docstring states two contracts, and both are load-bearing:

1. *"enforces all invariants from spec 1189 before touching the store"* — every
   pre-condition rejection must happen with nothing written.
2. *"raw provider exceptions never surface to callers. `_sanitise_error()`
   strips stack traces and internal details"* — this one is a **security**
   claim. A provider error body can carry an API key, an internal hostname, or
   a bucket path, and the failure lands in `job.error_message`, which the API
   serves to the caller. `TestErrorSanitisation` is written against that, not
   against the branch table.
"""

from __future__ import annotations

import asyncio

import pytest

from maistro_canvas.canvas.executor import CanvasExecutor, _sanitise_error
from maistro_canvas.protocols import ImageData
from maistro_canvas.types import (
    CanvasNotFoundError,
    CanvasRecord,
    GenerationJobRecord,
    JobAction,
    JobAlreadyTerminalError,
    JobInProgressError,
    JobNotDoneError,
    JobNotFoundError,
    JobStatus,
    LayerNotFoundError,
    LayerRecord,
    LayerType,
    PromptBlockedError,
    RefineNoSourceError,
    TextLayerNoGenError,
    UnknownModelError,
    VariantIndexOutOfRangeError,
)


class FakeStore:
    """The slice of `CanvasStore` the executor touches, over dicts.

    Real objects rather than mocks: several tests below assert that a rejected
    pre-condition wrote *nothing*, and `writes` is what makes that observable.
    A `Mock` would record the call and still satisfy an assertion about the
    return value.
    """

    def __init__(self) -> None:
        self.canvases: dict[str, CanvasRecord] = {}
        self.layers: dict[str, LayerRecord] = {}
        self.jobs: dict[str, GenerationJobRecord] = {}
        self.writes: list[str] = []

    async def get_canvas(self, canvas_id):
        return self.canvases.get(canvas_id)

    async def update_canvas(self, canvas):
        self.writes.append(f"update_canvas:{canvas.id}")
        self.canvases[canvas.id] = canvas
        return canvas

    async def get_layer(self, layer_id):
        return self.layers.get(layer_id)

    async def update_layer(self, layer):
        self.writes.append(f"update_layer:{layer.id}")
        self.layers[layer.id] = layer
        return layer

    async def get_job(self, job_id):
        return self.jobs.get(job_id)

    async def create_job(self, job):
        self.writes.append(f"create_job:{job.id}")
        self.jobs[job.id] = job
        return job

    async def update_job(self, job):
        self.writes.append(f"update_job:{job.id}")
        self.jobs[job.id] = job
        return job

    async def active_job_for_layer(self, layer_id):
        return next(
            (j for j in self.jobs.values() if j.layer_id == layer_id and j.is_active()), None
        )


class FakeImageClient:
    def __init__(self, *, urls=("u1",), refine_url="r1", fail=None) -> None:
        self.urls = list(urls)
        self.refine_url = refine_url
        self.fail = fail
        self.generate_calls: list[dict] = []
        self.refine_calls: list[dict] = []

    async def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        if self.fail:
            raise self.fail
        return [ImageData(width=8, height=8, url=u) for u in self.urls]

    async def refine(self, **kwargs):
        self.refine_calls.append(kwargs)
        if self.fail:
            raise self.fail
        return ImageData(width=8, height=8, url=self.refine_url)


class FakeRegistry:
    def __init__(self, *, registered=("m1",), default="m1") -> None:
        self.registered = set(registered)
        self.default = default

    def is_registered(self, model_id):
        return model_id in self.registered

    def get_default_draft(self):
        return self.default


class FakeWarden:
    def __init__(self, verdict="ALLOW") -> None:
        self.verdict = verdict
        self.scanned: list[str] = []

    async def scan_prompt(self, prompt):
        self.scanned.append(prompt)
        return self.verdict


@pytest.fixture
def store():
    s = FakeStore()
    s.canvases["c1"] = CanvasRecord(id="c1", name="c", width=64, height=48)
    s.layers["l1"] = LayerRecord(id="l1", canvas_id="c1", name="l", layer_type=LayerType.BACKGROUND)
    return s


@pytest.fixture
def client():
    return FakeImageClient()


@pytest.fixture
def warden():
    return FakeWarden()


@pytest.fixture
def executor(store, client, warden):
    return CanvasExecutor(
        store=store, image_client=client, model_registry=FakeRegistry(), warden=warden
    )


class TestErrorSanitisation:
    """The security half of the module's stated contract.

    A provider error body reaches `job.error_message`, which the API serves.
    These assert on what must *not* be in the output, because a test that only
    checks the friendly string still passes if the raw message is appended.
    """

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("HTTP 429 Too Many Requests", "rate limit reached"),
            ("rate_limit exceeded", "rate limit reached"),
            ("RateLimit hit", "rate limit reached"),
            ("too many requests", "rate limit reached"),
            ("HTTP 503", "temporarily unavailable"),
            ("Service Unavailable", "temporarily unavailable"),
            ("HTTP 401", "authentication error"),
            ("HTTP 403", "authentication error"),
            ("Unauthorized", "authentication error"),
            ("Forbidden", "authentication error"),
            ("connection timeout", "timed out"),
            ("request timed out", "timed out"),
            ("some novel failure", "provider error"),
        ],
    )
    def test_each_class_maps_to_its_safe_message(self, raw, expected):
        assert expected in _sanitise_error(Exception(raw))

    @pytest.mark.parametrize(
        "secret",
        [
            "sk-live-4f9a2c8d1e",
            "postgres://canvas:hunter2@10.0.0.4:5432/canvas",
            "s3://internal-canvas-bucket/private/key.png",
            'File "/srv/app/canvas/executor.py", line 288, in _execute_generate',
        ],
    )
    def test_no_sanitised_message_carries_the_raw_body(self, secret):
        """The property the contract actually promises. Written against the
        secret rather than the prefix: appending the raw message to a friendly
        one would satisfy every test above and leak all the same."""
        message = _sanitise_error(RuntimeError(f"provider said: {secret}"))
        assert secret not in message
        assert "provider said" not in message

    def test_a_classified_error_still_carries_no_raw_detail(self):
        leaky = "429 Too Many Requests for key sk-live-abcdef at 10.0.0.7"
        message = _sanitise_error(Exception(leaky))
        assert "rate limit reached" in message
        assert "sk-live-abcdef" not in message
        assert "10.0.0.7" not in message

    def test_an_exception_with_no_message_is_still_handled(self):
        assert "provider error" in _sanitise_error(RuntimeError())


class TestStartJobPreconditions:
    """Every rejection must leave the store untouched — the module claims the
    invariants are enforced *before* touching it."""

    async def test_a_valid_request_creates_a_pending_job(self, executor, store):
        job = await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.GENERATE, prompt="a cat"
        )
        assert job.status == JobStatus.PENDING
        assert store.jobs[job.id] is job
        assert job.model_id == "m1"

    async def test_an_unknown_layer_is_rejected(self, executor, store):
        with pytest.raises(LayerNotFoundError, match="nope"):
            await executor.start_job(canvas_id="c1", layer_id="nope", action=JobAction.GENERATE)
        assert store.writes == []

    async def test_a_text_layer_cannot_use_an_image_gen_action(self, executor, store):
        store.layers["t1"] = LayerRecord(
            id="t1", canvas_id="c1", name="t", layer_type=LayerType.TEXT
        )
        with pytest.raises(TextLayerNoGenError):
            await executor.start_job(canvas_id="c1", layer_id="t1", action=JobAction.GENERATE)
        assert store.writes == []

    async def test_a_text_layer_may_still_use_a_non_image_action(self, executor, store):
        store.layers["t1"] = LayerRecord(
            id="t1", canvas_id="c1", name="t", layer_type=LayerType.TEXT
        )
        job = await executor.start_job(canvas_id="c1", layer_id="t1", action=JobAction.TEXT)
        assert job.status == JobStatus.PENDING

    async def test_an_unregistered_model_is_rejected(self, executor, store):
        with pytest.raises(UnknownModelError, match="ghost"):
            await executor.start_job(
                canvas_id="c1", layer_id="l1", action=JobAction.GENERATE, model_id="ghost"
            )
        assert store.writes == []

    async def test_the_default_draft_model_is_used_when_none_is_given(self, executor):
        job = await executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.GENERATE)
        assert job.model_id == "m1"

    async def test_a_blocked_prompt_is_rejected_and_nothing_is_stored(self, store, client):
        """The warden verdict must stop the job before it exists — a blocked
        prompt persisted as a pending job would be retried by the runner."""
        blocked = CanvasExecutor(
            store=store,
            image_client=client,
            model_registry=FakeRegistry(),
            warden=FakeWarden("BLOCK"),
        )
        with pytest.raises(PromptBlockedError):
            await blocked.start_job(
                canvas_id="c1", layer_id="l1", action=JobAction.GENERATE, prompt="bad"
            )
        assert store.writes == []

    async def test_an_empty_prompt_is_not_scanned(self, executor, warden):
        await executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.GENERATE)
        assert warden.scanned == []

    async def test_a_non_empty_prompt_is_scanned(self, executor, warden):
        await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.GENERATE, prompt="a cat"
        )
        assert warden.scanned == ["a cat"]

    async def test_refine_without_a_source_image_is_rejected(self, executor, store):
        with pytest.raises(RefineNoSourceError, match="l1"):
            await executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.REFINE)
        assert store.writes == []

    async def test_refine_with_a_source_image_is_accepted(self, executor, store):
        store.layers["l1"].image_path = "existing.png"
        job = await executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.REFINE)
        assert job.action == JobAction.REFINE

    async def test_a_second_job_on_a_busy_layer_is_rejected(self, executor, store):
        first = await executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.GENERATE)
        with pytest.raises(JobInProgressError, match=first.id):
            await executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.GENERATE)

    async def test_a_layer_is_free_again_once_its_job_is_terminal(self, executor, store):
        first = await executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.GENERATE)
        first.status = JobStatus.DONE
        second = await executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.GENERATE)
        assert second.id != first.id

    async def test_concurrent_starts_on_one_layer_serialise_to_one_job(self, executor):
        """The per-layer lock. Without it both coroutines read
        `active_job_for_layer` as None before either wrote, and the layer ends
        up with two live jobs racing to set `image_path`."""
        results = await asyncio.gather(
            executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.GENERATE),
            executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.GENERATE),
            return_exceptions=True,
        )
        created = [r for r in results if isinstance(r, GenerationJobRecord)]
        rejected = [r for r in results if isinstance(r, JobInProgressError)]
        assert len(created) == 1
        assert len(rejected) == 1

    async def test_different_layers_do_not_block_each_other(self, executor, store):
        store.layers["l2"] = LayerRecord(id="l2", canvas_id="c1", name="l2")
        results = await asyncio.gather(
            executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.GENERATE),
            executor.start_job(canvas_id="c1", layer_id="l2", action=JobAction.GENERATE),
        )
        assert len({job.id for job in results}) == 2

    async def test_the_params_are_carried_onto_the_job(self, executor):
        job = await executor.start_job(
            canvas_id="c1",
            layer_id="l1",
            action=JobAction.GENERATE,
            count=3,
            seed=0,
            negative_prompt="blurry",
            region="top",
            strength=0.9,
        )
        assert job.params == {
            "count": 3,
            "seed": 0,
            "negative_prompt": "blurry",
            "region": "top",
            "strength": 0.9,
        }


class TestRunJob:
    async def _pending(self, executor, **kwargs):
        return await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.GENERATE, **kwargs
        )

    async def test_a_successful_run_records_the_result_paths(self, executor, store):
        job = await self._pending(executor)
        done = await executor.run_job(job.id)
        assert done.status == JobStatus.DONE
        assert done.result_paths == ["u1"]
        assert done.started_at is not None
        assert done.completed_at is not None

    async def test_an_unknown_job_raises(self, executor):
        with pytest.raises(JobNotFoundError, match="ghost"):
            await executor.run_job("ghost")

    async def test_a_non_pending_job_is_returned_unchanged(self, executor, store):
        job = await self._pending(executor)
        job.status = JobStatus.DONE
        before = len(store.writes)
        assert (await executor.run_job(job.id)).status == JobStatus.DONE
        assert len(store.writes) == before, "a terminal job was written again"

    async def test_a_provider_failure_marks_the_job_failed_with_a_safe_message(self, store, warden):
        """The two contracts meeting: the job fails cleanly *and* the message
        the API will serve carries nothing from the provider."""
        leaky = RuntimeError("500 boom at postgres://user:pw@10.0.0.9/db")
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageClient(fail=leaky),
            model_registry=FakeRegistry(),
            warden=warden,
        )
        job = await self._pending(executor)
        failed = await executor.run_job(job.id)
        assert failed.status == JobStatus.FAILED
        assert "10.0.0.9" not in failed.error_message
        assert "pw" not in failed.error_message
        assert failed.completed_at is not None

    async def test_a_missing_canvas_fails_the_job_rather_than_raising(self, executor, store):
        job = await self._pending(executor)
        del store.canvases["c1"]
        failed = await executor.run_job(job.id)
        assert failed.status == JobStatus.FAILED

    async def test_execute_action_surfaces_the_missing_canvas_directly(self, executor, store):
        job = await self._pending(executor)
        del store.canvases["c1"]
        with pytest.raises(CanvasNotFoundError, match="c1"):
            await executor._execute_action(job)

    async def test_a_non_image_gen_action_is_refused_by_the_dispatcher(self, executor, store):
        job = GenerationJobRecord(id="j", layer_id="l1", canvas_id="c1", action=JobAction.COMPOSITE)
        with pytest.raises(ValueError, match="not an image-gen action"):
            await executor._execute_action(job)

    async def test_execute_claimed_records_paths_without_touching_status(self, executor, store):
        """The `CanvasJobRunner` contract: the runner owns status and lease
        transitions, so this must not write either."""
        job = await self._pending(executor)
        before = len(store.writes)
        await executor._execute_claimed(job)
        assert job.result_paths == ["u1"]
        assert job.status == JobStatus.PENDING
        assert len(store.writes) == before


class TestGenerate:
    async def test_the_canvas_dimensions_are_passed_to_the_provider(self, executor, client):
        job = await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.GENERATE, count=1, seed=7
        )
        await executor.run_job(job.id)
        call = client.generate_calls[0]
        assert (call["width"], call["height"]) == (64, 48)
        assert call["seed"] == 7

    async def test_seed_zero_is_passed_through_rather_than_read_as_unset(self, executor, client):
        """`0` is a valid seed and falsy. A `params.get("seed") or None` would
        silently make every seed-0 generation non-reproducible."""
        job = await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.GENERATE, seed=0
        )
        await executor.run_job(job.id)
        assert client.generate_calls[0]["seed"] == 0

    async def test_urls_without_a_value_are_dropped(self, store, warden):
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageClient(urls=("a", "", "b")),
            model_registry=FakeRegistry(),
            warden=warden,
        )
        job = await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.GENERATE, count=3
        )
        assert (await executor.run_job(job.id)).result_paths == ["a", "b"]

    async def test_no_usable_urls_fails_the_job(self, store, warden):
        """A provider that returns 200 with empty URLs must not read as success
        — the layer would accept an empty `image_path` and render nothing."""
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageClient(urls=("", "")),
            model_registry=FakeRegistry(),
            warden=warden,
        )
        job = await executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.GENERATE)
        failed = await executor.run_job(job.id)
        assert failed.status == JobStatus.FAILED
        assert "provider error" in failed.error_message

    async def test_fewer_images_than_requested_still_succeeds(self, store, warden):
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageClient(urls=("only-one",)),
            model_registry=FakeRegistry(),
            warden=warden,
        )
        job = await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.GENERATE, count=4
        )
        done = await executor.run_job(job.id)
        assert done.status == JobStatus.DONE
        assert done.result_paths == ["only-one"]


class TestRefine:
    async def test_the_layers_current_image_is_the_refine_source(self, executor, store, client):
        store.layers["l1"].image_path = "before.png"
        job = await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.REFINE, region="top", strength=0.3
        )
        done = await executor.run_job(job.id)
        assert client.refine_calls[0]["source_url"] == "before.png"
        assert client.refine_calls[0]["region"] == "top"
        assert client.refine_calls[0]["strength"] == 0.3
        assert done.result_paths == ["r1"]

    async def test_losing_the_source_between_start_and_run_fails_the_job(self, executor, store):
        """Checked again at execution time, not only at start: the two are
        separated by a queue, and the layer can change in between."""
        store.layers["l1"].image_path = "before.png"
        job = await executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.REFINE)
        store.layers["l1"].image_path = None
        assert (await executor.run_job(job.id)).status == JobStatus.FAILED

    async def test_a_refine_returning_no_url_yields_no_paths(self, store, warden):
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageClient(refine_url=""),
            model_registry=FakeRegistry(),
            warden=warden,
        )
        store.layers["l1"].image_path = "before.png"
        job = await executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.REFINE)
        assert (await executor.run_job(job.id)).result_paths == []


class TestReference:
    async def test_a_hero_image_plus_three_turnaround_views(self, executor, store, client):
        job = await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.REFERENCE, prompt="a knight"
        )
        done = await executor.run_job(job.id)
        assert done.result_paths == ["u1", "r1", "r1", "r1"]
        assert [c["prompt"].rsplit(",", 1)[0].split()[-2:] for c in client.refine_calls] == [
            ["side", "view"],
            ["back", "view"],
            ["3/4", "view"],
        ]

    async def test_the_hero_is_generated_from_the_front(self, executor, client):
        job = await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.REFERENCE, prompt="a knight"
        )
        await executor.run_job(job.id)
        assert "front view" in client.generate_calls[0]["prompt"]

    async def test_no_hero_means_no_views_are_attempted(self, store, warden):
        """Refining against an empty source URL would send three doomed calls
        to the provider for each failed hero."""
        client = FakeImageClient(urls=("",))
        executor = CanvasExecutor(
            store=store, image_client=client, model_registry=FakeRegistry(), warden=warden
        )
        job = await executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.REFERENCE)
        assert (await executor.run_job(job.id)).result_paths == []
        assert client.refine_calls == []

    async def test_views_that_come_back_empty_are_dropped_not_padded(self, store, warden):
        client = FakeImageClient(urls=("hero",), refine_url="")
        executor = CanvasExecutor(
            store=store, image_client=client, model_registry=FakeRegistry(), warden=warden
        )
        job = await executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.REFERENCE)
        assert (await executor.run_job(job.id)).result_paths == ["hero"]


class TestAcceptVariant:
    async def _done(self, executor, store, paths=("a", "b", "c")):
        job = await executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.GENERATE)
        job.status = JobStatus.DONE
        job.result_paths = list(paths)
        return job

    async def test_accepting_sets_the_layer_image_and_records_the_index(self, executor, store):
        job = await self._done(executor, store)
        updated_job, layer = await executor.accept_variant(job.id, 1)
        assert layer.image_path == "b"
        assert updated_job.selected_index == 1

    async def test_accepting_advances_the_canvas_timestamp(self, executor, store):
        """The `canvas_updated_on_layer_accept` invariant — a client polling
        `updated_at` for changes would otherwise never see the new image."""
        job = await self._done(executor, store)
        before = store.canvases["c1"].updated_at
        await executor.accept_variant(job.id, 0)
        assert store.canvases["c1"].updated_at > before

    async def test_an_unknown_job_raises(self, executor):
        with pytest.raises(JobNotFoundError):
            await executor.accept_variant("ghost", 0)

    async def test_a_job_that_is_not_done_cannot_be_accepted(self, executor, store):
        job = await executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.GENERATE)
        with pytest.raises(JobNotDoneError, match="pending"):
            await executor.accept_variant(job.id, 0)

    @pytest.mark.parametrize("index", [-1, 3, 99])
    async def test_an_out_of_range_index_is_refused(self, executor, store, index):
        """`-1` matters on its own: Python would happily index it, silently
        accepting the last variant when the caller asked for something else."""
        job = await self._done(executor, store)
        with pytest.raises(VariantIndexOutOfRangeError):
            await executor.accept_variant(job.id, index)
        assert store.layers["l1"].image_path is None

    async def test_a_job_whose_layer_vanished_raises(self, executor, store):
        job = await self._done(executor, store)
        del store.layers["l1"]
        with pytest.raises(LayerNotFoundError):
            await executor.accept_variant(job.id, 0)

    async def test_a_vanished_canvas_does_not_undo_the_accepted_layer(self, executor, store):
        """The canvas touch is best-effort; losing it must not cost the user
        the variant they accepted."""
        job = await self._done(executor, store)
        del store.canvases["c1"]
        _, layer = await executor.accept_variant(job.id, 2)
        assert layer.image_path == "c"


class TestCancelJob:
    async def test_a_pending_job_can_be_cancelled(self, executor, store):
        job = await executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.GENERATE)
        cancelled = await executor.cancel_job(job.id)
        assert cancelled.status == JobStatus.CANCELLED
        assert cancelled.completed_at is not None

    async def test_a_running_job_can_be_cancelled(self, executor, store):
        job = await executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.GENERATE)
        job.status = JobStatus.RUNNING
        assert (await executor.cancel_job(job.id)).status == JobStatus.CANCELLED

    async def test_an_unknown_job_raises(self, executor):
        with pytest.raises(JobNotFoundError):
            await executor.cancel_job("ghost")

    @pytest.mark.parametrize("status", [JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED])
    async def test_a_terminal_job_cannot_be_cancelled(self, executor, store, status):
        """Re-cancelling a done job would rewrite `completed_at` and lose when
        the work actually finished."""
        job = await executor.start_job(canvas_id="c1", layer_id="l1", action=JobAction.GENERATE)
        job.status = status
        with pytest.raises(JobAlreadyTerminalError):
            await executor.cancel_job(job.id)


class TestLayerLocks:
    def test_one_lock_per_layer_reused_across_calls(self, executor):
        """A fresh lock per call would serialise nothing."""
        assert executor._layer_lock("x") is executor._layer_lock("x")
        assert executor._layer_lock("x") is not executor._layer_lock("y")
