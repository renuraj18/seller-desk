"""Master stock ledger. Every change to a saree's master stock is written to stock_moves with its reason.

Optionally (Inventory → "Take stock from orders") new orders take their quantity out of master stock and
cancelled / courier-returned orders put it back. Only orders first seen after the switch-on time count, so
history that is already reflected in your stock is never deducted twice."""
from ..db import get_conn, rows_to_dicts
from .secrets import get_setting, set_setting

# statuses whose units have left the shelf; cancelled and RTO come back (customer returns need a manual check)
DEDUCT = {"pending", "shipped", "delivered", "other", "customer_return"}
DEFAULT_LOW = 2


def low_stock_at() -> int:
    try:
        return max(0, int(get_setting("low_stock_at", str(DEFAULT_LOW))))
    except ValueError:
        return DEFAULT_LOW


def tracking_since() -> str | None:
    return get_setting("stock_from_orders_since") or None


def configure(from_orders: bool | None = None, low: int | None = None) -> dict:
    if low is not None:
        if low < 0 or low > 1000:
            raise ValueError("Low stock level must be between 0 and 1000")
        set_setting("low_stock_at", str(low))
    if from_orders is not None:
        if from_orders and not tracking_since():
            with get_conn() as c:
                set_setting("stock_from_orders_since", c.execute("SELECT datetime('now')").fetchone()[0])
        elif not from_orders:
            set_setting("stock_from_orders_since", "")
    return {"from_orders": bool(tracking_since()), "since": tracking_since(), "low_stock_at": low_stock_at()}


def adjust(c, product_id: int, *, delta: int | None = None, set_to: int | None = None, reason: str,
           note: str | None = None, account_id: int | None = None, order_ref: str | None = None,
           allow_negative: bool = False) -> int | None:
    """Change one product's master stock and log it. Returns the new stock, or None if nothing changed."""
    row = c.execute("SELECT stock_qty FROM products WHERE id=?", (product_id,)).fetchone()
    if not row:
        raise LookupError("Product not found")
    before = row["stock_qty"]
    if set_to is not None:
        after = max(0, int(set_to))
    else:
        after = (before or 0) + int(delta or 0)
        if not allow_negative:
            after = max(0, after)
    if after == before:
        return None
    c.execute("UPDATE products SET stock_qty=?, updated_at=datetime('now') WHERE id=?", (after, product_id))
    c.execute("INSERT INTO stock_moves (product_id, delta, qty_after, reason, note, account_id, order_ref) "
              "VALUES (?,?,?,?,?,?,?)", (product_id, after - (before or 0), after, reason, note, account_id, order_ref))
    return after


def reconcile_orders() -> int:
    """Bring master stock in line with the orders seen since tracking was switched on. Safe to repeat."""
    since = tracking_since()
    if not since:
        return 0
    moved = 0
    with get_conn() as c:
        rows = rows_to_dicts(c.execute(
            "SELECT o.id, o.product_id, o.account_id, o.order_id, o.qty, o.status, o.stock_effect FROM orders o "
            "JOIN products p ON p.id=o.product_id WHERE p.stock_qty IS NOT NULL AND "
            "(o.stock_effect IS NOT NULL OR o.first_seen_at >= ?)", (since,)))
        for o in rows:
            want = (o["qty"] or 1) if o["status"] in DEDUCT else 0
            have = o["stock_effect"] or 0
            if want != have:
                restock = have > want
                adjust(c, o["product_id"], delta=have - want, reason="order_restock" if restock else "order_sold",
                       note=f"{o['status']} order", account_id=o["account_id"], order_ref=o["order_id"], allow_negative=True)
                moved += 1
            if o["stock_effect"] != want:
                c.execute("UPDATE orders SET stock_effect=? WHERE id=?", (want, o["id"]))
    return moved


def release_order(c, order_row_id: int):
    """An order record is being deleted: give back any units it took."""
    o = c.execute("SELECT product_id, account_id, order_id, stock_effect FROM orders WHERE id=?", (order_row_id,)).fetchone()
    if o and o["product_id"] and o["stock_effect"]:
        adjust(c, o["product_id"], delta=o["stock_effect"], reason="order_deleted", account_id=o["account_id"],
               order_ref=o["order_id"], allow_negative=True)


def moves(product_id: int | None = None, limit: int = 100) -> list[dict]:
    sql = ("SELECT m.*, p.sku, a.name AS account_name FROM stock_moves m JOIN products p ON p.id=m.product_id "
           "LEFT JOIN accounts a ON a.id=m.account_id")
    args: list = []
    if product_id:
        sql += " WHERE m.product_id=?"
        args.append(product_id)
    with get_conn() as c:
        return rows_to_dicts(c.execute(sql + " ORDER BY m.id DESC LIMIT ?", (*args, min(limit, 500))))
