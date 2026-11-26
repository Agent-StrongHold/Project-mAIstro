"""The gallery unit skill's entrypoint module (skill family, #980).

The skill converts temperature units in host-provided report data — the kind
of small, pure transformation a skill ships. It *depends on* the gallery
weather connector at the extension level (manifest ``dependencies``), which
is a resolution-time fact the catalog and the reproducible lock own: the
platform installs the connector first or refuses the skill. The dependency
is not a Python import — this module never imports the connector's code, so
the package builds and tests alone.
"""

from __future__ import annotations

from collections.abc import Callable

PLUGIN: dict[str, object] = {
    "kind": "skill",
    "name": "gallery.unit_skill",
    "version": "1.0.0",
    "capabilities": ["workspace.read"],
    "handlers": ["convert_report_units", "c_to_f", "f_to_c"],
}


def c_to_f(celsius: float) -> float:
    """One pure conversion, exported so hosts (and tests) pin the arithmetic."""
    return celsius * 9.0 / 5.0 + 32.0


def f_to_c(fahrenheit: float) -> float:
    """The inverse conversion, equally pure."""
    return (fahrenheit - 32.0) * 5.0 / 9.0


def convert_report_units(report: dict[str, object]) -> dict[str, object]:
    """Convert every ``*_c`` numeric field of a report dict to ``*_f``.

    Pure data in, pure data out. Fields the skill does not recognize are
    passed through untouched: a skill reshapes what it was given, it does
    not invent structure the host never sent.
    """
    converted: dict[str, object] = {}
    for key, value in report.items():
        if key.endswith("_c") and isinstance(value, (int, float)) and not isinstance(value, bool):
            converted[f"{key[:-2]}_f"] = round(c_to_f(float(value)), 1)
        else:
            converted[key] = value
    return converted


HANDLERS: dict[str, Callable[..., object]] = {
    "convert_report_units": convert_report_units,
    "c_to_f": c_to_f,
    "f_to_c": f_to_c,
}
