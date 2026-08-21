import time
from unittest.mock import MagicMock, patch

import pytest
from server.lulu.client import LuluApiError, LuluAuthError, LuluClient
from server.lulu.constants import DEFAULT_PACKAGE, LULU_SANDBOX_BASE


@pytest.fixture
def mock_auth_response():
    return MagicMock(
        status_code=200,
        json=MagicMock(return_value={"access_token": "test-token-123", "expires_in": 300}),
    )


@pytest.fixture
def client():
    return LuluClient(
        client_key="test-key",
        client_secret="test-secret",
        contact_email="test@example.com",
        sandbox=True,
    )


class TestAuth:
    @patch("server.lulu.client.requests.post")
    def test_authenticate_success(self, mock_post, mock_auth_response, client):
        mock_post.return_value = mock_auth_response
        token = client._authenticate()
        assert token == "test-token-123"
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "Basic " in call_args[1]["headers"]["Authorization"]
        assert call_args[0][0].endswith("/auth/realms/glasstree/protocol/openid-connect/token")

    @patch("server.lulu.client.requests.post")
    def test_authenticate_failure(self, mock_post, client):
        mock_post.return_value = MagicMock(status_code=401, text="Unauthorized")
        with pytest.raises(LuluAuthError):
            client._authenticate()

    @patch("server.lulu.client.requests.post")
    def test_token_cached(self, mock_post, mock_auth_response, client):
        mock_post.return_value = mock_auth_response
        client._authenticate()
        assert client._get_token() == "test-token-123"
        assert mock_post.call_count == 1

    @patch("server.lulu.client.requests.post")
    def test_token_refreshed_after_expiry(self, mock_post, mock_auth_response, client):
        mock_post.return_value = mock_auth_response
        client._authenticate()
        client._token_expires = time.time() - 10
        token = client._get_token()
        assert token == "test-token-123"
        assert mock_post.call_count == 2


class TestPrintJobs:
    @patch("server.lulu.client.requests.request")
    @patch("server.lulu.client.requests.post")
    def test_get_print_jobs(self, mock_auth_post, mock_request, client, mock_auth_response):
        mock_auth_post.return_value = mock_auth_response
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"results": [{"id": 1, "status": {"name": "CREATED"}}]}),
        )
        jobs = client.get_print_jobs()
        assert len(jobs) == 1
        assert jobs[0]["id"] == 1

    @patch("server.lulu.client.requests.request")
    @patch("server.lulu.client.requests.post")
    def test_create_print_job(self, mock_auth_post, mock_request, client, mock_auth_response):
        mock_auth_post.return_value = mock_auth_response
        mock_request.return_value = MagicMock(
            status_code=201,
            json=MagicMock(return_value={"id": 42, "status": {"name": "CREATED"}}),
        )
        address = {
            "name": "Test Customer",
            "street1": "123 Main St",
            "city": "Austin",
            "postcode": "78701",
            "state_code": "TX",
            "country_code": "US",
            "phone_number": "555-1234",
        }
        result = client.create_print_job(
            interior_url="https://example.com/interior.pdf",
            cover_url="https://example.com/cover.pdf",
            title="The Dragon's New Friend",
            shipping_address=address,
        )
        assert result["id"] == 42
        call_args = mock_request.call_args
        payload = call_args[1]["json"]
        assert payload["shipping_level"] == "GROUND"
        assert payload["line_items"][0]["title"] == "The Dragon's New Friend"
        assert (
            payload["line_items"][0]["printable_normalization"]["pod_package_id"] == DEFAULT_PACKAGE
        )

    @patch("server.lulu.client.requests.request")
    @patch("server.lulu.client.requests.post")
    def test_create_hardcover_job(self, mock_auth_post, mock_request, client, mock_auth_response):
        mock_auth_post.return_value = mock_auth_response
        mock_request.return_value = MagicMock(
            status_code=201,
            json=MagicMock(return_value={"id": 43}),
        )
        result = client.create_print_job(
            interior_url="https://example.com/interior.pdf",
            cover_url="https://example.com/cover.pdf",
            title="Premium Book",
            shipping_address={
                "name": "T",
                "street1": "1 St",
                "city": "A",
                "postcode": "00000",
                "country_code": "US",
                "phone_number": "0",
            },
            pod_package_id="0850X0850FCSTDHC060UW444GXX",
        )
        assert result["id"] == 43
        payload = mock_request.call_args[1]["json"]
        assert (
            payload["line_items"][0]["printable_normalization"]["pod_package_id"]
            == "0850X0850FCSTDHC060UW444GXX"
        )


class TestShipping:
    @patch("server.lulu.client.requests.request")
    @patch("server.lulu.client.requests.post")
    def test_get_shipping_cost(self, mock_auth_post, mock_request, client, mock_auth_response):
        mock_auth_post.return_value = mock_auth_response
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "results": [
                        {"shipping_level": "GROUND", "cost": {"total_cost_incl_tax": "4.99"}}
                    ]
                }
            ),
        )
        result = client.get_shipping_cost(country_code="US", state_code="TX")
        assert "results" in result


class TestErrorHandling:
    @patch("server.lulu.client.requests.request")
    @patch("server.lulu.client.requests.post")
    def test_api_error_raises(self, mock_auth_post, mock_request, client, mock_auth_response):
        mock_auth_post.return_value = mock_auth_response
        mock_request.return_value = MagicMock(
            status_code=422,
            json=MagicMock(return_value={"error": "invalid PDF"}),
        )
        with pytest.raises(LuluApiError) as exc_info:
            client.get_print_jobs()
        assert exc_info.value.status_code == 422

    @patch("server.lulu.client.requests.post")
    def test_health_check_failure(self, mock_post, client):
        mock_post.return_value = MagicMock(status_code=401, text="Bad creds")
        assert client.health_check() is False

    @patch("server.lulu.client.requests.request")
    @patch("server.lulu.client.requests.post")
    def test_health_check_success(self, mock_auth_post, mock_request, client, mock_auth_response):
        mock_auth_post.return_value = mock_auth_response
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"results": []}),
        )
        assert client.health_check() is True


class TestSandboxVsProduction:
    def test_sandbox_url(self):
        c = LuluClient("k", "s", sandbox=True)
        assert c.base_url == LULU_SANDBOX_BASE

    def test_production_url(self):
        c = LuluClient("k", "s", sandbox=False)
        assert c.base_url == "https://api.lulu.com"


class TestJobStatus:
    @patch("server.lulu.client.requests.request")
    @patch("server.lulu.client.requests.post")
    def test_get_job_status(self, mock_auth_post, mock_request, client, mock_auth_response):
        mock_auth_post.return_value = mock_auth_response
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "id": 99,
                    "status": {"name": "PRINTING"},
                    "created_at": "2026-04-30T00:00:00Z",
                    "updated_at": "2026-04-30T01:00:00Z",
                    "tracking_url": "",
                    "tracking_numbers": [],
                    "line_items": [{"id": 1}],
                }
            ),
        )
        status = client.get_job_status("99")
        assert status["job_id"] == 99
        assert status["status"] == "PRINTING"
        assert status["created_at"] == "2026-04-30T00:00:00Z"

    @patch("server.lulu.client.requests.request")
    @patch("server.lulu.client.requests.post")
    def test_poll_until_complete_immediate(
        self, mock_auth_post, mock_request, client, mock_auth_response
    ):
        mock_auth_post.return_value = mock_auth_response
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "id": 100,
                    "status": {"name": "SHIPPED"},
                    "created_at": "",
                    "updated_at": "",
                    "tracking_url": "https://track.example.com",
                    "tracking_numbers": ["1Z999"],
                    "line_items": [],
                }
            ),
        )
        result = client.poll_until_complete("100", poll_interval=0, max_wait=5)
        assert result["status"] == "SHIPPED"
        assert result["tracking_url"] == "https://track.example.com"

    @patch("server.lulu.client.requests.request")
    @patch("server.lulu.client.requests.post")
    def test_poll_timeout_raises(self, mock_auth_post, mock_request, client, mock_auth_response):
        from server.lulu.client import LuluError

        mock_auth_post.return_value = mock_auth_response
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "id": 101,
                    "status": {"name": "PRINTING"},
                    "created_at": "",
                    "updated_at": "",
                    "tracking_url": "",
                    "tracking_numbers": [],
                    "line_items": [],
                }
            ),
        )
        with pytest.raises(LuluError, match="did not reach terminal state"):
            client.poll_until_complete("101", poll_interval=0, max_wait=1)

    @patch("server.lulu.client.requests.request")
    @patch("server.lulu.client.requests.post")
    def test_cancel_print_job(self, mock_auth_post, mock_request, client, mock_auth_response):
        mock_auth_post.return_value = mock_auth_response
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"id": 50, "status": {"name": "CANCELED"}}),
        )
        result = client.cancel_print_job("50")
        assert result["status"]["name"] == "CANCELED"
        call_args = mock_request.call_args
        assert call_args[0][0] == "PATCH"
        assert call_args[1]["json"] == {"status": "CANCELED"}
