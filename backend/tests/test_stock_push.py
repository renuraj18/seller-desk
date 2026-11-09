import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

os.environ.setdefault("SELLER_DESK_DATA", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import get_conn  # noqa: E402
from app.main import app  # noqa: E402
from app.services import order_sync, stock, stock_push  # noqa: E402
from app.services.secrets import set_setting  # noqa: E402

INV = "https://supplier.meesho.com/panel/v3/new/growth/3ylgo/inventory"
ORD = "https://supplier.meesho.com/panel/v3/new/growth/3ylgo/orders/pending"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def w(client):
    set_setting("agent_summary_after_sync", "0")
    firm = client.post("/api/firms", json={"name": "Push Firm"}).json()
    acc = client.post("/api/accounts", json={"firm_id": firm["id"], "marketplace": "meesho", "name": "Meesho Push"}).json()
    ids = {}
    for sku, qty in (("PU-A", 7), ("PU-NEG", -2), ("PU-DRAFT", 4), ("PU-NOSTOCK", None)):
        body = {"sku": sku, "name": sku}
        if qty is not None:
            body["stock_qty"] = qty
        ids[sku] = client.post("/api/products", json=body).json()["id"]
    with get_conn() as c:
        c.execute("UPDATE products SET stock_qty=-2 WHERE sku='PU-NEG'")
        for sku, status in (("PU-A", "live"), ("PU-NEG", "exported"), ("PU-DRAFT", "draft"), ("PU-NOSTOCK", "live")):
            c.execute("INSERT INTO listings (product_id, account_id, status, stock_qty) VALUES (?,?,?,3)", (ids[sku], acc["id"], status))
    yield {"firm": firm, "acc": acc, "ids": ids}
    for pid in ids.values():
        client.delete(f"/api/products/{pid}?force=true")
    client.delete(f"/api/firms/{firm['id']}")
    stock.configure(from_orders=False)


def test_targets_are_listed_sarees_only_and_never_negative(client, w):
    t = {r["sku"]: r for r in client.get(f"/api/ext/stockpush/targets?account_id={w['acc']['id']}").json()}
    assert set(t) == {"PU-A", "PU-NEG"}                      # draft and unknown-stock sarees are left alone
    assert t["PU-A"]["target"] == 7 and t["PU-NEG"]["target"] == 0


def test_page_url_is_checked(client, w):
    acc = w["acc"]["id"]
    assert client.post("/api/ext/stockpush/pages", json={"account_id": acc, "url": "https://evil.example/inv"}).status_code == 400
    assert client.post("/api/ext/stockpush/pages", json={"account_id": acc, "url": INV, "label": "Inventory"}).status_code == 200


def test_order_sync_ignores_stock_pages(client, w):
    firm = w["firm"]["id"]
    assert order_sync.claim(firm)["run_id"] is None          # only a stock page is taught: nothing for the order sync
    assert client.get("/api/sync/status").json()["pages"] == [] or all(p["kind"] == "orders" for p in client.get("/api/sync/status").json()["pages"])


def test_manual_push_flow(client, w):
    firm, acc = w["firm"]["id"], w["acc"]["id"]
    assert client.post("/api/stockpush/now").json()["queued"] == ["Push Firm"]
    assert client.post("/api/stockpush/now").json()["queued"] == []        # already waiting
    got = client.post("/api/ext/stockpush/claim", json={"firm_id": firm}).json()
    assert got["run_id"] and got["pages"][0]["url"] == INV
    assert client.post("/api/ext/stockpush/claim", json={"firm_id": firm}).json()["run_id"] is None
    page = got["pages"][0]["page_id"]
    r = client.post("/api/ext/stockpush/result", json={"run_id": got["run_id"], "page_id": page, "state": "ok", "found": 2,
                                                       "updated": 1, "failed": ["PU-NEG: No stock box in this row"], "not_on_page": 0})
    assert r.status_code == 200
    assert client.post("/api/ext/stockpush/result", json={"run_id": got["run_id"], "page_id": page, "state": "bogus"}).status_code == 400
    assert "1 stock figures changed" in client.post("/api/ext/stockpush/finish", json={"run_id": got["run_id"]}).json()["summary"]
    row = client.get("/api/stockpush/status").json()["pages"][0]
    assert row["last_state"] == "ok" and "failed" in row["last_error"]
    assert client.post("/api/ext/stockpush/result", json={"run_id": got["run_id"], "page_id": page, "state": "ok"}).status_code == 409


def test_schedule_after_orders_and_switch_off(client, w):
    firm = w["firm"]["id"]
    now = datetime(2026, 11, 9, 9, 30)
    assert stock_push.claim(firm, now)["run_id"]                          # 09:00 slot due
    assert stock_push.claim(firm, now)["run_id"] is None                  # same slot never twice
    with get_conn() as c:
        c.execute("UPDATE stock_runs SET status='done'")
    assert stock_push.request_after_orders(firm) is True                  # listing stock differs from master
    with get_conn() as c:
        c.execute("UPDATE stock_runs SET status='done'")
    client.put("/api/stockpush/settings", json={"enabled": False})
    assert stock_push.request_after_orders(firm) is False
    assert stock_push.claim(firm, datetime(2026, 11, 9, 14, 0))["run_id"] is None
    assert client.put("/api/stockpush/settings", json={"times": ["25:00"]}).status_code == 400
    client.put("/api/stockpush/settings", json={"enabled": True})
