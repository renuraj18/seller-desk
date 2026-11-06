from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import get_conn, row_to_dict, rows_to_dicts
from ..services.pricing import account_price, account_sku

router = APIRouter(prefix="/api", tags=["listings"])


class ListingIn(BaseModel):
    product_id: int
    account_id: int
    marketplace_sku: str | None = None
    listing_ref: str | None = None
    price: float | None = None
    mrp: float | None = None
    stock_qty: int | None = None
    title_override: str | None = None
    status: str = "draft"
    notes: str | None = None


class BulkAdd(BaseModel):
    account_id: int
    product_ids: list[int]


class BulkStatus(BaseModel):
    listing_ids: list[int]
    status: str


def _account(c, account_id):
    a = row_to_dict(c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())
    if not a:
        raise HTTPException(404, "Account not found")
    return a


@router.get("/accounts/{account_id}/listings")
def account_listings(account_id: int):
    """Every product, with its listing on this account (if any) and the effective price/SKU."""
    with get_conn() as c:
        acc = _account(c, account_id)
        products = rows_to_dicts(c.execute("SELECT * FROM products ORDER BY sku"))
        listings = {l["product_id"]: l for l in rows_to_dicts(
            c.execute("SELECT * FROM listings WHERE account_id=?", (account_id,)))}
    out = []
    for p in products:
        l = listings.get(p["id"])
        out.append({
            "product_id": p["id"], "sku": p["sku"], "name": p["name"], "fabric": p["fabric"], "color": p["color"],
            "image": (p.get("images") or [None])[0], "base_price": p["selling_price"], "mrp": p["mrp"],
            "cost_price": p["cost_price"],
            "listing": l,
            "effective_sku": account_sku(p, acc, l),
            "effective_price": account_price(p, acc, l),
        })
    return {"account": acc, "rows": out}


@router.put("/listings")
def upsert_listing(l: ListingIn):
    with get_conn() as c:
        c.execute(
            "INSERT INTO listings (product_id, account_id, marketplace_sku, listing_ref, price, mrp, stock_qty, "
            "title_override, status, notes) VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(product_id, account_id) DO UPDATE SET marketplace_sku=excluded.marketplace_sku, "
            "listing_ref=excluded.listing_ref, price=excluded.price, mrp=excluded.mrp, stock_qty=excluded.stock_qty, "
            "title_override=excluded.title_override, status=excluded.status, notes=excluded.notes",
            (l.product_id, l.account_id, l.marketplace_sku or None, l.listing_ref or None, l.price, l.mrp,
             l.stock_qty, l.title_override or None, l.status, l.notes))
        return row_to_dict(c.execute("SELECT * FROM listings WHERE product_id=? AND account_id=?",
                                     (l.product_id, l.account_id)).fetchone())


@router.post("/listings/bulk-add")
def bulk_add(b: BulkAdd):
    with get_conn() as c:
        _account(c, b.account_id)
        added = 0
        for pid in b.product_ids:
            cur = c.execute("INSERT OR IGNORE INTO listings (product_id, account_id) VALUES (?,?)",
                            (pid, b.account_id))
            added += cur.rowcount
    return {"added": added}


@router.post("/listings/bulk-status")
def bulk_status(b: BulkStatus):
    with get_conn() as c:
        c.executemany("UPDATE listings SET status=? WHERE id=?", [(b.status, i) for i in b.listing_ids])
    return {"updated": len(b.listing_ids)}


@router.delete("/listings/{listing_id}")
def delete_listing(listing_id: int):
    with get_conn() as c:
        c.execute("DELETE FROM listings WHERE id=?", (listing_id,))
    return {"ok": True}


@router.get("/dashboard")
def dashboard():
    with get_conn() as c:
        q = lambda sql, *a: c.execute(sql, a).fetchone()[0]
        accounts = rows_to_dicts(c.execute(
            "SELECT a.id, a.name, a.marketplace, f.name AS firm_name, "
            "SUM(CASE WHEN l.status='live' THEN 1 ELSE 0 END) AS live, "
            "SUM(CASE WHEN l.status='draft' THEN 1 ELSE 0 END) AS draft, "
            "SUM(CASE WHEN l.status='exported' THEN 1 ELSE 0 END) AS exported, "
            "SUM(CASE WHEN l.status IN ('rejected','inactive') THEN 1 ELSE 0 END) AS other "
            "FROM accounts a JOIN firms f ON f.id=a.firm_id LEFT JOIN listings l ON l.account_id=a.id "
            "GROUP BY a.id ORDER BY f.name, a.marketplace"))
        return {
            "firms": q("SELECT COUNT(*) FROM firms"),
            "accounts": q("SELECT COUNT(*) FROM accounts"),
            "products": q("SELECT COUNT(*) FROM products"),
            "listings": q("SELECT COUNT(*) FROM listings"),
            "templates": q("SELECT COUNT(*) FROM template_profiles"),
            "incomplete_products": q("SELECT COUNT(*) FROM products WHERE fabric IS NULL OR color IS NULL "
                                     "OR mrp IS NULL OR selling_price IS NULL OR hsn IS NULL OR images='[]'"),
            "by_account": accounts,
        }


# ------------------------------------------------------------------ inventory (master stock vs every account)

class StockChange(BaseModel):
    product_id: int
    stock_qty: int | None = None   # set to this
    delta: int | None = None       # or add/subtract this (e.g. -1 after a sale)


@router.get("/inventory")
def inventory():
    with get_conn() as c:
        products = rows_to_dicts(c.execute(
            "SELECT id, sku, parent_sku, name, fabric, color, saree_type, stock_qty, images FROM products "
            "ORDER BY COALESCE(parent_sku, sku), sku"))
        accounts = rows_to_dicts(c.execute(
            "SELECT a.id, a.name, a.marketplace, f.name AS firm_name FROM accounts a JOIN firms f ON f.id=a.firm_id "
            "WHERE a.active=1 ORDER BY f.name, a.marketplace, a.name"))
        listings = rows_to_dicts(c.execute("SELECT product_id, account_id, stock_qty, status FROM listings"))
    by = {(l["product_id"], l["account_id"]): l for l in listings}
    out_of_sync = 0
    for p in products:
        p["image"] = (p.pop("images") or [None])[0]
        p["accounts"] = {}
        for a in accounts:
            l = by.get((p["id"], a["id"]))
            if l:
                p["accounts"][a["id"]] = {"stock": l["stock_qty"], "status": l["status"]}
                if p["stock_qty"] is not None and l["stock_qty"] != p["stock_qty"] and l["status"] != "draft":
                    out_of_sync += 1
    return {"products": products, "accounts": accounts, "out_of_sync": out_of_sync}


@router.post("/inventory/stock")
def change_stock(changes: list[StockChange]):
    with get_conn() as c:
        for ch in changes:
            if ch.stock_qty is not None:
                c.execute("UPDATE products SET stock_qty=?, updated_at=datetime('now') WHERE id=?",
                          (max(0, ch.stock_qty), ch.product_id))
            elif ch.delta:
                c.execute("UPDATE products SET stock_qty=MAX(0, COALESCE(stock_qty,0)+?), updated_at=datetime('now') "
                          "WHERE id=?", (ch.delta, ch.product_id))
    return {"updated": len(changes)}


class MultiAdd(BaseModel):
    product_ids: list[int]
    account_ids: list[int]


@router.post("/listings/add-to-accounts")
def add_to_accounts(b: MultiAdd):
    """Queue sarees (draft listings) on several accounts at once; variants of a design come along."""
    with get_conn() as c:
        ids = set(b.product_ids)
        parents = [r["parent_sku"] for r in c.execute(
            f"SELECT DISTINCT parent_sku FROM products WHERE parent_sku IS NOT NULL AND id IN ({','.join('?' * len(ids))})",
            tuple(ids))] if ids else []
        for parent in parents:
            ids |= {r["id"] for r in c.execute("SELECT id FROM products WHERE parent_sku=?", (parent,))}
        added = 0
        for aid in b.account_ids:
            for pid in ids:
                added += c.execute("INSERT OR IGNORE INTO listings (product_id, account_id) VALUES (?,?)",
                                   (pid, aid)).rowcount
    return {"added": added, "products": len(ids)}
