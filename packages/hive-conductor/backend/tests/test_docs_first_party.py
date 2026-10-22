"""`/docs` under the enforced CSP, as served and as vendored (#1425).

The audit finding was exact: the page FastAPI generated loaded the Swagger UI
stylesheet and bundle from jsdelivr, its favicon from fastapi.tiangolo.com,
and inlined its bootstrap `<script>` — every one refused by the Conductor's
enforced first-party policy, leaving a blank container and a console full of
violations. The fix vendors the assets (`backend/static/swagger-ui/`) and
serves the bootstrap as a file, changing no directive anywhere.

So the assertions here are two halves, mirroring `test_csp.py`'s shape: one
asks whether the served document could render at all under the policy that
ships with it (first-party URLs only, no inline script, every referenced asset
actually served, the real schema reachable), and the other asks whether the
fix stayed inside the security boundary it was given (the policy on `/docs`
is byte-identical to the one on every other response; a hypothetical docs
exemption built from `'unsafe-inline'` or `'unsafe-eval'` is refused by the
canonical validator; nothing outside the whitelist is served).

`test_csp.py` keeps owning the policy itself; nothing here re-asserts its
directive table. What is new here is the document that must live inside it.
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
from routes import api_docs  # noqa: E402

ENFORCED = "content-security-policy"
REPORT_ONLY = "content-security-policy-report-only"

SPA_SHELL_MARKER = '<div id="root">'


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _client() -> TestClient:
    return TestClient(app)


def _docs_html() -> str:
    response = _client().get("/docs")
    assert response.status_code == 200
    return response.text


def _all_route_paths(application: Any) -> list[str]:
    """Route paths including those inside included routers.

    FastAPI 0.142 keeps each `include_router` as an `_IncludedRouter` wrapper
    around the original `APIRouter` rather than flattening its routes into
    `app.routes`, so counting a path means walking into each wrapper (nested
    includes nest wrappers)."""

    def walk(routes: Any, into: list[str]) -> None:
        for route in routes:
            original = getattr(route, "original_router", None)
            if original is not None:
                walk(original.routes, into)
            else:
                path = getattr(route, "path", "")
                if path:
                    into.append(path)

    paths: list[str] = []
    walk(application.router.routes, paths)
    return paths


def _referenced_urls(html: str) -> set[str]:
    """Every URL the document asks the browser to fetch.

    Deliberately structural rather than clever: `href`/`src` on any tag, plus
    the `<meta name="openapi-url">` the initializer reads. A new resource kind
    added without an attribute this sees would fail the asset tests instead —
    the whitelist is the authority, this is the net under it.
    """
    import re

    urls = set(re.findall(r'(?:href|src)="([^"]+)"', html))
    meta = re.search(r'<meta name="openapi-url" content="([^"]+)"', html)
    if meta:
        urls.add(meta.group(1))
    return urls


class TestTheDocumentCouldRender:
    def test_it_is_served_and_is_a_swagger_document(self) -> None:
        html = _docs_html()
        assert '<div id="swagger-ui"></div>' in html
        assert "Swagger UI" in html

    def test_every_url_it_names_is_first_party(self) -> None:
        """No scheme, no authority, no protocol-relative URL: everything the
        page fetches resolves against this origin, which is what `script-src
        'self'` / `style-src 'self'` / `img-src 'self'` can serve."""
        for url in _referenced_urls(_docs_html()):
            assert "://" not in url, url
            assert url.startswith("/"), url

    def test_it_has_no_inline_script(self) -> None:
        """`script-src 'self'` refuses an inline one — the third blocked
        resource in the audit's console capture, after the two CDN assets. The
        bootstrap lives in the served `swagger-initializer.js` instead."""
        html = _docs_html()
        script_lines = [line for line in html.splitlines() if "<script" in line]
        assert script_lines, "the document must load the vendored Swagger UI"
        assert [line for line in script_lines if "src=" not in line] == [], (
            "an inline <script> would be refused by the enforced policy"
        )

    def test_it_references_exactly_the_vendored_whitelist(self) -> None:
        """The whole document is accounted for — JavaScript, stylesheet,
        bootstrap, favicon, schema — and nothing the whitelist does not serve.
        A resource referenced but not vendored is a blank page; a resource
        vendored but never referenced is permission served for nothing."""
        referenced = {
            url.rsplit("/", 1)[-1]
            for url in _referenced_urls(_docs_html())
            if "/docs/static/" in url
        }
        assert referenced == set(api_docs._ASSETS)
        schema_url = next(u for u in _referenced_urls(_docs_html()) if "openapi" in u)
        assert schema_url.endswith("/openapi.json")

    def test_every_referenced_asset_is_actually_served(self) -> None:
        """Header/HTML checks alone cannot prove the page renders; this is the
        serving half. A 200 here with an empty body is not a pass — each asset
        must arrive as the bytes its recorded hash describes (next class)."""
        client = _client()
        for name, asset in api_docs._ASSETS.items():
            response = client.get(f"/docs/static/{name}")
            assert response.status_code == 200, name
            assert response.headers["content-type"] == asset.media_type, name
            assert len(response.content) > 0, name

    def test_the_openapi_document_is_served_and_describes_this_app(self) -> None:
        """The schema is the thing Swagger UI renders; the audit's acceptance
        check is the real document rendering, not a page that loads."""
        response = _client().get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert schema["info"]["title"] == app.title
        assert len(schema["paths"]) > 0

    def test_a_sub_path_deployment_gets_a_working_document(self) -> None:
        """A gateway mounting the app at a prefix must not strand the document:
        the asset and schema URLs follow ASGI `root_path`, the way FastAPI's
        own docs route handled it."""
        client = TestClient(app, root_path="/pm")
        response = client.get("/docs")
        assert response.status_code == 200
        assert 'content="/pm/openapi.json"' in response.text
        assert 'href="/pm/docs/static/swagger-ui.css"' in response.text
        assert 'src="/pm/docs/static/swagger-initializer.js"' in response.text


class TestTheVendoredAssets:
    def test_they_match_the_recorded_provenance(self) -> None:
        """A truncated re-download, a hand-patched bundle, or a file lost from
        the image must fail here rather than blank the page in production. The
        hashes recorded in `routes/api_docs.py` were taken from the pinned
        upstream release; the on-disk files must still be exactly those bytes."""
        assert api_docs.asset_fingerprints() == {
            name: asset.sha256 for name, asset in api_docs._ASSETS.items()
        }

    def test_a_missing_vendored_file_is_an_explicit_404(self, tmp_path: Any) -> None:
        """The failure mode the issue forbids is a page that 200s and renders
        nothing. With the vendored file gone, the asset route answers 404
        itself — it must not fall through to the SPA shell, which would look
        like a working page that never mounts Swagger UI."""
        empty_dir = tmp_path / "absent"
        empty_dir.mkdir()
        original = api_docs.ASSET_DIR
        api_docs.ASSET_DIR = empty_dir
        try:
            response = _client().get("/docs/static/swagger-ui-bundle.js")
        finally:
            api_docs.ASSET_DIR = original
        assert response.status_code == 404
        assert "missing from deployment" in response.json()["detail"]
        assert SPA_SHELL_MARKER not in response.text

    def test_nothing_outside_the_whitelist_is_served(self) -> None:
        """The docs asset path is a constrained surface: names that exist on
        disk (the README) and names that exist in upstream's dist but nothing
        references must both refuse, not serve."""
        client = _client()
        for name in ("README.md", "swagger-ui-standalone-preset.js", "main.py"):
            response = client.get(f"/docs/static/{name}")
            assert response.status_code == 404, name
            assert response.json()["detail"] == "not a docs asset", name

    def test_a_dot_segment_cannot_escape_the_whitelist(self) -> None:
        """Traversal reaches the route only in its encoded form (the client
        normalises a literal `..` away before the server sees it); the path
        parameter cannot carry a separator, so an encoded segment either fails
        the whitelist or falls to the SPA fallback — never to a file.
        `%2e%2e` decodes to a separator-free name and must hit the whitelist
        refusal, and the encoded separator must not serve `main.py`."""
        client = _client()
        assert client.get("/docs/static/%2e%2e").json()["detail"] == "not a docs asset"
        escaped = client.get("/docs/static/..%2Fmain.py")
        assert escaped.status_code == 404
        assert b"import" not in escaped.content

    def test_nested_docs_asset_paths_are_rejected_with_the_spa_built(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The route contract must hold in production, where the image ships
        `frontend/dist` and `main.py` registers its SPA catch-all. A docs-asset
        path with a second segment — a missing nested resource, or the
        encoded-separator form `..%2Fmain.py` (the ASGI path is percent-decoded
        before routing) — does not match the single-segment whitelist route, so
        only a dedicated rejection route keeps it from being answered by the
        SPA shell with 200. The module-level `app` here was created while
        `frontend/dist` was absent, which is exactly why the traversal test
        above passes for the wrong reason; this one builds an app with the
        directory present so the fallback it guards against actually exists
        (AGENTS.md: a test must fail against the regression it names)."""
        import main as main_module

        dist = tmp_path / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text(
            '<!DOCTYPE html><html><body><div id="root"></div></body></html>'
        )
        monkeypatch.setattr(main_module, "STATIC_DIR", dist)
        client = TestClient(main_module.create_app())
        for path in ("/docs/static/missing/file.js", "/docs/static/..%2Fmain.py"):
            response = client.get(path)
            assert response.status_code == 404, path
            assert response.json()["detail"] == "not a docs asset", path
            assert SPA_SHELL_MARKER not in response.text, path

    def test_the_default_docs_route_exists_exactly_once(self) -> None:
        """`docs_url=None` retired FastAPI's built-in page; the vendored route
        replaced it. A duplicate would leave whichever registered first
        deciding what `/docs` serves."""
        paths = _all_route_paths(app)
        assert paths.count("/docs") == 1
        # The other default docs route stays as FastAPI registered it — see
        # the module docstring in `routes.api_docs` for why /redoc is out of
        # scope here.
        assert "/redoc" in paths


class TestThePolicyIsUnchangedByDocs:
    def test_the_docs_response_carries_the_ordinary_policy(self) -> None:
        """Byte-for-byte the header every other response carries, under the
        enforcing name. The fix worked by making the page satisfy the policy;
        the policy never moved."""
        client = _client()
        assert client.get("/docs").headers[ENFORCED] == client.get("/health").headers[ENFORCED]
        assert REPORT_ONLY not in client.get("/docs").headers

    def test_the_served_policy_admits_no_inline_script_or_eval_or_third_party(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The production posture, read off the actual docs response: nothing
        here may widen script execution, and no http(s) origin may appear in
        any directive — the exact permission the audit found being used."""
        monkeypatch.setenv("ALLOW_INSECURE_TRANSPORT", "false")
        from config import get_settings

        get_settings.cache_clear()
        header = _client().get("/docs").headers[ENFORCED]

        assert "'unsafe-inline'" not in header
        assert "'unsafe-eval'" not in header
        assert "script-src 'self'" in header
        assert not [word for word in header.split() if word.startswith("http")]

    def test_a_docs_exception_woven_from_unsafe_inline_is_refused(self) -> None:
        """The shortcut this issue must not take: widening `script-src` so the
        old CDN page (or its inline bootstrap) could load. The canonical
        validator refuses it at construction — this documents that a future
        attempt dies in CI, not in a header nobody reads."""
        from services.csp_policy import conductor_policy

        from maistro.security.content_security_policy import (
            FORBIDDEN_IN_SCRIPT_SRC,
            InsecurePolicyError,
        )

        candidate = dict(conductor_policy().directives)
        candidate["script-src"] = ("'self'", FORBIDDEN_IN_SCRIPT_SRC)

        with pytest.raises(InsecurePolicyError, match="unsafe-inline"):
            __import__(
                "maistro.security.content_security_policy",
                fromlist=["ContentSecurityPolicy"],
            ).ContentSecurityPolicy.build(candidate)

    def test_an_eval_permission_is_refused_in_any_directive(self) -> None:
        """`'unsafe-eval'` is the other hollowing-out, and the validator takes
        it in *any* directive — asserted here through the docs-relevant style
        path so the refusal is tied to this page's dependency tree."""
        from services.csp_policy import conductor_policy

        from maistro.security.content_security_policy import (
            FORBIDDEN_ANYWHERE,
            ContentSecurityPolicy,
            InsecurePolicyError,
        )

        candidate = dict(conductor_policy().directives)
        candidate["style-src"] = ("'self'", FORBIDDEN_ANYWHERE)

        with pytest.raises(InsecurePolicyError, match="unsafe-eval"):
            ContentSecurityPolicy.build(candidate)

    def test_no_security_scheme_so_no_oauth2_redirect_is_required(self) -> None:
        """The vendored set has no `oauth2-redirect.html` because the served
        document declares no security schemes — the Authorize button that page
        serves cannot exist. The first OAuth2 flow added to the schema fails
        this test, and the fix is to vendor the redirect page and whitelist it
        in `routes/api_docs.py`, not to disable this assertion."""
        schema = _client().get("/openapi.json").json()
        schemes = (schema.get("components", {}) or {}).get("securitySchemes") or {}
        oauth2 = {k for k, v in schemes.items() if (v or {}).get("type") == "oauth2"}
        assert oauth2 == set(), (
            "an OAuth2 security scheme needs a first-party oauth2-redirect page; "
            "see the module docstring in routes/api_docs.py"
        )
