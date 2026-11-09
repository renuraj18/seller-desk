"""API used by the Seller Desk Chrome extension (autofill on Meesho / Flipkart / Amazon seller panels)."""

import io
import zipfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..db import dump, get_conn, row_to_dict, rows_to_dicts
from ..fields import _SYNONYMS, all_sources, normalise
from ..services import catalogs
from ..services.ai_writer import content_for_export
from ..services.pricing import account_price, account_sku
from ..services.template_filler import resolve_value

router = APIRouter(prefix="/api/ext", tags=["extension"])

EXT_DIR = Path(__file__).resolve().parents[3] / "extension"
Market = Literal["amazon", "flipkart", "meesho"]


def _account(c, account_id):
    a = row_to_dict(c.execute("SELECT a.*, f.name AS firm_name, f.address AS firm_address, f.pincode AS firm_pincode, "
                              "f.gstin AS firm_gstin FROM accounts a JOIN firms f ON f.id=a.firm_id "
                              "WHERE a.id=?", (account_id,)).fetchone())
    if not a:
        raise HTTPException(404, "Account not found")
    return a


@router.get("/ping")
def ping():
    return {"ok": True, "app": "seller-desk"}


@router.get("/context")
def context(marketplace: Market):
    """Everything the panel needs when it opens on a seller panel page."""
    with get_conn() as c:
        accounts = rows_to_dicts(c.execute(
            "SELECT a.id, a.name, a.marketplace, a.brand, a.sku_prefix, a.seller_id, a.store_name, a.add_catalog_url, f.name AS firm_name, "
            "(SELECT COUNT(*) FROM listings l WHERE l.account_id=a.id AND l.status='draft') AS to_list "
            "FROM accounts a JOIN firms f ON f.id=a.firm_id WHERE a.marketplace=? AND a.active=1 "
            "ORDER BY f.name, a.name", (marketplace,)))
        learned = rows_to_dicts(c.execute(
            "SELECT label_norm, label, source, value, value_map FROM form_fields WHERE marketplace=?", (marketplace,)))
    sources = [{"key": s["key"], "label": s["label"], "group": s["group"]} for s in all_sources()]
    return {
        "accounts": accounts,
        "sources": sources,
        "synonyms": [[syn, key] for syn, key in _SYNONYMS],
        "learned": learned,
    }


@router.get("/products")
def products(account_id: int, q: str = "", only: str = "all"):
    """Products with their status on this account. only=todo → listings still in draft."""
    with get_conn() as c:
        acc = _account(c, account_id)
        like = f"%{q}%"
        sql = ("SELECT p.*, l.status AS listing_status, l.price AS listing_price, l.marketplace_sku, l.listing_ref, "
               "l.id AS listing_id FROM products p LEFT JOIN listings l ON l.product_id=p.id AND l.account_id=? "
               "WHERE (?='' OR p.sku LIKE ? OR p.name LIKE ? OR p.fabric LIKE ? OR p.color LIKE ? OR p.saree_type LIKE ?)")
        if only == "todo":
            sql += " AND l.status='draft'"
        rows = rows_to_dicts(c.execute(sql + " ORDER BY p.sku LIMIT 200", (account_id, q, like, like, like, like, like)))
        drafts = {(r["product_id"]): r for r in rows_to_dicts(c.execute(
            "SELECT product_id, approved, score FROM content_drafts WHERE marketplace=?", (acc["marketplace"],)))}
    out = []
    for p in rows:
        listing = {"price": p["listing_price"], "marketplace_sku": p["marketplace_sku"]}
        d = drafts.get(p["id"]) or {}
        out.append({
            "id": p["id"], "sku": p["sku"], "name": p["name"], "fabric": p["fabric"], "color": p["color"],
            "saree_type": p["saree_type"], "image": (p.get("images") or [None])[0],
            "status": p["listing_status"], "listing_ref": p["listing_ref"],
            "account_sku": account_sku(p, acc, listing), "price": account_price(p, acc, listing),
            "content_approved": bool(d.get("approved")), "score": d.get("score"),
            "parent_sku": p["parent_sku"], "stock": p["stock_qty"],
        })
    with get_conn() as c:
        for item in out:      # on Meesho a design of 12 colours is two catalogs of 9 + 3
            if item["parent_sku"]:
                no, ids = catalogs.catalog_of(c, item["id"], account_id)
                item["catalog_ids"] = ids
                item["group_key"] = f"{item['parent_sku']}#{no or 1}"
                item["catalog_parent_sku"] = catalogs.account_parent(item["parent_sku"], "", no)
            else:
                item["group_key"] = None
    groups: dict = {}
    for item in out:
        if item["group_key"]:
            groups.setdefault(item["group_key"], []).append(item)
    for item in out:
        item["variant_count"] = len(item["catalog_ids"]) if item["group_key"] else 1
    return out


@router.get("/payload")
def payload(product_id: int, account_id: int):
    """Every value the extension may type into a form for this product on this account."""
    with get_conn() as c:
        acc = _account(c, account_id)
        p = row_to_dict(c.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone())
        if not p:
            raise HTTPException(404, "Product not found")
        catalogs.catalog_of(c, product_id, account_id)       # places the saree in a catalog (Meesho: 9 per catalog)
        listing = row_to_dict(c.execute("SELECT * FROM listings WHERE product_id=? AND account_id=?",
                                        (product_id, account_id)).fetchone())
    gen = content_for_export(p, acc["marketplace"], brand=acc.get("brand") or None,
                             title_override=(listing or {}).get("title_override"))
    values = {}
    for s in all_sources():
        if s["key"] == "const.custom":
            continue
        v = resolve_value(s["key"], None, p, acc, listing, gen)
        if v not in (None, ""):
            values[s["key"]] = v
    return {
        "product": {"id": p["id"], "sku": p["sku"], "name": p["name"]},
        "account": {"id": acc["id"], "name": acc["name"], "firm_name": acc["firm_name"],
                    "marketplace": acc["marketplace"]},
        "values": values,
        "images": [u for u in (p.get("images") or []) if u],
        "content_source": gen.get("source"),
    }


@router.get("/payload-group")
def payload_group(product_id: int, account_id: int):
    """Payloads for every colour variant of this saree's design (one per variant, sorted by SKU)."""
    with get_conn() as c:
        p = row_to_dict(c.execute("SELECT id, parent_sku FROM products WHERE id=?", (product_id,)).fetchone())
        if not p:
            raise HTTPException(404, "Product not found")
        _, ids = catalogs.catalog_of(c, product_id, account_id)     # one catalog's worth: at most 9 colours on Meesho
    return [payload(i, account_id) for i in ids]


# ------------------------------------------------------------------ stock

@router.get("/stock")
def stock(account_id: int):
    """Master stock vs. the stock last seen on this account, for every product listed there."""
    with get_conn() as c:
        acc = _account(c, account_id)
        rows = rows_to_dicts(c.execute(
            "SELECT p.id, p.sku, p.parent_sku, p.color, p.stock_qty, p.images, l.marketplace_sku, l.listing_ref, "
            "l.stock_qty AS seen_stock, l.price, l.status FROM listings l JOIN products p ON p.id=l.product_id "
            "WHERE l.account_id=? ORDER BY p.sku", (account_id,)))
    out = []
    for r in rows:
        listing = {"marketplace_sku": r["marketplace_sku"]}
        out.append({
            "product_id": r["id"], "sku": r["sku"], "color": r["color"], "parent_sku": r["parent_sku"],
            "account_sku": account_sku(r, acc, listing), "listing_ref": r["listing_ref"],
            "image": (r["images"] or [None])[0], "target": r["stock_qty"], "seen": r["seen_stock"],
            "status": r["status"],
        })
    return out


class SeenRow(BaseModel):
    key: str                     # SKU / ASIN / FSN text found on the page
    stock: int | None = None


class SeenIn(BaseModel):
    account_id: int
    rows: list[SeenRow]


@router.post("/stock-seen")
def stock_seen(body: SeenIn):
    """Stock read off the marketplace's inventory page by the extension."""
    keys = {r["account_sku"]: r for r in stock(body.account_id)}
    by_ref = {r["listing_ref"]: r for r in keys.values() if r["listing_ref"]}
    updated, unknown = 0, []
    with get_conn() as c:
        for row in body.rows:
            hit = keys.get(row.key) or by_ref.get(row.key)
            if not hit:
                unknown.append(row.key)
                continue
            if row.stock is not None:
                c.execute("UPDATE listings SET stock_qty=? WHERE product_id=? AND account_id=?",
                          (row.stock, hit["product_id"], body.account_id))
                c.execute("UPDATE remote_listings SET stock=?, synced_at=datetime('now') "
                          "WHERE account_id=? AND remote_sku=?", (row.stock, body.account_id, hit["account_sku"]))
                updated += 1
    return {"updated": updated, "unknown": unknown[:50]}


class StockSet(BaseModel):
    product_id: int
    account_id: int
    stock: int


@router.post("/stock-set")
def stock_set(body: StockSet):
    """The extension changed the stock on the marketplace page to this number."""
    with get_conn() as c:
        c.execute("UPDATE listings SET stock_qty=? WHERE product_id=? AND account_id=?",
                  (body.stock, body.product_id, body.account_id))
    return {"ok": True}


class LearnedField(BaseModel):
    label: str
    source: str = ""
    value: str | None = None
    value_map: dict = {}


@router.put("/fields/{marketplace}")
def learn_field(marketplace: Market, f: LearnedField):
    key = normalise(f.label)
    if not key:
        raise HTTPException(400, "Field label is empty")
    with get_conn() as c:
        c.execute("INSERT INTO form_fields (marketplace, label_norm, label, source, value, value_map) "
                  "VALUES (?,?,?,?,?,?) ON CONFLICT(marketplace, label_norm) DO UPDATE SET label=excluded.label, "
                  "source=excluded.source, value=excluded.value, value_map=excluded.value_map, "
                  "origin='taught', updated_at=datetime('now')",
                  (marketplace, key, f.label.strip()[:200], f.source, f.value, dump(f.value_map or {})))
    return {"ok": True, "label_norm": key}


@router.get("/fields")
def list_fields():
    with get_conn() as c:
        return rows_to_dicts(c.execute("SELECT * FROM form_fields ORDER BY marketplace, label"))


@router.delete("/fields/{field_id}")
def delete_field(field_id: int):
    with get_conn() as c:
        c.execute("DELETE FROM form_fields WHERE id=?", (field_id,))
    return {"ok": True}


class DoneIn(BaseModel):
    product_id: int
    account_id: int
    listing_ref: str | None = None


@router.post("/done")
def mark_done(d: DoneIn):
    """Called after the seller submits the form on the marketplace."""
    with get_conn() as c:
        c.execute("INSERT INTO listings (product_id, account_id, status, listing_ref, last_exported_at) "
                  "VALUES (?,?,'exported',?,datetime('now')) ON CONFLICT(product_id, account_id) DO UPDATE SET "
                  "status=CASE WHEN status IN ('draft','rejected') THEN 'exported' ELSE status END, "
                  "listing_ref=COALESCE(excluded.listing_ref, listing_ref), last_exported_at=datetime('now')",
                  (d.product_id, d.account_id, d.listing_ref or None))
    return {"ok": True}


MAX_IMAGE = 15 * 1024 * 1024


@router.get("/image")
def image(url: str):
    """Fetch a product image for upload into a seller panel (the extension can't read arbitrary sites)."""
    from .media import media_path
    local = media_path(url)
    if local:
        ctype = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}[local.suffix]
        return Response(local.read_bytes(), media_type=ctype)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, "Only http(s) image URLs are supported")
    try:
        r = requests.get(url, timeout=30, stream=True, headers={"User-Agent": "SellerDesk/1.0"})
        r.raise_for_status()
        ctype = r.headers.get("content-type", "").split(";")[0]
        if not ctype.startswith("image/"):
            raise HTTPException(400, f"Not an image ({ctype or 'unknown type'})")
        data = r.raw.read(MAX_IMAGE + 1, decode_content=True)
    except requests.RequestException as e:
        raise HTTPException(502, f"Could not download image: {e}")
    if len(data) > MAX_IMAGE:
        raise HTTPException(400, "Image is larger than 15 MB")
    return Response(data, media_type=ctype)


@router.get("/download")
def download_extension():
    if not EXT_DIR.exists():
        raise HTTPException(404, "Extension folder not found")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in EXT_DIR.rglob("*"):
            if f.is_file() and not f.name.startswith("."):
                z.write(f, Path("seller-desk-extension") / f.relative_to(EXT_DIR))
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": "attachment; filename=seller-desk-extension.zip"})
