"""`GET /design/systems` — the list, and where each entry came from (#293).

The Conductor used to register one fabricated `DesignSystem` under a real
system's slug when the bundled set failed to import. Had this route existed
then, it would have shown a complete-looking catalogue of one entry
indistinguishable from the packaged article: same slug, same shape, no marker
of any kind. Two properties follow, and they are what is asserted here.

- Every entry says its origin, recorded by the loader that read the files.
- A service that did not start says so, with the cause, instead of returning
  an empty list. "No systems" and "we could not load the systems" are
  different facts, and #293 was months of the second rendered as the first.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from main import app
from services import design_service

from maistro_design.systems.importer import (
    BUNDLED_SLUGS,
    ORIGIN_BUNDLED,
    ORIGIN_CATALOG,
    ORIGIN_EXTERNAL,
)

PATH = "/v1/design/systems"


@pytest.fixture
async def client(monkeypatch):
    """An authenticated client over a really-started design service.

    `start_design_service` is called for real, so what these tests read is the
    wiring the container gets rather than a registry assembled here. The app's
    lifespan is deliberately not run: it re-initialises the stores and drops
    the seeded test user, which is why `test_api.py` builds its clients the
    same way.
    """
    monkeypatch.setattr(design_service, "_get_async_session_factory", lambda: None)
    monkeypatch.setattr(design_service, "_engine_singleton", None)
    monkeypatch.setattr(design_service, "_status", design_service.DesignServiceStatus())

    class _Settings:
        open_design_url = None
        open_design_api_key = None

    await design_service.start_design_service(_Settings())

    c = TestClient(app)
    response = c.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert response.status_code == 200, f"login failed: {response.text}"
    return c


class TestTheList:
    def test_it_returns_every_bundled_system(self, client):
        body = client.get(PATH).json()
        assert {s["slug"] for s in body["systems"]} == set(BUNDLED_SLUGS)

    def test_every_entry_names_its_origin(self, client):
        """The property the stub could not have satisfied. `bundled` is a claim
        about which files were read, made by the reader."""
        body = client.get(PATH).json()
        assert {s["origin"] for s in body["systems"]} == {ORIGIN_BUNDLED}

    def test_the_origin_vocabulary_is_closed(self, client):
        """Three values, none of them inferred. A fourth appearing means
        something is reporting a source it did not read from."""
        body = client.get(PATH).json()
        allowed = {ORIGIN_BUNDLED, ORIGIN_CATALOG, ORIGIN_EXTERNAL}
        assert {s["origin"] for s in body["systems"]} <= allowed

    def test_entries_carry_enough_to_tell_a_real_system_from_a_shell(self, client):
        """`default` is the case a slug cannot settle: the stub answered to the
        same name. Token counts are what distinguished them."""
        body = client.get(PATH).json()
        default = next(s for s in body["systems"] if s["slug"] == "default")
        assert default["color_count"] > 0
        assert default["trust_tier"] == "t1"

    def test_the_catalog_block_reports_the_optional_tier(self, client):
        body = client.get(PATH).json()
        assert body["catalog"]["available"] is True
        assert body["catalog"]["cause"] is None
        assert body["catalog"]["count"] > 100

    def test_the_response_is_ordered(self, client):
        """A list that reshuffles per request is one nobody can diff."""
        slugs = [s["slug"] for s in client.get(PATH).json()["systems"]]
        assert slugs == sorted(slugs)


class TestWhenTheServiceDidNotStart:
    def test_it_answers_503_with_the_recorded_cause(self, monkeypatch, client):
        """Not 200-with-nothing, and not a bare 503. The cause is the whole
        point: it is what a log line was doing badly before."""
        monkeypatch.setattr(
            design_service,
            "_status",
            design_service.DesignServiceStatus(cause="FileNotFoundError: manifest.json"),
        )
        response = client.get(PATH)
        assert response.status_code == 503
        assert "manifest.json" in response.json()["detail"]

    def test_a_status_with_no_cause_still_refuses(self, monkeypatch, client):
        """Degraded and unable to say why is still degraded. Returning the list
        anyway is the failure mode this route exists to end."""
        monkeypatch.setattr(design_service, "_status", design_service.DesignServiceStatus())
        assert client.get(PATH).status_code == 503

    def test_a_degraded_catalog_does_not_take_the_route_down(self, monkeypatch, client):
        """The optional half degrades; the required half still answers."""
        monkeypatch.setattr(
            design_service,
            "_status",
            design_service.DesignServiceStatus(
                ready=True,
                bundled_slugs=BUNDLED_SLUGS,
                catalog_available=False,
                catalog_cause="FileNotFoundError: catalog.json",
            ),
        )
        body = client.get(PATH).json()
        assert body["systems"]
        assert body["catalog"]["available"] is False
        assert body["catalog"]["count"] == 0
        assert "catalog.json" in body["catalog"]["cause"]


class TestEveryEngineRouteReportsTheCause:
    """#413. #293 gave startup an answerable status; only one route asked.

    The rest called `get_design_engine()`, caught its generic
    `RuntimeError("DesignEngine not initialized ...")` in a blanket handler and
    returned 500 -- discarding both the recorded cause and the
    service-unavailable semantics the status exists to express. A broken
    install answered "internal server error" on three routes out of four,
    which is the shape of #293 with a smaller blast radius.
    """

    CAUSE = "FileNotFoundError: systems/bundled/default/manifest.json"

    @pytest.fixture
    def broken(self, monkeypatch, client):
        monkeypatch.setattr(
            design_service,
            "_status",
            design_service.DesignServiceStatus(cause=self.CAUSE),
        )
        monkeypatch.setattr(design_service, "_engine_singleton", None)
        monkeypatch.setattr(design_service, "_store_singleton", None)
        return client

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/v1/design/systems"),
            ("get", "/v1/design/skills"),
            ("get", "/v1/design/skills/login-flow/discovery"),
            ("get", "/v1/design/projects"),
            ("get", "/v1/design/projects/some-id"),
            ("post", "/v1/design/projects"),
        ],
    )
    def test_it_answers_503_not_500(self, broken, method, path):
        # A valid body: FastAPI validates before the handler runs, so an
        # invalid one would 422 without ever reaching the readiness check.
        body = (
            {"skill_slug": "login-flow", "responses": {"auth_methods": "email"}}
            if method == "post"
            else None
        )
        response = getattr(broken, method)(path, **({"json": body} if body else {}))
        assert response.status_code == 503, f"{path} returned {response.status_code}"

    @pytest.mark.parametrize(
        "path",
        ["/v1/design/systems", "/v1/design/skills", "/v1/design/projects"],
    )
    def test_the_recorded_cause_reaches_the_caller(self, broken, path):
        """A 503 saying only "unavailable" is the log line again. The cause is
        the thing #293 added and the thing these routes were dropping."""
        assert "manifest.json" in broken.get(path).json()["detail"]

    def test_a_ready_service_is_not_affected(self, client):
        """The guard must not have made working routes fail."""
        assert client.get("/v1/design/skills").status_code == 200
        assert client.get("/v1/design/systems").status_code == 200
