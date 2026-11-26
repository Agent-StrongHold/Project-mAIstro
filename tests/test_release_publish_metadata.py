"""The PyPI publish set ships complete PyPI-visible metadata (release gate).

`release.yml`'s wheels job runs `twine check --strict dist/*` before anything
is published; a package whose metadata is incomplete (no `long_description`,
i.e. no declared readme) fails that gate at tag time and blocks the whole
release — discovered for maistro-canvas/-evolve/-rsi/-ext-sdk by actually
building the publish set and running the gate while verifying the release
workflows end-to-end (#84). This contract pins the property those packages
were missing so it cannot regress: every package named in the workflow's
PUBLISH_SET declares a `readme` that exists on disk.

The workflow file is parsed rather than a second list kept here: the workflow
is the operative gate, and a duplicate list would drift from it exactly the
way the missing readmes drifted from it.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def _publish_set() -> list[str]:
    """The PUBLISH_SET the release workflow itself declares (wheels job env)."""
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    publish_set = workflow["jobs"]["wheels"]["env"]["PUBLISH_SET"]
    assert isinstance(publish_set, str) and publish_set.strip()
    return publish_set.split()


def test_publish_set_is_non_empty_and_known() -> None:
    """The workflow declares the publish set this contract checks."""
    names = _publish_set()
    assert len(names) == len(set(names)), "PUBLISH_SET repeats a package"
    for name in names:
        assert (ROOT / "packages" / name / "pyproject.toml").is_file(), (
            f"packages/{name}/pyproject.toml is missing from the publish set"
        )


@pytest.mark.parametrize("package", _publish_set(), ids=lambda p: p)
def test_publish_set_package_declares_an_existing_readme(package: str) -> None:
    """Every publish-set package declares `readme` pointing at a real file.

    With `twine check --strict`, a missing readme is a warning, and a warning
    fails the release's build/check gate. The declared file must also exist:
    a build that cannot read it fails later and less clearly.
    """
    pyproject = ROOT / "packages" / package / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project", {})
    readme = project.get("readme")
    assert readme, (
        f"{pyproject.relative_to(ROOT)} declares no readme — twine check "
        f"--strict fails on the missing long_description at tag time"
    )
    readme_path = pyproject.parent / readme
    assert readme_path.is_file(), f"declared readme {readme} does not exist"
    assert readme_path.stat().st_size > 0, f"declared readme {readme} is empty"
