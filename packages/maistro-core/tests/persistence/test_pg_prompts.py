"""The pure helpers in `maistro.persistence.pg_prompts`.

The store's own behaviour is in `test_prompt_store_conformance.py`, against a
real server. What used to be here drove `PgPromptManager` through a fake
connection and asserted the sequence of SQL strings it emitted. Those tests
passed while two unconditional failures sat in the code they covered -- a fake
enforces no keys, so neither the unusable `ON CONFLICT` arbiter nor the
primary-key collision behind it could be observed (#328).

Asserting an emitted SQL string is asserting that the code is what it is.
`_parse_config` and `_lock_key` are genuinely pure and stay here; everything
else moved to where a database can disagree with it.
"""

from __future__ import annotations

from maistro.persistence.pg_prompts import _lock_key, _parse_config


class TestParseConfig:
    def test_none_is_an_empty_dict(self) -> None:
        assert _parse_config(None) == {}

    def test_a_json_string_is_parsed(self) -> None:
        assert _parse_config('{"temperature": 0.7}') == {"temperature": 0.7}

    def test_a_dict_is_copied_rather_than_aliased(self) -> None:
        original = {"temperature": 0.7}

        parsed = _parse_config(original)
        parsed["temperature"] = 0.1

        assert original == {"temperature": 0.7}

    def test_anything_else_is_an_empty_dict(self) -> None:
        assert _parse_config(42) == {}


class TestLockKey:
    def test_the_key_fits_the_signed_32_bit_argument_postgres_takes(self) -> None:
        """`pg_advisory_xact_lock(int, int)` takes `integer`, not `bigint`. A
        key outside that range is a runtime error on the lock statement -- the
        one statement in `upsert` whose failure would otherwise look like a
        deadlock."""
        for name in ("", "a", "agent.alpha", "x" * 4096, "ünïcodé.name"):
            assert -(2**31) <= _lock_key(name) < 2**31, name

    def test_one_name_always_gets_one_key(self) -> None:
        """Hashed in Python rather than by `hashtext()` because that function's
        output is not stable across PostgreSQL majors, and this repository runs
        17 and 18 against the same rows."""
        assert _lock_key("agent.alpha") == _lock_key("agent.alpha")

    def test_different_names_get_different_keys(self) -> None:
        keys = {_lock_key(f"agent.{i}") for i in range(1000)}

        assert len(keys) > 990, "collisions would serialize unrelated prompts"
