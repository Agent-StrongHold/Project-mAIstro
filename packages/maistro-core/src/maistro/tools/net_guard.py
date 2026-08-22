"""Compatibility shim: the SSRF guard now lives in `maistro.security.ssrf`.

`maistro-core` is a library other products import (AGENTS.md: "downstream
products (Conductor, Stronghold, Canvas) consume this repo"), so moving a
module out from under its published import path is a breaking change for
callers this repository cannot see. `SSRFBlockedError` and
`validate_outbound_url` were both exported from here.

This re-exports rather than reimplements. There is still exactly one guard —
the move in #154 existed to delete a second copy, and a shim that carried its
own logic would recreate the problem it fixed. Import it from
`maistro.security.ssrf` in new code; this path is kept for existing callers and
warns rather than failing silently, so a consumer learns about the move from
their own test run instead of from a later diff.
"""

from __future__ import annotations

import warnings

from maistro.security.ssrf import (
    SSRFBlockedError,
    avalidate_outbound_url,
    validate_outbound_url,
)

warnings.warn(
    "maistro.tools.net_guard has moved to maistro.security.ssrf; "
    "this compatibility shim re-exports it and will be removed in a future release.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["SSRFBlockedError", "avalidate_outbound_url", "validate_outbound_url"]
