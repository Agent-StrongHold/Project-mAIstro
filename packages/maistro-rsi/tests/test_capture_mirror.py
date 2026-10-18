"""The RSI capture mirror stays pinned to the canonical sandbox capture.

``maistro_rsi.sandbox._capture`` re-implements the asyncio flavor of
``maistro.tools.sandbox._capture`` (plus the retention-limit policy of
``maistro.sandbox.protocol``) because the seam must not import maistro-core:
the promotion-surface gate reads the AST from the promotion roots, and any
import edge — even function-level — onto maistro-core drags the whole
core cascade onto the promotion path (see the mirror's docstring and
``maistro_evolve._candidate_env`` for the precedent). Test code is not on the
promotion path, so both sides are imported here and compared: constants,
policy, notice text, and drain behavior. A silent drift would make the RSI
runtime and the core backends disagree about how much output a child may
retain — and the weaker bound would win.
"""

from __future__ import annotations

import asyncio

import pytest


def test_capture_constants_mirror_the_canonical_module() -> None:
    import maistro_rsi.sandbox._capture as mirror
    from maistro.sandbox.protocol import (
        DEFAULT_MAX_OUTPUT_BYTES as CORE_DEFAULT,
    )
    from maistro.sandbox.protocol import (
        MAX_OUTPUT_BYTES_CEILING as CORE_CEILING,
    )
    from maistro.tools.sandbox._capture import _CHUNK as CORE_CHUNK
    from maistro.tools.sandbox._capture import _TRUNCATION_NOTICE as CORE_NOTICE

    assert mirror.DEFAULT_MAX_OUTPUT_BYTES == CORE_DEFAULT
    assert mirror.MAX_OUTPUT_BYTES_CEILING == CORE_CEILING
    assert mirror._CHUNK == CORE_CHUNK
    assert mirror._TRUNCATION_NOTICE == CORE_NOTICE


def test_clamped_output_limit_mirrors_the_canonical_policy() -> None:
    import maistro_rsi.sandbox._capture as mirror
    from maistro.sandbox.protocol import clamped_output_limit as core_clamp

    for value in (1, 100, mirror.MAX_OUTPUT_BYTES_CEILING, 10**9):
        assert mirror.clamped_output_limit(value) == core_clamp(value)
    for bad in (0, -1, -1000):
        with pytest.raises(ValueError):
            mirror.clamped_output_limit(bad)
        with pytest.raises(ValueError):
            core_clamp(bad)


def test_truncation_notice_mirrors_the_canonical_text() -> None:
    import maistro_rsi.sandbox._capture as mirror
    from maistro.tools.sandbox._capture import truncation_notice as core_notice

    for limit in (1, 4096, mirror.MAX_OUTPUT_BYTES_CEILING):
        assert mirror.truncation_notice(limit) == core_notice(limit)


async def test_read_stream_bounded_behaves_identically_to_the_canonical() -> None:
    import maistro_rsi.sandbox._capture as mirror
    from maistro.tools.sandbox._capture import read_stream_bounded as core_read

    async def drained(read) -> tuple[bytes, bool]:
        reader = asyncio.StreamReader()
        reader.feed_data(b"x" * 5000)
        reader.feed_eof()
        captured = await read(reader, 1000)
        return captured.data, captured.truncated

    assert await drained(mirror.read_stream_bounded) == await drained(core_read)


async def test_communicate_bounded_behaves_identically_to_the_canonical() -> None:
    import maistro_rsi.sandbox._capture as mirror
    from maistro.tools.sandbox._capture import communicate_bounded as core_communicate

    async def drained(communicate) -> tuple[bytes, bool, bytes, bool]:
        proc = await asyncio.create_subprocess_exec(
            "python3",
            "-c",
            "import sys; sys.stdout.write('a' * 9000); sys.stderr.write('b' * 9000)",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await communicate(proc, 512)
        await proc.wait()
        return out.data, out.truncated, err.data, err.truncated

    assert await drained(mirror.communicate_bounded) == await drained(core_communicate)
