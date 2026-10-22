"""The gallery weather connector's entrypoint module (tool family, #980).

Same posture as the first-party reference extension: the manifest-declared
object is plain data naming what a host may call, and every handler is a
pure function. Validation never imports this file — a host reads the
manifest, checks it against the platform schema, resolves its grants, and
only then loads this module.

The connector *declares* ``network.outbound`` because a deployed connector
fetches forecasts; the fetch itself belongs to the host's approved transport
(one outbound seam, one credential store — the extension never holds a
socket). What ships here is the data shaping a host invokes through the
governed tool surface: pure functions over data the host already fetched.
"""

from __future__ import annotations

from collections.abc import Callable

#: The object the manifest's entry point names. ``kind`` is the extension
#: family; ``capabilities`` mirrors the manifest's authority declaration;
#: ``handlers`` names the callables in this module a host may invoke.
PLUGIN: dict[str, object] = {
    "kind": "tool",
    "name": "gallery.weather_connector",
    "version": "1.0.0",
    "capabilities": ["network.outbound", "tool.invoke"],
    "handlers": ["current_forecast_brief"],
}


def current_forecast_brief(location: str, forecast: dict[str, object]) -> str:
    """Format one already-fetched forecast into a one-line brief.

    Pure on purpose: no I/O, no clock, no environment. ``forecast`` is the
    payload the host's transport retrieved from the provider the manifest
    declares; malformed or absent fields degrade to "unknown" instead of
    raising, so a broken upstream degrades the brief, not the Run.
    """
    summary = forecast.get("summary") if isinstance(forecast, dict) else None
    high = forecast.get("high_c") if isinstance(forecast, dict) else None
    low = forecast.get("low_c") if isinstance(forecast, dict) else None
    return (
        f"{location}: {summary if isinstance(summary, str) else 'unknown'}"
        f", high {high if isinstance(high, (int, float)) else '?'}°C"
        f", low {low if isinstance(low, (int, float)) else '?'}°C"
    )


#: Exported for hosts that enumerate what an entry point object offers.
HANDLERS: dict[str, Callable[[str, dict[str, object]], str]] = {
    "current_forecast_brief": current_forecast_brief,
}
