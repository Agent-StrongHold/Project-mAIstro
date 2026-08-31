"""Wiring evidence for formal-suite Hypothesis profile selection."""

from __future__ import annotations

import os
from datetime import timedelta

from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st
from hypothesis.database import DirectoryBasedExampleDatabase


@given(st.booleans())
def test_active_hypothesis_profile_matches_pytest_mode(_sample: bool, pytestconfig) -> None:
    """Canary property intentionally inherits the active suite profile."""
    nightly = pytestconfig.getoption("--nightly")
    expected_profile = "maistro-nightly" if nightly else "maistro-ci"
    expected_examples = int(
        os.environ.get(
            "MAISTRO_FORMAL_NIGHTLY_EXAMPLES" if nightly else "MAISTRO_FORMAL_CI_EXAMPLES",
            "10000" if nightly else "100",
        )
    )
    active = settings()

    assert settings.get_current_profile_name() == expected_profile
    assert active.max_examples == expected_examples
    assert active.print_blob is True

    if nightly:
        assert active.phases == (
            Phase.explicit,
            Phase.reuse,
            Phase.generate,
            Phase.target,
            Phase.shrink,
        )
        assert active.deadline is None
        assert isinstance(active.database, DirectoryBasedExampleDatabase)
        assert active.derandomize is False
        assert active.suppress_health_check == ()
    else:
        assert active.phases == (Phase.explicit, Phase.generate, Phase.shrink)
        assert active.deadline == timedelta(seconds=60)
        assert active.database is None
        assert active.derandomize is True
        assert HealthCheck.too_slow in active.suppress_health_check
