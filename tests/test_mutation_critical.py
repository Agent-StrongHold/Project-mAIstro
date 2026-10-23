"""Tests for the mutation-critical file list loader (#330).

The list decides where the PR gate mutates and what the nightly measures. A
gate that cannot read its scope — or reads one that quietly shrank — passes by
doing nothing, which is exactly the placeholder #330 removes. Every failure
mode here is one the loader must make explicit.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mutation_critical.py"
REAL_LIST = ROOT / "quality" / "mutation-critical-files.json"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("mutation_critical", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_list(tmp_path: Path, payload) -> Path:
    path = tmp_path / "critical.json"
    path.write_text(json.dumps(payload) if isinstance(payload, dict) else payload, encoding="utf-8")
    return path


VALID = {
    "version": 1,
    "domains": ["secret-comparison"],
    "entries": [
        {
            "source": "packages/maistro-core/src/maistro/security/secret_equal.py",
            "domain": "secret-comparison",
            "reason": "the constant-time comparison primitive",
            "evidence": ["#320"],
        }
    ],
}


class TestLoadRejectsUnusableLists:
    def test_a_missing_list_is_an_error_not_an_empty_scope(self, tmp_path, mod):
        with pytest.raises(mod.CriticalListError, match="missing"):
            mod.load(tmp_path / "nope.json")

    def test_unparseable_json_is_an_error(self, tmp_path, mod):
        path = _write_list(tmp_path, "{not json")
        with pytest.raises(mod.CriticalListError, match="unreadable"):
            mod.load(path)

    def test_an_empty_entries_array_is_an_error(self, tmp_path, mod):
        # A silently emptied list is the governance failure: the gate would run
        # against nothing and report green.
        payload = dict(VALID, entries=[])
        with pytest.raises(mod.CriticalListError, match="non-empty 'entries'"):
            mod.load(_write_list(tmp_path, payload))

    def test_an_entry_missing_a_field_is_an_error(self, tmp_path, mod):
        payload = dict(VALID)
        entry = dict(payload["entries"][0])
        del entry["reason"]
        payload["entries"] = [entry]
        with pytest.raises(mod.CriticalListError, match="missing field"):
            mod.load(_write_list(tmp_path, payload))

    def test_an_undeclared_domain_is_an_error(self, tmp_path, mod):
        payload = json.loads(json.dumps(VALID))
        payload["entries"][0]["domain"] = "undeclared-domain"
        with pytest.raises(mod.CriticalListError, match="not declared"):
            mod.load(_write_list(tmp_path, payload))

    def test_a_duplicate_source_is_an_error(self, tmp_path, mod):
        payload = json.loads(json.dumps(VALID))
        payload["entries"] = payload["entries"] * 2
        with pytest.raises(mod.CriticalListError, match="duplicate"):
            mod.load(_write_list(tmp_path, payload))

    def test_a_path_that_does_not_exist_is_an_error(self, tmp_path, mod, monkeypatch):
        payload = json.loads(json.dumps(VALID))
        payload["entries"][0]["source"] = "packages/ghost/file.py"
        monkeypatch.setattr(mod, "ROOT", tmp_path)
        with pytest.raises(mod.CriticalListError, match="does not exist"):
            mod.load(_write_list(tmp_path, payload))


class TestTheCommittedList:
    """The real governance artifact, asserted at both ends."""

    def test_the_committed_list_validates(self, mod):
        mod.load(REAL_LIST)  # must not raise

    def test_the_three_demonstrated_modules_are_critical(self, mod):
        sources = set(mod.sources(mod.load(REAL_LIST)))
        assert {
            "packages/maistro-core/src/maistro/security/secret_equal.py",
            "packages/maistro-core/src/maistro/security/resource_policy.py",
            "packages/maistro-core/src/maistro/privilege.py",
        } <= sources

    def test_every_audit_domain_is_represented(self, mod):
        payload = mod.load(REAL_LIST)
        covered = {entry["domain"] for entry in payload["entries"]}
        assert covered == set(payload["domains"])


class TestIntersectAndEmit:
    def test_intersect_selects_only_critical_changed_files(self, mod):
        payload = mod.load(REAL_LIST)
        changed = [
            "packages/maistro-core/src/maistro/security/secret_equal.py",
            "packages/maistro-core/src/maistro/agents/base.py",
        ]
        assert mod.intersect(payload, changed) == [
            "packages/maistro-core/src/maistro/security/secret_equal.py"
        ]

    def test_changed_from_emits_target_rows(self, tmp_path, mod):
        changed = tmp_path / "changed.txt"
        changed.write_text(
            "packages/maistro-core/src/maistro/security/secret_equal.py\n",
            encoding="utf-8",
        )
        result = mod.main(["--list", str(REAL_LIST), "--changed-from", str(changed)])
        assert result == 0

    def test_unresolvable_critical_source_is_an_error(self, tmp_path, mod, monkeypatch):
        # A critical source with no test scope must fail loudly, never widen to
        # the whole suite and never skip silently.
        payload = json.loads(json.dumps(VALID))
        payload["entries"][0]["source"] = "scripts/definitely-not-a-gate.py"
        monkeypatch.setattr(mod, "ROOT", ROOT)
        real_isfile = Path.is_file

        def patched(self):
            if self.name == "definitely-not-a-gate.py":
                return True
            return real_isfile(self)

        monkeypatch.setattr(Path, "is_file", patched)
        loaded = mod.load(_write_list(tmp_path, payload))
        assert mod.intersect(loaded, ["scripts/definitely-not-a-gate.py"])
        assert mod._emit_targets(mod.intersect(loaded, ["scripts/definitely-not-a-gate.py"])) == 1

    def test_no_overlap_reports_zero_and_exits_zero(self, tmp_path, mod):
        changed = tmp_path / "changed.txt"
        changed.write_text("README.md\n", encoding="utf-8")
        assert mod.main(["--list", str(REAL_LIST), "--changed-from", str(changed)]) == 0

    def test_sources_mode_lists_every_entry(self, mod, capsys):
        assert mod.main(["--list", str(REAL_LIST), "--sources"]) == 0
        out = capsys.readouterr().out.splitlines()
        assert len(out) == len(mod.load(REAL_LIST)["entries"])
