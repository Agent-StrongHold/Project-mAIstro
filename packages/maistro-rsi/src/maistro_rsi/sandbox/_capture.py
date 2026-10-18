"""Bounded host-side capture of child output (#1197) — RSI-local mirror.

Mirrors the asyncio flavor of the canonical ``maistro.tools.sandbox._capture``
plus the retention limit policy of ``maistro.sandbox.protocol`` (maistro-core).
This seam MUST NOT import the canonical modules, not even lazily inside a
try/except: any import of a maistro-core leaf drags the package initializers —
and through them the general-purpose core cascade (fence -> runs -> graph ->
capabilities) — onto the promotion path.
``scripts/check-promotion-surface.py`` walks the AST from the promotion roots
(this package included), and a function-level import is still an import edge;
the core cascade is neither protected nor tolerated there. The same argument,
and the same pin-by-test answer, is documented in
``maistro_evolve._candidate_env`` for the credential boundary.

The contract being mirrored: retain at most ``limit`` bytes per stream; beyond
the limit keep reading and *discard* (never buffer), so the child can neither
grow host memory nor wedge against a full pipe; report what happened via the
``truncated`` flag / the textual notice. The sync ``Popen`` flavor of the
canonical module has no mirror because nothing in this package spawns
children synchronously.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

#: Read/drain chunk size — mirrors the canonical module exactly (pinned by
#: test): small enough that a chunk never meaningfully overshoots the limit,
#: large enough that draining a discarded stream is not a syscall-per-byte tax.
_CHUNK = 65536

#: Mirrors ``maistro.sandbox.protocol.DEFAULT_MAX_OUTPUT_BYTES`` exactly.
DEFAULT_MAX_OUTPUT_BYTES = 1024 * 1024

#: Mirrors ``maistro.sandbox.protocol.MAX_OUTPUT_BYTES_CEILING`` exactly: a
#: caller may lower the limit per workload; nothing can raise the retained
#: output above this.
MAX_OUTPUT_BYTES_CEILING = 8 * 1024 * 1024

#: Mirrors ``maistro.tools.sandbox._capture._TRUNCATION_NOTICE`` exactly: the marker
#: appended when a ``(int, str)``-shaped caller must declare truncation in the
#: output itself.
_TRUNCATION_NOTICE = "\n[maistro: output truncated at {} bytes; the rest was discarded]"


@dataclass(frozen=True)
class BoundedCapture:
    """What a bounded drain retained from one output stream."""

    #: The retained bytes (never more than the limit).
    data: bytes
    #: True when bytes beyond `data` were drained and discarded.
    truncated: bool


def clamped_output_limit(value: int) -> int:
    """Host policy for retained output: positive, never above the ceiling.

    Mirrors ``maistro.sandbox.protocol.clamped_output_limit`` exactly,
    including the ValueError on non-positive limits.
    """
    if value <= 0:
        raise ValueError(f"max_output_bytes must be positive, got {value}")
    return min(value, MAX_OUTPUT_BYTES_CEILING)


def truncation_notice(limit: int) -> str:
    """The textual notice appended when a merged-output caller truncated."""
    return _TRUNCATION_NOTICE.format(clamped_output_limit(limit))


async def read_stream_bounded(stream: asyncio.StreamReader, limit: int) -> BoundedCapture:
    """Drain an asyncio stream to EOF, retaining at most `limit` bytes.

    Reads run to EOF even after the limit is hit — discarding chunks — so the
    writing child is never blocked on a full pipe and this coroutine always
    terminates when the child does.
    """
    chunks: list[bytes] = []
    retained = 0
    truncated = False
    while chunk := await stream.read(_CHUNK):
        if retained < limit:
            take = chunk[: limit - retained]
            chunks.append(take)
            retained += len(take)
            if len(take) < len(chunk):
                truncated = True
        else:
            truncated = True
    return BoundedCapture(b"".join(chunks), truncated)


async def _empty() -> BoundedCapture:
    return BoundedCapture(b"", False)


async def communicate_bounded(
    process: asyncio.subprocess.Process, limit: int
) -> tuple[BoundedCapture, BoundedCapture]:
    """Drain a subprocess's stdout/stderr concurrently, bounded per stream.

    Concurrent because a child that fills both pipes must be able to progress
    on either while we drain the other — a sequential drain can deadlock
    exactly in the simultaneous-output case. A `None` stream (merged
    `stderr=STDOUT`, or no pipe) yields an empty capture.

    Reaps the child before returning: EOF on both streams only proves the
    child closed its fds, not that it exited — without the wait, a child that
    closes stdout/stderr and keeps running would be reported from a still-
    `None` `returncode` (``returncode or 0`` reads as false success) and
    outlive `exec` unsupervised. Mirrors the canonical module exactly.
    """
    streams = (process.stdout, process.stderr)
    results = await asyncio.gather(
        *(
            read_stream_bounded(stream, limit) if stream is not None else _empty()
            for stream in streams
        )
    )
    await process.wait()
    stdout, stderr = results
    return stdout, stderr


__all__ = [
    "DEFAULT_MAX_OUTPUT_BYTES",
    "MAX_OUTPUT_BYTES_CEILING",
    "BoundedCapture",
    "clamped_output_limit",
    "communicate_bounded",
    "read_stream_bounded",
    "truncation_notice",
]
