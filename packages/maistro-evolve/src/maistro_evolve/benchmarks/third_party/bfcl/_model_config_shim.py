"""NOT upstream code — the one authored substitution in this vendored tree.

Upstream's ``ast_checker`` imports ``MODEL_CONFIG_MAPPING`` (the registry of
every model on the BFCL leaderboard) from a module that transitively imports
every vendor SDK. The checker consults it on exactly one line — whether a model
is granted the ``.``→``_`` function-name accommodation that OpenAI-style APIs
need because they forbid dots in function names.

This shim answers ``underscore_to_dot = False`` for every model name: no
accommodation, the response must name the function exactly as the ground truth
does. That is strictly HARSHER than what any leaderboard model receives — it can
only turn upstream-valid answers invalid, never the reverse — so a score
produced under it never overstates against the official checker.

Verified byte-for-byte by ``scripts/vendor_bfcl.py --check`` like everything
else here; edits fail CI.
"""


class _NoAccommodation:
    underscore_to_dot = False


class _AllModels(dict):  # noqa: RUF049 - upstream indexes by arbitrary model name
    def __missing__(self, key: str) -> _NoAccommodation:
        return _NoAccommodation()


MODEL_CONFIG_MAPPING = _AllModels()
