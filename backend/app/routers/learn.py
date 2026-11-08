"""Learn each marketplace's add-product form from one live listing (the top seller), as a repeatable one-time activity."""

import json
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import dump, get_conn, rows_to_dicts
from ..fields import normalise
from ..services import learn as svc
from . import extension

router = APIRouter(prefix="/api/learn", tags=["learn"])
Market = Literal["amazon", "flipkart", "meesho"]


def _target(marketplace: str) -> dict | None:
    with get_conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (f"learn_target_{marketplace}",)).fetchone()
    try:
        return json.loads(row["value"]) if row and row["value"] else None
    except ValueError:
        return None


def _resolve(marketplace: str) -> dict:
    """The chosen target if still valid, else the current top seller."""
    top = svc.top_sellers(marketplace)
    chosen = _target(marketplace)
    pick = None
    if chosen:
        pick = next((x for x in top["candidates"] if x["product_id"] == chosen.get("product_id")
                     and x["account_id"] == chosen.get("account_id")), None)
        if not pick:
            with get_conn() as c:
                r = c.execute("SELECT p.id AS product_id, p.sku, p.name, p.color, a.id AS account_id, a.name AS account_name "
                              "FROM products p, accounts a WHERE p.id=? AND a.id=? AND a.marketplace=?",
                              (chosen.get("product_id"), chosen.get("account_id"), marketplace)).fetchone()
            if r:
                pick = {**dict(r), "sold": 0}
    if not pick and top["candidates"]:
        pick = top["candidates"][0]
    return {"source": top["source"], "candidates": top["candidates"], "target": pick,
            "chosen": bool(chosen and pick and pick["product_id"] == chosen.get("product_id"))}


@router.get("/status")
def status():
    """Per marketplace: who the top seller is, and when the form was last learned."""
    out = {}
    with get_conn() as c:
        for mp in ("meesho", "flipkart", "amazon"):
            run = c.execute("SELECT r.*, p.sku, a.name AS account_name FROM learn_runs r "
                            "LEFT JOIN products p ON p.id=r.product_id LEFT JOIN accounts a ON a.id=r.account_id "
                            "WHERE r.marketplace=? ORDER BY r.id DESC LIMIT 1", (mp,)).fetchone()
            counts = {r["origin"] or "taught": r["n"] for r in c.execute(
                "SELECT origin, COUNT(*) AS n FROM form_fields WHERE marketplace=? GROUP BY origin", (mp,))}
            out[mp] = {**_resolve(mp), "last_run": dict(run) if run else None,
                       "learned_fields": counts.get("learned", 0), "taught_fields": counts.get("taught", 0)}
    return out


@router.get("/target")
def target(marketplace: Market):
    return _resolve(marketplace)


class TargetIn(BaseModel):
    marketplace: Market
    product_id: int
    account_id: int


@router.put("/target")
def set_target(t: TargetIn):
    with get_conn() as c:
        ok = c.execute("SELECT 1 FROM accounts WHERE id=? AND marketplace=?", (t.account_id, t.marketplace)).fetchone()
        if not ok or not c.execute("SELECT 1 FROM products WHERE id=?", (t.product_id,)).fetchone():
            raise HTTPException(404, "Product or account not found for this marketplace")
        c.execute("INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                  "updated_at=datetime('now')", (f"learn_target_{t.marketplace}", json.dumps(t.model_dump(include={"product_id", "account_id"}))))
    return _resolve(t.marketplace)


class SeenField(BaseModel):
    label: str
    value: str | None = None
    kind: str = "text"
    options: list[str] = []


class ProposeIn(BaseModel):
    marketplace: Market
    product_id: int
    account_id: int
    fields: list[SeenField]


@router.post("/propose")
def propose(body: ProposeIn):
    pl = extension.payload(body.product_id, body.account_id)
    rows = svc.propose(pl["values"], [f.model_dump() for f in body.fields])
    with get_conn() as c:
        known = {r["label_norm"]: r for r in rows_to_dicts(c.execute(
            "SELECT label_norm, source, value, value_map FROM form_fields WHERE marketplace=?", (body.marketplace,)))}
    for r in rows:
        r["sd_value"] = pl["values"].get(r["source"]) if r["source"] != "const.custom" else r["value"]
        prev = known.get(r["label_norm"])
        r["previous"] = prev["source"] if prev else None
        r["changed"] = bool(prev) and prev["source"] != r["source"]
    summary = {k: sum(1 for r in rows if r["confidence"] == k) for k in ("high", "medium", "ambiguous", "label", "fixed", "empty")}
    return {"product": pl["product"], "account": pl["account"], "summary": summary, "fields": rows}


class SaveItem(BaseModel):
    label: str
    source: str = ""
    value: str | None = None
    value_map: dict = {}
    sample: str | None = None


class SaveIn(BaseModel):
    marketplace: Market
    product_id: int
    account_id: int
    fields_seen: int = 0
    items: list[SaveItem]


@router.post("/save")
def save(body: SaveIn):
    saved = 0
    with get_conn() as c:
        for it in body.items:
            key = normalise(it.label)
            if not key:
                continue
            c.execute("INSERT INTO form_fields (marketplace, label_norm, label, source, value, value_map, origin, sample) "
                      "VALUES (?,?,?,?,?,?,'learned',?) ON CONFLICT(marketplace, label_norm) DO UPDATE SET "
                      "label=excluded.label, source=excluded.source, value=excluded.value, value_map=excluded.value_map, "
                      "origin='learned', sample=excluded.sample, updated_at=datetime('now')",
                      (body.marketplace, key, it.label.strip()[:200], it.source, it.value if it.source == "const.custom" else None,
                       dump(it.value_map or {}), (it.sample or "")[:200]))
            saved += 1
        c.execute("INSERT INTO learn_runs (marketplace, product_id, account_id, fields_seen, fields_saved) VALUES (?,?,?,?,?)",
                  (body.marketplace, body.product_id, body.account_id, body.fields_seen, saved))
    return {"ok": True, "saved": saved}
