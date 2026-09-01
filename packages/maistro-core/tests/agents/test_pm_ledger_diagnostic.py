"""Temporary deterministic ledger transformer for #129 closeout."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[4]
_RADON = _ROOT / "quality" / "radon-baseline.json"
_VULTURE = _ROOT / "quality" / "vulture-baseline.json"
_DIRECT = _ROOT / "quality" / "direct-effect-call-sites.json"
_MODEL_EGRESS = _ROOT / "quality" / "model-egress.json"

_RADON_STALE = (
    "packages/maistro-core/src/maistro/tools/atlassian/client.py::"
    "AtlassianMCPClient._parse_confluence_page"
)
_VULTURE_STALE = {
    "packages/maistro-core/src/maistro/tools/atlassian/client.py::unused method 'confluence_get_page'",
    "packages/maistro-core/src/maistro/tools/atlassian/client.py::unused method 'confluence_search'",
    "packages/maistro-core/src/maistro/tools/atlassian/client.py::unused method 'healthz'",
    "packages/maistro-core/src/maistro/tools/atlassian/client.py::unused method 'jira_get_issue'",
    "packages/maistro-core/src/maistro/tools/atlassian/client.py::unused method 'jira_get_my_issues'",
    "packages/maistro-core/src/maistro/tools/atlassian/client.py::unused method 'jira_search_by_text'",
    "packages/maistro-core/src/maistro/tools/atlassian/client.py::unused method 'jira_search_issues'",
}
_VULTURE_DECLARATIVE = (
    "packages/maistro-core/src/maistro/graph/nodes/jira_poll.py::unused variable 'issuetype'"
)
_RETIRED_EFFECT_PATHS = {
    "packages/maistro-core/src/maistro/agents/pm_llm_call.py",
    "packages/maistro-core/src/maistro/agents/pm_runner.py",
}


def _encoded(value: object) -> str:
    text = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    return base64.b64encode(text.encode()).decode()


def _emit_exact_pm_closeout_ledgers() -> None:
    radon = json.loads(_RADON.read_text(encoding="utf-8"))
    old_entries = radon["entries"]
    new_entries = [entry for entry in old_entries if entry["key"] != _RADON_STALE]
    assert len(old_entries) - len(new_entries) == 1
    radon["entries"] = new_entries

    vulture = json.loads(_VULTURE.read_text(encoding="utf-8"))
    rules = {rule["id"]: rule for rule in vulture["rules"]}
    public = rules["core-public-api-surface"]["findings"]
    assert _VULTURE_STALE.intersection(public) == _VULTURE_STALE
    rules["core-public-api-surface"]["findings"] = [
        finding for finding in public if finding not in _VULTURE_STALE
    ]
    declarative = rules["pydantic-declarative-field"]["findings"]
    assert _VULTURE_DECLARATIVE not in declarative
    declarative.append(_VULTURE_DECLARATIVE)
    declarative.sort()

    direct = json.loads(_DIRECT.read_text(encoding="utf-8"))
    sites = direct["sites"]
    retired_site_ids = [
        site_id for site_id, site in sites.items() if site["path"] in _RETIRED_EFFECT_PATHS
    ]
    assert len(retired_site_ids) == 8
    direct["sites"] = {
        site_id: site for site_id, site in sites.items() if site_id not in retired_site_ids
    }

    model_egress = json.loads(_MODEL_EGRESS.read_text(encoding="utf-8"))
    modules = model_egress["modules"]
    assert modules.count("maistro.agents.pm_llm_call") == 1
    model_egress["modules"] = [m for m in modules if m != "maistro.agents.pm_llm_call"]

    message = (
        "#129_LEDGER_BLOBS\n"
        f"RADON_B64={_encoded(radon)}\n"
        f"VULTURE_B64={_encoded(vulture)}\n"
        f"DIRECT_B64={_encoded(direct)}\n"
        f"MODEL_EGRESS_B64={_encoded(model_egress)}\n"
        "END_129_LEDGER_BLOBS"
    )
    print(message, flush=True)
    pytest.exit("#129 diagnostic emitted", returncode=1)


_emit_exact_pm_closeout_ledgers()
