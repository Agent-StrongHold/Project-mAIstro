import os

import pytest

CI_MAX_EXAMPLES = int(os.environ.get("MAISTRO_FORMAL_CI_EXAMPLES", "100"))
NIGHTLY_MAX_EXAMPLES = int(os.environ.get("MAISTRO_FORMAL_NIGHTLY_EXAMPLES", "10000"))


def pytest_configure(config):
    config.addinivalue_line("markers", "nightly: only runs in nightly mode")


def pytest_collection_modifyitems(config, items):
    nightly = config.getoption("--nightly", default=False)
    if nightly:
        for item in items:
            if "nightly" not in item.keywords:
                item.add_marker(
                    pytest.mark.hypothesis(
                        max_examples=NIGHTLY_MAX_EXAMPLES,
                        deadline=None,
                    )
                )
    else:
        skip_nightly = pytest.mark.skip(reason="nightly only (--nightly)")
        for item in items:
            if "nightly" in item.keywords:
                item.add_marker(skip_nightly)
            else:
                item.add_marker(
                    pytest.mark.hypothesis(
                        max_examples=CI_MAX_EXAMPLES,
                        deadline=None,
                    )
                )


def pytest_addoption(parser):
    parser.addoption("--nightly", action="store_true", default=False, help="Run nightly deep exploration")
