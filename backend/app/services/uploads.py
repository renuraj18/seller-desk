"""Upload queue for new catalog.

The user queues sarees for accounts. The Seller Desk extension in that firm's Chrome profile picks the jobs up,
opens the account's add-catalog page in a background tab, fills the form and attaches the photos. By default it
stops there and the user reviews and submits; with "Submit by itself" on it also clicks the page's Submit button.
At most MAX_OPEN filled forms wait for review per firm, so a long queue never piles up open tabs."""
import json

from ..db import dump, get_conn, row_to_dict, rows_to_dicts
from . import catalogs
from .secrets import get_setting, set_setting

MAX_OPEN = 5
STALE_MIN = 10
ACTIVE = ("queued", "filling", "filled")
STATUSES = ("queued", "filling", "filled", "submitted", "failed", "cancelled")
REQUIRED = (("fabric", "fabric"), ("color", "colour"), ("mrp", "MRP"), ("selling_price", "selling price"), ("hsn", "HSN"))


def auto_submit() -> bool:
    return get_setting("upload_auto_submit", "0") == "1"


def paused() -> bool:
    return get_setting("upload_paused", "0") == "1"


def set_paused(on: bool) -> bool:
    set_setting("upload_paused", "1" if on else "0")
    return on


def set_auto_submit(on: bool) -> bool:
    set_setting("upload_auto_submit", "1" if on else "0")
    return on


def missing_for(p: dict) -> list[str]:
    miss = [label for key, label in REQUIRED if p.get(key) in (None, "")]
    if not [u for u in (p.get("images") or []) if u]:
        miss.append("photos")
    return miss


def _group(c, product_ids: list[int]) -> list[list[dict]]:
    """Products grouped by design (parent SKU): one catalog form carries all colour variants of a design."""
    seen, groups = set(), []
    for pid in product_ids:
        p = row_to_dict(c.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone())
        if not p or p["id"] in seen:
            continue
        members = [p] if not p["parent_sku"] else rows_to_dicts(c.execute(
            "SELECT * FROM products WHERE parent_sku=? ORDER BY sku", (p["parent_sku"],)))
        seen |= {m["id"] for m in members}
        groups.append(members)
    return groups


def queue(product_ids: list[int], account_ids: list[int]) -> dict:
    """One job per catalog. A design with more colours than the marketplace allows per catalog (Meesho: 9) becomes
    several catalogs; the extra ones get a parent SKU with -2, -3 … so each stays within the limit."""
    queued, skipped, splits = 0, [], []
    with get_conn() as c:
        accounts = {a["id"]: a for a in rows_to_dicts(c.execute(
            f"SELECT id, name, marketplace, add_catalog_url FROM accounts WHERE active=1 AND id IN ({','.join('?' * len(account_ids))})",
            tuple(account_ids)))} if account_ids else {}
        for members in _group(c, product_ids):
            for aid in account_ids:
                acc = accounts.get(aid)
                base = members[0]["parent_sku"] or members[0]["sku"]
                if not acc:
                    skipped.append({"sku": base, "account": str(aid), "reason": "Account not found or switched off"})
                    continue
                catalogs.assign(c, aid, [m["id"] for m in members])
                by_no: dict[int, list[dict]] = {}
                for m in members:
                    no = c.execute("SELECT catalog_no FROM listings WHERE product_id=? AND account_id=?", (m["id"], aid)).fetchone()
                    by_no.setdefault((no["catalog_no"] if no else None) or 1, []).append(m)
                if len(by_no) > 1:
                    splits.append({"sku": base, "account": acc["name"], "catalogs": [len(v) for _, v in sorted(by_no.items())],
                                   "limit": catalogs.limit_for(acc["marketplace"])})
                for no, group in sorted(by_no.items()):
                    lead = group[0]
                    label = {"sku": catalogs.account_parent(lead["parent_sku"], "", no) if lead["parent_sku"] else lead["sku"], "account": acc["name"]}
                    if not acc["add_catalog_url"]:
                        skipped.append({**label, "reason": "No add-catalog page taught for this account yet (open it on the portal, then Seller Desk extension → Use this page)"})
                        continue
                    bad = {m["sku"]: missing_for(m) for m in group if missing_for(m)}
                    if bad:
                        sku, what = next(iter(bad.items()))
                        skipped.append({**label, "reason": f"{sku} is missing {', '.join(what)}" + (f" (and {len(bad) - 1} more)" if len(bad) > 1 else "")})
                        continue
                    pids = [m["id"] for m in group]
                    marks = ",".join("?" * len(pids))
                    if c.execute(f"SELECT 1 FROM upload_jobs WHERE account_id=? AND product_id IN ({marks}) AND status IN "
                                 "('queued','filling','filled')", (aid, *pids)).fetchone():
                        skipped.append({**label, "reason": "Already in the queue"})
                        continue
                    if c.execute(f"SELECT 1 FROM listings WHERE account_id=? AND product_id IN ({marks}) AND status IN "
                                 "('exported','live')", (aid, *pids)).fetchone():
                        skipped.append({**label, "reason": "Already listed on this account"})
                        continue
                    c.execute("INSERT INTO upload_jobs (account_id, product_id) VALUES (?,?)", (aid, lead["id"]))
                    queued += 1
    return {"queued": queued, "skipped": skipped, "splits": splits}


def claim(firm_id: int) -> dict:
    """Hand the firm's extension its next jobs. Never gives the same job out twice. Nothing while the queue is paused."""
    if paused():
        return {"jobs": []}
    with get_conn() as c:
        c.execute("UPDATE upload_jobs SET status='failed', message='Timed out: the extension did not report back', "
                  "updated_at=datetime('now') WHERE status='filling' AND updated_at < datetime('now', ?) AND account_id IN "
                  "(SELECT id FROM accounts WHERE firm_id=?)", (f"-{STALE_MIN} minutes", firm_id))
        open_n = c.execute("SELECT COUNT(*) FROM upload_jobs j JOIN accounts a ON a.id=j.account_id "
                           "WHERE a.firm_id=? AND j.status IN ('filling','filled')", (firm_id,)).fetchone()[0]
        room = MAX_OPEN - open_n
        if room <= 0:
            return {"jobs": []}
        jobs = rows_to_dicts(c.execute(
            "SELECT j.id AS job_id, j.product_id, j.account_id, a.marketplace, a.add_catalog_url AS url, p.sku "
            "FROM upload_jobs j JOIN accounts a ON a.id=j.account_id AND a.firm_id=? AND a.active=1 "
            "JOIN products p ON p.id=j.product_id WHERE j.status='queued' ORDER BY j.id LIMIT ?", (firm_id, room)))
        for j in jobs:
            c.execute("UPDATE upload_jobs SET status='filling', attempts=attempts+1, message=NULL, updated_at=datetime('now') "
                      "WHERE id=?", (j["job_id"],))
    return {"jobs": jobs, "submit": auto_submit()}


def update(job_id: int, status: str, message: str | None = None, detail: dict | None = None) -> dict:
    if status not in STATUSES:
        raise ValueError("Unknown status")
    with get_conn() as c:
        j = row_to_dict(c.execute("SELECT * FROM upload_jobs WHERE id=?", (job_id,)).fetchone())
        if not j:
            raise LookupError("Job not found")
        c.execute("UPDATE upload_jobs SET status=?, message=?, detail=COALESCE(?, detail), updated_at=datetime('now') WHERE id=?",
                  (status, (message or "")[:400] or None, dump(detail) if detail else None, job_id))
        if status == "submitted":
            _, ids = catalogs.catalog_of(c, j["product_id"], j["account_id"])
            for pid in ids:
                c.execute("INSERT INTO listings (product_id, account_id, status, last_exported_at) VALUES (?,?,'exported',datetime('now')) "
                          "ON CONFLICT(product_id, account_id) DO UPDATE SET "
                          "status=CASE WHEN status IN ('draft','rejected') THEN 'exported' ELSE status END, "
                          "last_exported_at=datetime('now')", (pid, j["account_id"]))
    return {"ok": True}


def retry(job_id: int):
    with get_conn() as c:
        n = c.execute("UPDATE upload_jobs SET status='queued', message=NULL, updated_at=datetime('now') "
                      "WHERE id=? AND status IN ('failed','cancelled')", (job_id,)).rowcount
    if not n:
        raise ValueError("Only failed or cancelled jobs can be retried")


def listing(limit: int = 300) -> dict:
    with get_conn() as c:
        jobs = rows_to_dicts(c.execute(
            "SELECT j.*, p.sku, p.parent_sku, p.name, p.color, p.images, a.name AS account_name, a.marketplace, "
            "f.name AS firm FROM upload_jobs j JOIN products p ON p.id=j.product_id JOIN accounts a ON a.id=j.account_id "
            "JOIN firms f ON f.id=a.firm_id ORDER BY (j.status IN ('queued','filling','filled')) DESC, j.id DESC LIMIT ?", (limit,)))
        accounts = rows_to_dicts(c.execute(
            "SELECT a.id, a.name, a.marketplace, a.add_catalog_url, f.name AS firm FROM accounts a JOIN firms f ON f.id=a.firm_id "
            "WHERE a.active=1 ORDER BY f.name, a.marketplace, a.name"))
    with get_conn() as c:
        for j in jobs:
            no, ids = catalogs.catalog_of(c, j["product_id"], j["account_id"])
            j["catalog_parent_sku"] = catalogs.account_parent(j["parent_sku"], "", no) if j["parent_sku"] else None
            j["catalog_size"] = len(ids)
    for j in jobs:
        j["image"] = (j.pop("images") or [None])[0]
        try:
            j["detail"] = json.loads(j["detail"]) if j.get("detail") else None
        except ValueError:
            j["detail"] = None
    counts = {s: 0 for s in STATUSES}
    for j in jobs:
        counts[j["status"]] += 1
    return {"jobs": jobs, "accounts": accounts, "counts": counts, "auto_submit": auto_submit(), "paused": paused(), "max_open": MAX_OPEN}
