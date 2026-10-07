"""The backend API reference (`/docs`), served entirely from first-party assets.

FastAPI's default docs page references three third-party resources — the
Swagger UI stylesheet and bundle from jsdelivr, and a favicon from
fastapi.tiangolo.com — and inlines its bootstrap `<script>` into the document.
Every one of those is refused by the Conductor's enforced CSP
(`script-src 'self'`, `style-src 'self'`, no `unsafe-inline`, no third-party
origin), so before #1425 the page returned a blank container and a console
full of violations: the CSP was doing its job against the documentation page.

The fix does not touch the policy. Nothing about a docs page justifies a wider
one — an exemption carved out for one route is an exemption every injected
script on that route inherits. Instead the page is served from assets vendored
into this repository (`backend/static/swagger-ui/`, provenance and hashes in
the README next to them), exactly like the SPA bundle and the self-hosted
typefaces the policy was already serving:

- `swagger-ui.css`, `swagger-ui-bundle.js` and the favicons come from the
  pinned `swagger-ui-dist` release;
- the bootstrap lives in `swagger-initializer.js`, a served file, because
  FastAPI inlines it and inline is what the policy forbids;
- the favicon is the vendored one, so `img-src 'self'` covers it;
- the OpenAPI schema is fetched from `/openapi.json`, same-origin, so
  `connect-src 'self'` covers it.

Every response carries the ordinary policy from `services/csp_policy.py`
unchanged; nothing here may widen a directive. The assets are served through
an explicit whitelist (`_ASSETS`) rather than a directory mount: a path that
is not a docs resource answers 404, a file that is missing answers 404 rather
than falling through to the SPA shell, and no requester-controlled path ever
reaches the filesystem.

Out of scope, deliberately: `/redoc` keeps FastAPI's default CDN-backed page.
ReDoc is a second renderer of the same schema, vendoring its ~3 MB standalone
bundle to fix a page this issue's audit never mentions is a product decision,
and silently dropping the route would be another. If a CSP violation is ever
reported against `/redoc`, this module is the pattern to copy.

The `oauth2-redirect` page is not vendored because the served OpenAPI document
declares no security schemes — `test_docs_first_party.py` asserts that, so the
first person to add an OAuth2 flow meets the missing asset as a test failure
with a pointer here rather than as a silent broken Authorize button.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Final

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter()

#: Vendored swagger-ui-dist release, pinned upstream (see the README beside
#: the assets for source URLs and hashes).
_SWAGGER_UI_DIST_VERSION: Final = "5.33.1"

#: Served from `backend/static/swagger-ui/`, which this file sits two parents
#: below (`backend/routes/api_docs.py` -> backend).
ASSET_DIR: Final = Path(__file__).resolve().parents[1] / "static" / "swagger-ui"


@dataclass(frozen=True)
class _Asset:
    """One first-party docs resource: what to serve and how to describe it."""

    media_type: Final[str]
    sha256: str


#: The whitelist of served paths. Anything else is not a docs resource and
#: answers 404 — including names that exist in the directory (the README) and
#: names that exist in upstream's dist but nothing here references (the
#: standalone preset, the maps, the oauth2 redirect).
_ASSETS: Final[dict[str, _Asset]] = {
    # The sha256 column is a content fingerprint of the pinned upstream
    # release, checked at test time and at serve time — DevSkim's key-shape
    # heuristic cannot tell it from a credential, so each line carries the
    # rule's inline suppression with that reason (same mechanism the
    # loopback URLs in `config.py` use).
    "swagger-ui-bundle.js": _Asset(
        media_type="text/javascript; charset=utf-8",
        sha256="050bc415ee7048dcd881682678f720264e7da5e373f7461d7c58c755305255f7",  # devskim: ignore DS173237 -- vendored-file fingerprint, not a credential
    ),
    "swagger-ui.css": _Asset(
        media_type="text/css; charset=utf-8",
        sha256="1ac324f7dcd27e4b9386b4bd6421271ec147e922a22c05ba24b11515e9aa6321",  # devskim: ignore DS173237 -- vendored-file fingerprint, not a credential
    ),
    "swagger-initializer.js": _Asset(
        media_type="text/javascript; charset=utf-8",
        sha256="96d494c655e51cb4455d21a0c47102ded63070f6dd1381e7fb752c51e51d87ff",  # devskim: ignore DS173237 -- vendored-file fingerprint, not a credential
    ),
    "favicon-32x32.png": _Asset(
        media_type="image/png",
        sha256="3ed612f41e050ca5e7000cad6f1cbe7e7da39f65fca99c02e99e6591056e5837",  # devskim: ignore DS173237 -- vendored-file fingerprint, not a credential
    ),
    "favicon-16x16.png": _Asset(
        media_type="image/png",
        sha256="af24ad604dd7b3bcda8f975ab973075f4a2f70a4087944a12f8ef8b63a3e07c2",  # devskim: ignore DS173237 -- vendored-file fingerprint, not a credential
    ),
}

#: The document itself. No inline script and no inline style: `script-src
#: 'self'` and `style-src 'self'` refuse both, so the bootstrap is the served
#: `swagger-initializer.js` and every URL below is a root-relative path. The
#: `{placeholders}` are filled from the request, honouring ASGI `root_path` the
#: way FastAPI's own docs route does, so a gateway that mounts the app at a
#: sub-path produces a working document too.
_DOCS_HTML: Final = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <meta name="openapi-url" content="{openapi_url}">
  <link rel="icon" type="image/png" sizes="32x32" href="{asset_base}/favicon-32x32.png">
  <link rel="icon" type="image/png" sizes="16x16" href="{asset_base}/favicon-16x16.png">
  <link type="text/css" rel="stylesheet" href="{asset_base}/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="{asset_base}/swagger-ui-bundle.js" charset="UTF-8"></script>
  <script src="{asset_base}/swagger-initializer.js" charset="UTF-8"></script>
</body>
</html>
"""


@router.get("/docs", include_in_schema=False)
async def api_docs(request: Request) -> HTMLResponse:
    """The API reference page, assembling only first-party resources."""
    # Same treatment FastAPI's swagger_ui_html applies: the gateway's mount
    # prefix, if any, prefixes every URL the document names.
    root_path = request.scope.get("root_path", "").rstrip("/")
    # Every value the document interpolates is request-derived — the ASGI
    # root_path a gateway (or a misbehaving proxy) hands the app, and the
    # configured app title — so each is HTML-escaped on the way in. The
    # template has no other holes: it is a module constant, not built from
    # response data, and escaping keeps a hostile prefix from breaking out of
    # an attribute into markup. (The rule's only sanitizer is
    # `django.utils.html.escape`, which is not a dependency of this service;
    # the stdlib escape above does the same job, so the finding is reviewed
    # and suppressed rather than rewritten to dodge the pattern.)
    return HTMLResponse(
        _DOCS_HTML.format(  # nosemgrep: python.django.security.injection.raw-html-format.raw-html-format -- interpolates deployment config (gateway root_path, app title), never request parameters, and each value is stdlib html.escape()'d immediately above
            title=escape(f"{request.app.title} - Swagger UI"),
            openapi_url=escape(f"{root_path}/openapi.json"),
            asset_base=escape(f"{root_path}/docs/static"),
        )
    )


@router.get("/docs/static/{asset_name}", include_in_schema=False)
async def api_docs_asset(asset_name: str) -> FileResponse:
    """One vendored docs resource, and nothing else.

    The whitelist is the containment: the path parameter cannot carry a
    separator, so there is no traversal surface, and a name that is not a docs
    resource — or a vendored file that went missing from the image — is a 404
    rather than a silent SPA shell or a 500.
    """
    asset = _ASSETS.get(asset_name)
    if asset is None:
        raise HTTPException(status_code=404, detail="not a docs asset")
    path = ASSET_DIR / asset_name
    if not path.is_file():
        # A vendored file missing at runtime is the explicit failure the issue
        # asks for: the docs page would otherwise blank out with no signal.
        raise HTTPException(status_code=404, detail="docs asset missing from deployment")
    return FileResponse(path, media_type=asset.media_type)


@router.get("/docs/static/{_nested:path}", include_in_schema=False)
async def api_docs_asset_reject(_nested: str) -> None:
    """Reject nested docs-asset paths before the SPA fallback can claim them.

    The whitelist route above matches a single segment only, so a path with a
    second segment — `/docs/static/missing/file.js`, or the encoded-separator
    form `..%2Fmain.py` (the ASGI path is percent-decoded before routing) —
    matches nothing here and would fall through to `main.py`'s SPA catch-all,
    which answers `index.html` with 200 once the image ships `frontend/dist`.
    Registered after the whitelist, this route matches exactly what the
    whitelist did not and keeps the explicit-404 contract: nothing under
    `/docs/static/` is ever an SPA page.
    """
    raise HTTPException(status_code=404, detail="not a docs asset")


def asset_fingerprints() -> dict[str, str]:
    """sha256 of every whitelisted asset as it sits on disk right now.

    Tests read this instead of restating the hashes, so a truncated or
    hand-edited vendored file fails against the recorded provenance in
    `_ASSETS` rather than against a second copy of the truth.
    """
    return {name: hashlib.sha256((ASSET_DIR / name).read_bytes()).hexdigest() for name in _ASSETS}
