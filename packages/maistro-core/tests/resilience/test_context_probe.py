from __future__ import annotations

import pytest

from maistro.resilience.context_probe import PROBE_SIZES, ContextProbe


class TestGetContextLength:
    def test_unknown_model_returns_none(self):
        probe = ContextProbe()
        assert probe.get_context_length("unknown-model") is None

    @pytest.mark.ac("ADR-066/AC-38")
    def test_known_model_returns_length(self):
        probe = ContextProbe()
        probe.set_known_length("gpt-4", 128000)
        assert probe.get_context_length("gpt-4") == 128000


class TestSetKnownLength:
    def test_populates_cache(self):
        probe = ContextProbe()
        probe.set_known_length("gpt-4", 128000)
        assert probe.get_context_length("gpt-4") == 128000

    def test_overwrites_existing(self):
        probe = ContextProbe()
        probe.set_known_length("gpt-4", 8000)
        probe.set_known_length("gpt-4", 128000)
        assert probe.get_context_length("gpt-4") == 128000

    def test_resets_probe_index(self):
        probe = ContextProbe()
        probe._probe_index["new-model"] = 2
        probe.set_known_length("new-model", 65536)
        assert "new-model" not in probe._probe_index


class TestProbeNextSize:
    def test_returns_first_probe_for_new_model(self):
        probe = ContextProbe()
        assert probe.probe_next_size("new-model") == 4096

    @pytest.mark.ac("ADR-066/AC-38")
    def test_returns_none_when_cached(self):
        probe = ContextProbe()
        probe.set_known_length("model", 8192)
        assert probe.probe_next_size("model") is None

    def test_returns_none_when_exhausted(self):
        probe = ContextProbe()
        probe._probe_index["model"] = len(PROBE_SIZES)
        assert probe.probe_next_size("model") is None

    def test_returns_subsequent_probes(self):
        probe = ContextProbe()
        assert probe.probe_next_size("m") == 4096
        probe._probe_index["m"] = 1
        assert probe.probe_next_size("m") == 16384
        probe._probe_index["m"] = 2
        assert probe.probe_next_size("m") == 65536


class TestRecordOverflow:
    def test_caches_limit(self):
        probe = ContextProbe()
        result = probe.record_overflow("model", 16384)
        assert result == 16383
        assert probe.get_context_length("model") == 16383

    def test_clears_probe_index(self):
        probe = ContextProbe()
        probe._probe_index["model"] = 2
        probe.record_overflow("model", 8192)
        assert "model" not in probe._probe_index

    def test_probe_next_returns_none_after_overflow(self):
        probe = ContextProbe()
        probe.record_overflow("model", 8192)
        assert probe.probe_next_size("model") is None


class TestRecordSuccess:
    def test_advances_probe_index(self):
        probe = ContextProbe()
        probe.record_success("model", 4096)
        assert probe._probe_index["model"] == 1
        assert probe.get_context_length("model") is None

    @pytest.mark.ac("ADR-066/AC-39")
    def test_advances_through_tiers(self):
        probe = ContextProbe()
        probe.record_success("model", 4096)
        probe.record_success("model", 16384)
        probe.record_success("model", 65536)
        assert probe._probe_index["model"] == 3
        assert probe.get_context_length("model") is None

    @pytest.mark.ac("ADR-066/AC-39")
    def test_caches_on_final_tier(self):
        probe = ContextProbe()
        for size in PROBE_SIZES[:-1]:
            probe.record_success("model", size)
        assert probe._probe_index["model"] == len(PROBE_SIZES) - 1
        probe.record_success("model", PROBE_SIZES[-1])
        assert probe.get_context_length("model") == PROBE_SIZES[-1]
        assert probe.probe_next_size("model") is None

    def test_no_op_when_cached(self):
        probe = ContextProbe()
        probe.set_known_length("model", 8192)
        probe.record_success("model", 4096)
        assert probe.get_context_length("model") == 8192

    def test_ignores_below_first_tier(self):
        probe = ContextProbe()
        probe.record_success("model", 100)
        assert probe._probe_index.get("model", 0) == 0


class TestProbeSizes:
    def test_probe_sizes_match_spec(self):
        assert PROBE_SIZES == [4096, 16384, 65536, 131072, 204800]
