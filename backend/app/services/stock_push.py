"""Automatic stock push to the seller portals.

Master stock lives in Seller Desk. The extension in each firm's Chrome profile opens the account's taught inventory
page in a background tab, finds each saree's row, and where the portal's number differs it types the master number
and presses the row's Save button. A run starts at the scheduled times, after an order sync changed stock, or when
the user presses "Push stock now". Only listed sarees (live / exported) with a known master stock are touched, and
negative stock is sent as 0."""
import re
from datetime import datetime, timedelta

from ..db import get_conn, row_to_dict, rows_to_dicts
from .order_sync import LAST_POLL, check_page_url
from .secrets import get_setting, set_setting

DEFAULT_TIMES = "09:00,13:00,18:00"
STALE_RUN_MIN = 25
STATES = ("ok", "empty", "signed_out", "error")


def enabled() -> bool:
    return get_setting("stock_push_enabled", "1") == "1"


def get_times() -> list[str]:
    return [t for t in (get_setting("stock_push_times") or DEFAULT_TIMES).split(",") if t]


def configure(times: list[str] | None, on: bool | None) -> dict:
    if times is not None:
        clean = sorted({t.strip() for t in times if t.strip()})
        for t in clean:
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
                raise ValueError(f"'{t}' is not a time like 09:00")
        set_setting("stock_push_times", ",".join(clean))
    if on is not None:
        set_setting("stock_push_enabled", "1" if on else "0")
    return {"times": get_times(), "enabled": enabled()}


def _slot(now: datetime) -> str | None:
    times = get_times()
    if not times:
        return None
    today = [t for t in times if t <= now.strftime("%H:%M")]
    return f"{now:%Y-%m-%d} {today[-1]}" if today else f"{now - timedelta(days=1):%Y-%m-%d} {times[-1]}"


def add_page(account_id: int, url: str, label: str | None) -> int:
    with get_conn() as c:
        check_page_url(c, account_id, url)
        c.execute("INSERT INTO sync_pages (account_id, url, label, kind) VALUES (?,?,?, 'stock') "
                  "ON CONFLICT(account_id, url) DO UPDATE SET label=excluded.label, kind='stock'", (account_id, url, label))
        return c.execute("SELECT id FROM sync_pages WHERE account_id=? AND url=?", (account_id, url)).fetchone()[0]


def _pages(c, firm_id: int) -> list[dict]:
    return rows_to_dicts(c.execute(
        "SELECT p.id AS page_id, p.account_id, p.url, p.label, a.marketplace, a.name AS account_name FROM sync_pages p "
        "JOIN accounts a ON a.id=p.account_id WHERE a.firm_id=? AND a.active=1 AND p.kind='stock' ORDER BY p.id", (firm_id,)))


def claim(firm_id: int, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    with get_conn() as c:
        pages = _pages(c, firm_id)
        if not pages or not enabled():
            return {"run_id": None}
        c.execute("UPDATE stock_runs SET status='done', finished_at=datetime('now'), summary='Timed out: the extension did not "
                  "finish' WHERE firm_id=? AND status='running' AND started_at < datetime('now', ?)",
                  (firm_id, f"-{STALE_RUN_MIN} minutes"))
        if c.execute("SELECT 1 FROM stock_runs WHERE firm_id=? AND status='running'", (firm_id,)).fetchone():
            return {"run_id": None}
        run = c.execute("SELECT id FROM stock_runs WHERE firm_id=? AND status='requested' ORDER BY id LIMIT 1", (firm_id,)).fetchone()
        run_id = run["id"] if run else None
        if run_id is None:
            slot = _slot(now)
            if not slot or c.execute("SELECT 1 FROM stock_runs WHERE firm_id=? AND slot=?", (firm_id, slot)).fetchone():
                return {"run_id": None}
            run_id = c.execute("INSERT INTO stock_runs (firm_id, trigger, status, slot) VALUES (?, 'schedule', 'running', ?)",
                               (firm_id, slot)).lastrowid
        c.execute("UPDATE stock_runs SET status='running', started_at=datetime('now') WHERE id=?", (run_id,))
    return {"run_id": run_id, "pages": pages}


def _request(c, firm_id: int, trigger: str) -> bool:
    if c.execute("SELECT 1 FROM stock_runs WHERE firm_id=? AND status IN ('requested','running')", (firm_id,)).fetchone():
        return False
    c.execute("INSERT INTO stock_runs (firm_id, trigger, status) VALUES (?, ?, 'requested')", (firm_id, trigger))
    return True


def request_now() -> dict:
    queued = []
    with get_conn() as c:
        for f in rows_to_dicts(c.execute(
                "SELECT DISTINCT f.id, f.name FROM firms f JOIN accounts a ON a.firm_id=f.id "
                "JOIN sync_pages p ON p.account_id=a.id AND p.kind='stock'")):
            if _request(c, f["id"], "manual"):
                queued.append(f["name"])
    return {"queued": queued}


def mismatches(c, firm_id: int | None = None) -> int:
    sql = ("SELECT COUNT(*) FROM listings l JOIN products p ON p.id=l.product_id JOIN accounts a ON a.id=l.account_id "
           "WHERE l.status IN ('live','exported') AND p.stock_qty IS NOT NULL AND (l.stock_qty IS NULL OR l.stock_qty != MAX(0, p.stock_qty))")
    args: tuple = ()
    if firm_id:
        sql += " AND a.firm_id=?"
        args = (firm_id,)
    return c.execute(sql, args).fetchone()[0]


def request_after_orders(firm_id: int) -> bool:
    """An order sync changed master stock: push it out if a taught portal is out of step."""
    if not enabled():
        return False
    with get_conn() as c:
        if not c.execute("SELECT 1 FROM sync_pages p JOIN accounts a ON a.id=p.account_id WHERE a.firm_id=? AND p.kind='stock'",
                         (firm_id,)).fetchone():
            return False
        if not mismatches(c, firm_id):
            return False
        return _request(c, firm_id, "after_orders")


def save_result(run_id: int, page_id: int, state: str, found: int, updated: int, failed: list[str],
                not_on_page: int, error: str | None) -> dict:
    if state not in STATES:
        raise ValueError(f"state must be one of {', '.join(STATES)}")
    with get_conn() as c:
        run = row_to_dict(c.execute("SELECT * FROM stock_runs WHERE id=?", (run_id,)).fetchone())
        if not run or run["status"] != "running":
            raise LookupError("This stock run is not active")
        page = row_to_dict(c.execute("SELECT p.*, a.firm_id FROM sync_pages p JOIN accounts a ON a.id=p.account_id "
                                     "WHERE p.id=? AND p.kind='stock'", (page_id,)).fetchone())
        if not page or page["firm_id"] != run["firm_id"]:
            raise ValueError("That page does not belong to this run")
        note = error or "; ".join(filter(None, [
            f"{len(failed)} failed: " + ", ".join(failed[:3]) if failed else "",
            f"{not_on_page} listed SKU(s) not on this page" if not_on_page else ""]))
        c.execute("UPDATE sync_pages SET last_run_at=datetime('now'), last_state=?, last_rows=?, last_error=? WHERE id=?",
                  (state, updated, note[:300] or None, page_id))
    return {"state": state, "updated": updated}


def finish(run_id: int) -> dict:
    with get_conn() as c:
        run = row_to_dict(c.execute("SELECT * FROM stock_runs WHERE id=?", (run_id,)).fetchone())
        if not run:
            raise LookupError("Run not found")
        pages = rows_to_dicts(c.execute(
            "SELECT p.last_state, p.last_rows FROM sync_pages p JOIN accounts a ON a.id=p.account_id "
            "WHERE a.firm_id=? AND p.kind='stock' AND p.last_run_at >= ?", (run["firm_id"], run["started_at"] or "")))
        ok = [p for p in pages if p["last_state"] == "ok"]
        summary = f"{len(ok)} of {len(pages)} pages read, {sum(p['last_rows'] or 0 for p in ok)} stock figures changed"
        c.execute("UPDATE stock_runs SET status='done', finished_at=datetime('now'), summary=? WHERE id=?", (summary, run_id))
    return {"summary": summary}


def status() -> dict:
    now = datetime.now()
    with get_conn() as c:
        firms = rows_to_dicts(c.execute(
            "SELECT f.id, f.name, COUNT(p.id) AS pages FROM firms f LEFT JOIN accounts a ON a.firm_id=f.id "
            "LEFT JOIN sync_pages p ON p.account_id=a.id AND p.kind='stock' GROUP BY f.id ORDER BY f.name"))
        for f in firms:
            f["last_run"] = row_to_dict(c.execute(
                "SELECT trigger, status, created_at, finished_at, summary FROM stock_runs WHERE firm_id=? ORDER BY id DESC LIMIT 1",
                (f["id"],)).fetchone())
            seen = LAST_POLL.get(f["id"])
            f["extension_seen_seconds_ago"] = int((now - seen).total_seconds()) if seen else None
            f["out_of_step"] = mismatches(c, f["id"])
        pages = rows_to_dicts(c.execute(
            "SELECT p.*, a.name AS account_name, a.marketplace, f.name AS firm FROM sync_pages p JOIN accounts a ON a.id=p.account_id "
            "JOIN firms f ON f.id=a.firm_id WHERE p.kind='stock' ORDER BY f.name, a.marketplace, p.id"))
    return {"enabled": enabled(), "times": get_times(), "firms": firms, "pages": pages}
