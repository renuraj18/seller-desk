from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from ..db import get_conn, rows_to_dicts
from ..services import orders as svc

router = APIRouter(tags=["orders"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _filters(firm_id=None, account_id=None, marketplace=None, status=None, date_from=None, date_to=None, q=None):
    return {k: v for k, v in dict(firm_id=firm_id, account_id=account_id, marketplace=marketplace, status=status,
                                   date_from=date_from, date_to=date_to, q=q).items() if v}


@router.get("/api/orders")
def list_orders(firm_id: int | None = None, account_id: int | None = None, marketplace: str | None = None,
                status: str | None = None, date_from: str | None = None, date_to: str | None = None,
                q: str | None = None, limit: int = 1000):
    rows = svc.all_orders(_filters(firm_id, account_id, marketplace, status, date_from, date_to, q))
    summary = {s: 0 for s in svc.STATUS_LABEL}
    charges = {"cancel": 0.0, "returns": 0.0}
    for r in rows:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
        charges["cancel"] += r["cancel_charges"] or 0
        charges["returns"] += r["return_charges"] or 0
    return {"total": len(rows), "summary": summary, "charges": charges, "orders": rows[:limit],
            "labels": svc.STATUS_LABEL, "master_path": str(svc.MASTER_PATH)}


@router.get("/api/orders/master.xlsx")
def master(firm_id: int | None = None, account_id: int | None = None, marketplace: str | None = None,
           status: str | None = None, date_from: str | None = None, date_to: str | None = None):
    data = svc.master_bytes(_filters(firm_id, account_id, marketplace, status, date_from, date_to))
    return Response(data, media_type=XLSX, headers={"Content-Disposition": "attachment; filename=orders_master.xlsx"})


@router.post("/api/accounts/{account_id}/orders-file")
async def import_orders(account_id: int, file: UploadFile = File(...), default_status: str = Form("")):
    with get_conn() as c:
        if not c.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,)).fetchone():
            raise HTTPException(404, "Account not found")
    try:
        rows = svc.parse_orders_file(file.filename or "orders.xlsx", await file.read(), default_status or None)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Could not read this file: {e}")
    res = svc.save_orders(account_id, rows, "file")
    return {"rows": len(rows), **res}


class OrderEdit(BaseModel):
    status: str | None = None
    cancel_charges: float | None = None
    return_charges: float | None = None
    awb: str | None = None


@router.put("/api/orders/{order_id}")
def edit_order(order_id: int, body: OrderEdit):
    if body.status and body.status not in svc.STATUS_LABEL:
        raise HTTPException(400, "Unknown status")
    with get_conn() as c:
        c.execute("UPDATE orders SET status=COALESCE(?, status), cancel_charges=?, return_charges=?, "
                  "awb=COALESCE(?, awb), updated_at=datetime('now') WHERE id=?",
                  (body.status, body.cancel_charges, body.return_charges, body.awb, order_id))
    svc.write_master()
    return {"ok": True}


@router.delete("/api/orders/{order_id}")
def delete_order(order_id: int):
    with get_conn() as c:
        c.execute("DELETE FROM orders WHERE id=?", (order_id,))
    svc.write_master()
    return {"ok": True}


# ---------------------------------------------------------------- from the extension

class SeenOrder(BaseModel):
    order_id: str
    sub_order_id: str | None = ""
    sku: str | None = None
    order_date: str | None = None
    status_text: str | None = None
    sale_amount: float | None = None
    awb: str | None = None


class SeenOrders(BaseModel):
    account_id: int
    page_status: str | None = None     # status to use when a row shows none (e.g. the "Cancelled" tab)
    rows: list[SeenOrder]


@router.post("/api/ext/orders-seen")
def orders_seen(body: SeenOrders):
    rows = []
    for r in body.rows:
        st = r.status_text or body.page_status
        rows.append({**r.model_dump(), "order_date": svc.parse_date(r.order_date),
                     "status_text": st, "status": svc.normalise_status(st) if st else None})
    res = svc.save_orders(body.account_id, rows, "extension")
    return {"rows": len(rows), **res}


@router.get("/api/ext/known-skus")
def known_skus(account_id: int):
    """SKUs the extension should look for in order rows on this account."""
    with get_conn() as c:
        acc = c.execute("SELECT sku_prefix FROM accounts WHERE id=?", (account_id,)).fetchone()
        pre = (acc["sku_prefix"] if acc else "") or ""
        rows = rows_to_dicts(c.execute(
            "SELECT p.sku, l.marketplace_sku FROM products p LEFT JOIN listings l ON l.product_id=p.id AND l.account_id=?",
            (account_id,)))
    out = set()
    for r in rows:
        out.add(r["marketplace_sku"] or f"{pre}{r['sku']}")
        out.add(r["sku"])
    return sorted(out)
