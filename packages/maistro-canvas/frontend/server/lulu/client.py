import base64
import contextlib
import logging
import time
from typing import Any

import requests

from .constants import (
    DEFAULT_PACKAGE,
    LULU_API_BASE,
    LULU_AUTH_URL,
    LULU_COST_CALCULATIONS_URL,
    LULU_FILE_UPLOAD_URL,
    LULU_PRINT_JOBS_URL,
    LULU_SANDBOX_BASE,
    LULU_SHIPPING_OPTIONS_URL,
    PICTURE_BOOK_FORMATS,
    SPINE_WIDTH_FORMULA_PAPERBACK,
)

logger = logging.getLogger("lulu")


class LuluError(Exception):
    pass


class LuluAuthError(LuluError):
    pass


class LuluApiError(LuluError):
    def __init__(self, message: str, status_code: int, response_body: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class LuluClient:
    def __init__(
        self,
        client_key: str,
        client_secret: str,
        contact_email: str = "",
        sandbox: bool = True,
    ):
        self.client_key = client_key
        self.client_secret = client_secret
        self.contact_email = contact_email
        self.base_url = LULU_SANDBOX_BASE if sandbox else LULU_API_BASE
        self._token: str | None = None
        self._token_expires: float = 0.0

    def _authenticate(self) -> str:
        url = self.base_url + LULU_AUTH_URL
        combined = f"{self.client_key}:{self.client_secret}"
        b64 = base64.b64encode(combined.encode("ascii")).decode("ascii")
        resp = requests.post(
            url,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {b64}"},
            timeout=30,
        )
        if resp.status_code != 200:
            raise LuluAuthError(f"Auth failed ({resp.status_code}): {resp.text[:200]}")
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires = time.time() + data.get("expires_in", 300) - 30
        logger.info(
            "Authenticated with Lulu %s", "sandbox" if "sandbox" in self.base_url else "production"
        )
        token: str = data["access_token"]
        self._token = token
        self._token_expires = time.time() + data.get("expires_in", 300) - 30
        logger.info(
            "Authenticated with Lulu %s", "sandbox" if "sandbox" in self.base_url else "production"
        )
        return token

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires:
            return self._token
        return self._authenticate()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Cache-Control": "no-cache",
        }

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        url = self.base_url + path
        resp = requests.request(method, url, headers=self._headers(), timeout=60, **kwargs)
        if resp.status_code >= 400:
            body = None
            with contextlib.suppress(Exception):
                body = resp.json()
            raise LuluApiError(
                f"{method} {path} failed ({resp.status_code})",
                status_code=resp.status_code,
                response_body=body,
            )
        if resp.status_code == 204:
            return {}
        return resp.json()

    def get_print_jobs(self) -> list[dict[str, Any]]:
        data = self._request("GET", LULU_PRINT_JOBS_URL)
        return data.get("results", [])

    def get_print_job(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"{LULU_PRINT_JOBS_URL}{job_id}/")

    def create_print_job(
        self,
        interior_url: str,
        cover_url: str,
        title: str,
        shipping_address: dict[str, str],
        quantity: int = 1,
        pod_package_id: str = DEFAULT_PACKAGE,
        shipping_level: str = "GROUND",
        external_id: str | None = None,
    ) -> dict[str, Any]:
        if external_id is None:
            external_id = f"mcp-{int(time.time())}"
        line_item = {
            "external_id": external_id + "-item1",
            "printable_normalization": {
                "cover": {"source_url": cover_url},
                "interior": {"source_url": interior_url},
                "pod_package_id": pod_package_id,
            },
            "quantity": quantity,
            "title": title,
        }
        payload = {
            "contact_email": self.contact_email,
            "external_id": external_id,
            "line_items": [line_item],
            "production_delay": 30,
            "shipping_address": shipping_address,
            "shipping_level": shipping_level,
        }
        result = self._request("POST", LULU_PRINT_JOBS_URL, json=payload)
        job_id = result.get("id", "?")
        logger.info("Created print job %s: %s", job_id, title)
        return result

    def cancel_print_job(self, job_id: str) -> dict[str, Any]:
        return self._request(
            "PATCH", f"{LULU_PRINT_JOBS_URL}{job_id}/", json={"status": "CANCELED"}
        )

    def get_shipping_options(self, **params) -> dict[str, Any]:
        return self._request("GET", LULU_SHIPPING_OPTIONS_URL, params=params)

    def get_shipping_cost(
        self,
        pod_package_id: str = DEFAULT_PACKAGE,
        quantity: int = 1,
        country_code: str = "US",
        state_code: str = "",
        postcode: str = "",
    ) -> dict[str, Any]:
        params = {
            "pod_package_id": pod_package_id,
            "quantity": quantity,
            "country_code": country_code,
        }
        if state_code:
            params["state_code"] = state_code
        if postcode:
            params["postcode"] = postcode
        return self.get_shipping_options(**params)

    def upload_file(
        self, file_bytes: bytes, filename: str, content_type: str = "application/pdf"
    ) -> dict[str, Any]:
        files = {"file": (filename, file_bytes, content_type)}
        resp = requests.post(
            self.base_url + LULU_FILE_UPLOAD_URL,
            headers=self._headers(),
            files=files,
            timeout=300,
        )
        if resp.status_code >= 400:
            raise LuluApiError(f"File upload failed ({resp.status_code})", resp.status_code)
        return resp.json()

    def health_check(self) -> bool:
        try:
            self._authenticate()
            self._request("GET", LULU_PRINT_JOBS_URL)
            return True
        except Exception as e:
            logger.error("Lulu health check failed: %s", e)
            return False

    def calculate_cost(
        self,
        line_items: list[dict[str, Any]],
        shipping_address: dict[str, str],
        shipping_option: str = "GROUND_HD",
    ) -> dict[str, Any]:
        payload = {
            "line_items": line_items,
            "shipping_address": shipping_address,
            "shipping_option": shipping_option,
        }
        return self._request("POST", LULU_COST_CALCULATIONS_URL, json=payload)

    @staticmethod
    def estimate_print_cost(
        pod_package_id: str,
        page_count: int,
        quantity: int = 1,
    ) -> dict[str, Any]:
        fmt = PICTURE_BOOK_FORMATS.get(pod_package_id)
        if not fmt:
            raise LuluError(f"Unknown package ID: {pod_package_id}")
        if page_count < fmt["min_pages"] or page_count > fmt["max_pages"]:
            raise LuluError(
                f"Page count {page_count} out of range "
                f"({fmt['min_pages']}-{fmt['max_pages']}) for {pod_package_id}"
            )
        unit_cost = fmt["base_price_usd"] + (page_count * fmt["per_page_price_usd"])
        return {
            "pod_package_id": pod_package_id,
            "page_count": page_count,
            "quantity": quantity,
            "unit_cost": round(unit_cost, 2),
            "total_print_cost": round(unit_cost * quantity, 2),
            "format": fmt["name"],
        }

    def get_job_status(self, job_id: str) -> dict[str, Any]:
        data = self.get_print_job(job_id)
        status = data.get("status", {})
        return {
            "job_id": data.get("id", job_id),
            "status": status.get("name", "UNKNOWN"),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
            "tracking_url": data.get("tracking_url", ""),
            "tracking_numbers": data.get("tracking_numbers", []),
            "line_items": data.get("line_items", []),
        }

    def poll_until_complete(
        self,
        job_id: str,
        poll_interval: int = 60,
        max_wait: int = 3600,
        terminal_states: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        if terminal_states is None:
            terminal_states = ("SHIPPED", "CANCELED", "REJECTED", "COMPLETED")
        import time as _time

        start = _time.monotonic()
        while _time.monotonic() - start < max_wait:
            status = self.get_job_status(job_id)
            state = status["status"]
            logger.info("Job %s status: %s", job_id, state)
            if state in terminal_states:
                return status
            _time.sleep(poll_interval)
        raise LuluError(f"Job {job_id} did not reach terminal state within {max_wait}s")

    @staticmethod
    def spine_width_inches(page_count: int) -> float:
        return round(SPINE_WIDTH_FORMULA_PAPERBACK(page_count), 4)
