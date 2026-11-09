import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("SELLER_DESK_DATA", tempfile.mkdtemp())
os.environ["OPENCLAW_GATEWAY_TOKEN"] = "test-token"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import agents as agents_svc  # noqa: E402


class FakeResp:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.ok, self.text = data, status, status < 400, json.dumps(data)

    def json(self):
        return self._data


def call(name, args, cid="c1"):
    return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}


def answer(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def data(client):
    firm = client.post("/api/firms", json={"name": "Agent Test Firm"}).json()
    mee = client.post("/api/accounts", json={"firm_id": firm["id"], "marketplace": "meesho", "name": "Meesho AT"}).json()
    amz = client.post("/api/accounts", json={"firm_id": firm["id"], "marketplace": "amazon", "name": "Amazon AT"}).json()
    p = client.post("/api/products", json={"sku": "AT-001", "name": "Agent Test Saree", "brand": "Shanthi",
                                           "fabric": "Cotton", "color": "Blue", "stock_qty": 8,
                                           "selling_price": 900, "mrp": 1500}).json()
    client.put("/api/listings", json={"product_id": p["id"], "account_id": mee["id"], "stock_qty": 5, "status": "live"})
    yield {"meesho": mee, "amazon": amz, "product": p}
    # the database is shared with test_app.py in one pytest run: leave it as we found it
    client.delete(f"/api/products/{p['id']}")
    client.delete(f"/api/firms/{firm['id']}")
    agents_svc.clear_history("meesho"), agents_svc.clear_history("amazon"), agents_svc.clear_history("flipkart")


def scripted(monkeypatch, replies):
    """Make the gateway return these replies in order and record what Seller Desk sent."""
    sent = []

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append({"url": url, "headers": headers, "body": json})
        return FakeResp(replies.pop(0))
    monkeypatch.setattr(agents_svc.requests, "post", fake_post)
    return sent


def test_agent_reads_with_tools_and_proposes_stock_fix(client, data, monkeypatch):
    pid = data["product"]["id"]
    sent = scripted(monkeypatch, [
        call("get_stock_mismatches", {}),
        call("propose_master_stock", {"product_id": pid, "stock_qty": 5, "reason": "Meesho shows 5"}, "c2"),
        answer("AT-001 differs: master 8, Meesho 5. I proposed setting master to 5."),
    ])
    r = client.post("/api/agents/meesho/chat", json={"message": "Any stock mismatches?"}).json()
    assert r["message"]["role"] == "assistant" and "AT-001" in r["message"]["content"]
    assert len(r["proposals"]) == 1
    # routed to the Meesho agent with the gateway token and Seller Desk's tools
    assert sent[0]["body"]["model"] == "openclaw/meesho"
    assert sent[0]["headers"]["Authorization"] == "Bearer test-token"
    assert {t["function"]["name"] for t in sent[0]["body"]["tools"]} >= {"get_overview", "propose_content_draft"}
    # the tool result went back to the agent and showed the mismatch
    tool_msg = [m for m in sent[1]["body"]["messages"] if m["role"] == "tool"][0]
    assert '"master_stock": 8' in tool_msg["content"] and '"account_stock": 5' in tool_msg["content"]

    # nothing changes until the user approves
    assert client.get(f"/api/products/{pid}").json()["stock_qty"] == 8
    prop = client.get("/api/agents/proposals?status=pending&marketplace=meesho").json()["proposals"][0]
    assert prop["kind"] == "master_stock" and prop["payload"]["stock_qty"] == 5
    done = client.post(f"/api/agents/proposals/{prop['id']}/decide", json={"approve": True}).json()
    assert done["status"] == "applied"
    assert client.get(f"/api/products/{pid}").json()["stock_qty"] == 5
    # a decided proposal cannot be applied twice
    assert client.post(f"/api/agents/proposals/{prop['id']}/decide", json={"approve": True}).status_code == 409

    msgs = client.get("/api/agents/meesho/messages").json()["messages"]
    assert [m["role"] for m in msgs[-2:]] == ["user", "assistant"]
    assert msgs[-1]["tools"][0]["name"] == "get_stock_mismatches"


def test_agent_cannot_touch_other_marketplace_accounts(client, data, monkeypatch):
    sent = scripted(monkeypatch, [
        call("get_listings", {"account_id": data["amazon"]["id"]}),
        call("propose_listing_status", {"product_id": data["product"]["id"], "account_id": data["amazon"]["id"],
                                        "status": "inactive", "reason": "x"}, "c2"),
        answer("I can only see Meesho accounts."),
    ])
    r = client.post("/api/agents/meesho/chat", json={"message": "Show Amazon listings"}).json()
    assert r["proposals"] == []
    results = [m["content"] for s in sent for m in s["body"]["messages"] if m["role"] == "tool"]
    assert all("not a Meesho account" in t for t in results[-2:])


def test_content_proposal_respects_marketplace_limits(client, data, monkeypatch):
    long_title = "Shanthi Cotton Saree Blue " * 10
    scripted(monkeypatch, [
        call("propose_content_draft", {"product_id": data["product"]["id"], "title": long_title,
                                       "bullets": ["Soft cotton"], "reason": "no content yet"}),
        answer("Drafted."),
    ])
    client.post("/api/agents/amazon/chat", json={"message": "Write content for AT-001"})
    prop = client.get("/api/agents/proposals?marketplace=amazon&status=pending").json()["proposals"][0]
    assert len(prop["payload"]["title"]) <= 75
    assert client.post(f"/api/agents/proposals/{prop['id']}/decide", json={"approve": True}).json()["status"] == "applied"
    d = client.get(f"/api/products/{data['product']['id']}/drafts").json()["drafts"]["amazon"]
    assert d["saved"] and d["source"] == "agent" and not d["approved"] and len(d["title"]) <= 75


def test_gateway_errors_are_shown_not_raised(client, monkeypatch):
    monkeypatch.setattr(agents_svc.requests, "post",
                        lambda *a, **k: FakeResp({"error": {"message": "rate limited"}}, 429))
    r = client.post("/api/agents/flipkart/chat", json={"message": "hi"}).json()
    assert r["message"]["role"] == "error" and "rate limited" in r["message"]["content"]


def test_status_when_gateway_down(client, monkeypatch):
    def down(*a, **k):
        raise agents_svc.requests.ConnectionError()
    monkeypatch.setattr(agents_svc.requests, "get", down)
    s = client.get("/api/agents/status").json()
    assert s["reachable"] is False and "not running" in s["problem"]


def test_reject_and_task(client, monkeypatch):
    scripted(monkeypatch, [call("add_task", {"title": "Import this week's Flipkart orders file"}), answer("Added.")])
    client.post("/api/agents/flipkart/chat", json={"message": "what should I do?"})
    prop = client.get("/api/agents/proposals?marketplace=flipkart&status=pending").json()["proposals"][0]
    assert prop["kind"] == "task"
    assert client.post(f"/api/agents/proposals/{prop['id']}/decide", json={"approve": False}).json()["status"] == "rejected"


def test_firm_browser_profile_is_validated(client, data):
    firm_id = data["meesho"]["firm_id"]
    assert client.put(f"/api/firms/{firm_id}", json={"name": "Agent Test Firm", "browser_profile": "Bad Name!"}).status_code == 422
    assert client.put(f"/api/firms/{firm_id}", json={"name": "Agent Test Firm",
                                                     "browser_profile": "chrome-agent-test"}).json()["browser_profile"] == "chrome-agent-test"


def fake_chrome(monkeypatch, tabs, pages):
    """Stand in for the openclaw CLI: `tabs` returns these tabs, `snapshot` returns pages[target]."""
    from app.services import live_panel
    calls = []

    def run(args):
        calls.append(args)
        if args[-1] == "tabs":
            return json.dumps({"tabs": tabs})
        return pages[args[args.index("--target-id") + 1]]
    monkeypatch.setattr(live_panel, "_run", run)
    return calls


def test_live_panel_reads_only_the_accounts_seller_tab(client, data, monkeypatch):
    calls = fake_chrome(monkeypatch, [
        {"tabId": "t1", "url": "https://chatgpt.com/c/private"},
        {"tabId": "t2", "url": "https://supplier.meesho.com/panel/v3/new/growth/abc/home"},
        {"tabId": "t3", "url": "https://supplier.meesho.com/panel/v3/new/growth/abc/settings/bank-details"},
        {"tabId": "t4", "url": "https://supplier.meesho.com.evil.example/panel"},
        {"tabId": "t5", "url": "https://supplier.meesho.com/panel/v3/new/growth/xyz/home"},
    ], {
        "t2": '- heading "Welcome back, Meesho AT" [ref=x:1]\n  - statictext "Pending Orders"\n  - heading "3" [ref=x:2]',
        "t5": '- heading "Welcome back, Other Shop" [ref=x:3]\n  - heading "9" [ref=x:4]',
    })
    sent = scripted(monkeypatch, [call("read_live_panel", {"account_id": data["meesho"]["id"]}), answer("3 pending (live panel)")])
    client.post("/api/agents/meesho/chat", json={"message": "live pending orders?"})
    out = json.loads([m for m in sent[1]["body"]["messages"] if m["role"] == "tool"][0]["content"])
    assert out["ok"] and out["source"] == "LIVE seller panel" and out["skipped_private_pages"] == 1
    assert [p["url"] for p in out["pages"]] == ["https://supplier.meesho.com/panel/v3/new/growth/abc/home"]
    assert "Pending Orders" in out["pages"][0]["text"] and "ref=" not in out["pages"][0]["text"]
    # used the firm's own profile; only listed tabs and took snapshots of seller-panel pages
    assert all(c[:3] == ["browser", "--browser-profile", "chrome-agent-test"] for c in calls)
    snapped = [c[c.index("--target-id") + 1] for c in calls if "snapshot" in c]
    assert sorted(snapped) == ["t2", "t5"]
    assert not any(verb in c for c in calls for verb in ("open", "navigate", "act", "click", "close"))


def test_live_panel_with_no_tab_or_no_profile(client, data, monkeypatch):
    fake_chrome(monkeypatch, [{"tabId": "t1", "url": "https://chatgpt.com/"}], {})
    from app.services import live_panel
    r = live_panel.read("meesho", data["meesho"]["id"])
    assert r["ok"] is False and "No open supplier.meesho.com tab" in r["note"]
    with pytest.raises(ValueError, match="not a meesho account"):
        live_panel.read("meesho", data["amazon"]["id"])
    firm_id = data["meesho"]["firm_id"]
    client.put(f"/api/firms/{firm_id}", json={"name": "Agent Test Firm", "browser_profile": None})
    with pytest.raises(ValueError, match="no browser profile"):
        live_panel.read("meesho", data["meesho"]["id"])


def test_brief_forbids_passing_off_seller_desk_figures_as_live(client, monkeypatch):
    sent = scripted(monkeypatch, [answer("ok")])
    client.post("/api/agents/amazon/chat", json={"message": "hi"})
    brief = sent[0]["body"]["messages"][0]["content"]
    assert "read_live_panel" in brief and "Never present Seller Desk figures as live" in brief


def test_live_panel_code_picks_exactly_one_account_tab(client, data, monkeypatch):
    firm_id = data["meesho"]["firm_id"]
    client.put(f"/api/firms/{firm_id}", json={"name": "Agent Test Firm", "browser_profile": "chrome-agent-test"})
    acc = client.get("/api/accounts").json()
    mee = next(a for a in acc if a["id"] == data["meesho"]["id"])
    mee["panel_match"] = "fx6ao"
    assert client.put(f"/api/accounts/{mee['id']}", json=mee).json()["panel_match"] == "fx6ao"
    calls = fake_chrome(monkeypatch, [
        {"tabId": "t1", "url": "https://supplier.meesho.com/panel/v3/new/growth/3ylgo/home"},
        {"tabId": "t2", "url": "https://supplier.meesho.com/panel/v3/new/growth/fx6ao/home"},
        {"tabId": "t3", "url": "https://supplier.meesho.com/panel/v3/new/growth/fx6ao/settings/bank-details"},
    ], {"t2": '- heading "Welcome back, Same Looking Name" [ref=x:1]'})
    from app.services import live_panel
    r = live_panel.read("meesho", mee["id"])
    assert [p["url"] for p in r["pages"]] == ["https://supplier.meesho.com/panel/v3/new/growth/fx6ao/home"]
    assert r["pages"][0]["matches_account"] is True
    assert [c[c.index("--target-id") + 1] for c in calls if "snapshot" in c] == ["t2"]  # nothing else was read


def test_extract_figures_reports_what_is_missing():
    from app.services import live_panel
    text = "Pending Orders\n[heading] 1\nOut of Stock\n[heading] 6\nLow Stock\n[heading] 0\n[button] 4  Catalog(s) at risk"
    r = live_panel.extract_figures("meesho", text)
    assert r["figures"] == {"Pending Orders": "1", "Out of Stock": "6", "Low Stock": "0", "Catalog(s) at risk": "4"}
    assert set(r["not_shown_on_page"]) == {"Download Labels", "Catalog(s) blocked"}
    assert live_panel.extract_figures("meesho", "Pending Orders\n[heading] 2")["figures"] == {"Pending Orders": "2"}
