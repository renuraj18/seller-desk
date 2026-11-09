"""Scheduling and bookkeeping for the extension's automatic order sync.

The extension in each firm's Chrome profile asks Seller Desk "is there work for my firm?" every minute (claim).
Seller Desk answers with the taught order pages when a scheduled time has passed or the user pressed Sync now.
The extension opens each page in a background tab, reads the order rows and posts them back (result), then
reports it is finished."""
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

from ..db import get_conn, row_to_dict, rows_to_dicts
from . import orders as orders_svc
from .live_panel import PANEL_HOST
from .secrets import get_setting, set_setting

DEFAULT_TIMES = "08:30,12:30,17:30"
STALE_RUN_MIN = 20
LAST_POLL: dict[int, datetime] = {}     # firm id -> when its extension last asked for work (not stored)
STATES = ("ok", "empty", "signed_out", "error")


def get_times() -> list[str]:
    return [t for t in (get_setting("order_sync_times") or DEFAULT_TIMES).split(",") if t]


def set_times(times: list[str]) -> list[str]:
    clean = sorted({t.strip() for t in times if t.strip()})
    for t in clean:
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
            raise ValueError(f"'{t}' is not a time like 08:30")
    set_setting("order_sync_times", ",".join(clean))
    return clean


def latest_slot(now: datetime) -> str | None:
    times = get_times()
    if not times:
        return None
    today = [t for t in times if t <= now.strftime("%H:%M")]
    if today:
        return f"{now:%Y-%m-%d} {today[-1]}"
    return f"{now - timedelta(days=1):%Y-%m-%d} {times[-1]}"


def check_page_url(c, account_id: int, url: str) -> dict:
    acc = row_to_dict(c.execute("SELECT id, marketplace FROM accounts WHERE id=?", (account_id,)).fetchone())
    if not acc:
        raise ValueError("Account not found")
    u = urlparse(url)
    if u.scheme != "https" or u.hostname != PANEL_HOST[acc["marketplace"]]:
        raise ValueError(f"Only https://{PANEL_HOST[acc['marketplace']]} pages can be synced for a {acc['marketplace']} account")
    return acc


def claim(firm_id: int, now: datetime | None = None) -> dict:
    """Give the firm's extension its work, if any. Never gives the same run out twice."""
    now = now or datetime.now()
    LAST_POLL[firm_id] = now
    with get_conn() as c:
        pages = rows_to_dicts(c.execute(
            "SELECT p.id AS page_id, p.account_id, p.url, p.status, p.tab_label, a.marketplace, a.name AS account_name "
            "FROM sync_pages p JOIN accounts a ON a.id=p.account_id WHERE a.firm_id=? AND a.active=1 AND p.kind='orders' ORDER BY p.id",
            (firm_id,)))
        if not pages:
            return {"run_id": None}
        c.execute("UPDATE order_syncs SET status='done', finished_at=datetime('now'), summary='Timed out: the extension did "
                  "not finish' WHERE firm_id=? AND status='running' AND started_at < datetime('now', ?)",
                  (firm_id, f"-{STALE_RUN_MIN} minutes"))
        if c.execute("SELECT 1 FROM order_syncs WHERE firm_id=? AND status='running'", (firm_id,)).fetchone():
            return {"run_id": None}
        run = c.execute("SELECT id FROM order_syncs WHERE firm_id=? AND status='requested' ORDER BY id LIMIT 1",
                        (firm_id,)).fetchone()
        run_id = run["id"] if run else None
        if run_id is None:
            slot = latest_slot(now)
            if not slot or c.execute("SELECT 1 FROM order_syncs WHERE firm_id=? AND slot=?", (firm_id, slot)).fetchone():
                return {"run_id": None}
            run_id = c.execute("INSERT INTO order_syncs (firm_id, trigger, status, slot) VALUES (?, 'schedule', 'running', ?)",
                               (firm_id, slot)).lastrowid
        c.execute("UPDATE order_syncs SET status='running', started_at=datetime('now') WHERE id=?", (run_id,))
    return {"run_id": run_id, "pages": pages}


def request_now() -> dict:
    """Sync now: queue a run for every firm that has taught pages (unless one is already waiting or running)."""
    queued = []
    with get_conn() as c:
        for f in rows_to_dicts(c.execute(
                "SELECT DISTINCT f.id, f.name FROM firms f JOIN accounts a ON a.firm_id=f.id "
                "JOIN sync_pages p ON p.account_id=a.id AND p.kind='orders'")):
            if c.execute("SELECT 1 FROM order_syncs WHERE firm_id=? AND status IN ('requested','running')", (f["id"],)).fetchone():
                continue
            c.execute("INSERT INTO order_syncs (firm_id, trigger, status) VALUES (?, 'manual', 'requested')", (f["id"],))
            queued.append(f["name"])
    return {"queued": queued}


def save_result(run_id: int, page_id: int, state: str, rows: list[dict], error: str | None, tab_hint: str | None) -> dict:
    if state not in STATES:
        raise ValueError(f"state must be one of {', '.join(STATES)}")
    with get_conn() as c:
        run = row_to_dict(c.execute("SELECT * FROM order_syncs WHERE id=?", (run_id,)).fetchone())
        if not run or run["status"] != "running":
            raise LookupError("This sync run is not active")
        page = row_to_dict(c.execute(
            "SELECT p.*, a.firm_id FROM sync_pages p JOIN accounts a ON a.id=p.account_id WHERE p.id=?", (page_id,)).fetchone())
        if not page or page["firm_id"] != run["firm_id"]:
            raise ValueError("That page does not belong to this run")
    saved = {"created": 0, "updated": 0}
    if state == "ok" and rows:
        st_default = page["status"] or tab_hint
        prepared = []
        for r in rows:
            st = r.get("status_text") or st_default
            prepared.append({**r, "order_date": orders_svc.parse_date(r.get("order_date")), "status_text": st,
                             "status": orders_svc.normalise_status(st) if st else None})
        saved = orders_svc.save_orders(page["account_id"], prepared, "extension")
    with get_conn() as c:
        c.execute("UPDATE sync_pages SET last_run_at=datetime('now'), last_state=?, last_rows=?, last_error=? WHERE id=?",
                  (state, len(rows) if state == "ok" else 0, (error or "")[:300] or None, page_id))
    return {"state": state, "rows": len(rows), **{k: saved.get(k, 0) for k in ("created", "updated")}}


def finish(run_id: int) -> dict:
    with get_conn() as c:
        run = row_to_dict(c.execute("SELECT * FROM order_syncs WHERE id=?", (run_id,)).fetchone())
        if not run:
            raise LookupError("Run not found")
        pages = rows_to_dicts(c.execute(
            "SELECT p.last_state, p.last_rows, p.last_run_at FROM sync_pages p JOIN accounts a ON a.id=p.account_id "
            "WHERE a.firm_id=? AND p.kind='orders' AND p.last_run_at >= ?", (run["firm_id"], run["started_at"] or "")))
        ok = [p for p in pages if p["last_state"] == "ok"]
        summary = f"{len(ok)} of {len(pages)} pages read, {sum(p['last_rows'] or 0 for p in ok)} order rows"
        c.execute("UPDATE order_syncs SET status='done', finished_at=datetime('now'), summary=? WHERE id=?", (summary, run_id))
        busy = c.execute("SELECT 1 FROM order_syncs WHERE status IN ('requested','running')").fetchone()
    return {"summary": summary, "others_pending": bool(busy), "firm_id": run["firm_id"]}


def status() -> dict:
    now = datetime.now()
    with get_conn() as c:
        firms = rows_to_dicts(c.execute(
            "SELECT f.id, f.name, f.browser_profile, COUNT(p.id) AS pages FROM firms f "
            "LEFT JOIN accounts a ON a.firm_id=f.id LEFT JOIN sync_pages p ON p.account_id=a.id AND p.kind='orders' GROUP BY f.id ORDER BY f.name"))
        for f in firms:
            f["last_run"] = row_to_dict(c.execute(
                "SELECT trigger, status, created_at, started_at, finished_at, summary FROM order_syncs "
                "WHERE firm_id=? ORDER BY id DESC LIMIT 1", (f["id"],)).fetchone())
            seen = LAST_POLL.get(f["id"])
            f["extension_seen_seconds_ago"] = int((now - seen).total_seconds()) if seen else None
        pages = rows_to_dicts(c.execute(
            "SELECT p.*, a.name AS account_name, a.marketplace, f.name AS firm FROM sync_pages p "
            "JOIN accounts a ON a.id=p.account_id JOIN firms f ON f.id=a.firm_id WHERE p.kind='orders' ORDER BY f.name, a.marketplace, p.id"))
    return {"times": get_times(), "firms": firms, "pages": pages}
