"""The version sites `bump_version.py` claims to keep in lockstep (#660).

The script's safety rests on one property: `Site.extract` treats "found 0" as
a failure, so a declaration that drifts out of the shape its row expects is
*loud* rather than silently dropped from the checked set. Everything here
exists to protect that property while widening what a row accepts.

`packages/hive-conductor/pyproject.toml` is the case that motivated it. The
file was registered nowhere — not its `[project] version`, not either of its
two `maistro-core` bounds — and its bounds are capped (`>=0.9.0,<2`) where
every registered sibling's is not, so the old pattern could not have matched
them even if a row had existed. Loosening a pattern to admit a cap is exactly
the kind of change that can turn one silent site into fifteen, which is why
the negative cases below outnumber the positive ones.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "bump_version.py"


@pytest.fixture(scope="module")
def bump():
    spec = importlib.util.spec_from_file_location("_bump_version", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        del sys.modules[spec.name]
        raise
    yield mod
    del sys.modules["_bump_version"]


class TestWhatAnInterPackageRowAccepts:
    @pytest.mark.parametrize(
        "declaration,expected",
        [
            ('    "maistro-core[bcrypt]>=0.9.0,<2",\n', "0.9.0"),
            ('    "maistro-core[bcrypt]>=0.9.0",\n', "0.9.0"),
            ('    "maistro-core[bcrypt]>=0.9.0, <2",\n', "0.9.0"),
            ('    "maistro-core[bcrypt]>=0.9.0,<=2.1",\n', "0.9.0"),
        ],
    )
    def test_a_lower_bound_is_read_capped_or_not(self, bump, declaration, expected) -> None:
        assert bump._interpkg_pattern("maistro-core[bcrypt]").findall(declaration) == [expected]

    @pytest.mark.parametrize(
        "declaration,why",
        [
            ("\"maistro-core>=0.9.0 ; python_version < '3.13'\",", "an environment marker"),
            ('"maistro-core==0.9.0",', "a pin rather than a lower bound"),
            ('"maistro-core>=0.9.0,<2,!=1.5.0",', "a second trailing clause"),
            ('"maistro-core~=0.9.0",', "a compatible-release operator"),
        ],
    )
    def test_a_declaration_of_another_shape_still_matches_nothing(
        self, bump, declaration, why
    ) -> None:
        """This is the load-bearing half. Admitting the cap with a `.*` tail
        would satisfy every case above *and* every case here, and the row would
        then keep passing over a declaration whose meaning had changed —
        turning the one failure mode the script has into no failure at all."""
        assert bump._interpkg_pattern("maistro-core").findall(declaration) == [], why

    def test_a_bare_row_does_not_read_an_extras_declaration(self, bump) -> None:
        """`maistro-core` and `maistro-core[bcrypt]` are separate requirements
        with separate bounds. A row that matched both would report one number
        for two facts, and `extract`'s exactly-one rule would start failing on
        files that hold both."""
        both = '"maistro-core>=0.9.0",\n"maistro-core[bcrypt]>=0.9.0,<2",\n'

        assert bump._interpkg_pattern("maistro-core").findall(both) == ["0.9.0"]
        assert bump._interpkg_pattern("maistro-core[bcrypt]").findall(both) == ["0.9.0"]


class TestADriftedSiteStillFails:
    def test_extract_refuses_a_declaration_its_row_no_longer_matches(
        self, bump, tmp_path: Path
    ) -> None:
        """The property the widening must not cost: a site that stops matching
        is an error, not a quiet removal from the 35."""
        path = tmp_path / "pyproject.toml"
        path.write_text('dependencies = ["maistro-core@git+https://example/x"]\n', encoding="utf-8")
        site = bump.Site(path, bump._interpkg_pattern("maistro-core"), "inter-package dep:x")

        with pytest.raises(SystemExit, match="expected exactly 1 match"):
            site.extract()


class TestRewritingACappedBound:
    def test_the_bump_moves_the_lower_bound_and_leaves_the_cap(self, bump, tmp_path: Path) -> None:
        """A cap is a compatibility statement, not a version site. Rewriting it
        along with the lower bound would silently narrow — or invert — a range
        the bump was never asked to touch."""
        path = tmp_path / "pyproject.toml"
        path.write_text('    "maistro-core[bcrypt]>=0.9.0,<2",\n', encoding="utf-8")
        site = bump.Site(path, bump._interpkg_pattern("maistro-core[bcrypt]"), "inter-package dep")

        site.rewrite("1.0.0")

        assert path.read_text(encoding="utf-8") == '    "maistro-core[bcrypt]>=1.0.0,<2",\n'

    @pytest.mark.parametrize(
        "declaration,expected",
        [
            ('"maistro-core>=0.9.0,<10.9.0"', '"maistro-core>=1.0.0,<10.9.0"'),
            ('"maistro-core>=0.9.0,<0.9.05"', '"maistro-core>=1.0.0,<0.9.05"'),
            ('"maistro-core>=0.9.0,<0.9.0"', '"maistro-core>=1.0.0,<0.9.0"'),
        ],
    )
    def test_a_cap_containing_the_version_text_is_left_alone(
        self, bump, tmp_path: Path, declaration, expected
    ) -> None:
        """The case the `<2` above cannot see, and the reason it is not enough.

        Rewriting used to substitute the old version everywhere in the match,
        which was safe only while a match could not span more than the version.
        Once the row admits an upper bound, a cap that contains the same digits
        moves with it: `<10.9.0` became `<11.0.0` (Codex, #660). A cap is a
        compatibility statement, not a version site."""
        path = tmp_path / "pyproject.toml"
        path.write_text(declaration, encoding="utf-8")
        site = bump.Site(path, bump._interpkg_pattern("maistro-core"), "inter-package dep")

        site.rewrite("1.0.0")

        assert path.read_text(encoding="utf-8") == expected


class TestTheRegisteredCorpus:
    """Against the real tree, because registration is the claim #660 is about."""

    @pytest.mark.parametrize(
        "label_fragment",
        [
            "pyproject:packages/hive-conductor/pyproject.toml",
            "inter-package dep:packages/hive-conductor/pyproject.toml:maistro-core[bcrypt]",
            "inter-package dep:packages/hive-conductor/pyproject.toml:maistro-core[observability]",
        ],
    )
    def test_the_conductor_site_is_registered(self, bump, label_fragment) -> None:
        assert any(site.label == label_fragment for site in bump.ALL_SITES), label_fragment

    def test_every_registered_site_resolves_to_exactly_one_occurrence(self, bump) -> None:
        """`check()` collects these into a report; asserting them here names the
        offending site directly instead of through an exit code."""
        version = bump.VERSION_FILE.read_text(encoding="utf-8").strip()

        for site in bump.ALL_SITES:
            assert site.extract() == version, site.label
