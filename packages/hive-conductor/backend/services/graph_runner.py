"""Compatibility facade for Hive DAG execution.

Graph traversal and execution authority live in ``canonical_dag_runner`` and
``maistro.graph.durable_runs``. This module keeps the historical import path
for product callers while exposing only per-node compatibility helpers from
``legacy_dag_node``. It intentionally contains no dependency scheduler,
process-pool fan-out, or terminal-state implementation (#835).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from services import legacy_dag_node as _legacy_dag_node
from services.canonical_dag_runner import execute_dag as _canonical_execute_dag
from services.canonical_dag_runner import genome_to_dag
from services.dag_execution_scope import DagExecutionScope

# Historical helper imports remain available for existing tests and downstream
# callers, but their implementation now lives with the one-node compatibility
# adapter. Explicit aliases keep this facade truthful: none of these helpers
# participate in graph traversal or Run lifecycle here.
STUB_LLM_REFUSAL = _legacy_dag_node.STUB_LLM_REFUSAL
StubLLMNotAllowedError = _legacy_dag_node.StubLLMNotAllowedError
_NODE_SCRIPT = _legacy_dag_node._NODE_SCRIPT
_build_dependency_graph = _legacy_dag_node._build_dependency_graph
_build_llm_call = _legacy_dag_node._build_llm_call
_classify_node_execution = _legacy_dag_node._classify_node_execution
_invoke_subprocess_usage_hooks = _legacy_dag_node._invoke_subprocess_usage_hooks
_parse_node_script_output = _legacy_dag_node._parse_node_script_output
_run_llm_node = _legacy_dag_node._run_llm_node
_run_node_subprocess = _legacy_dag_node._run_node_subprocess
_run_subprocess_wave = _legacy_dag_node._run_subprocess_wave
_run_tool_node = _legacy_dag_node._run_tool_node
llm_gateway_configured = _legacy_dag_node.llm_gateway_configured
stub_llm_allowed = _legacy_dag_node.stub_llm_allowed

logger = logging.getLogger("hive.graph_runner")


def public_failure(exc: BaseException) -> str:
    """The failure text a transport may show: the exception kind, never its message."""
    return f"{type(exc).__name__}: execution failed; see server logs"


class CanonicalDagExecutionError(RuntimeError):
    """The canonical Run reached a non-success terminal state."""

    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        status = str(result.get("status") or "failed")
        detail = str(result.get("error") or f"canonical Run ended {status}")
        super().__init__(detail)


async def execute_dag(dag_data: dict, **kwargs: Any) -> dict[str, Any]:
    """Run through the canonical durable executor and fail closed on failure.

    Historical callers treated a normal return as successful execution. Keep
    that contract truthful by raising when canonical Run truth is not
    ``completed`` instead of letting old wrappers stamp a failed Run as
    completed.

    The raw ``_build_llm_call`` handed to the canonical executor is a
    compatibility fallback only (#718): when the bridge Container and gateway
    are configured, a node's model call crosses the governed Binding ->
    Invocation egress and this builder is never used for it; the canonical
    Invocation authority records the quota evidence. The injection stays so
    tests that patch this module's attribute keep working. New Graph work
    always requires the canonical Run and continuation owners (#1113).
    """
    result = await _canonical_execute_dag(
        dag_data,
        llm_builder=_build_llm_call,
        **kwargs,
    )
    if result.get("status") != "completed":
        raise CanonicalDagExecutionError(result)
    return result


def _node_frames(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "status": "node_complete",
            "node_id": node_id,
            "role": node_result.get("role", "worker"),
            "response": node_result.get("response", ""),
            "success": bool(node_result.get("success")),
            "run_id": result.get("run_id"),
        }
        for node_id, node_result in result.get("node_results", {}).items()
    ]


#: Idle interval between websocket heartbeat frames (#1183). Matched to the
#: SSE route's 15s keepalive comment: intermediaries treat both transports
#: alike, and a client can distinguish alive-idle from a dead socket after
#: at most one interval.
STREAM_HEARTBEAT_SECONDS = 15.0

#: Ceiling on the live-progress channel between node execution and the
#: streaming generator (#1183). A consumer that stops reading cannot grow
#: server memory without bound: excess live frames are dropped (counted),
#: and the stream says so explicitly instead of presenting a contiguous
#: stream that silently lost events.
STREAM_PROGRESS_QUEUE_MAX = 256


class _ProgressChannel:
    """Bounded hand-off of live node frames from the executing Run to the stream.

    `publish` never blocks and never raises: a stalled stream consumer must
    not stall the canonical Run, so overflow is counted (and later reported
    as a resync condition) rather than buffered without bound.
    """

    __slots__ = ("dropped", "queue")

    def __init__(self, maxsize: int) -> None:
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=maxsize)
        self.dropped: int = 0

    def publish(self, frame: dict[str, Any]) -> bool:
        try:
            self.queue.put_nowait(frame)
        except asyncio.QueueFull:
            self.dropped += 1
            return False
        return True

    def drain(self) -> list[dict[str, Any]]:
        frames: list[dict[str, Any]] = []
        while True:
            try:
                frames.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                return frames


def _live_node_frame(event: dict[str, Any]) -> dict[str, Any]:
    """Project one live node transition onto the historical frame shape.

    Same vocabulary the post-settlement replay always used (`node_complete`
    with a success flag), so the shipped DagBuilder needs no new state — the
    only additions are the `seq` cursor and, when the live copy of a long
    response was capped, an explicit `response_truncated` flag (the full text
    stays in the canonical result and the run record).
    """
    frame: dict[str, Any] = {
        "status": "node_complete",
        "node_id": event.get("node_id"),
        "role": event.get("role", "worker"),
        "response": event.get("response", ""),
        "success": event.get("kind") == "node_completed",
        "run_id": event.get("run_id"),
    }
    if event.get("response_truncated"):
        frame["response_truncated"] = True
    return frame


class _LiveSink:
    """Turn node transitions into recorded, seq-stamped stream frames.

    Recording (via ``on_event``) happens BEFORE a frame is published: a frame
    that reaches the client is already durable, so a disconnect cannot lose
    projected progress. The sink never raises — execution truth never depends
    on the stream.
    """

    def __init__(
        self,
        channel: _ProgressChannel,
        on_event: Callable[[dict[str, Any]], Awaitable[int | None] | int | None],
    ) -> None:
        self.channel = channel
        self.on_event = on_event
        self.run_id = ""
        self.terminal_nodes: set[str] = set()
        self.seq_by_node: dict[str, int | None] = {}

    async def __call__(self, event: dict[str, Any]) -> None:
        run_id = str(event.get("run_id") or "")
        if run_id:
            self.run_id = run_id
        seq: int | None = None
        try:
            returned = self.on_event(event)
            if isinstance(returned, Awaitable):
                returned = await returned
            if isinstance(returned, int) and returned > 0:
                seq = returned
        except Exception:
            logger.warning("Streaming progress sink failed", exc_info=True)
        if event.get("kind") == "node_started":
            # Start transitions feed the projection (SSE "running" state) but
            # are not websocket frames: the frame vocabulary stays exactly
            # what the shipped client already knows.
            return
        node_id = str(event.get("node_id") or "")
        if node_id and self.channel.publish({**_live_node_frame(event), "seq": seq}):
            # Track only frames that actually entered the channel: a frame
            # lost to a full channel was never streamed, and its node must be
            # backfilled from canonical truth at settlement (#1183).
            self.terminal_nodes.add(node_id)
            self.seq_by_node[node_id] = seq


async def _pump_live_frames(
    exec_task: asyncio.Task[dict[str, Any]],
    channel: _ProgressChannel,
    *,
    keepalive_interval: float,
    sink: _LiveSink,
) -> AsyncIterator[dict[str, Any]]:
    """Yield live frames until the Run settles; heartbeat while idle.

    One frame per wait, any buffered backlog drained eagerly, and exactly one
    bounded heartbeat per idle interval — the traffic that lets intermediaries
    and clients tell alive-idle from a dead socket (#1183).
    """
    timeout = keepalive_interval if keepalive_interval and keepalive_interval > 0 else None
    while True:
        getter: asyncio.Future[dict[str, Any]] = asyncio.ensure_future(channel.queue.get())
        done: set[asyncio.Future[Any]] = set()
        try:
            done, _ = await asyncio.wait(
                {exec_task, getter}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            # `asyncio.wait` can be interrupted (cancellation) before it
            # assigns `done`; the preset empty set keeps this guard truthful.
            if getter not in done:
                getter.cancel()
        if getter in done:
            for frame in (getter.result(), *channel.drain()):
                yield frame
            if exec_task in done:
                return
            continue
        if exec_task in done:
            for frame in channel.drain():
                yield frame
            return
        yield {"status": "heartbeat", "run_id": sink.run_id, "ts": time.time()}


async def _abort_live_execution(exec_task: asyncio.Task[dict[str, Any]]) -> None:
    """Tear down an in-flight Run when its stream goes away (#355, #1183).

    Closing the stream cancels the Run — the same semantics awaiting it inline
    always had. Stranded canonical evidence is reclaimed by recovery. (The
    pump's own pending getter is cancelled in the pump's `finally` when the
    wait is interrupted.)
    """
    if not exec_task.done():
        exec_task.cancel()
    with contextlib.suppress(BaseException):
        await exec_task


async def _reconciled_frames(
    result: dict[str, Any],
    *,
    on_result: Callable[[dict[str, Any]], Awaitable[None]] | None,
    skipped_nodes: set[str],
    seq_by_node: dict[str, int | None],
    missed_live_frames: int,
    fallback_run_id: str,
) -> AsyncIterator[dict[str, Any]]:
    """The post-settlement tail: projection hand-over, resync, replay, terminal.

    Nodes whose terminal frame already streamed live are not replayed — the
    client saw them; everything else is backfilled from canonical truth so a
    consumer converges on the Run's real outcome even after lost live frames
    (#1183).
    """
    if on_result is not None:
        await on_result(result)
    run_id = str(result.get("run_id") or fallback_run_id)
    if missed_live_frames:
        # Explicit discontinuity marker (#1183): live frames were lost to a
        # consumer that stopped reading. The replay below restores every
        # node's terminal state from canonical truth, and the run record
        # (GET /v1/dag-runs/{id}) holds the full event history.
        yield {
            "status": "resync",
            "run_id": run_id,
            "missed_live_frames": missed_live_frames,
            "recover": f"GET /v1/dag-runs/{run_id}",
        }
    for frame in _node_frames(result):
        if frame["node_id"] in skipped_nodes:
            continue
        seq = seq_by_node.get(frame["node_id"])
        yield {**frame, **({"seq": seq} if seq is not None else {})}


def _completed_terminal(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "completed",
        "run_id": result.get("run_id"),
        "cycles": result.get("cycles", 0),
        "annotations": result.get("annotations", {}),
    }


def _failed_terminal(result: dict[str, Any], exc: CanonicalDagExecutionError) -> dict[str, Any]:
    return {
        "status": result.get("status", "failed"),
        "run_id": result.get("run_id"),
        "error": str(exc),
    }


async def _replay_stream(
    dag_data: dict,
    *,
    on_result: Callable[[dict[str, Any]], Awaitable[None]] | None,
    **kwargs: Any,
) -> AsyncIterator[dict[str, Any]]:
    """The historical mode: run to settlement, then project the outcome."""
    try:
        result = await execute_dag(dag_data, **kwargs)
    except CanonicalDagExecutionError as exc:
        result = exc.result
        terminal = _failed_terminal(result, exc)
    except Exception as exc:
        logger.warning("Graph execution failed", exc_info=exc)
        yield {"status": "failed", "error": public_failure(exc)}
        return
    else:
        terminal = _completed_terminal(result)

    if on_result is not None:
        await on_result(result)
    for frame in _node_frames(result):
        yield frame
    yield terminal


async def execute_dag_streaming(
    dag_data: dict,
    *,
    on_result: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    on_event: Callable[[dict[str, Any]], Awaitable[int | None] | int | None] | None = None,
    keepalive_interval: float = STREAM_HEARTBEAT_SECONDS,
    **kwargs: Any,
) -> AsyncIterator[dict[str, Any]]:
    """Stream one canonical Run's progress onto the historical frame shape.

    Two modes share one contract (#1183):

    - **Live** (an ``on_event`` sink is attached, as the websocket route
      does): node frames are emitted while the Run is in flight, each stamped
      with the durable sequence number the sink recorded for it. Idle stretches
      carry bounded `heartbeat` frames. If the bounded progress channel
      overflows because the consumer stopped reading, the stream says so with
      an explicit `resync` frame and replays the missed nodes' terminal state
      from canonical truth before the terminal frame — a dropped live frame
      never masquerades as a contiguous stream.
    - **Replay** (no ``on_event``): the historical behavior — the Run runs to
      settlement and its node outcomes are projected afterwards. Kept for
      callers that attach no live durability (and pinned by tests).

    ``on_result`` receives the canonical result as soon as the Run settles,
    before any post-settlement frame is sent, so a client that disconnects
    mid-stream cannot keep the caller from recording its projection. It must
    not raise: the Run has already settled, and an exception here fails the
    stream. In live mode each node frame is additionally durable before it is
    sent: the ``on_event`` sink records it (returning its sequence number)
    before the frame is published. Closing the stream cancels the in-flight
    Run, exactly as awaiting it inline always did (#355).
    """
    entry = dag_data.get("entry_node") or (
        dag_data.get("nodes", [{}])[0].get("id") if dag_data.get("nodes") else ""
    )
    live = on_event is not None
    started: dict[str, Any] = {
        "status": "started",
        "node_count": len(dag_data.get("nodes", [])),
        "entry": entry,
    }
    if live:
        # Tell the client the idle cadence it may rely on (#1183).
        started["heartbeat_seconds"] = keepalive_interval
    yield started

    if not live:
        async for frame in _replay_stream(dag_data, on_result=on_result, **kwargs):
            yield frame
        return

    channel = _ProgressChannel(STREAM_PROGRESS_QUEUE_MAX)
    sink = _LiveSink(channel, on_event)
    exec_task = asyncio.create_task(execute_dag(dag_data, on_event=sink, **kwargs))
    try:
        async for frame in _pump_live_frames(
            exec_task, channel, keepalive_interval=keepalive_interval, sink=sink
        ):
            yield frame
        try:
            result = exec_task.result()
        except CanonicalDagExecutionError as exc:
            result = exc.result
            terminal = _failed_terminal(result, exc)
        except Exception as exc:
            logger.warning("Graph execution failed", exc_info=exc)
            yield {"status": "failed", "error": public_failure(exc)}
            return
        else:
            terminal = _completed_terminal(result)

        async for frame in _reconciled_frames(
            result,
            on_result=on_result,
            skipped_nodes=sink.terminal_nodes,
            seq_by_node=sink.seq_by_node,
            missed_live_frames=channel.dropped,
            fallback_run_id=sink.run_id,
        ):
            yield frame
        yield terminal
    finally:
        await _abort_live_execution(exec_task)


async def execute_champion(*, scope: DagExecutionScope | None = None) -> dict[str, Any]:
    """Run the current evolution champion through the same canonical DAG adapter."""
    try:
        from services.evolution import get_evolution_service

        service = get_evolution_service()
    except RuntimeError:
        return {"status": "error", "error": "evolution service not started"}
    if service.population is None:
        return {"status": "error", "error": "population not initialized"}
    champion = service.population.get_champion()
    if champion is None:
        return {"status": "error", "error": "no champion yet"}
    result = await execute_dag(genome_to_dag(champion), **({"scope": scope} if scope else {}))
    result["genome_id"] = champion.id
    result["fitness"] = champion.fitness_score
    result["generation"] = champion.generation
    return result
