import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("SELLER_DESK_DATA", tempfile.mkdtemp())
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "mcp_server"))

pytest.importorskip("mcp")
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def sd():
    with TestClient(app) as c:
        server._client = c
        yield c


def test_tool_list_has_no_dangerous_tools():
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert {"save_content_draft", "seo_check", "set_template_mapping", "fill_template"} <= names
    read_only = {"list_upload_templates", "get_upload_template"}      # reading the Excel templates, not uploading
    assert not {n for n in names - read_only if any(w in n for w in ("approve", "delete", "queue", "upload", "stock", "order", "submit"))}


def test_catalog_workflow(sd):
    rules = server.get_marketplace_rules("amazon")
    assert rules["limits"]["title_max"] == 75 and rules["data_sources_templates_can_use"]
    server.save_keyword_set("MCP Kanjivaram", "mcpkanji", "kanjivaram silk saree", notes="test")
    ks = server.save_keyword_set("MCP Kanjivaram", "mcpkanji", "kanjivaram silk saree,pure zari", notes="again")
    assert ks["action"] == "updated"
    made = server.create_product("MCP-001", {"fabric": "Silk", "saree_type": "mcpkanji", "color": "Maroon", "mrp": 4999,
                                              "stock_qty": 99, "images": []})
    pid = made["id"]
    p = server.get_product(pid)
    assert p["stock_qty"] is None                       # stock is never set by Claude
    assert "pattern" in p["missing_attributes"] and "images" in p["missing_attributes"]
    long_title = "Kanjivaram Silk Saree for Women " + "Zari Border " * 10
    chk = server.seo_check(pid, "amazon", long_title, ["b"] * 5, "d" * 200)
    assert len(chk["content_after_limits"]["title"]) <= 75
    d = server.save_content_draft(pid, "amazon", long_title, ["b"] * 5, "d" * 200, "kanjivaram")
    assert d["approved"] is False and d["title_length"] <= 75
    assert server.get_product(pid)["seo_drafts"]["amazon"]["approved"] in (0, False)
    with pytest.raises(server.SellerDeskError):
        server.create_product("MCP-BAD", {"nonsense": 1})
    sd.delete(f"/api/products/{pid}")
    for k in sd.get("/api/keyword-sets").json():
        if k["name"] == "MCP Kanjivaram":
            sd.delete(f"/api/keyword-sets/{k['id']}")


def test_cannot_edit_listed_saree(sd):
    firm = sd.post("/api/firms", json={"name": "MCP Firm"}).json()
    acc = sd.post("/api/accounts", json={"firm_id": firm["id"], "marketplace": "meesho", "name": "MCP Meesho"}).json()
    p = sd.post("/api/products", json={"sku": "MCP-LIVE", "name": "x"}).json()
    sd.put("/api/listings", json={"product_id": p["id"], "account_id": acc["id"], "status": "live"})
    with pytest.raises(server.SellerDeskError, match="already listed"):
        server.update_product(p["id"], {"color": "Red"})
    assert sd.delete(f"/api/products/{p['id']}").status_code == 409          # live on an account: held back
    assert sd.post("/api/products/delete", json={"product_ids": [p["id"]]}).json()["held_back"][0]["sku"] == "MCP-LIVE"
    assert sd.post("/api/products/delete", json={"product_ids": [p["id"]], "force": True}).json()["deleted"] == 1
    sd.delete(f"/api/firms/{firm['id']}")


def test_unreachable_server_message():
    import httpx
    old = server._client
    server._client = httpx.Client(base_url="http://127.0.0.1:9", timeout=2)
    try:
        with pytest.raises(server.SellerDeskError, match="not reachable"):
            server.overview()
    finally:
        server._client = old


def _jpg(path, data=b"\xff\xd8\xff\xe0fake"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_variations_folder_scan_and_import(sd, tmp_path):
    for colour in ("Maroon", "bottle_green", "03 Navy Blue"):
        for i in range(1, 5):
            _jpg(tmp_path / colour / f"{i}.jpg")
    _jpg(tmp_path / "IMG_2" / "IMG_1.jpg")
    (tmp_path / ".hidden").mkdir()
    tpl = sd.post("/api/product-templates", json={"name": "MCP Var Tpl", "fabric": "Silk", "mrp": 4999, "hsn": "5007",
                                                  "variations_dir": str(tmp_path)}).json()
    assert sd.post("/api/product-templates", json={"name": "Bad Dir", "variations_dir": "relative/path"}).status_code == 400
    scan = server.scan_template_variations(tpl["id"])
    colours = {v["colour"] for v in scan["designs"][0]["variants"]}
    assert colours == {"Maroon", "Bottle Green", "Navy Blue", None}
    assert any("no readable colour" in w for w in scan["warnings"])
    res = server.add_variations_from_template(tpl["id"], "MCPVAR", attributes={"pattern": "Woven Design", "stock_qty": 50})
    assert sorted(c["colour"] for c in res["created"]) == ["Bottle Green", "Maroon", "Navy Blue"]
    assert all(c["photos"] == 4 for c in res["created"]) and len(res["skipped"]) == 1
    maroon = next(c for c in res["created"] if c["colour"] == "Maroon")
    p = server.get_product(maroon["product_id"])
    assert p["parent_sku"] == "MCPVAR" and p["fabric"] == "Silk" and p["mrp"] == 4999 and p["pattern"] == "Woven Design"
    assert p["stock_qty"] is None and p["sku"] == "MCPVAR-MAROON" and p["images"][0].startswith("/media/")
    _jpg(tmp_path / "Rani Pink" / "1.jpg")                 # a new colour arrives later
    again = server.add_variations_from_template(tpl["id"], "MCPVAR")
    assert [c["colour"] for c in again["created"]] == ["Rani Pink"]
    assert (tmp_path / "Maroon" / "1.jpg").exists()          # originals untouched
    for c in res["created"] + again["created"]:
        sd.delete(f"/api/products/{c['product_id']}")
    sd.delete(f"/api/product-templates/{tpl['id']}")


def test_several_designs_need_a_choice(sd, tmp_path):
    for design in ("Zari", "Butta"):
        for colour in ("Red", "Blue"):
            _jpg(tmp_path / design / colour / "1.jpg")
    tpl = sd.post("/api/product-templates", json={"name": "MCP Multi Tpl", "variations_dir": str(tmp_path)}).json()
    with pytest.raises(server.SellerDeskError, match="2 designs"):
        server.add_variations_from_template(tpl["id"], "MCPMULTI")
    res = server.add_variations_from_template(tpl["id"], "MCPMULTI", design="Zari")
    assert len(res["created"]) == 2
    for c in res["created"]:
        sd.delete(f"/api/products/{c['product_id']}")
    sd.delete(f"/api/product-templates/{tpl['id']}")
