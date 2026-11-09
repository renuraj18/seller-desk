"""Order & shipment tracker: one master list of orders for every account, kept as an Excel file too.

Orders arrive from report files downloaded from the seller panels or from the browser extension reading the
orders pages. Statuses are normalised to: pending, shipped, delivered, cancelled, courier_return (RTO),
customer_return.
"""

import io
import re
from datetime import date, datetime

import openpyxl
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ..db import DATA_DIR, dump, get_conn, rows_to_dicts
from ..fields import normalise
from . import stock
from .marketplaces import _num

MASTER_PATH = DATA_DIR / "orders_master.xlsx"

STATUS_LABEL = {
    "pending": "Pending", "shipped": "Shipped", "delivered": "Delivered", "cancelled": "Cancelled",
    "courier_return": "Courier return (RTO)", "customer_return": "Customer return", "other": "Other",
}
STATUS_RANK = {"pending": 0, "other": 0, "shipped": 1, "delivered": 2, "cancelled": 3, "courier_return": 3,
               "customer_return": 3}


def normalise_status(text) -> str | None:
    t = str(text or "").lower()
    if not t.strip():
        return None
    if re.search(r"\brto\b|return to origin|courier return|undeliver|returned to seller|lost in transit", t):
        return "courier_return"
    if re.search(r"customer return|\breturn|replacement|refund", t):
        return "customer_return"
    if "cancel" in t:
        return "cancelled"
    if re.search(r"ready to ship|unshipped|not shipped|\brts\b|pending|awaiting|to be shipped|yet to ship", t):
        return "pending"
    if re.search(r"ship|transit|out for delivery|dispatch|handed over|picked up|manifest", t):
        return "shipped"
    if "deliver" in t:
        return "delivered"
    if re.search(r"pending|new|ready to ship|\brts\b|approved|unshipped|accepted|on hold|label|packed|confirm", t):
        return "pending"
    return "other"


def parse_date(v) -> str | None:
    if v is None or str(v).strip() in ("", "nan", "NaT"):
        return None
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:$|[T\s])", s)
    if iso:  # year-first is unambiguous; day-first parsing would swap the month and day of 2026-11-02
        try:
            d = datetime(int(iso[1]), int(iso[2]), int(iso[3]))
            return d.strftime("%Y-%m-%d") if 2015 <= d.year <= 2100 else None
        except ValueError:
            return None
    for dayfirst in (True, False):
        try:
            d = pd.to_datetime(s, dayfirst=dayfirst, errors="raise")
            if 2015 <= d.year <= 2100:
                return d.strftime("%Y-%m-%d")
        except (ValueError, OverflowError, TypeError):
            continue
    return None


# ------------------------------------------------------------------ saving

def save_orders(account_id: int, rows: list[dict], source: str) -> dict:
    """Upsert orders. A later status only replaces an earlier one if it moves forward
    (pending → shipped → delivered / cancelled / return), so an old page can't undo a return."""
    created = updated = 0
    with get_conn() as c:
        for r in rows:
            oid = str(r.get("order_id") or "").strip()
            if not oid:
                continue
            sub = str(r.get("sub_order_id") or "").strip()
            status = r.get("status") or normalise_status(r.get("status_text"))
            existing = c.execute("SELECT * FROM orders WHERE account_id=? AND order_id=? AND sub_order_id=?",
                                 (account_id, oid, sub)).fetchone()
            if existing:
                ex = dict(existing)
                keep_status = ex["status"] and status and STATUS_RANK.get(status, 0) < STATUS_RANK.get(ex["status"], 0)
                new_status = ex["status"] if keep_status or not status else status
                c.execute(
                    "UPDATE orders SET status=?, status_text=COALESCE(?, status_text), order_date=COALESCE(order_date, ?), "
                    "sku=COALESCE(?, sku), qty=COALESCE(?, qty), sale_amount=COALESCE(?, sale_amount), "
                    "cancel_charges=COALESCE(?, cancel_charges), return_charges=COALESCE(?, return_charges), "
                    "awb=COALESCE(?, awb), updated_at=datetime('now') WHERE id=?",
                    (new_status, r.get("status_text"), r.get("order_date"), r.get("sku"), r.get("qty"),
                     r.get("sale_amount"), r.get("cancel_charges"), r.get("return_charges"), r.get("awb"), ex["id"]))
                updated += 1
            else:
                c.execute(
                    "INSERT INTO orders (account_id, order_id, sub_order_id, order_date, sku, qty, sale_amount, status, "
                    "status_text, cancel_charges, return_charges, awb, source, raw, updated_at, first_seen_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
                    (account_id, oid, sub, r.get("order_date"), r.get("sku"), r.get("qty") or 1, r.get("sale_amount"),
                     status or "pending", r.get("status_text"), r.get("cancel_charges"), r.get("return_charges"),
                     r.get("awb"), source, dump(r.get("raw") or {})))
                created += 1
    link_products()
    stock_moves = stock.reconcile_orders()
    master = write_master()
    return {"created": created, "updated": updated, "master_saved": master, "stock_moves": stock_moves}


def link_products():
    """Attach product_id by SKU (account SKU, then master SKU) so MRP and P&L can be worked out."""
    with get_conn() as c:
        pending = rows_to_dicts(c.execute(
            "SELECT o.id, o.sku, o.account_id, a.sku_prefix FROM orders o JOIN accounts a ON a.id=o.account_id "
            "WHERE o.product_id IS NULL AND o.sku IS NOT NULL"))
        for o in pending:
            hit = c.execute("SELECT product_id FROM listings WHERE account_id=? AND marketplace_sku=?",
                            (o["account_id"], o["sku"])).fetchone()
            if not hit:
                sku = o["sku"]
                pre = o.get("sku_prefix") or ""
                if pre and sku.startswith(pre):
                    sku = sku[len(pre):]
                hit = c.execute("SELECT id AS product_id FROM products WHERE sku=? OR sku=?", (o["sku"], sku)).fetchone()
            if hit:
                c.execute("UPDATE orders SET product_id=? WHERE id=?", (hit["product_id"], o["id"]))


# ------------------------------------------------------------------ report files

ORDER_COLUMNS = {
    "order_id": ["order id", "amazon-order-id", "order-id", "order no", "order number", "orderid"],
    "sub_order_id": ["sub order no", "sub order id", "suborder id", "sub order number", "order item id",
                     "order-item-id", "order item no"],
    "order_date": ["order date", "purchase-date", "purchase date", "order date & time", "ordered on", "created date",
                   "order date time", "order placed date", "dispatch date"],
    "sku": ["sku", "seller-sku", "sku id", "sku code", "seller sku", "seller sku id", "product sku"],
    "qty": ["quantity", "qty", "quantity-purchased", "quantity purchased", "units"],
    "sale_amount": ["item-price", "selling price", "invoice amount", "order value", "final sale amount",
                    "supplier listed price", "price"],
    "status_text": ["status", "order status", "order-status", "item-status", "live order status", "order state",
                    "return type", "shipment status", "current status"],
    "cancel_charges": ["cancellation charges", "cancellation fee", "cancellation penalty", "penalty",
                       "cancellation charge"],
    "return_charges": ["return shipping charge", "return charges", "reverse shipping charges", "rto charges",
                       "return shipping fee", "reverse shipping fee"],
    "awb": ["awb", "awb number", "awb no", "tracking id", "tracking number", "tracking-id"],
}


def _lookup():
    lk = {}
    for f, names in ORDER_COLUMNS.items():
        for n in names:
            lk.setdefault(normalise(n), f)
    return lk


def _frames(filename: str, data: bytes) -> list[pd.DataFrame]:
    name = filename.lower()
    if name.endswith((".txt", ".tsv")):
        return [pd.read_csv(io.BytesIO(data), sep="\t", dtype=str, keep_default_na=False, encoding_errors="replace")]
    if name.endswith(".csv"):
        raw = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False, header=None, encoding_errors="replace")
        sheets = {"csv": raw}
    else:
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=str, keep_default_na=False, header=None)
    lk = _lookup()
    out = []
    for raw in sheets.values():
        best_row, best_hits = 0, 0
        for i in range(min(12, len(raw))):
            hits = sum(1 for v in raw.iloc[i].tolist() if normalise(v) in lk)
            if hits > best_hits:
                best_row, best_hits = i, hits
        if best_hits >= 2:
            df = raw.iloc[best_row + 1:].copy()
            df.columns = [str(c) for c in raw.iloc[best_row].tolist()]
            out.append(df)
    return out


def parse_orders_file(filename: str, data: bytes, default_status: str | None = None) -> list[dict]:
    lk = _lookup()
    rows = []
    for df in _frames(filename, data):
        colmap = {}
        for c in df.columns:
            f = lk.get(normalise(c))
            if f and f not in colmap.values():
                colmap[c] = f
        if "order_id" not in colmap.values() and "sub_order_id" not in colmap.values():
            continue
        for rec in df.to_dict("records"):
            r = {f: str(rec.get(c, "")).strip() for c, f in colmap.items()}
            oid = r.get("order_id") or r.get("sub_order_id")
            if not oid or oid.lower() in ("nan", "order id"):
                continue
            # Meesho sub-order "123456789_1": order id is the part before the underscore
            if not r.get("order_id") and re.fullmatch(r"\d+_\d+", oid):
                r["order_id"] = oid.split("_")[0]
            elif not r.get("order_id"):
                r["order_id"] = oid
            st = r.get("status_text") or default_status
            qty = _num(r.get("qty"))
            rows.append({
                "order_id": r["order_id"], "sub_order_id": r.get("sub_order_id") or "",
                "order_date": parse_date(r.get("order_date")), "sku": r.get("sku") or None,
                "qty": int(qty) if qty else None, "sale_amount": _num(r.get("sale_amount")),
                "status_text": st or None, "status": normalise_status(st) if st else None,
                "cancel_charges": abs(_num(r.get("cancel_charges")) or 0) or None,
                "return_charges": abs(_num(r.get("return_charges")) or 0) or None,
                "awb": r.get("awb") or None, "raw": {k: str(v) for k, v in rec.items()},
            })
    if not rows:
        raise ValueError("No order ID column found. Upload an orders, returns or payments report from the seller panel.")
    return rows


# ------------------------------------------------------------------ master Excel

def all_orders(filters: dict | None = None) -> list[dict]:
    f = filters or {}
    sql = ("SELECT o.*, a.name AS account_name, a.marketplace, a.sku_prefix, fm.name AS firm_name, fm.id AS firm_id, "
           "p.sku AS product_sku, p.mrp AS product_mrp, p.cost_price, l.mrp AS listing_mrp "
           "FROM orders o JOIN accounts a ON a.id=o.account_id JOIN firms fm ON fm.id=a.firm_id "
           "LEFT JOIN products p ON p.id=o.product_id "
           "LEFT JOIN listings l ON l.product_id=o.product_id AND l.account_id=o.account_id WHERE 1=1")
    args: list = []
    for key, col in (("firm_id", "fm.id"), ("account_id", "a.id"), ("marketplace", "a.marketplace"), ("status", "o.status")):
        if f.get(key):
            sql += f" AND {col}=?"
            args.append(f[key])
    if f.get("date_from"):
        sql += " AND o.order_date>=?"
        args.append(f["date_from"])
    if f.get("date_to"):
        sql += " AND o.order_date<=?"
        args.append(f["date_to"])
    if f.get("q"):
        sql += " AND (o.order_id LIKE ? OR o.sub_order_id LIKE ? OR o.sku LIKE ? OR o.awb LIKE ?)"
        args += [f"%{f['q']}%"] * 4
    with get_conn() as c:
        rows = rows_to_dicts(c.execute(sql + " ORDER BY o.order_date DESC, o.id DESC", args))
    for r in rows:
        r["mrp"] = r.get("listing_mrp") or r.get("product_mrp")
        r.pop("raw", None)
    return rows


HEADERS = ["Order date", "Firm", "Platform", "Account", "Order ID", "Sub-order / item ID", "SKU", "Qty", "MRP",
           "Selling price", "Status", "Cancellation charges", "Return / RTO charges", "AWB / tracking", "Marketplace status",
           "Last updated"]


def master_bytes(filters: dict | None = None) -> bytes:
    rows = all_orders(filters)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Orders"
    head_fill = PatternFill("solid", fgColor="2A1A1D")
    fills = {"cancelled": "FDE7E5", "courier_return": "FFF1D6", "customer_return": "FCE9F3", "delivered": "E2F3E8",
             "shipped": "E8F0FE"}
    ws.append(HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
        cell.alignment = Alignment(vertical="center")
    for r in rows:
        ws.append([
            datetime.strptime(r["order_date"], "%Y-%m-%d").date() if r.get("order_date") else None,
            r["firm_name"], r["marketplace"].title(), r["account_name"], r["order_id"], r["sub_order_id"] or None,
            r["sku"], r["qty"], r["mrp"], r["sale_amount"], STATUS_LABEL.get(r["status"], r["status"]),
            r["cancel_charges"], r["return_charges"], r["awb"], r["status_text"], r["updated_at"],
        ])
        if r["status"] in fills:
            ws.cell(row=ws.max_row, column=11).fill = PatternFill("solid", fgColor=fills[r["status"]])
    widths = [12, 18, 10, 20, 22, 22, 18, 6, 10, 12, 20, 12, 12, 18, 22, 19]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2, min_col=1, max_col=1):
        row[0].number_format = "DD-MMM-YYYY"
    for col in (9, 10, 12, 13):
        for row in ws.iter_rows(min_row=2, min_col=col, max_col=col):
            row[0].number_format = "₹#,##0.00"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}{max(1, ws.max_row)}"

    # Summary: firm × platform × status counts and charges
    sm = wb.create_sheet("Summary")
    statuses = ["pending", "shipped", "delivered", "cancelled", "courier_return", "customer_return"]
    sm.append(["Firm", "Platform", "Orders", *[STATUS_LABEL[s] for s in statuses], "Cancellation charges",
               "Return / RTO charges", "Return rate %"])
    for cell in sm[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
    groups: dict = {}
    for r in rows:
        g = groups.setdefault((r["firm_name"], r["marketplace"].title()), {"n": 0, "cc": 0.0, "rc": 0.0, **{s: 0 for s in statuses}})
        g["n"] += 1
        g[r["status"]] = g.get(r["status"], 0) + 1
        g["cc"] += r["cancel_charges"] or 0
        g["rc"] += r["return_charges"] or 0
    for (firm, mp), g in sorted(groups.items()):
        returns = g["courier_return"] + g["customer_return"]
        sm.append([firm, mp, g["n"], *[g[s] for s in statuses], round(g["cc"], 2), round(g["rc"], 2),
                   round(100 * returns / g["n"], 1) if g["n"] else 0])
    for i in range(1, 13):
        sm.column_dimensions[get_column_letter(i)].width = 16
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def write_master() -> str:
    """Rewrite data/orders_master.xlsx. If it's open in Excel (locked on Windows), write a dated copy instead."""
    data = master_bytes()
    try:
        MASTER_PATH.write_bytes(data)
        return str(MASTER_PATH)
    except PermissionError:
        alt = MASTER_PATH.with_name(f"orders_master_{datetime.now():%Y%m%d_%H%M%S}.xlsx")
        alt.write_bytes(data)
        return str(alt)
