"""Daily order check: plain rules over the orders Seller Desk already holds. No AI, no browser; runs in a moment.

The report says what needs action today, and how fresh each account's data is, so numbers are never shown as
current when the last sync failed or the account was signed out."""
from datetime import date, datetime, timedelta

from ..db import get_conn, rows_to_dicts
from .orders import STATUS_LABEL, normalise_status

OVERDUE_DAYS = 2        # a pending order older than this has probably missed its dispatch date
STALE_HOURS = 26        # no successful sync for this long = data is out of date
RETURN_STATES = ("courier_return", "customer_return")


def _age_days(d: str | None, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(d)).days if d else None
    except ValueError:
        return None


def report(today: date | None = None) -> dict:
    today = today or date.today()
    now = datetime.now()
    out_accounts, attention = [], []
    with get_conn() as c:
        accounts = rows_to_dicts(c.execute(
            "SELECT a.id, a.name, a.marketplace, f.id AS firm_id, f.name AS firm FROM accounts a "
            "JOIN firms f ON f.id=a.firm_id WHERE a.active=1 ORDER BY f.name, a.marketplace, a.name"))
        for a in accounts:
            by = {r["status"] or "other": r["n"] for r in c.execute(
                "SELECT status, COUNT(*) n FROM orders WHERE account_id=? GROUP BY status", (a["id"],))}
            pend = rows_to_dicts(c.execute(
                "SELECT o.order_id, o.sub_order_id, o.sku, o.order_date, p.stock_qty FROM orders o "
                "LEFT JOIN products p ON p.id=o.product_id WHERE o.account_id=? AND o.status='pending' "
                "ORDER BY o.order_date", (a["id"],)))
            pages = rows_to_dicts(c.execute(
                "SELECT id, url, status, tab_label, label, last_run_at, last_state, last_rows, last_error FROM sync_pages "
                "WHERE account_id=? AND kind='orders' ORDER BY id", (a["id"],)))
            # An order still marked pending that the latest successful Pending-page read did not show has probably
            # shipped or been cancelled. Count it apart instead of reporting it as pending.
            pend_reads = [p["last_run_at"] for p in pages if p["last_state"] == "ok" and p["last_run_at"]
                          and normalise_status(p["status"] or p["tab_label"] or "") == "pending"]
            unconfirmed = []
            if pend_reads:
                since = (datetime.strptime(max(pend_reads), "%Y-%m-%d %H:%M:%S") - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
                seen = {(r["order_id"], r["sub_order_id"]) for r in c.execute(
                    "SELECT order_id, sub_order_id FROM orders WHERE account_id=? AND status='pending' AND updated_at>=?",
                    (a["id"], since))}
                unconfirmed = [p for p in pend if (p["order_id"], p["sub_order_id"]) not in seen]
                pend = [p for p in pend if (p["order_id"], p["sub_order_id"]) in seen]
            ages = [(_age_days(p["order_date"], today), p) for p in pend]
            overdue = [p for age, p in ages if age is not None and age > OVERDUE_DAYS]
            no_stock = [p for p in pend if p["stock_qty"] is not None and p["stock_qty"] <= 0]
            new_returns = c.execute(
                f"SELECT COUNT(*) FROM orders WHERE account_id=? AND status IN ({','.join('?' * len(RETURN_STATES))}) "
                "AND updated_at >= datetime('now','-1 day')", (a["id"], *RETURN_STATES)).fetchone()[0]
            ok_times = [p["last_run_at"] for p in pages if p["last_state"] == "ok" and p["last_run_at"]]
            last_ok = max(ok_times) if ok_times else None
            newest = c.execute("SELECT MAX(order_date) FROM orders WHERE account_id=?", (a["id"],)).fetchone()[0]

            acc = {**a, "orders_by_status": by, "pending": len(pend),
                   "oldest_pending_date": pend[0]["order_date"] if pend else None,
                   "oldest_pending_days": ages[0][0] if ages else None,
                   "pending_unconfirmed": len(unconfirmed), "pending_overdue": len(overdue), "pending_no_stock": len(no_stock),
                   "returns_updated_24h": new_returns, "newest_order_date": newest,
                   "last_sync_ok": last_ok, "sync_pages": pages}
            who = f"{a['name']} ({a['firm']})"
            if not pages:
                attention.append({"level": "info", "account": who, "marketplace": a["marketplace"],
                                  "text": "No order pages taught for daily sync (extension → Orders → Add to daily sync)."})
            for p in pages:
                if p["last_state"] == "signed_out":
                    attention.append({"level": "high", "account": who, "marketplace": a["marketplace"],
                                      "text": f"Signed out of the seller panel: sign in again in the {a['firm']} Chrome profile."})
                    break
            else:
                failed = [p for p in pages if p["last_state"] in ("error", "empty")]
                if failed:
                    attention.append({"level": "med", "account": who, "marketplace": a["marketplace"],
                                      "text": f"{len(failed)} order page(s) could not be read: {failed[0]['last_error'] or 'no orders found'}."})
            if pages and (not last_ok or datetime.strptime(last_ok, "%Y-%m-%d %H:%M:%S") < now - timedelta(hours=STALE_HOURS)) \
                    and not any(p["last_state"] == "signed_out" for p in pages):
                attention.append({"level": "med", "account": who, "marketplace": a["marketplace"],
                                  "text": "Order data is out of date (no successful sync in the last day)."})
            if unconfirmed:
                attention.append({"level": "med", "account": who, "marketplace": a["marketplace"],
                                  "text": f"{len(unconfirmed)} order(s) are marked pending in Seller Desk but were not on the latest "
                                          "Pending page: they have probably shipped or been cancelled. Teach the Shipped and "
                                          "Cancelled pages too, or import the report."})
            if overdue:
                attention.append({"level": "high", "account": who, "marketplace": a["marketplace"],
                                  "text": f"{len(overdue)} pending order(s) older than {OVERDUE_DAYS} days: dispatch them first "
                                          f"(oldest {acc['oldest_pending_date']})."})
            if no_stock:
                attention.append({"level": "high", "account": who, "marketplace": a["marketplace"],
                                  "text": f"{len(no_stock)} pending order(s) are for SKUs with no master stock: "
                                          + ", ".join(sorted({p['sku'] or p['order_id'] for p in no_stock})[:5]) + "."})
            if new_returns:
                attention.append({"level": "med", "account": who, "marketplace": a["marketplace"],
                                  "text": f"{new_returns} return/RTO order(s) changed in the last 24 hours."})
            out_accounts.append(acc)
        runs = rows_to_dicts(c.execute(
            "SELECT s.*, f.name AS firm FROM order_syncs s JOIN firms f ON f.id=s.firm_id "
            "WHERE s.id IN (SELECT MAX(id) FROM order_syncs GROUP BY firm_id) ORDER BY f.name"))
    order = {"high": 0, "med": 1, "info": 2}
    attention.sort(key=lambda x: order[x["level"]])
    return {"generated_at": now.isoformat(timespec="seconds"), "today": today.isoformat(),
            "status_labels": STATUS_LABEL, "accounts": out_accounts, "attention": attention, "latest_syncs": runs}
