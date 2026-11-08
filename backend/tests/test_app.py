import io
import json
import os
import sys
import tempfile
from pathlib import Path

import openpyxl
import pytest
from openpyxl.worksheet.datavalidation import DataValidation

TMP = tempfile.mkdtemp()
os.environ["SELLER_DESK_DATA"] = TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import ai_writer, content, marketplaces  # noqa: E402

SAREE = {
    "sku": "KS-001", "name": "Kanchi Zari Butta", "brand": "Shanthi", "fabric": "Kanjivaram Silk",
    "saree_type": "Kanjivaram", "color": "Maroon", "pattern": "Woven Design", "work": "Zari Work",
    "border": "Contrast Zari", "pallu": "Rich Zari", "occasion": "Wedding", "saree_length_m": 5.5,
    "blouse_piece": "Unstitched Blouse Piece", "blouse_length_m": 0.8, "wash_care": "Dry Clean Only",
    "net_weight_g": 700, "hsn": "5007", "gst_rate": 5, "mrp": 4999, "selling_price": 2499, "cost_price": 1400,
    "stock_qty": 10, "images": "https://img/1.jpg\nhttps://img/2.jpg",
}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def setup_data(client):
    firm = client.post("/api/firms", json={"name": "Shanthi Silks", "gstin": "33ABCDE1234F1Z5"}).json()
    firm2 = client.post("/api/firms", json={"name": "Raj Textiles"}).json()
    amz = client.post("/api/accounts", json={"firm_id": firm["id"], "marketplace": "amazon", "name": "Amazon Main",
                                             "sku_prefix": "A1-", "price_markup_pct": 10, "price_round_to": 9}).json()
    mee = client.post("/api/accounts", json={"firm_id": firm2["id"], "marketplace": "meesho",
                                             "name": "Meesho Raj"}).json()
    fk = client.post("/api/accounts", json={"firm_id": firm2["id"], "marketplace": "flipkart",
                                            "name": "Flipkart Raj"}).json()
    p = client.post("/api/products", json=SAREE).json()
    return {"amazon": amz, "meesho": mee, "flipkart": fk, "product": p}


# ---------------------------------------------------------------- products & content

def test_product_created(setup_data):
    p = setup_data["product"]
    assert p["sku"] == "KS-001" and p["images"] == ["https://img/1.jpg", "https://img/2.jpg"]


def test_amazon_title_rules():
    p = {**SAREE, "images": []}
    g = content.generate_all(p, "amazon")
    assert len(g["title"]) <= 75, g["title"]
    assert g["title"].startswith("Shanthi Women's")
    words = g["title"].lower().split()
    assert all(words.count(w) == 1 for w in ("kanjivaram", "silk", "saree")), g["title"]
    assert "Work work" not in " ".join(g["bullets"])
    assert not any(ch in g["title"] for ch in "|;:!?")
    assert 0 < len(g["highlights"]) <= 125
    assert len(g["search_terms"].encode()) <= 249 and "shanthi" not in g["search_terms"].split()
    assert len(g["bullets"]) == 5


def test_meesho_and_flipkart_titles():
    p = {**SAREE, "images": []}
    assert "Saree" in content.generate_title(p, "meesho")
    assert len(content.generate_title(p, "flipkart")) <= 100


def test_seo_check_flags_problems():
    p = {**SAREE, "images": [], "hsn": None}
    chk = content.seo_check({"title": "x" * 90, "bullets": []}, p, "amazon", ["kanjivaram"])
    joined = " ".join(chk["issues"])
    assert "limit is 75" in joined and "hsn" in joined and chk["score"] < 60


def test_enforce_rules():
    d = ai_writer.enforce_rules({"title": "Shanthi: Silk | Silk Silk Saree! " + "word " * 20, "highlights": "a, " * 80,
                                 "bullets": ["one"] * 7, "search_terms": "shanthi silk silk saree " * 30},
                                {"brand": "Shanthi"}, "amazon")
    assert len(d["title"]) <= 75 and ":" not in d["title"] and "!" not in d["title"]
    assert d["title"].lower().split().count("silk") <= 2
    assert len(d["highlights"]) <= 125 and len(d["bullets"]) == 5
    assert "shanthi" not in d["search_terms"].split() and len(d["search_terms"].encode()) <= 249


def test_drafts_endpoint_and_manual_save(client, setup_data):
    pid = setup_data["product"]["id"]
    r = client.get(f"/api/products/{pid}/drafts").json()
    assert set(r["drafts"]) == {"amazon", "flipkart", "meesho"} and r["ai_enabled"] is False
    saved = client.put(f"/api/products/{pid}/drafts/amazon", json={
        "title": "Shanthi Women's Kanjivaram Silk Saree with Blouse Piece", "highlights": "Maroon, Zari Work",
        "bullets": ["A", "B", "C", "D", "E"], "description": "d" * 200, "search_terms": "sari wedding",
        "approved": True}).json()
    assert saved["approved"] == 1 and saved["source"] == "manual" and isinstance(saved["issues"], list)


def test_ai_draft_without_key_gives_clear_error(client, setup_data):
    r = client.post(f"/api/products/{setup_data['product']['id']}/drafts/meesho/ai")
    assert r.status_code == 400 and "API key" in r.json()["detail"]


def test_ai_draft_with_mocked_claude(client, setup_data, monkeypatch):
    class Block:
        type = "text"
        text = json.dumps({"title": "Maroon Zari Woven Kanjivaram Silk Saree with Unstitched Blouse Piece",
                           "highlights": "", "bullets": ["Rich zari pallu"] * 5, "description": "x" * 400,
                           "search_terms": "wedding saree, silk saree"})

    class Msgs:
        def create(self, **kw):
            assert "Kanjivaram" in kw["messages"][0]["content"]
            return type("M", (), {"content": [Block()]})()

    monkeypatch.setattr(ai_writer, "_client", lambda: type("C", (), {"messages": Msgs()})())
    r = client.post(f"/api/products/{setup_data['product']['id']}/drafts/meesho/ai").json()
    assert r["source"] == "ai" and r["title"].startswith("Maroon")


def test_settings_key_is_masked(client):
    client.put("/api/settings", json={"anthropic_api_key": "sk-ant-test-123456"})
    s = client.get("/api/settings").json()
    assert s["anthropic_api_key"].endswith("3456") and "sk-ant" not in s["anthropic_api_key"]
    client.put("/api/settings", json={"anthropic_api_key": ""})


def test_import_template_roundtrip(client):
    tpl = client.get("/api/products/import-template")
    wb = openpyxl.load_workbook(io.BytesIO(tpl.content))
    ws = wb["Products"]
    headers = [c.value for c in ws[1]]
    row = {h: None for h in headers}
    row.update(sku="BN-002", fabric="Banarasi Silk", color="Red", mrp="3,999", selling_price=1999, image_1="https://i/1")
    for c, h in enumerate(headers, start=1):
        ws.cell(row=3, column=c, value=row[h])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post("/api/products/import", files={"file": ("p.xlsx", buf.getvalue())}).json()
    assert r["created"] == 1
    prods = client.get("/api/products", params={"q": "BN-002"}).json()
    assert prods[0]["mrp"] == 3999 and prods[0]["images"] == ["https://i/1"]


# ---------------------------------------------------------------- template filler

def _amazon_like_template() -> bytes:
    wb = openpyxl.Workbook()
    ins = wb.active
    ins.title = "Instructions"
    ins["A1"] = "Read me"
    vv = wb.create_sheet("Valid Values")
    for i, v in enumerate(["Silk", "Kanjivaram Silk", "Cotton"], start=1):
        vv.cell(row=i, column=1, value=v)
    ws = wb.create_sheet("Template")
    ws["A1"] = "TemplateType=fptcustom"
    labels = ["Seller SKU", "Product Name", "Brand Name", "Item Highlights", "Standard Price", "Quantity",
              "Fabric Type", "Colour", "Bullet Point 1", "Main Image URL", "Search Terms"]
    names = ["item_sku", "item_name", "brand_name", "item_highlights", "standard_price", "quantity",
             "fabric_type", "color_name", "bullet_point1", "main_image_url", "generic_keywords"]
    for c, (l, n) in enumerate(zip(labels, names), start=1):
        ws.cell(row=2, column=c, value=l)
        ws.cell(row=3, column=c, value=n)
    dv = DataValidation(type="list", formula1="'Valid Values'!$A$1:$A$3")
    ws.add_data_validation(dv)
    dv.add("G4:G1000")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _meesho_like_template() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Saree"
    headers = ["Product Name", "Variation", "Meesho Price", "Wrong/Defective Returns Price", "MRP", "GST %",
               "HSN ID", "Net Weight (gms)", "Inventory", "Saree Fabric", "Blouse", "Color", "Occasion",
               "Image 1 (Front)", "Image 2", "Country of Origin", "Product ID / Style ID"]
    for c, h in enumerate(headers, start=1):
        ws.cell(row=1, column=c, value=h)
        ws.cell(row=2, column=c, value="This field is mandatory. Please enter the value as per the dropdown list")
    dv = DataValidation(type="list", formula1='"Kanjivaram Silk,Cotton,Georgette"')
    ws.add_data_validation(dv)
    dv.add("J3:J500")
    dv2 = DataValidation(type="list", formula1='"5,12,18"')
    ws.add_data_validation(dv2)
    dv2.add("F3:F500")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_amazon_template_detect_and_fill(client, setup_data):
    r = client.post("/api/templates", data={"name": "Saree flat file", "marketplace": "amazon"},
                    files={"file": ("saree.xlsx", _amazon_like_template())}).json()
    assert r["sheet_name"] == "Template" and r["header_row"] == 3 and r["data_start_row"] == 4
    m = r["mapping"]
    assert m["A"]["source"] == "listing.sku" and m["B"]["source"] == "gen.title"
    assert m["D"]["source"] == "gen.highlights" and m["E"]["source"] == "listing.price"
    assert m["G"]["source"] == "product.fabric" and m["I"]["source"] == "gen.bullet_1"
    assert m["J"]["source"] == "image.1" and m["K"]["source"] == "gen.search_terms"
    fabric_col = next(c for c in r["columns"] if c["letter"] == "G")
    assert fabric_col["allowed"] == ["Silk", "Kanjivaram Silk", "Cotton"]

    exp = client.post(f"/api/templates/{r['id']}/export", json={
        "account_id": setup_data["amazon"]["id"], "product_ids": [setup_data["product"]["id"]]}).json()
    assert exp["product_count"] == 1 and exp["warnings"] == []
    f = client.get(f"/api/exports/{exp['export_id']}/download")
    ws = openpyxl.load_workbook(io.BytesIO(f.content))["Template"]
    assert ws["A4"].value == "A1-KS-001"                 # account SKU prefix
    assert ws["E4"].value == 2749                       # 2499 * 1.10 = 2748.9 -> ends in 9
    assert ws["B4"].value.startswith("Shanthi Women's") and len(ws["B4"].value) <= 75  # approved manual draft
    assert ws["D4"].value == "Maroon, Zari Work"
    assert ws["G4"].value == "Kanjivaram Silk" and ws["J4"].value == "https://img/1.jpg"
    listing = client.get(f"/api/accounts/{setup_data['amazon']['id']}/listings").json()
    row = next(x for x in listing["rows"] if x["sku"] == "KS-001")
    assert row["listing"]["status"] == "exported"


def test_meesho_template_skips_instruction_row_and_snaps_dropdowns(client, setup_data):
    r = client.post("/api/templates", data={"name": "Meesho saree", "marketplace": "meesho"},
                    files={"file": ("m.xlsx", _meesho_like_template())}).json()
    assert r["header_row"] == 1 and r["data_start_row"] == 3
    m = r["mapping"]
    assert m["C"]["source"] == "listing.price" and m["D"]["source"] == "listing.return_price"
    assert m["F"]["source"] == "product.gst_rate" and m["G"]["source"] == "product.hsn"
    assert m["N"]["source"] == "image.1" and m["Q"]["source"] == "listing.sku"
    # map "Variation" to a constant via the API
    m["B"] = {"source": "const.custom", "value": "Free Size", "value_map": {}}
    m["K"]["value_map"] = {"Unstitched Blouse Piece": "Separate Blouse Piece"}
    client.put(f"/api/templates/{r['id']}", json={"mapping": m})
    # wrong-marketplace account is refused
    bad = client.post(f"/api/templates/{r['id']}/export", json={
        "account_id": setup_data["amazon"]["id"], "product_ids": [setup_data["product"]["id"]]})
    assert bad.status_code == 400
    exp = client.post(f"/api/templates/{r['id']}/export", json={
        "account_id": setup_data["meesho"]["id"], "product_ids": [setup_data["product"]["id"]]}).json()
    ws = openpyxl.load_workbook(io.BytesIO(client.get(f"/api/exports/{exp['export_id']}/download").content))["Saree"]
    assert ws["A3"].value.startswith("Maroon")         # AI draft for meesho from earlier test
    assert ws["B3"].value == "Free Size" and ws["C3"].value == 2499 and ws["D3"].value == 2469   # returns price = price - 30
    assert str(ws["F3"].value) == "5" and ws["J3"].value == "Kanjivaram Silk"
    assert ws["K3"].value == "Separate Blouse Piece"
    assert ws["A2"].value.startswith("This field")     # instruction row untouched


# ---------------------------------------------------------------- inventory & connections

AMAZON_REPORT = ("item-name\titem-description\tlisting-id\tseller-sku\tprice\tquantity\topen-date\timage-url\t"
                 "item-is-marketplace\tproduct-id-type\tzshop-shipping-fee\titem-note\titem-condition\t"
                 "zshop-category1\tzshop-browse-path\tzshop-storefront-feature\tasin1\tasin2\tasin3\t"
                 "will-ship-internationally\texpedited-shipping\tzshop-boldface\tproduct-id\tbid-for-featured-placement\t"
                 "add-delete\tpending-quantity\tfulfillment-channel\tmerchant-shipping-group\tstatus\n"
                 "Shanthi Maroon Kanjivaram Silk Saree\t\tL1\tA1-KS-001\t2799.00\t4\t2025-01-01\t\ty\t1\t\t\t11\t\t\t\t"
                 "B0ABC12345\t\t\t\t\t\tB0ABC12345\t\t\t0\tDEFAULT\tMigrated\tActive\n"
                 "Shanthi Green Soft Silk Saree with Blouse\t\tL2\tA1-SS-9\t1499\t0\t2025-01-01\t\ty\t1\t\t\t11\t\t\t\t"
                 "B0XYZ99999\t\t\t\t\t\tB0XYZ99999\t\t\t0\tDEFAULT\tMigrated\tInactive\n")


def test_amazon_report_parse_and_match(client, setup_data):
    aid = setup_data["amazon"]["id"]
    r = client.post(f"/api/accounts/{aid}/inventory-file",
                    files={"file": ("All+Listings+Report.txt", AMAZON_REPORT.encode())}).json()
    assert r == {"rows": 2, "matched": 1}
    rows = client.get(f"/api/accounts/{aid}/remote-listings").json()
    matched = next(x for x in rows if x["remote_sku"] == "A1-KS-001")
    assert matched["product_sku"] == "KS-001" and matched["match_method"] == "prefix"
    lst = client.get(f"/api/accounts/{aid}/listings").json()
    row = next(x for x in lst["rows"] if x["sku"] == "KS-001")
    assert row["listing"]["listing_ref"] == "B0ABC12345" and row["listing"]["status"] == "live"
    assert row["listing"]["stock_qty"] == 4
    # create a master product from the unmatched one, attributes guessed from the title
    un = next(x for x in rows if x["remote_sku"] == "A1-SS-9")
    pid = client.post(f"/api/remote-listings/{un['id']}/create-product", json={}).json()["product_id"]
    p = client.get(f"/api/products/{pid}").json()
    assert p["sku"] == "SS-9" and p["fabric"] == "Soft Silk" and p["color"] == "Green"


def test_meesho_inventory_excel(client, setup_data):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Inventory export"])
    ws.append(["Catalog ID", "Product Name", "SKU ID", "Meesho Price", "Current Stock", "Status"])
    ws.append(["123456", "Maroon Kanjivaram Saree", "KS-001", "2399", "7", "Active"])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(f"/api/accounts/{setup_data['meesho']['id']}/inventory-file",
                    files={"file": ("inv.xlsx", buf.getvalue())}).json()
    assert r == {"rows": 1, "matched": 1}


def test_meesho_has_no_api_sync(client, setup_data):
    r = client.post(f"/api/accounts/{setup_data['meesho']['id']}/sync")
    assert r.status_code == 400


def test_credentials_encrypted_and_masked(client, setup_data):
    aid = setup_data["flipkart"]["id"]
    client.put(f"/api/accounts/{aid}/credentials", json={"client_id": "app123", "client_secret": "supersecret99"})
    got = client.get(f"/api/accounts/{aid}/credentials").json()
    assert got["client_id"] == "app123" and got["client_secret"].endswith("et99") and "super" not in got["client_secret"]
    raw = Path(TMP, "seller_desk.db").read_bytes()
    assert b"supersecret99" not in raw
    # saving the masked value back must not overwrite the real secret
    client.put(f"/api/accounts/{aid}/credentials", json={"client_id": "app123", "client_secret": got["client_secret"]})
    from app.services.secrets import get_credentials
    assert get_credentials(aid)["client_secret"] == "supersecret99"


class FakeResp:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.text = data, status, json.dumps(data)

    def json(self):
        return self._d


class FakeFlipkart:
    def get(self, url, **kw):
        assert kw["params"]["grant_type"] == "client_credentials" and kw["auth"] == ("id", "sec")
        return FakeResp({"access_token": "tok", "expires_in": 3600})

    def request(self, method, url, **kw):
        assert kw["headers"]["Authorization"] == "Bearer tok"
        if url.endswith("/listings/v3/product/search"):
            if kw["json"]["internalState"] == "ACTIVE" and kw["json"]["batchNo"] == 0:
                return FakeResp({"totalListingsCount": 1, "listingData": [{
                    "listingId": "LST1", "sellerId": "s", "productId": "SARFSN123", "sku": "KS-001", "status": "ACTIVE",
                    "product_name": "Kanjivaram saree", "vertical": "saree",
                    "product_description": {"ssp": 2599, "esp": None, "mrp": 4999}}]})
            return FakeResp({"totalListingsCount": 0, "listingData": []})
        if "/listings/v3/" in url:
            return FakeResp({"available": {"KS-001": {"locations": [{"id": "L", "inventory": 3}]}}})
        raise AssertionError(url)


def test_flipkart_client_fetch():
    c = marketplaces.FlipkartClient({"client_id": "id", "client_secret": "sec"}, session=FakeFlipkart())
    rows = c.fetch_all_listings()
    assert rows[0]["remote_sku"] == "KS-001" and rows[0]["listing_ref"] == "SARFSN123"
    assert rows[0]["price"] == 2599 and rows[0]["mrp"] == 4999 and rows[0]["stock"] == 3


def test_amazon_client_requires_credentials():
    with pytest.raises(marketplaces.MarketplaceError):
        marketplaces.AmazonClient({"client_id": "x"})


def test_dashboard(client):
    d = client.get("/api/dashboard").json()
    assert d["firms"] == 2 and d["accounts"] == 3 and d["products"] >= 2


# ---------------------------------------------------------------- variants, photos, inventory

def _png() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 50), (120, 20, 40)).save(buf, "PNG")
    return buf.getvalue()


def test_media_upload_and_folder_import(client, setup_data):
    up = client.post("/api/media", files=[("files", ("maroon-1.png", _png(), "image/png")),
                                          ("files", ("notes.txt", b"x", "text/plain"))]).json()
    assert len(up) == 1 and up[0]["url"].startswith("/media/")
    assert client.get(up[0]["url"]).status_code == 200
    r = client.post("/api/products/import-designs", json={
        "account_ids": [setup_data["meesho"]["id"]],
        "designs": [{"parent_sku": "KB-77", "attributes": {"fabric": "Kanjivaram Silk", "selling_price": 2999, "mrp": 5999},
                     "variants": [{"sku": "KB-77-MAROON", "color": "Maroon", "images": [up[0]["url"]], "stock_qty": 4,
                                   "attributes": {"pattern": "Zari Woven"}},
                                  {"sku": "KB-77-GREEN", "color": "Green", "images": [], "stock_qty": 2}]}]}).json()
    assert r["created"] == 2
    prods = client.get("/api/products", params={"q": "KB-77"}).json()
    assert {p["parent_sku"] for p in prods} == {"KB-77"} and {p["color"] for p in prods} == {"Maroon", "Green"}
    maroon = next(p for p in prods if p["color"] == "Maroon")
    assert maroon["pattern"] == "Zari Woven" and maroon["fabric"] == "Kanjivaram Silk"
    # extension: both variants come back as one group, and the local photo is served by the image proxy
    grp = client.get("/api/ext/payload-group", params={"product_id": maroon["id"], "account_id": setup_data["meesho"]["id"]}).json()
    assert [g["values"]["product.color"] for g in grp] == ["Green", "Maroon"]
    assert grp[1]["values"]["listing.parent_sku"] == "KB-77"
    img = client.get("/api/ext/image", params={"url": up[0]["url"]})
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"


def test_add_colour_variants(client, setup_data):
    pid = setup_data["product"]["id"]
    r = client.post(f"/api/products/{pid}/variants", json={"colors": ["Bottle Green", "Navy"]}).json()
    assert r == {"created": 2, "parent_sku": "KS-001"}
    vs = client.get(f"/api/products/{pid}/variants").json()
    assert sorted(v["sku"] for v in vs) == ["KS-001", "KS-001-BOTTLEGREE", "KS-001-NAVY"]
    assert all(v["fabric"] == "Kanjivaram Silk" for v in vs)


def test_add_to_accounts_includes_variants(client, setup_data):
    r = client.post("/api/listings/add-to-accounts", json={
        "product_ids": [setup_data["product"]["id"]], "account_ids": [setup_data["flipkart"]["id"]]}).json()
    assert r["products"] == 3 and r["added"] == 3


def test_inventory_and_stock_from_extension(client, setup_data):
    aid = setup_data["amazon"]["id"]
    st = client.get("/api/ext/stock", params={"account_id": aid}).json()
    ks = next(r for r in st if r["sku"] == "KS-001")
    assert ks["account_sku"] == "A1-KS-001"
    seen = client.post("/api/ext/stock-seen", json={"account_id": aid, "rows": [
        {"key": "A1-KS-001", "stock": 2}, {"key": "NOT-OURS", "stock": 9}]}).json()
    assert seen == {"updated": 1, "unknown": ["NOT-OURS"]}
    client.post("/api/inventory/stock", json=[{"product_id": setup_data["product"]["id"], "delta": -3}])
    inv = client.get("/api/inventory").json()
    p = next(x for x in inv["products"] if x["sku"] == "KS-001")
    acc_stock = p["accounts"].get(str(aid)) or p["accounts"].get(aid)
    assert p["stock_qty"] == 7 and acc_stock["stock"] == 2
    assert inv["out_of_sync"] >= 1


# ---------------------------------------------------------------- orders

def test_status_rules():
    from app.services.orders import normalise_status as n
    assert n("RTO Delivered") == "courier_return" and n("Return to origin") == "courier_return"
    assert n("Customer Return completed") == "customer_return" and n("Cancelled by supplier") == "cancelled"
    assert n("Out for delivery") == "shipped" and n("Delivered") == "delivered" and n("Ready to ship") == "pending"


def test_orders_capture_import_and_master_excel(client, setup_data):
    mid = setup_data["meesho"]["id"]
    skus = client.get("/api/ext/known-skus", params={"account_id": mid}).json()
    assert "KS-001" in skus
    r = client.post("/api/ext/orders-seen", json={"account_id": mid, "page_status": "Shipped", "rows": [
        {"order_id": "214567890", "sub_order_id": "214567890_1", "sku": "KS-001", "order_date": "04 Nov 2026"},
        {"order_id": "214567891", "sub_order_id": "214567891_1", "status_text": "RTO Delivered"}]}).json()
    assert r["created"] == 2 and r["master_saved"].endswith(".xlsx")
    # an older page saying "Shipped" must not undo the RTO
    client.post("/api/ext/orders-seen", json={"account_id": mid, "page_status": "Shipped",
                                               "rows": [{"order_id": "214567891", "sub_order_id": "214567891_1"}]})
    # Meesho payments-style file adds cancellation charges + a cancelled order
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Payments to date"])
    ws.append(["Sub Order No", "Order Date", "SKU", "Live Order Status", "Cancellation Charges", "Return Shipping Charge"])
    ws.append(["214567892_1", "02-11-2026", "KS-001", "Cancelled", "-35.4", ""])
    ws.append(["214567891_1", "03-11-2026", "", "RTO", "", "-62"])
    buf = io.BytesIO()
    wb.save(buf)
    imp = client.post(f"/api/accounts/{mid}/orders-file", files={"file": ("payments.xlsx", buf.getvalue())}).json()
    assert imp["rows"] == 2 and imp["created"] == 1 and imp["updated"] == 1
    data = client.get("/api/orders", params={"account_id": mid}).json()
    by = {o["sub_order_id"]: o for o in data["orders"]}
    assert by["214567890_1"]["status"] == "shipped" and by["214567890_1"]["order_date"] == "2026-11-04"
    assert by["214567890_1"]["mrp"] == 4999                  # MRP from the product via SKU
    assert by["214567891_1"]["status"] == "courier_return" and by["214567891_1"]["return_charges"] == 62
    assert by["214567892_1"]["status"] == "cancelled" and by["214567892_1"]["cancel_charges"] == 35.4
    assert by["214567892_1"]["order_id"] == "214567892" and by["214567892_1"]["firm_name"] == "Raj Textiles"
    x = openpyxl.load_workbook(io.BytesIO(client.get("/api/orders/master.xlsx").content))
    ws = x["Orders"]
    assert [c.value for c in ws[1]][:6] == ["Order date", "Firm", "Platform", "Account", "Order ID", "Sub-order / item ID"]
    statuses = {ws.cell(row=i, column=11).value for i in range(2, ws.max_row + 1)}
    assert {"Shipped", "Courier return (RTO)", "Cancelled"} <= statuses
    summary = x["Summary"]
    assert summary["A2"].value == "Raj Textiles" and summary["B2"].value == "Meesho"
