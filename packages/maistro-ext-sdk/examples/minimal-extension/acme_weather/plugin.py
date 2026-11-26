"""The minimal extension's entrypoint module.

Deliberately boring: the SDK never imports this file while validating the
extension — validation reads ``extension.json`` and ``stat``s this path. A
host imports it only after the manifest has been accepted.
"""

from __future__ import annotations

#: The object the manifest's entrypoint names. The M9-A2 lifecycle contracts
#: will type this; M9-A1 only requires that the host can find it by name.
PLUGIN = {
    "kind": "tool",
    "name": "acme.weather",
    "version": "1.0.0",
}
