import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("SELLER_DESK_DATA", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import get_conn  # noqa: E402
from app.main import app  # noqa: E402
from app.services import orders, stock, uploads  # noqa: E402

PANEL = "https://supplier.meesho.com/panel/v3/new/growth/3ylgo/catalogs/add"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def world(client):
    firm = client.post("/api/firms", json={"name": "Stock Test Firm"}).json()
    acc = client.post("/api/accounts", json={"firm_id": firm["id"], "marketplace": "meesho", "name": "Meesho Stock"}).json()
    full = dict(fabric="Silk", color="Red", mrp=999, selling_price=499, hsn="5007", images=["https://x.test/a.jpg"])
    ready = client.post("/api/products", json={"sku": "ST-READY", "name": "Ready", "stock_qty": 5, **full}).json()
    bare = client.post("/api/products", json={"sku": "ST-BARE", "name": "Bare", "stock_qty": 3}).json()
    yield {"firm": firm, "acc": acc, "ready": ready, "bare": bare}
    for p in (ready, bare):
        client.delete(f"/api/products/{p['id']}")
    client.delete(f"/api/firms/{firm['id']}")
    stock.configure(from_orders=False)


def level(client, pid):
    return next(p for p in client.get("/api/inventory").json()["products"] if p["id"] == pid)["stock_qty"]


def test_manual_changes_are_logged(client, world):
    pid = world["ready"]["id"]
    client.post("/api/inventory/stock", json=[{"product_id": pid, "delta": -1}])
    client.post("/api/inventory/stock", json=[{"product_id": pid, "stock_qty": 7}])
    moves = client.get(f"/api/inventory/moves?product_id={pid}").json()["moves"]
    assert [(m["reason"], m["delta"], m["qty_after"]) for m in moves[:2]] == [("set", 3, 7), ("manual", -1, 4)]
    assert level(client, pid) == 7


def test_orders_take_and_return_stock_only_after_switch_on(client, world):
    pid, acc = world["ready"]["id"], world["acc"]["id"]
    row = {"order_id": "OLD1", "sku": "ST-READY", "qty": 2, "status": "pending", "status_text": "Pending"}
    orders.save_orders(acc, [row], "test")                       # before tracking: never counted
    with get_conn() as c:                                        # (same-second timestamps: make it clearly older)
        c.execute("UPDATE orders SET first_seen_at='2000-01-01 00:00:00' WHERE order_id='OLD1'")
    assert level(client, pid) == 7
    stock.configure(from_orders=True)
    orders.save_orders(acc, [row], "test")                       # same old order seen again: still not counted
    assert level(client, pid) == 7
    new = {"order_id": "NEW1", "sku": "ST-READY", "qty": 2, "status": "pending", "status_text": "Pending"}
    orders.save_orders(acc, [new], "test")
    assert level(client, pid) == 5
    orders.save_orders(acc, [new], "test")                       # re-reading the page must not deduct twice
    assert level(client, pid) == 5
    orders.save_orders(acc, [{**new, "status": "shipped"}], "test")
    assert level(client, pid) == 5
    orders.save_orders(acc, [{**new, "status": "cancelled", "status_text": "Cancelled"}], "test")
    assert level(client, pid) == 7                               # cancelled: put back
    reasons = [m["reason"] for m in client.get(f"/api/inventory/moves?product_id={pid}").json()["moves"][:2]]
    assert reasons == ["order_restock", "order_sold"]


def test_oversold_and_deleted_order(client, world):
    pid, acc = world["ready"]["id"], world["acc"]["id"]
    big = {"order_id": "BIG1", "sku": "ST-READY", "qty": 9, "status": "pending", "status_text": "Pending"}
    orders.save_orders(acc, [big], "test")
    inv = client.get("/api/inventory").json()
    p = next(x for x in inv["products"] if x["id"] == pid)
    assert p["stock_qty"] == -2 and p["level"] == "oversold" and inv["counts"]["oversold"] >= 1
    row = next(o for o in client.get("/api/orders?q=BIG1").json()["orders"])
    client.delete(f"/api/orders/{row['id']}")
    assert level(client, pid) == 7


def test_unknown_stock_is_not_invented(client, world):
    acc = world["acc"]["id"]
    p = client.post("/api/products", json={"sku": "ST-NOSTOCK", "name": "No stock figure"}).json()
    orders.save_orders(acc, [{"order_id": "NS1", "sku": "ST-NOSTOCK", "qty": 1, "status": "pending"}], "test")
    assert level(client, p["id"]) is None
    client.delete(f"/api/products/{p['id']}")


def test_upload_queue_rules(client, world):
    acc, ready, bare = world["acc"]["id"], world["ready"]["id"], world["bare"]["id"]
    r = client.post("/api/uploads/queue", json={"product_ids": [ready], "account_ids": [acc]}).json()
    assert r["queued"] == 0 and "No add-catalog page" in r["skipped"][0]["reason"]
    assert client.put(f"/api/ext/accounts/{acc}/add-catalog-url", json={"url": "https://evil.example/add"}).status_code == 400
    assert client.put(f"/api/ext/accounts/{acc}/add-catalog-url", json={"url": PANEL}).status_code == 200
    r = client.post("/api/uploads/queue", json={"product_ids": [bare, ready], "account_ids": [acc]}).json()
    assert r["queued"] == 1
    assert "missing" in r["skipped"][0]["reason"] and "photos" in r["skipped"][0]["reason"]
    again = client.post("/api/uploads/queue", json={"product_ids": [ready], "account_ids": [acc]}).json()
    assert again["queued"] == 0 and again["skipped"][0]["reason"] == "Already in the queue"


def test_upload_claim_report_and_review_cap(client, world):
    acc, ready, firm = world["acc"]["id"], world["ready"]["id"], world["firm"]["id"]
    got = client.post("/api/ext/upload/claim", json={"firm_id": firm}).json()
    assert len(got["jobs"]) == 1 and got["jobs"][0]["url"] == PANEL and got["submit"] is False
    assert client.post("/api/ext/upload/claim", json={"firm_id": firm}).json()["jobs"] == []   # not given out twice
    job = got["jobs"][0]["job_id"]
    assert client.post("/api/ext/upload/update", json={"job_id": job, "status": "filled"}).status_code == 200
    assert client.post("/api/ext/upload/update", json={"job_id": job, "status": "queued"}).status_code == 400
    client.post(f"/api/uploads/{job}/status", json={"status": "submitted"})
    row = next(r for r in client.get(f"/api/accounts/{acc}/listings").json()["rows"] if r["product_id"] == ready)
    assert row["listing"]["status"] == "exported"
    assert client.post(f"/api/uploads/{job}/status", json={"status": "queued"}).status_code == 409
    assert uploads.MAX_OPEN >= 1


def test_meesho_catalog_split_at_nine(client, world):
    acc = world["acc"]["id"]
    client.put(f"/api/ext/accounts/{acc}/add-catalog-url", json={"url": PANEL})
    ids = []
    full = dict(fabric="Silk", mrp=999, selling_price=499, hsn="5007", images=["https://x.test/a.jpg"], parent_sku="SPLIT")
    for i in range(12):
        ids.append(client.post("/api/products", json={"sku": f"SPLIT-{i:02d}", "color": f"C{i}", **full}).json()["id"])
    r = client.post("/api/uploads/queue", json={"product_ids": [ids[0]], "account_ids": [acc]}).json()
    assert r["queued"] == 2 and r["splits"][0]["catalogs"] == [9, 3] and r["splits"][0]["limit"] == 9
    first = client.get(f"/api/ext/payload-group?product_id={ids[0]}&account_id={acc}").json()
    last = client.get(f"/api/ext/payload-group?product_id={ids[11]}&account_id={acc}").json()
    assert len(first) == 9 and len(last) == 3
    assert first[0]["values"]["listing.parent_sku"] == "SPLIT" and last[0]["values"]["listing.parent_sku"] == "SPLIT-2"
    # a new colour later joins the catalog with room (the 3-colour one) and never moves the others
    new = client.post("/api/products", json={"sku": "SPLIT-99", "color": "Late", **full}).json()["id"]
    again = client.get(f"/api/ext/payload-group?product_id={new}&account_id={acc}").json()
    assert len(again) == 4 and again[0]["values"]["listing.parent_sku"] == "SPLIT-2"
    assert len(client.get(f"/api/ext/payload-group?product_id={ids[0]}&account_id={acc}").json()) == 9
    jobs = [j for j in client.get("/api/uploads").json()["jobs"] if j["parent_sku"] == "SPLIT"]
    assert sorted(j["catalog_parent_sku"] for j in jobs) == ["SPLIT", "SPLIT-2"]
    # Amazon has no such limit: all colours stay in one group
    for pid in ids + [new]:
        client.post("/api/products/delete", json={"product_ids": [pid], "force": True})


def test_meesho_description_uses_1400_and_is_capped(client, world):
    from app.services import ai_writer, content
    assert content.MARKETPLACE_RULES["meesho"]["description_max"] == 1400
    telugu = "ఈ beautiful saree కి golden Kolam motifs. " * 60
    out = ai_writer.enforce_rules({"title": "t", "bullets": [], "description": telugu, "search_terms": ""}, {}, "meesho")
    assert 1000 < len(out["description"]) <= 1400
    short = content.seo_check({"title": "x" * 60, "bullets": ["b"] * 5, "description": "d" * 300}, {}, "meesho")
    assert any("Meesho allows 1400" in i for i in short["issues"])
    assert not any("Description" in i for i in content.seo_check({"title": "x" * 60, "bullets": ["b"] * 5, "description": "d" * 1000}, {}, "meesho")["issues"])
    langs = client.get("/api/settings").json()["meesho_languages"]
    assert all(l in langs for l in ("Tamil", "Hindi", "Telugu", "Malayalam", "Kannada"))
    assert "Kannada" in ai_writer.MARKETPLACE_BRIEF["meesho"] or "every language" in ai_writer.MARKETPLACE_BRIEF["meesho"].lower()


def test_paused_queue_hands_out_nothing(client, world):
    firm = world["firm"]["id"]
    client.put("/api/uploads/settings", json={"paused": True})
    assert client.get("/api/uploads").json()["paused"] is True
    assert client.post("/api/ext/upload/claim", json={"firm_id": firm}).json()["jobs"] == []
    client.put("/api/uploads/settings", json={"paused": False})


def test_meesho_style_template_layout(tmp_path):
    """Headers that carry their help text, a links row, formula rows and a Validation Sheet of dropdown values."""
    import openpyxl
    from openpyxl.worksheet.datavalidation import DataValidation
    from app.services import template_filler as tf
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sarees-Fill this"
    heads = ["Product Name", "Variation", "Meesho Price", "Color"]
    ws.append(["Sarees Template"])
    ws.append(["* Compulsory Field"] * 4)
    ws.append([f"\n\n{h}\n\nPlease enter the value for {h}. It must follow the marketplace rules." for h in heads])
    ws.append(["Tutorial Link", "'Validation Sheet'!B2", None, "'Validation Sheet'!D2"])
    for r in range(5, 9):
        ws.cell(row=r, column=3, value=f'=IF(A{r}>28,A{r}-28,"Not Required")')
    vs = wb.create_sheet("Validation Sheet")
    vs.append(heads)
    vs.append(["", "", "", ""])
    vs.append(["", "Free Size", "", "Maroon"])
    dv = DataValidation(type="list", formula1="'Validation Sheet'!$B$3:$B$3")
    ws.add_data_validation(dv)
    dv.add("B5:B8")
    path = tmp_path / "t.xlsx"
    wb.save(path)
    info = tf.analyse(path)
    assert info["sheet_name"] == "Sarees-Fill this" and info["header_row"] == 3 and info["data_start_row"] == 5
    cols = {c["header"]: c for c in info["columns"]}
    assert set(cols) == set(heads) and cols["Variation"]["allowed"] == ["Free Size"]
    assert cols["Product Name"]["label"] is None          # "* Compulsory Field" is a flag, not a caption


def test_image_links_parse_save_and_fill(client, world, tmp_path):
    import openpyxl
    from app.services import template_filler as tf
    a, b = world["ready"]["id"], world["bare"]["id"]
    base = "https://images.example.com/p/"
    prod = [{"id": a, "sku": "ST-READY"}, {"id": b, "sku": "ST-BARE"}]
    from app.services import image_links as il
    # blocks without SKUs go to the sarees in order
    r = il.parse(f"{base}1.jpg\n{base}2.jpg\n\n{base}3.jpg\n", prod)
    assert r["links"] == {a: [base + "1.jpg", base + "2.jpg"], b: [base + "3.jpg"]}
    # SKU lines, and 'SKU<tab>link' lines, win over order
    r = il.parse(f"ST-BARE\n{base}9.jpg\nST-READY\t{base}7.jpg\n", prod)
    assert r["links"] == {b: [base + "9.jpg"], a: [base + "7.jpg"]}
    assert client.put(f"/api/products/{a}/image-links/meesho", json={"links": ["https://drive.google.com/file/d/x"]}).status_code == 400
    assert client.put(f"/api/products/{a}/image-links/meesho", json={"links": ["http://insecure.example/a.jpg"]}).status_code == 400
    res = client.post("/api/image-links/paste", json={"marketplace": "meesho", "product_ids": [a, b], "text": f"{base}1.jpg\n{base}2.jpg\n\n{base}3.jpg", "save": True}).json()
    assert res["saved"] and client.get(f"/api/image-links?marketplace=meesho&product_ids={a},{b}").json()["links"][str(a)] == [base + "1.jpg", base + "2.jpg"]
    # the Excel fill uses the links for Image columns, and warns when Image 1 has none
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Fill"
    ws.append(["Image 1 (Front)", "Image 2"])
    ws.append([None, None])
    wb.save(tmp_path / "t.xlsx")
    profile = {"stored_path": str(tmp_path / "t.xlsx"), "name": "T", "sheet_name": "Fill", "data_start_row": 2,
               "columns": [{"letter": "A", "header": "Image 1 (Front)"}, {"letter": "B", "header": "Image 2"}],
               "mapping": {"A": {"source": "image.1"}, "B": {"source": "image.2"}}}
    acc = {"marketplace": "meesho", "name": "Acc", "sku_prefix": ""}
    prods = [{"id": a, "sku": "ST-READY", "images": ["/media/local.png"]}, {"id": b, "sku": "ST-BARE", "images": ["/media/local2.png"]}]
    client.put(f"/api/products/{b}/image-links/meesho", json={"links": []})
    out, warnings = tf.fill(profile, prods, acc, {}, tmp_path)
    sheet = openpyxl.load_workbook(out)["Fill"]
    assert sheet["A2"].value == base + "1.jpg" and sheet["B2"].value == base + "2.jpg"      # never the local /media path
    assert sheet["A3"].value is None and "no image link" in warnings[0]["issue"] and warnings[0]["sku"] == "ST-BARE"
