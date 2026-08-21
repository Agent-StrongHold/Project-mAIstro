"""Constant-time secret comparison.

Uses HMAC-based comparison to prevent timing attacks. Ported from
TypeScript secret-equal pattern: both inputs are HMAC-SHA256 hashed
with a fixed key before comparison, producing fixed-length digests
regardless of input length.
"""

from __future__ import annotations

import hashlib
import hmac

# Fixed key for HMAC — not a secret, just ensures fixed-length comparison
_HMAC_KEY = b"maistro-timing-safe-compare"


def secret_equal(a: str, b: str) -> bool:
    """Compare two strings in constant time.

    Both inputs are HMAC-SHA256 hashed before comparison to:
    1. Produce fixed-length digests (prevents length leakage)
    2. Use hmac.compare_digest for constant-time byte comparison
    """
    if not isinstance(a, str) or not isinstance(b, str):
        # Type confusion defense — consume time, return False
        hmac.compare_digest(b"dummy-a", b"dummy-b")
        return False

    digest_a = hmac.new(_HMAC_KEY, a.encode("utf-8"), hashlib.sha256).digest()
    digest_b = hmac.new(_HMAC_KEY, b.encode("utf-8"), hashlib.sha256).digest()

    return hmac.compare_digest(digest_a, digest_b)
