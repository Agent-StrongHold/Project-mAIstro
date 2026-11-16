"""The reference extension's entrypoint module.

Same shape as the SDK's own minimal example: a manifest-declared object the
host can find by name. Validation never imports this file — a host reads
``extension.json``, checks it against the SDK's schema, resolves its grants,
and only then loads this module. That ordering is the whole security posture:
code runs only after data about the code was accepted.

The object is deliberately plain data plus one pure function. It imports
nothing — not the SDK, not the product — which is why this package builds and
tests in a bare venv with zero dependencies (see ``scripts/check-reference-extension.py``).
The M9-A2 lifecycle contracts (#950) will type the entrypoint and the context
object it receives; until then this module documents the declarative half of
the contract by being exactly the thing a manifest points at.
"""

from __future__ import annotations

from collections.abc import Callable

#: The object the manifest's entrypoint names. Keys beyond the identity triple
#: are the extension's own declaration of what a host may call: ``handler``
#: names a callable in this module, and ``capabilities`` mirrors the manifest
#: (here: empty — a greeter reads nothing, writes nothing, and reaches nothing).
PLUGIN: dict[str, object] = {
    "kind": "tool",
    "name": "reference.greeter",
    "version": "1.0.0",
    "capabilities": [],
    "handler": "greet",
}


def greet(target: str = "world") -> str:
    """Return a greeting for ``target``.

    The sample handler a host calls after loading ``PLUGIN``. Pure on purpose:
    no I/O, no clock, no environment — the extension declared the
    ``read-only`` effect and nothing else, and the implementation keeps that
    promise. An extension that needed the network would have to declare
    ``network.outbound`` in ``extension.json`` first; the manifest is the
    authority *declaration*, and the host turns declarations into grants.
    """
    return f"Hello, {target}!"


#: Exported for hosts that enumerate what an entrypoint object offers.
HANDLERS: dict[str, Callable[[str], str]] = {"greet": greet}
