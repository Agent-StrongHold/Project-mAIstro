"""Provider-specific `QuotaVerifier` implementations.

Only providers that expose a real balance/usage endpoint get one here — most
of the roster doesn't (see `reconciliation.py`'s module docstring) and
reconciles ambiently via response headers/body instead.
"""
