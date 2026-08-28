"""A ratchet's oracle comes from the base, not from the tree being judged (#534).

These build real git repositories rather than faking `git`, because the thing
under test *is* the git plumbing: which commit a ledger is read from, and what
happens when that commit is missing, shallow, or unreadable. A mocked `git show`
would agree with whatever the implementation happened to do.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from scripts.ratchet_provenance import (
    BASE_REV_ENV,
    Baseline,
    Provenance,
    RatchetProvenanceError,
    head_sha,
    load_authorizations,
    require_measurement,
    require_metric_version,
    resolve_baseline,
)

LEDGER = "quality/ledger.json"


def _run(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _run(repo, "add", "-A")
    _run(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", message)
    return _run(repo, "rev-parse", "HEAD")


def _write(repo: Path, rel: str, payload: object) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo whose trunk carries a ledger tolerating exactly one entry."""
    monkeypatch.delenv(BASE_REV_ENV, raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    _run(root, "init", "-q", "-b", "develop")
    _write(root, LEDGER, {"tolerated": ["known"]})
    _commit(root, "trunk ledger")
    # `origin/develop` is what the resolver looks for by default; a local clone
    # of ourselves is the cheapest way to have a real remote-tracking ref.
    _run(root, "remote", "add", "origin", str(root))
    _run(root, "fetch", "-q", "origin")
    _run(root, "checkout", "-q", "-b", "candidate")
    return root


class TestTheBaselineComesFromTheBase:
    def test_a_candidates_edit_to_the_ledger_is_not_what_gets_read(self, repo: Path) -> None:
        """The defect this exists to close: banking on the branch changes nothing."""
        _write(repo, LEDGER, {"tolerated": ["known", "newly-added-by-the-candidate"]})
        _commit(repo, "weaken the metric and bank it, in one commit")

        baseline = resolve_baseline(repo / LEDGER, root=repo)

        assert baseline.origin == "base"
        assert baseline.loads()["tolerated"] == ["known"]

    def test_the_base_sha_is_the_merge_base_not_the_moving_tip(self, repo: Path) -> None:
        """Judged against where this branch left the base.

        Otherwise a regression somebody else pushed to the trunk afterwards
        would fail this branch, which is not its monotonicity to answer for.
        """
        forked_at = _run(repo, "rev-parse", "HEAD")
        _run(repo, "checkout", "-q", "develop")
        _write(repo, LEDGER, {"tolerated": ["known", "landed-after-the-fork"]})
        _commit(repo, "trunk moves on")
        _run(repo, "fetch", "-q", "origin")
        _run(repo, "checkout", "-q", "candidate")

        baseline = resolve_baseline(repo / LEDGER, root=repo)

        assert baseline.base_sha == forked_at
        assert baseline.loads()["tolerated"] == ["known"]

    def test_a_ledger_absent_at_the_base_tolerates_nothing(self, repo: Path) -> None:
        """A brand-new ratchet starts from an empty floor, not the candidate's."""
        _write(repo, "quality/brand-new.json", {"tolerated": ["seeded-on-the-branch"]})
        _commit(repo, "add a new ratchet with a pre-populated ledger")

        baseline = resolve_baseline(repo / "quality/brand-new.json", root=repo)

        assert baseline.absent_at_base
        assert baseline.origin == "base"
        assert baseline.loads(default={"tolerated": []})["tolerated"] == []


class TestUnreadableTrustIsAFailureNotAFallback:
    def test_a_named_base_that_cannot_be_resolved_raises(self, repo: Path) -> None:
        """The hole this closes: never hand judgment back to the candidate."""
        with pytest.raises(RatchetProvenanceError, match="could not be resolved"):
            resolve_baseline(repo / LEDGER, base="origin/no-such-branch", root=repo)

    def test_an_unreachable_base_raises_rather_than_reading_the_worktree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two histories with no merge base is the shallow-clone symptom."""
        monkeypatch.delenv(BASE_REV_ENV, raising=False)
        root = tmp_path / "orphan"
        root.mkdir()
        _run(root, "init", "-q", "-b", "develop")
        _write(root, LEDGER, {"tolerated": ["known"]})
        _commit(root, "one history")
        _run(root, "checkout", "-q", "--orphan", "unrelated")
        _write(root, LEDGER, {"tolerated": []})
        _commit(root, "a wholly unrelated history")

        with pytest.raises(RatchetProvenanceError, match="no merge base"):
            resolve_baseline(root / LEDGER, base="develop", root=root)

    def test_a_ledger_that_is_not_json_at_the_base_raises(self, repo: Path) -> None:
        (repo / LEDGER).write_text("{ not json", encoding="utf-8")
        _commit(repo, "trunk ledger is corrupt")
        _run(repo, "checkout", "-q", "develop")
        _run(repo, "merge", "-q", "candidate")
        _run(repo, "fetch", "-q", "origin")
        _run(repo, "checkout", "-q", "candidate")

        with pytest.raises(RatchetProvenanceError, match="not valid JSON"):
            resolve_baseline(repo / LEDGER, root=repo).loads()

    def test_a_path_outside_the_repo_raises(self, repo: Path, tmp_path: Path) -> None:
        outside = tmp_path / "elsewhere.json"
        outside.write_text("{}", encoding="utf-8")

        with pytest.raises(RatchetProvenanceError, match="outside"):
            resolve_baseline(outside, base="develop", root=repo)


class TestTheDeveloperLoopStillWorks:
    def test_no_base_anywhere_reads_the_worktree_and_says_so(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fresh clone with no `origin/develop` must not fail every gate."""
        monkeypatch.delenv(BASE_REV_ENV, raising=False)
        root = tmp_path / "solo"
        root.mkdir()
        _run(root, "init", "-q", "-b", "develop")
        _write(root, LEDGER, {"tolerated": ["local"]})
        _commit(root, "only ever local")

        baseline = resolve_baseline(root / LEDGER, root=root)

        assert baseline.origin == "worktree"
        assert baseline.base_sha is None
        assert baseline.loads()["tolerated"] == ["local"]

    def test_the_environment_overrides_the_default_trunk(self, repo: Path) -> None:
        """CI names the base explicitly rather than guessing at the trunk."""
        forked_at = _run(repo, "rev-parse", "HEAD")
        _write(repo, LEDGER, {"tolerated": ["known", "candidate-only"]})
        _commit(repo, "branch edit")

        baseline = resolve_baseline(repo / LEDGER, base=forked_at, root=repo)

        assert baseline.base_sha == forked_at
        assert baseline.loads()["tolerated"] == ["known"]

    def test_a_missing_worktree_ledger_is_absent_not_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(BASE_REV_ENV, raising=False)
        root = tmp_path / "empty"
        root.mkdir()
        _run(root, "init", "-q", "-b", "develop")
        _write(root, "seed.txt", "x")
        _commit(root, "seed")

        baseline = resolve_baseline(root / LEDGER, root=root)

        assert baseline.absent_at_base
        assert baseline.loads(default={"tolerated": []})["tolerated"] == []


class TestTheNonPassingStates:
    def test_an_empty_measurement_is_refused(self) -> None:
        """ "No findings" and "did not look" are indistinguishable without this."""
        with pytest.raises(RatchetProvenanceError, match="measured no fields"):
            require_measurement([], ratchet="wiring-reads", what="fields")

    def test_a_real_measurement_passes(self) -> None:
        require_measurement(["one"], ratchet="wiring-reads", what="fields")

    def test_a_changed_metric_definition_is_refused(self) -> None:
        baseline = Baseline(text="{}", origin="base", base_sha="a" * 40, path=Path("l.json"))

        with pytest.raises(RatchetProvenanceError, match="different question"):
            require_metric_version("2", recorded="1", ratchet="r", baseline=baseline)

    def test_an_unrecorded_metric_version_is_not_a_failure(self) -> None:
        """A ledger predating versioning is grandfathered, not broken."""
        baseline = Baseline(text="{}", origin="base", base_sha="a" * 40, path=Path("l.json"))

        require_metric_version("1", recorded=None, ratchet="r", baseline=baseline)


class TestTheProvenanceRecord:
    def _provenance(self, baseline: Baseline, **kwargs: object) -> Provenance:
        defaults: dict[str, object] = {
            "ratchet": "wiring-reads",
            "baseline": baseline,
            "tool": "ast",
            "metric_definition_version": "1",
            "old_value": "16 unread",
            "new_value": "17 unread",
            "candidate_sha": "b" * 40,
        }
        defaults.update(kwargs)
        return Provenance(**defaults)  # type: ignore[arg-type]

    def test_it_carries_every_field_the_definition_of_done_names(self) -> None:
        baseline = Baseline(text="{}", origin="base", base_sha="a" * 40, path=Path("l.json"))

        record = self._provenance(baseline, authorizations=("#516 -- @owner",)).as_dict()

        assert set(record) == {
            "ratchet",
            "baseline_origin",
            "base_sha",
            "candidate_sha",
            "tool",
            "metric_definition_version",
            "old_value",
            "new_value",
            "authorizations",
        }
        assert record["base_sha"] == "a" * 40
        assert record["authorizations"] == ["#516 -- @owner"]

    def test_a_worktree_verdict_says_it_is_not_a_monotonicity_check(self) -> None:
        """The reader has to be able to tell a real gate from a local run."""
        baseline = Baseline(text="{}", origin="worktree", base_sha=None, path=Path("l.json"))

        assert "NOT a monotonicity check" in self._provenance(baseline).render()

    def test_a_base_verdict_names_the_commit_it_judged_against(self) -> None:
        baseline = Baseline(text="{}", origin="base", base_sha="a" * 40, path=Path("l.json"))

        assert "base " + "a" * 12 in self._provenance(baseline).render()

    def test_an_absent_base_ledger_is_called_out_in_the_record(self) -> None:
        baseline = Baseline(text=None, origin="base", base_sha="a" * 40, path=Path("l.json"))

        assert "nothing is tolerated yet" in self._provenance(baseline).render()


def test_head_sha_reports_the_candidate_commit(repo: Path) -> None:
    assert head_sha(repo) == _run(repo, "rev-parse", "HEAD")


class TestAuthorizationsAreASeparateAct:
    """`--update` writes the ledger; it never writes this file (#534).

    That separation is the whole mechanism — if banking could authorize
    itself the gate would be back where it started — so the parsing and the
    refusals get their own coverage rather than riding on a ratchet's tests.
    """

    def _write_auth(self, tmp_path: Path, payload: object) -> Path:
        path = tmp_path / "ratchet-authorizations.json"
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        return path

    def test_an_absent_file_authorizes_nothing(self, tmp_path: Path) -> None:
        """The default state: no floor-raise is pre-approved."""
        assert load_authorizations("wiring-reads", path=tmp_path / "absent.json") == {}

    def test_a_complete_record_is_granted_and_reads_back_as_prose(self, tmp_path: Path) -> None:
        path = self._write_auth(
            tmp_path,
            {
                "wiring-reads": {
                    "demo.Root.field": {
                        "owner": "@owner",
                        "issue": "#534",
                        "reason": "consumed by a downstream product",
                    }
                }
            },
        )

        granted = load_authorizations("wiring-reads", path=path)

        assert granted == {"demo.Root.field": "#534 -- @owner: consumed by a downstream product"}

    @pytest.mark.parametrize("missing", ["owner", "issue", "reason"])
    def test_an_incomplete_record_is_refused(self, tmp_path: Path, missing: str) -> None:
        """An unexplained floor-raise is not an authorization."""
        record = {"owner": "@owner", "issue": "#534", "reason": "because"}
        record[missing] = "   "
        path = self._write_auth(tmp_path, {"wiring-reads": {"demo.Root.field": record}})

        with pytest.raises(RatchetProvenanceError, match=missing):
            load_authorizations("wiring-reads", path=path)

    def test_another_ratchets_authorizations_do_not_leak(self, tmp_path: Path) -> None:
        """One file, many ratchets: a grant is scoped to the one that earned it."""
        path = self._write_auth(
            tmp_path,
            {"vulture": {"other.entry": {"owner": "@o", "issue": "#1", "reason": "r"}}},
        )

        assert load_authorizations("wiring-reads", path=path) == {}

    def test_a_ratchet_present_with_no_entries_is_empty_not_an_error(self, tmp_path: Path) -> None:
        path = self._write_auth(tmp_path, {"wiring-reads": None})

        assert load_authorizations("wiring-reads", path=path) == {}

    def test_an_unparseable_file_is_refused_rather_than_ignored(self, tmp_path: Path) -> None:
        """Silently treating a corrupt authorizations file as "nothing is
        authorized" would be safe; treating it as unreadable is honest, and
        the difference matters when someone is trying to land a floor-raise."""
        path = tmp_path / "ratchet-authorizations.json"
        path.write_text("{ not json", encoding="utf-8")

        with pytest.raises(RatchetProvenanceError, match="not valid JSON"):
            load_authorizations("wiring-reads", path=path)


class TestTheRemainingResolverPaths:
    def test_the_environment_variable_is_honored(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CI names the base through `RATCHET_BASE_REV` rather than relying on
        the default trunk ref existing in the checkout."""
        forked_at = _run(repo, "rev-parse", "HEAD")
        _write(repo, LEDGER, {"tolerated": ["known", "candidate-only"]})
        _commit(repo, "branch edit")
        monkeypatch.setenv(BASE_REV_ENV, forked_at)

        baseline = resolve_baseline(repo / LEDGER, root=repo)

        assert baseline.base_sha == forked_at
        assert baseline.loads()["tolerated"] == ["known"]

    def test_a_ledger_that_exists_but_cannot_be_read_raises(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`cat-file -e` says the blob is there and `show` still fails — a
        damaged object store. Never a fallback to the worktree.
        """
        import scripts.ratchet_provenance as module

        real_git = module._git

        def _fail_show(args: list[str], *, root: Path):
            if args and args[0] == "show":
                return subprocess.CompletedProcess(args, 128, "", "object file is empty")
            return real_git(args, root=root)

        monkeypatch.setattr(module, "_git", _fail_show)

        with pytest.raises(RatchetProvenanceError, match="could not be read"):
            resolve_baseline(repo / LEDGER, root=repo)
