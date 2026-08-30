"""What a provider said about a call's token usage, or that it said nothing.

A leaf on purpose. This parser has two consumers on opposite sides of the
system -- the agent strategies, which sum it into an `Outcome`, and the quota
recorder, which counts it into the usage log -- and it began life inside
`recorder.py`. Importing it from there made `maistro.quota.recorder` reachable,
and with it `quota.ambient` and `quota.reconciliation`, neither of which the
agent strategies use and neither of which anything wires: the reachability
metric would have reported three modules connected on the strength of one
four-line function (#717).

So it imports nothing beyond the standard library, and being reachable says
only what it means -- that something parses a usage object.
"""

from __future__ import annotations

from typing import Any


def reported_usage(response_json: dict[str, Any]) -> tuple[int, int] | None:
    """(input_tokens, output_tokens) if the provider reported them, else `None`.

    The distinction `extract_usage` cannot make. A provider that returns no
    `usage` object and one that returns zeros are different facts, and folding
    them together is what makes a turn's stored total unreadable: `0` means
    "free" and "nobody said" at once (ADR-083026-aba1, #717).

    Malformed is absent, not zero, for the same reason — an upstream that sent
    something unparseable did not report a measurement.
    """
    usage = response_json.get("usage")
    if not isinstance(usage, dict):
        return None
    try:
        return int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)
    except (TypeError, ValueError):
        return None


def extract_usage(response_json: dict[str, Any]) -> tuple[int, int]:
    """Pull (input_tokens, output_tokens) out of an OpenAI-compatible response
    body. Missing/malformed `usage` reads as (0, 0), not an error — a
    misbehaving upstream shouldn't take down the call that already succeeded.

    The quota log counts tokens and has nowhere to put an absence, so it takes
    the zero. A caller that needs to tell the two apart wants `reported_usage`,
    which this delegates to so there is one parser rather than two."""
    return reported_usage(response_json) or (0, 0)


__all__ = ["extract_usage", "reported_usage"]
