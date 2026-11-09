from typing import Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..db import get_conn, row_to_dict, rows_to_dicts
from ..fields import PRODUCT_FIELD_KEYS, PRODUCT_FIELDS, all_sources
from ..services import content as content_svc
from ..services import importer

router = APIRouter(prefix="/api", tags=["products"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/fields")
def fields():
    return {"product_fields": PRODUCT_FIELDS,
            "sources": [{k: v for k, v in s.items() if k != "synonyms"} for s in all_sources()],
            "marketplace_rules": content_svc.MARKETPLACE_RULES}


def _get(c, product_id):
    p = row_to_dict(c.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone())
    if not p:
        raise HTTPException(404, "Product not found")
    return p


def _clean(data: dict) -> dict:
    out = {k: v for k, v in data.items() if k in PRODUCT_FIELD_KEYS}
    if "images" in out and not isinstance(out["images"], list):
        out["images"] = [u.strip() for u in str(out["images"] or "").splitlines() if u.strip()]
    for k, v in list(out.items()):
        if isinstance(v, str):
            out[k] = v.strip() or None
    return out


def upsert(c, data: dict, product_id: int | None = None) -> int:
    data = importer.to_db_values(_clean(data))
    if not data.get("sku") and not product_id:
        raise HTTPException(400, "SKU is required")
    if product_id is None:
        existing = c.execute("SELECT id FROM products WHERE sku=?", (data["sku"],)).fetchone()
        product_id = existing["id"] if existing else None
    if product_id:
        if not data:
            return product_id
        sets = ", ".join(f"{k}=?" for k in data)
        c.execute(f"UPDATE products SET {sets}, updated_at=datetime('now') WHERE id=?", (*data.values(), product_id))
        return product_id
    cols = ", ".join(data)
    cur = c.execute(f"INSERT INTO products ({cols}) VALUES ({', '.join('?' * len(data))})", tuple(data.values()))
    return cur.lastrowid


@router.get("/products")
def list_products(q: str = "", limit: int = 500):
    with get_conn() as c:
        like = f"%{q}%"
        rows = c.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM listings l WHERE l.product_id=p.id) AS listing_count "
            "FROM products p WHERE ?='' OR sku LIKE ? OR name LIKE ? OR fabric LIKE ? OR color LIKE ? "
            "OR saree_type LIKE ? ORDER BY p.updated_at DESC LIMIT ?",
            (q, like, like, like, like, like, limit))
        return rows_to_dicts(rows)


@router.post("/products")
def create_product(data: dict):
    with get_conn() as c:
        if c.execute("SELECT 1 FROM products WHERE sku=?", ((data.get("sku") or "").strip(),)).fetchone():
            raise HTTPException(400, "A product with this SKU already exists")
        pid = upsert(c, data)
        return _get(c, pid)


@router.get("/products/import-template")
def import_template():
    return Response(importer.import_template_bytes(), media_type=XLSX,
                    headers={"Content-Disposition": "attachment; filename=saree_products_import.xlsx"})


@router.get("/products/export")
def export_products():
    with get_conn() as c:
        products = rows_to_dicts(c.execute("SELECT * FROM products ORDER BY sku"))
    return Response(importer.import_template_bytes(products), media_type=XLSX,
                    headers={"Content-Disposition": "attachment; filename=saree_products.xlsx"})


@router.post("/products/import")
async def import_products(file: UploadFile = File(...)):
    rows, errors = importer.parse_upload(file.filename or "upload.xlsx", await file.read())
    created = updated = 0
    with get_conn() as c:
        for r in rows:
            exists = c.execute("SELECT 1 FROM products WHERE sku=?", (r["sku"],)).fetchone()
            if not r.get("images"):
                r.pop("images", None)   # don't wipe images when the sheet has none
            upsert(c, r)
            updated += bool(exists)
            created += not exists
    return {"created": created, "updated": updated, "messages": errors}


@router.get("/products/{product_id}")
def get_product(product_id: int):
    with get_conn() as c:
        p = _get(c, product_id)
        p["listings"] = rows_to_dicts(c.execute(
            "SELECT l.*, a.name AS account_name, a.marketplace FROM listings l JOIN accounts a ON a.id=l.account_id "
            "WHERE l.product_id=?", (product_id,)))
        return p


@router.put("/products/{product_id}")
def update_product(product_id: int, data: dict):
    with get_conn() as c:
        _get(c, product_id)
        sku = (data.get("sku") or "").strip()
        clash = c.execute("SELECT id FROM products WHERE sku=? AND id<>?", (sku, product_id)).fetchone()
        if clash:
            raise HTTPException(400, "Another product already uses this SKU")
        upsert(c, data, product_id)
        return _get(c, product_id)


def _listed_on(c, product_id: int) -> list[str]:
    return [f"{r['name']} ({r['status']})" for r in c.execute(
        "SELECT a.name, l.status FROM listings l JOIN accounts a ON a.id=l.account_id "
        "WHERE l.product_id=? AND l.status IN ('exported','live','inactive')", (product_id,))]


@router.delete("/products/{product_id}")
def delete_product(product_id: int, force: bool = False):
    with get_conn() as c:
        listed = _listed_on(c, product_id)
        if listed and not force:
            raise HTTPException(409, f"Still listed on {', '.join(listed)}. Deleting here does not remove it from the marketplace.")
        c.execute("DELETE FROM products WHERE id=?", (product_id,))
    return {"ok": True}


class BulkDelete(BaseModel):
    product_ids: list[int] = Field(min_length=1, max_length=500)
    force: bool = False


@router.post("/products/delete")
def delete_products(b: BulkDelete):
    """Delete several sarees. Ones that are exported or live on an account are held back unless force is set."""
    deleted, held = 0, []
    with get_conn() as c:
        for pid in b.product_ids:
            row = c.execute("SELECT sku FROM products WHERE id=?", (pid,)).fetchone()
            if not row:
                continue
            listed = _listed_on(c, pid)
            if listed and not b.force:
                held.append({"id": pid, "sku": row["sku"], "listed_on": listed})
                continue
            c.execute("DELETE FROM products WHERE id=?", (pid,))
            deleted += 1
    return {"deleted": deleted, "held_back": held}


@router.post("/products/{product_id}/duplicate")
def duplicate_product(product_id: int, new_sku: str):
    with get_conn() as c:
        p = _get(c, product_id)
        if c.execute("SELECT 1 FROM products WHERE sku=?", (new_sku,)).fetchone():
            raise HTTPException(400, "SKU already exists")
        p = {k: v for k, v in p.items() if k in PRODUCT_FIELD_KEYS}
        p["sku"] = new_sku
        return _get(c, upsert(c, p))


@router.post("/content/preview")
def preview_content(data: dict, marketplace: Literal["amazon", "flipkart", "meesho"] = "amazon",
                    brand: str | None = None):
    """Generate content for an unsaved form, so the editor can show it live."""
    return content_svc.generate_all(_clean(data), marketplace, brand=brand)


@router.get("/products/{product_id}/content")
def product_content(product_id: int):
    with get_conn() as c:
        p = _get(c, product_id)
    return {m: content_svc.generate_all(p, m) for m in ("amazon", "flipkart", "meesho")}
