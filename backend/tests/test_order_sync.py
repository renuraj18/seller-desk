import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

os.environ.setdefault("SELLER_DESK_DATA", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import daily_check, order_sync  # noqa: E402
from app.services.secrets import set_setting  # noqa: E402

MEESHO = "https://supplier.meesho.com/panel/v3/new/growth/3ylgo/orders/pending"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def data(client):
    set_setting("agent_summary_after_sync", "0")          # tests never call the real agents
    firm = client.post("/api/firms", json={"name": "Sync Test Firm"}).json()
    other = client.post("/api/firms", json={"name": "Sync Other Firm"}).json()
    mee = client.post("/api/accounts", json={"firm_id": firm["id"], "marketplace": "meesho", "name": "Meesho Sync"}).json()
    amz = client.post("/api/accounts", json={"firm_id": other["id"], "marketplace": "amazon", "name": "Amazon Sync"}).json()
    p = client.post("/api/products", json={"sku": "SY-001", "name": "Sync Saree", "stock_qty": 0}).json()
    yield {"firm": firm, "other": other, "meesho": mee, "amazon": amz, "product": p}
    client.delete(f"/api/products/{p['id']}")
    client.delete(f"/api/firms/{firm['id']}")
    client.delete(f"/api/firms/{other['id']}")


def row(oid, **kw):
    return {"order_id": oid, "sub_order_id": f"{oid}_1", "sku": "SY-001", "order_date": "2026-11-01",
            "status_text": None, **kw}


def test_only_the_marketplaces_own_panel_pages_can_be_taught(client, data):
    acc = data["meesho"]["id"]
    for bad in ("https://evil.example/panel", "http://supplier.meesho.com/x", "https://supplier.meesho.com.evil.io/x",
                "https://sellercentral.amazon.in/orders"):
        assert client.post("/api/ext/sync/pages", json={"account_id": acc, "url": bad}).status_code == 400
    ok = client.post("/api/ext/sync/pages", json={"account_id": acc, "url": MEESHO, "status": "Pending", "tab_label": "Pending"})
    assert ok.status_code == 200


def test_manual_sync_claim_result_finish(client, data):
    firm = data["firm"]["id"]
    assert client.post("/api/ext/sync/claim", json={"firm_id": data["other"]["id"]}).json()["run_id"] is None  # no pages
    assert client.post("/api/sync/now").json()["queued"] == ["Sync Test Firm"]
    assert client.post("/api/sync/now").json()["queued"] == []                       # already waiting
    c = client.post("/api/ext/sync/claim", json={"firm_id": firm}).json()
    assert c["run_id"] and c["pages"][0]["url"] == MEESHO and c["pages"][0]["marketplace"] == "meesho"
    assert client.post("/api/ext/sync/claim", json={"firm_id": firm}).json()["run_id"] is None  # never handed out twice
    page = c["pages"][0]["page_id"]
    r = client.post("/api/ext/sync/result", json={"run_id": c["run_id"], "page_id": page, "state": "ok", "rows": [
        row("A1", order_date="2026-11-02"), row("A2", status_text="Cancelled"), row("A3", order_date="2026-11-09")]}).json()
    assert r["state"] == "ok" and r["created"] == 3
    f = client.post("/api/ext/sync/finish", json={"run_id": c["run_id"]}).json()
    assert "1 of 1 pages read, 3 order rows" in f["summary"]
    orders = client.get(f"/api/orders?account_id={data['meesho']['id']}").json()["orders"]
    by = {o["order_id"]: o["status"] for o in orders}
    assert by == {"A1": "pending", "A2": "cancelled", "A3": "pending"}   # page status Pending is the default
    # a result for a run that is no longer active is refused
    assert client.post("/api/ext/sync/result", json={"run_id": c["run_id"], "page_id": page, "state": "ok", "rows": []}).status_code == 409


def test_other_firms_pages_cannot_be_reported_into_a_run(client, data):
    client.post("/api/sync/now")
    c = client.post("/api/ext/sync/claim", json={"firm_id": data["firm"]["id"]}).json()
    amz_page = client.post("/api/ext/sync/pages", json={"account_id": data["amazon"]["id"],
                                                        "url": "https://sellercentral.amazon.in/orders-v3"}).json()["id"]
    assert client.post("/api/ext/sync/result", json={"run_id": c["run_id"], "page_id": amz_page, "state": "ok",
                                                     "rows": [row("X1")]}).status_code == 400
    client.post("/api/ext/sync/finish", json={"run_id": c["run_id"]})


def test_schedule_slots_run_once_each(client, data):
    set_setting("order_sync_times", "08:30,12:30")
    firm = data["firm"]["id"]
    now = datetime(2036, 5, 5, 13, 0)
    assert order_sync.latest_slot(now) == "2036-05-05 12:30"
    assert order_sync.latest_slot(datetime(2036, 5, 5, 7, 0)) == "2036-05-04 12:30"
    first = order_sync.claim(firm, now)
    assert first["run_id"]
    order_sync.finish(first["run_id"])
    assert order_sync.claim(firm, now)["run_id"] is None                        # same slot is not repeated
    nxt = order_sync.claim(firm, datetime(2036, 5, 6, 9, 0))
    assert nxt["run_id"]                                                         # a new day's slot runs
    order_sync.finish(nxt["run_id"])
    assert client.put("/api/sync/times", json={"times": ["8:30"]}).status_code == 400
    assert client.put("/api/sync/times", json={"times": ["17:30", "09:00"]}).json()["times"] == ["09:00", "17:30"]


def test_daily_check_flags_what_needs_action(client, data):
    client.post("/api/orders" if False else "/api/sync/now")
    acc = data["meesho"]["id"]
    rep = daily_check.report(datetime(2026, 11, 9).date())
    me = next(a for a in rep["accounts"] if a["id"] == acc)
    assert me["pending"] == 2 and me["oldest_pending_date"] == "2026-11-02" and me["oldest_pending_days"] == 7
    assert me["pending_overdue"] == 1                              # A1 is older than 2 days; A3 is today
    texts = " ".join(x["text"] for x in rep["attention"] if x["account"].startswith("Meesho Sync"))
    assert "older than 2 days" in texts
    # an account whose page reported signed_out is called out, and its data is not presented as fresh
    pid = me["sync_pages"][0]["id"]
    from app.db import get_conn
    with get_conn() as c:
        c.execute("UPDATE sync_pages SET last_state='signed_out' WHERE id=?", (pid,))
    rep = daily_check.report(datetime(2026, 11, 9).date())
    assert any("Signed out" in x["text"] and x["level"] == "high" for x in rep["attention"])


def test_agent_tool_returns_only_its_marketplace(client, data):
    from app.services import agents
    out = agents._daily_check("meesho")
    assert {a["account_id"] for a in out["accounts"]} >= {data["meesho"]["id"]}
    assert data["amazon"]["id"] not in {a["account_id"] for a in out["accounts"]}


def test_iso_dates_are_not_read_day_first():
    from app.services.orders import parse_date
    assert parse_date("2026-11-02") == "2026-11-02"
    assert parse_date("2026-11-02 10:30:00") == "2026-11-02"
    assert parse_date("02/11/2026") == "2026-11-02"      # day-first for slash dates, as before
    assert parse_date("2 Nov 2026") == "2026-11-02"
    assert parse_date("2026-13-40") is None


def test_pending_not_on_the_latest_pending_page_is_counted_apart(client, data):
    from app.db import get_conn
    acc = data["meesho"]["id"]
    client.post("/api/sync/now")
    with get_conn() as c:   # the sync pages were marked signed_out by an earlier test; mark the Pending page read now
        c.execute("UPDATE sync_pages SET last_state='ok', last_run_at=datetime('now') WHERE account_id=?", (acc,))
        c.execute("UPDATE orders SET updated_at=datetime('now','-3 hours') WHERE account_id=? AND order_id='A1'", (acc,))
    rep = daily_check.report(datetime(2026, 11, 9).date())
    me = next(a for a in rep["accounts"] if a["id"] == acc)
    assert me["pending"] == 1 and me["pending_unconfirmed"] == 1           # only A3 was seen on the latest read
    assert me["pending_overdue"] == 0                                       # the unseen A1 is not reported as overdue
    assert any("not on the latest" in x["text"] for x in rep["attention"])
