"""Local conftest for registry tests.

The root `tests/conftest.py` has an autouse fixture that imports
`maistro.config.settings` (which depends on `pydantic_settings`)
to reset engine singletons between tests. The registry tool is
deliberately decoupled from the engine and runs with a minimal
dep set in CI (`pydantic` + `pyyaml` + `pytest` only) per
`engine#ADR-039`.

This local conftest defines a same-named autouse fixture that
pytest uses *instead of* the parent's, so the engine import never
happens for registry tests. Fixture-name override is a documented
pytest mechanism (https://docs.pytest.org/en/stable/how-to/fixtures.html
#override-a-fixture-on-a-folder-conftest-level).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _reset_singletons() -> Iterator[None]:
    """No-op override of the root tests/conftest.py autouse fixture.

    Registry tests don't touch engine singletons; we deliberately
    skip the import to keep the registry tool's dep surface minimal.
    """
    yield
