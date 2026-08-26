"""The Conductor's Content-Security-Policy, as served and as written (#310).

Two halves, and they answer different questions. The route tests ask whether
the header reaches a response at all — the failure mode that produced this
issue was not a weak policy but no policy. The policy tests ask whether what it
contains still matches what the front end actually loads, which is the failure
mode that arrives later, quietly, the first time someone adds a CDN.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from main import app  # noqa: E402

_FRONTEND = _BACKEND.parent / "frontend"

ENFORCED = "content-security-policy"
REPORT_ONLY = "content-security-policy-report-only"


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _client() -> TestClient:
    return TestClient(app)


class TestTheHeaderReachesEveryResponse:
    @pytest.mark.parametrize("path", ["/health", "/v1/auth/whoami", "/v1/setup/status"])
    def test_an_unauthenticated_response_carries_it(self, path: str) -> None:
        """Including the public ones. The login page is the document an
        injection would be delivered to, and it is served without a session."""
        assert ENFORCED in _client().get(path).headers

    def test_an_authenticated_response_carries_it(self, authed_client: Any) -> None:
        assert ENFORCED in authed_client.get("/v1/chat/sessions").headers

    def test_a_refusal_carries_it_too(self) -> None:
        """A 401 is still a document a browser may render."""
        assert ENFORCED in _client().get("/v1/agents").headers

    def test_it_is_not_also_sent_report_only(self) -> None:
        """Both headers at once is the state that looks like belt and braces
        and is actually one enforced policy plus a duplicate nobody reads."""
        headers = _client().get("/health").headers

        assert ENFORCED in headers
        assert REPORT_ONLY not in headers


class TestTheRolloutSwitch:
    def test_report_only_moves_the_policy_to_the_other_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from config import get_settings

        enforced_value = _client().get("/health").headers[ENFORCED]

        monkeypatch.setenv("CSP_REPORT_ONLY", "true")
        get_settings.cache_clear()
        headers = _client().get("/health").headers

        assert ENFORCED not in headers
        assert headers[REPORT_ONLY] == enforced_value

    def test_enforcement_is_the_default(self) -> None:
        """A report-only policy nobody promotes protects nothing while looking
        like it does, so the shipped default has to be the enforcing one."""
        from config import Settings

        assert Settings(_env_file=None).csp_report_only is False


class TestTheDevelopmentPolicyIsDistinct:
    def test_this_suite_runs_under_the_development_policy(self) -> None:
        """Stated rather than discovered. `conftest.py` declares the suite a
        local-development context (#369), so every other route assertion here
        sees the *development* header — which is why the production shape is
        asserted by forcing the flag off below rather than by trusting the
        ambient default."""
        from config import get_settings
        from services.csp_policy import VITE_DEV_ORIGINS

        assert get_settings().allow_insecure_transport is True
        assert any(
            origin in _client().get("/health").headers[ENFORCED] for origin in VITE_DEV_ORIGINS
        )

    def test_a_production_run_gets_no_dev_origins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from config import get_settings
        from services.csp_policy import VITE_DEV_ORIGINS

        monkeypatch.setenv("ALLOW_INSECURE_TRANSPORT", "false")
        get_settings.cache_clear()

        production = _client().get("/health").headers[ENFORCED]

        assert not any(origin in production for origin in VITE_DEV_ORIGINS)

    def test_it_is_driven_by_the_existing_local_development_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`ALLOW_INSECURE_TRANSPORT` is where a deployment already declares a
        local run, and start-up refuses to combine it with a production cookie
        posture (#369). A second switch would be a second way to ship the loose
        policy by accident, so the same flag has to move the policy both ways."""
        from config import get_settings
        from services.csp_policy import VITE_DEV_ORIGINS

        monkeypatch.setenv("ALLOW_INSECURE_TRANSPORT", "false")
        get_settings.cache_clear()
        production = _client().get("/health").headers[ENFORCED]

        monkeypatch.setenv("ALLOW_INSECURE_TRANSPORT", "true")
        get_settings.cache_clear()
        development = _client().get("/health").headers[ENFORCED]

        assert production != development
        assert not any(origin in production for origin in VITE_DEV_ORIGINS)
        assert all(origin in development for origin in VITE_DEV_ORIGINS)

    def test_development_still_refuses_inline_script(self) -> None:
        """The dev policy is looser in two named ways and no others. A dev
        policy that permitted inline script would let a violation reach
        production undetected, because nobody would ever see it locally."""
        from services.csp_policy import conductor_policy

        assert conductor_policy(development=True).sources_for("script-src") == ("'self'",)

    def test_upgrade_insecure_requests_is_production_only(self) -> None:
        """A local run is plain HTTP; the directive would upgrade every request
        to a port nothing is listening on."""
        from services.csp_policy import conductor_policy

        assert "upgrade-insecure-requests" in conductor_policy().header_value()
        assert "upgrade-insecure-requests" not in conductor_policy(development=True).header_value()


class TestThePolicyMatchesWhatTheFrontEndLoads:
    """The half that rots. Every assertion here is anchored to a file in
    `frontend/`, so a source that stops being needed, or an origin that starts
    being needed, shows up as a failure rather than as an unnoticed permission.
    """

    def test_the_only_third_party_origins_are_the_font_hosts_index_html_names(self) -> None:
        import re

        from services.csp_policy import FONT_FILE_ORIGIN, FONT_STYLESHEET_ORIGIN, conductor_policy

        index_html = (_FRONTEND / "index.html").read_text(encoding="utf-8")
        wanted = {
            f"{scheme}://{host}"
            for scheme, host in re.findall(r"(https)://([a-zA-Z0-9.-]+)", index_html)
        }
        served = {
            source
            for _name, sources in conductor_policy().directives
            for source in sources
            if source.startswith("http")
        }

        assert served == wanted == {FONT_STYLESHEET_ORIGIN, FONT_FILE_ORIGIN}

    def test_nothing_in_the_frontend_injects_a_stylesheet_at_runtime(self) -> None:
        """`style-src` has no `'unsafe-inline'`, so a runtime `<style>` element
        would be blocked and the feature it styles would silently lose its
        appearance. The four that existed were moved into `index.css`."""
        offenders = [
            path.relative_to(_FRONTEND).as_posix()
            for path in (_FRONTEND / "src").rglob("*.tsx")
            if 'document.createElement("style")' in path.read_text(encoding="utf-8")
            or "<style>{`" in path.read_text(encoding="utf-8")
        ]

        assert offenders == []

    def test_the_built_document_has_no_inline_script(self) -> None:
        """`script-src 'self'` blocks one. Vite emits a served module today;
        a plugin that inlines the entry would break the app in production and
        pass every backend test."""
        dist_index = _FRONTEND / "dist" / "index.html"
        if not dist_index.is_file():
            pytest.skip("frontend not built; the e2e job builds it")

        markup = dist_index.read_text(encoding="utf-8")

        assert "<script" in markup
        assert not [
            line for line in markup.splitlines() if "<script" in line and "src=" not in line
        ]

    @pytest.mark.parametrize(
        ("directive", "expected"),
        [
            ("default-src", ("'self'",)),
            ("script-src", ("'self'",)),
            ("object-src", ("'none'",)),
            ("frame-src", ("'none'",)),
            ("frame-ancestors", ("'none'",)),
            ("base-uri", ("'self'",)),
            ("form-action", ("'self'",)),
        ],
    )
    def test_the_directives_that_should_admit_nothing_else(
        self, directive: str, expected: tuple[str, ...]
    ) -> None:
        from services.csp_policy import conductor_policy

        assert conductor_policy().sources_for(directive) == expected
