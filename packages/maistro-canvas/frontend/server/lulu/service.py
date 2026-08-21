import os
import sys

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(__file__))

from lulu.client import LuluApiError, LuluClient, LuluError
from lulu.constants import (
    DEFAULT_PACKAGE,
    PICTURE_BOOK_FORMATS,
    SHIPPING_LEVELS,
    SPINE_WIDTH_FORMULA_PAPERBACK,
)
from lulu.preflight import preflight_cover, preflight_interior

SANDBOX = os.environ.get("LULU_SANDBOX", "true").lower() != "false"
CLIENT_KEY = os.environ.get("LULU_CLIENT_KEY", "")
CLIENT_SECRET = os.environ.get("LULU_CLIENT_SECRET", "")
CONTACT_EMAIL = os.environ.get("LULU_CONTACT_EMAIL", "")

client: LuluClient | None = None
if CLIENT_KEY and CLIENT_SECRET:
    client = LuluClient(CLIENT_KEY, CLIENT_SECRET, contact_email=CONTACT_EMAIL, sandbox=SANDBOX)

app = FastAPI(title="Lulu Print Service", version="0.9.0")
# CORS allow-list — set LULU_CORS_ORIGINS (comma-separated) in deployment.
# Defaults to local-dev origins rather than a wildcard.
_CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "LULU_CORS_ORIGINS", "http://localhost:5173,http://localhost:5174"
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware, allow_origins=_CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"]
)


class Address(BaseModel):
    name: str
    street1: str
    street2: str = ""
    city: str
    postcode: str
    state_code: str = ""
    country_code: str = "US"
    phone_number: str = ""


class PrintOrder(BaseModel):
    interior_url: str
    cover_url: str
    title: str
    shipping_address: Address
    quantity: int = 1
    pod_package_id: str = DEFAULT_PACKAGE
    shipping_level: str = "GROUND_HD"


class CostEstimateRequest(BaseModel):
    pod_package_id: str = DEFAULT_PACKAGE
    page_count: int = 32
    quantity: int = 1


class LiveCostRequest(BaseModel):
    line_items: list[dict]
    shipping_address: Address
    shipping_option: str = "GROUND_HD"


def _require_client() -> LuluClient:
    if not client:
        raise HTTPException(
            503, "Lulu API not configured (set LULU_CLIENT_KEY + LULU_CLIENT_SECRET)"
        )
    return client


@app.get("/health")
def health():
    if not client:
        return {"configured": False, "healthy": False}
    return {"configured": True, "healthy": client.health_check(), "sandbox": SANDBOX}


@app.get("/packages")
def packages():
    return PICTURE_BOOK_FORMATS


@app.get("/shipping-options")
def shipping_options():
    return SHIPPING_LEVELS


@app.post("/estimate")
def estimate_cost(req: CostEstimateRequest):
    try:
        return LuluClient.estimate_print_cost(
            pod_package_id=req.pod_package_id,
            page_count=req.page_count,
            quantity=req.quantity,
        )
    except LuluError as e:
        raise HTTPException(400, detail=str(e)) from None


@app.post("/calculate-cost")
def calculate_cost(req: LiveCostRequest):
    c = _require_client()
    try:
        return c.calculate_cost(
            line_items=req.line_items,
            shipping_address=req.shipping_address.model_dump(),
            shipping_option=req.shipping_option,
        )
    except LuluApiError as e:
        raise HTTPException(e.status_code, detail=str(e)) from None


@app.get("/spine-width")
def spine_width(page_count: int = 32):
    return {
        "page_count": page_count,
        "spine_width_inches": round(SPINE_WIDTH_FORMULA_PAPERBACK(page_count), 4),
    }


@app.get("/shipping-cost")
def shipping_cost(
    pod_package_id: str = DEFAULT_PACKAGE,
    quantity: int = 1,
    country_code: str = "US",
    state_code: str = "",
    postcode: str = "",
):
    c = _require_client()
    try:
        return c.get_shipping_cost(
            pod_package_id=pod_package_id,
            quantity=quantity,
            country_code=country_code,
            state_code=state_code,
            postcode=postcode,
        )
    except LuluApiError as e:
        raise HTTPException(e.status_code, detail=str(e)) from None


@app.post("/order")
def create_order(order: PrintOrder):
    c = _require_client()
    try:
        return c.create_print_job(
            interior_url=order.interior_url,
            cover_url=order.cover_url,
            title=order.title,
            shipping_address=order.shipping_address.model_dump(),
            quantity=order.quantity,
            pod_package_id=order.pod_package_id,
            shipping_level=order.shipping_level,
        )
    except LuluApiError as e:
        raise HTTPException(e.status_code, detail=str(e)) from None


@app.get("/orders")
def list_orders():
    c = _require_client()
    try:
        return c.get_print_jobs()
    except LuluApiError as e:
        raise HTTPException(e.status_code, detail=str(e)) from None


@app.get("/orders/{job_id}")
def get_order(job_id: str):
    c = _require_client()
    try:
        return c.get_print_job(job_id)
    except LuluApiError as e:
        raise HTTPException(e.status_code, detail=str(e)) from None


@app.post("/orders/{job_id}/cancel")
def cancel_order(job_id: str):
    c = _require_client()
    try:
        return c.cancel_print_job(job_id)
    except LuluApiError as e:
        raise HTTPException(e.status_code, detail=str(e)) from None


@app.get("/orders/{job_id}/status")
def job_status(job_id: str):
    c = _require_client()
    try:
        return c.get_job_status(job_id)
    except LuluApiError as e:
        raise HTTPException(e.status_code, detail=str(e)) from None


class PreflightRequest(BaseModel):
    pdf_path: str
    pod_package_id: str = DEFAULT_PACKAGE
    page_count: int | None = None


class CoverPreflightRequest(BaseModel):
    pdf_path: str
    pod_package_id: str = DEFAULT_PACKAGE
    interior_page_count: int = 32


@app.post("/preflight/interior")
def preflight_interior_endpoint(req: PreflightRequest):
    result = preflight_interior(
        pdf_path=req.pdf_path,
        pod_package_id=req.pod_package_id,
        expected_page_count=req.page_count,
    )
    return {
        "passed": result.passed,
        "page_count": result.page_count,
        "page_width_pt": result.page_width_pt,
        "page_height_pt": result.page_height_pt,
        "errors": [{"code": e.code, "message": e.message} for e in result.errors],
        "warnings": [{"code": w.code, "message": w.message} for w in result.warnings],
    }


@app.post("/preflight/cover")
def preflight_cover_endpoint(req: CoverPreflightRequest):
    result = preflight_cover(
        pdf_path=req.pdf_path,
        pod_package_id=req.pod_package_id,
        page_count=req.interior_page_count,
    )
    return {
        "passed": result.passed,
        "page_count": result.page_count,
        "page_width_pt": result.page_width_pt,
        "page_height_pt": result.page_height_pt,
        "errors": [{"code": e.code, "message": e.message} for e in result.errors],
        "warnings": [{"code": w.code, "message": w.message} for w in result.warnings],
    }


if __name__ == "__main__":
    import os

    import uvicorn

    # Loopback by default; container deploys set LULU_BIND_HOST=0.0.0.0 so
    # an accidental local `python service.py` doesn't expose Lulu on the LAN.
    bind_host = os.getenv("LULU_BIND_HOST", "127.0.0.1")
    uvicorn.run(app, host=bind_host, port=8260)
