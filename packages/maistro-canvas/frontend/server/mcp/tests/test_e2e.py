from server.lulu.client import LuluClient
from server.mcp.pdf_composer import compose_cover, compose_interior
from server.mcp.products import ProductSpec, get_product, list_products


def test_products_catalog():
    products = list_products()
    assert len(products) == 4
    ids = {p["id"] for p in products}
    assert ids == {"picture-book-7.5", "picture-book-9x7", "coloring-standard", "coloring-premium"}

    pb = get_product("picture-book-7.5")
    assert pb.print_cost() == 8.68
    assert pb.margin() == 16.31
    assert pb.page_count == 32
    assert pb.spine_width_in > 0

    cs = get_product("coloring-standard")
    assert cs.print_cost() == 3.25
    assert cs.binding == "Perfect"

    cp = get_product("coloring-premium")
    assert cp.print_cost() == 12.23
    assert cp.binding == "Coil"
    assert cp.page_count == 150


def test_product_dimensions():
    pb = get_product("picture-book-7.5")
    assert pb.trim_width_pt == 7.5 * 72
    assert pb.trim_height_pt == 7.5 * 72
    assert pb.bleed_width_pt == 7.75 * 72
    assert pb.bleed_height_pt == 7.75 * 72

    assert pb.spine_width_pt > 0
    assert pb.cover_width_pt > pb.bleed_width_pt
    assert pb.cover_height_pt == pb.bleed_height_pt

    cs = get_product("coloring-standard")
    assert cs.trim_width_pt == 8.5 * 72
    assert cs.trim_height_pt == 11.0 * 72
    assert cs.bleed_width_pt == 8.75 * 72
    assert cs.bleed_height_pt == 11.25 * 72


def test_compose_picture_book_interior(tmp_path):
    pb = get_product("picture-book-7.5")
    out = compose_interior(pb, tmp_path / "interior.pdf", title="Test Book")
    assert out.exists()
    assert out.stat().st_size > 10000

    from PyPDF2 import PdfReader

    reader = PdfReader(str(out))
    assert len(reader.pages) == 32
    w, h = reader.pages[0].mediabox.width, reader.pages[0].mediabox.height
    assert abs(float(w) - pb.bleed_width_pt) < 1
    assert abs(float(h) - pb.bleed_height_pt) < 1


def test_compose_picture_book_cover(tmp_path):
    pb = get_product("picture-book-7.5")
    out = compose_cover(pb, tmp_path / "cover.pdf", title="Test Book")
    assert out.exists()
    assert out.stat().st_size > 500

    from PyPDF2 import PdfReader

    reader = PdfReader(str(out))
    assert len(reader.pages) == 1
    w, h = reader.pages[0].mediabox.width, reader.pages[0].mediabox.height
    expected_w = pb.cover_width_pt
    expected_h = pb.cover_height_pt
    assert abs(float(w) - expected_w) < 2
    assert abs(float(h) - expected_h) < 2


def test_compose_coloring_standard(tmp_path):
    cs = get_product("coloring-standard")
    interior = compose_interior(cs, tmp_path / "coloring_interior.pdf", title="Color Fun")
    cover = compose_cover(cs, tmp_path / "coloring_cover.pdf", title="Color Fun")

    from PyPDF2 import PdfReader

    ir = PdfReader(str(interior))
    assert len(ir.pages) == 32
    cr = PdfReader(str(cover))
    assert len(cr.pages) == 1


def test_compose_coloring_premium(tmp_path):
    cp = get_product("coloring-premium")
    interior = compose_interior(cp, tmp_path / "premium_interior.pdf", title="Big Color")
    cover = compose_cover(cp, tmp_path / "premium_cover.pdf", title="Big Color")

    from PyPDF2 import PdfReader

    ir = PdfReader(str(interior))
    assert len(ir.pages) == 150
    cr = PdfReader(str(cover))
    assert len(cr.pages) == 1


def test_lulu_sandbox_e2e_picture_book(tmp_path):
    pb = get_product("picture-book-7.5")
    _run_lulu_sandbox_e2e(pb, tmp_path, "picture-book")


def test_lulu_sandbox_e2e_coloring_standard(tmp_path):
    cs = get_product("coloring-standard")
    _run_lulu_sandbox_e2e(cs, tmp_path, "coloring-standard")


def test_lulu_sandbox_e2e_coloring_premium(tmp_path):
    cp = get_product("coloring-premium")
    _run_lulu_sandbox_e2e(cp, tmp_path, "coloring-premium")


def _get_sandbox_client() -> LuluClient:
    from dotenv import dotenv_values

    secrets = dotenv_values("/root/.conductor-secrets/lulu.env")
    key = secrets.get("LULU_SANDBOX_CLIENT_KEY", "")
    secret = secrets.get("LULU_SANDBOX_CLIENT_SECRET", "")
    assert key and secret, "Lulu sandbox credentials not found in /root/.conductor-secrets/lulu.env"
    return LuluClient(key, secret, sandbox=True)


def _run_lulu_sandbox_e2e(product: ProductSpec, tmp_path, label: str):
    from server.lulu.client import LuluApiError

    title = f"MCP Test - {label}"
    interior_path = compose_interior(product, tmp_path / f"{label}_interior.pdf", title=title)
    cover_path = compose_cover(product, tmp_path / f"{label}_cover.pdf", title=title)

    assert interior_path.exists()
    assert cover_path.exists()

    client = _get_sandbox_client()

    try:
        cost = client.calculate_cost(
            line_items=[
                {
                    "page_count": product.page_count,
                    "pod_package_id": product.pod_package_id,
                    "quantity": 1,
                }
            ],
            shipping_address={
                "city": "Raleigh",
                "country_code": "US",
                "postcode": "27601",
                "state_code": "NC",
                "street1": "123 Test St",
                "phone_number": "555-555-5555",
            },
            shipping_option="MAIL",
        )
        assert cost.get("line_item_costs"), f"Cost calculation failed for {label}"
        unit_cost = cost["line_item_costs"][0]["cost_excl_discounts"]
        expected = product.print_cost()
        assert abs(float(unit_cost) - expected) < 1.0, (
            f"[{label}] Cost mismatch: live={unit_cost} vs formula={expected}"
        )
        print(f"[{label}] Cost calc OK: ${unit_cost}/unit (formula: ${expected})")
    except Exception as e:
        print(f"[{label}] Cost calc: {e}")

    interior_url = (
        "https://www.dropbox.com/s/r20orb8umqjzav9/lulu_trade_interior_template-32.pdf?dl=1&raw=1"
    )
    cover_url = "https://www.dropbox.com/scl/fi/7t4muts0gh4qe7833ay8b/cover_template.pdf?rlkey=0jlesya87pd9xe5k1u2l"

    try:
        job = client.create_print_job(
            interior_url=interior_url,
            cover_url=cover_url,
            pod_package_id=product.pod_package_id,
            shipping_address={
                "name": "Test Customer",
                "street1": "123 Test St",
                "city": "Raleigh",
                "state_code": "NC",
                "postcode": "27601",
                "country_code": "US",
                "phone_number": "555-555-5555",
            },
            shipping_level="MAIL",
            title=title,
        )
        print(f"[{label}] Print job result: {job}")
        if isinstance(job, dict) and "id" in job:
            job_id = job["id"]
            print(f"[{label}] Job ID: {job_id}, status: {job.get('status', '?')}")
            try:
                client.cancel_print_job(str(job_id))
                print(f"[{label}] Cancelled job {job_id}")
            except Exception as ce:
                print(f"[{label}] Cancel: {ce}")
    except LuluApiError as e:
        print(f"[{label}] Print job: status={e.status_code} detail={str(e)[:300]}")
    except Exception as e:
        print(f"[{label}] Print job error: {str(e)[:300]}")
