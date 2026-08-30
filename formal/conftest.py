import os

import pytest
from hypothesis import HealthCheck, settings
from hypothesis.database import DirectoryBasedExampleDatabase

CI_MAX_EXAMPLES = int(os.environ.get("MAISTRO_FORMAL_CI_EXAMPLES", "100"))
NIGHTLY_MAX_EXAMPLES = int(os.environ.get("MAISTRO_FORMAL_NIGHTLY_EXAMPLES", "10000"))
CI_PROFILE = "maistro-ci"
NIGHTLY_PROFILE = "maistro-nightly"
NIGHTLY_DATABASE_PATH = ".hypothesis/examples"


def _load_hypothesis_profile(*, nightly: bool) -> str:
    """Register and load the live suite-wide Hypothesis profile."""
    settings.register_profile(
        CI_PROFILE,
        max_examples=CI_MAX_EXAMPLES,
        deadline=None,
        print_blob=True,
        database=None,
        derandomize=True,
        suppress_health_check=(HealthCheck.too_slow,),
    )
    settings.register_profile(
        NIGHTLY_PROFILE,
        max_examples=NIGHTLY_MAX_EXAMPLES,
        deadline=None,
        print_blob=True,
        database=DirectoryBasedExampleDatabase(NIGHTLY_DATABASE_PATH),
        derandomize=False,
        suppress_health_check=(),
    )
    profile = NIGHTLY_PROFILE if nightly else CI_PROFILE
    settings.load_profile(profile)
    return profile


def pytest_configure(config):
    config.addinivalue_line("markers", "nightly: only runs in nightly mode")
    _load_hypothesis_profile(nightly=config.getoption("--nightly", default=False))


def pytest_collection_modifyitems(config, items):
    if config.getoption("--nightly", default=False):
        return

    skip_nightly = pytest.mark.skip(reason="nightly only (--nightly)")
    for item in items:
        if "nightly" in item.keywords:
            item.add_marker(skip_nightly)


def pytest_addoption(parser):
    parser.addoption("--nightly", action="store_true", default=False, help="Run nightly deep exploration")
