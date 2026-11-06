"""Bring marketplace inventory into Seller Desk and link it to the product master.

Sources: API pulls (Amazon report, Flipkart search) or files downloaded from the seller panels
(Amazon "All Listings Report", Flipkart "My Listings" export, Meesho Inventory download).
"""

import io
import json
import re

import pandas as pd

from ..db import dump, get_conn, row_to_dict, rows_to_dicts
from ..fields import normalise
from .marketplaces import _num, parse_amazon_listings_report

FILE_COLUMNS = {
    "remote_sku": ["seller-sku", "seller sku", "sku", "seller sku id", "sku id", "sku code", "style id",
                   "product id / style id", "supplier sku", "your sku"],
    "listing_ref": ["asin1", "asin", "fsn", "flipkart serial number", "catalog id", "product id", "meesho pid",
                    "listing ref"],
    "listing_id": ["listing-id", "listing id", "flipkart listing id"],
    "title": ["item-name", "item name", "product name", "product title", "title", "catalog name"],
    "price": ["price", "your selling price", "selling price", "meesho price", "current price", "your price"],
    "mrp": ["mrp", "maximum retail price"],
    "stock": ["quantity", "stock", "inventory", "current stock", "system stock count", "available stock",
              "stock count"],
    "status": ["status", "listing status", "active status", "catalog status"],
    "image": ["image-url", "image url", "image", "main image"],
}

# Map marketplace statuses onto our listing statuses
STATUS_MAP = {"active": "live", "buyable": "live", "live": "live", "inactive": "inactive", "incomplete": "rejected",
              "blocked": "inactive", "inactivated_by_flipkart": "inactive", "ready_for_activation": "exported",
              "paused": "inactive", "out of stock": "live"}


def _lookup():
    lk = {}
    for field, names in FILE_COLUMNS.items():
        for n in names:
            lk.setdefault(normalise(n), field)
    return lk


def parse_inventory_file(filename: str, data: bytes) -> list[dict]:
    name = filename.lower()
    if name.endswith(".txt") or name.endswith(".tsv"):
        text = data[:4000].decode("utf-8", errors="ignore")
        if "seller-sku" in text:
            return parse_amazon_listings_report(data)
        df = pd.read_csv(io.BytesIO(data), sep="\t", dtype=str, keep_default_na=False)
        frames = [df]
    elif name.endswith(".csv"):
        frames = [pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)]
    else:
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=str, keep_default_na=False, header=None)
        frames = []
        lk = _lookup()
        for _, raw in sheets.items():
            # find the header row (panel exports sometimes have a title row on top)
            best_row, best_hits = 0, 0
            for i in range(min(10, len(raw))):
                hits = sum(1 for v in raw.iloc[i].tolist() if normalise(v) in lk)
                if hits > best_hits:
                    best_row, best_hits = i, hits
            if best_hits >= 2:
                df = raw.iloc[best_row + 1:].copy()
                df.columns = [str(c) for c in raw.iloc[best_row].tolist()]
                frames.append(df)
        if not frames:
            raise ValueError("Couldn't find a SKU / price / stock header in this file")
    lk = _lookup()
    out = []
    for df in frames:
        colmap = {}
        for c in df.columns:
            f = lk.get(normalise(c))
            if f and f not in colmap.values():
                colmap[c] = f
        if "remote_sku" not in colmap.values():
            continue
        for rec in df.to_dict("records"):
            row = {f: str(rec.get(c, "")).strip() for c, f in colmap.items()}
            if not row.get("remote_sku"):
                continue
            stock = _num(row.get("stock"))
            out.append({
                "remote_sku": row["remote_sku"], "listing_ref": row.get("listing_ref") or None,
                "listing_id": row.get("listing_id") or None, "title": row.get("title") or None,
                "price": _num(row.get("price")), "mrp": _num(row.get("mrp")),
                "stock": int(stock) if stock is not None else None, "status": row.get("status") or None,
                "image": row.get("image") or None, "raw": {k: str(v) for k, v in rec.items()},
            })
    if not out:
        raise ValueError("No rows with a SKU column were found in this file")
    return out


def store_remote_listings(account_id: int, rows: list[dict], source: str) -> dict:
    with get_conn() as c:
        for r in rows:
            c.execute(
                "INSERT INTO remote_listings (account_id, remote_sku, listing_ref, listing_id, title, price, mrp, stock, "
                "status, image, raw, source, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now')) "
                "ON CONFLICT(account_id, remote_sku) DO UPDATE SET listing_ref=COALESCE(excluded.listing_ref, listing_ref), "
                "listing_id=COALESCE(excluded.listing_id, listing_id), title=COALESCE(excluded.title, title), "
                "price=COALESCE(excluded.price, price), mrp=COALESCE(excluded.mrp, mrp), "
                "stock=COALESCE(excluded.stock, stock), status=COALESCE(excluded.status, status), "
                "image=COALESCE(excluded.image, image), raw=excluded.raw, source=excluded.source, "
                "synced_at=excluded.synced_at",
                (account_id, r["remote_sku"], r.get("listing_ref"), r.get("listing_id"), r.get("title"), r.get("price"),
                 r.get("mrp"), r.get("stock"), r.get("status"), r.get("image"), dump(r.get("raw") or {}), source))
    matched = auto_match(account_id)
    return {"rows": len(rows), "matched": matched}


def _strip_prefix(sku: str, prefix: str) -> str:
    return sku[len(prefix):] if prefix and sku.startswith(prefix) else sku


def auto_match(account_id: int) -> int:
    """Link unmatched remote listings to master products: exact SKU, then SKU without the account prefix,
    then case/punctuation-insensitive."""
    with get_conn() as c:
        acc = row_to_dict(c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())
        products = rows_to_dicts(c.execute("SELECT id, sku FROM products"))
        by_sku = {p["sku"]: p["id"] for p in products}
        by_norm = {re.sub(r"[^a-z0-9]", "", p["sku"].lower()): p["id"] for p in products}
        pending = rows_to_dicts(c.execute(
            "SELECT * FROM remote_listings WHERE account_id=? AND product_id IS NULL", (account_id,)))
        n = 0
        for r in pending:
            sku = r["remote_sku"]
            pid, how = by_sku.get(sku), "exact"
            if not pid:
                pid, how = by_sku.get(_strip_prefix(sku, acc.get("sku_prefix") or "")), "prefix"
            if not pid:
                pid, how = by_norm.get(re.sub(r"[^a-z0-9]", "", _strip_prefix(sku, acc.get("sku_prefix") or "").lower())), "fuzzy"
            if pid:
                _link(c, r, pid, how)
                n += 1
        # refresh live data on already-linked listings
        for r in rows_to_dicts(c.execute(
                "SELECT * FROM remote_listings WHERE account_id=? AND product_id IS NOT NULL", (account_id,))):
            _sync_listing(c, r, r["product_id"])
    return n


def _sync_listing(c, r: dict, product_id: int):
    status = STATUS_MAP.get(str(r.get("status") or "").lower().strip(), None)
    c.execute(
        "INSERT INTO listings (product_id, account_id, marketplace_sku, listing_ref, price, mrp, stock_qty, status) "
        "VALUES (?,?,?,?,?,?,?,COALESCE(?, 'live')) ON CONFLICT(product_id, account_id) DO UPDATE SET "
        "marketplace_sku=excluded.marketplace_sku, listing_ref=COALESCE(excluded.listing_ref, listing_ref), "
        "price=COALESCE(excluded.price, price), mrp=COALESCE(excluded.mrp, mrp), "
        "stock_qty=COALESCE(excluded.stock_qty, stock_qty), status=COALESCE(?, status)",
        (product_id, r["account_id"], r["remote_sku"], r.get("listing_ref"), r.get("price"), r.get("mrp"),
         r.get("stock"), status, status))


def _link(c, r: dict, product_id: int, how: str):
    c.execute("UPDATE remote_listings SET product_id=?, match_method=? WHERE id=?", (product_id, how, r["id"]))
    _sync_listing(c, r, product_id)


def link(remote_id: int, product_id: int):
    with get_conn() as c:
        r = row_to_dict(c.execute("SELECT * FROM remote_listings WHERE id=?", (remote_id,)).fetchone())
        if not r:
            raise ValueError("Listing not found")
        _link(c, r, product_id, "manual")


def unlink(remote_id: int):
    with get_conn() as c:
        r = row_to_dict(c.execute("SELECT * FROM remote_listings WHERE id=?", (remote_id,)).fetchone())
        if r and r["product_id"]:
            c.execute("DELETE FROM listings WHERE product_id=? AND account_id=? AND marketplace_sku=?",
                      (r["product_id"], r["account_id"], r["remote_sku"]))
            c.execute("UPDATE remote_listings SET product_id=NULL, match_method=NULL WHERE id=?", (remote_id,))


def create_product_from(remote_id: int, sku: str | None = None) -> int:
    """Turn an unmatched marketplace listing into a master product (title → name, price → base price)."""
    with get_conn() as c:
        r = row_to_dict(c.execute("SELECT r.*, a.sku_prefix FROM remote_listings r JOIN accounts a "
                                  "ON a.id=r.account_id WHERE r.id=?", (remote_id,)).fetchone())
        if not r:
            raise ValueError("Listing not found")
        new_sku = sku or _strip_prefix(r["remote_sku"], r.get("sku_prefix") or "")
        if c.execute("SELECT 1 FROM products WHERE sku=?", (new_sku,)).fetchone():
            raise ValueError(f"SKU {new_sku} already exists — link to it instead")
        guess = guess_attributes(r.get("title") or "")
        cur = c.execute(
            "INSERT INTO products (sku, name, selling_price, mrp, stock_qty, images, fabric, color, saree_type) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (new_sku, (r.get("title") or "")[:120] or None, r.get("price"), r.get("mrp"), r.get("stock"),
             json.dumps([r["image"]] if r.get("image") else []), guess.get("fabric"), guess.get("color"),
             guess.get("saree_type")))
        pid = cur.lastrowid
        _link(c, r, pid, "created")
        return pid


_FABRICS = ["kanjivaram silk", "banarasi silk", "tussar silk", "soft silk", "art silk", "pure silk", "cotton silk",
            "silk blend", "georgette", "chiffon", "organza", "linen", "cotton", "crepe", "satin", "net", "viscose", "silk"]
_TYPES = ["kanjivaram", "banarasi", "chanderi", "paithani", "patola", "bandhani", "leheriya", "pochampally",
          "kota doria", "tant", "mysore silk"]
_COLORS = ["maroon", "red", "pink", "magenta", "rani", "orange", "peach", "yellow", "mustard", "gold", "green",
           "olive", "teal", "turquoise", "sky blue", "navy blue", "blue", "purple", "violet", "lavender", "wine",
           "brown", "beige", "cream", "off white", "white", "grey", "silver", "black", "multicolor"]


def guess_attributes(title: str) -> dict:
    t = title.lower()
    out = {}
    for group, key in ((_FABRICS, "fabric"), (_TYPES, "saree_type"), (_COLORS, "color")):
        for v in group:
            if re.search(rf"\b{re.escape(v)}\b", t):
                out[key] = v.title()
                break
    return out
