import threading

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..db import get_conn, row_to_dict, rows_to_dicts
from ..services import inventory
from ..services import secrets as sec
from ..services.marketplaces import CREDENTIAL_FIELDS, MarketplaceError, client_for

router = APIRouter(prefix="/api", tags=["connections"])


def _account(account_id: int) -> dict:
    with get_conn() as c:
        a = row_to_dict(c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())
    if not a:
        raise HTTPException(404, "Account not found")
    return a


@router.get("/connections")
def connections():
    with get_conn() as c:
        accounts = rows_to_dicts(c.execute(
            "SELECT a.id, a.name, a.marketplace, f.name AS firm_name, cr.last_test_at, cr.last_test_ok, "
            "cr.last_test_message, (cr.account_id IS NOT NULL) AS has_credentials, "
            "(SELECT COUNT(*) FROM remote_listings r WHERE r.account_id=a.id) AS remote_count, "
            "(SELECT COUNT(*) FROM remote_listings r WHERE r.account_id=a.id AND r.product_id IS NULL) AS unmatched, "
            "(SELECT MAX(synced_at) FROM remote_listings r WHERE r.account_id=a.id) AS last_sync "
            "FROM accounts a JOIN firms f ON f.id=a.firm_id LEFT JOIN account_credentials cr ON cr.account_id=a.id "
            "ORDER BY f.name, a.marketplace, a.name"))
        runs = rows_to_dicts(c.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 30"))
    return {"accounts": accounts, "credential_fields": CREDENTIAL_FIELDS, "runs": runs}


@router.get("/accounts/{account_id}/credentials")
def get_creds(account_id: int):
    a = _account(account_id)
    creds = sec.get_credentials(account_id) or {}
    fields = CREDENTIAL_FIELDS[a["marketplace"]]
    return {f["key"]: (sec.mask(creds.get(f["key"])) if f["secret"] else creds.get(f["key"], "")) for f in fields}


@router.put("/accounts/{account_id}/credentials")
def put_creds(account_id: int, body: dict):
    a = _account(account_id)
    allowed = {f["key"] for f in CREDENTIAL_FIELDS[a["marketplace"]]}
    clean = {k: str(v).strip() for k, v in body.items() if k in allowed and v and not str(v).startswith("•")}
    sec.save_credentials(account_id, clean)
    return {"ok": True}


@router.delete("/accounts/{account_id}/credentials")
def delete_creds(account_id: int):
    sec.delete_credentials(account_id)
    return {"ok": True}


@router.post("/accounts/{account_id}/test")
def test_connection(account_id: int):
    a = _account(account_id)
    creds = sec.get_credentials(account_id)
    if not creds:
        raise HTTPException(400, "Save credentials first")
    try:
        msg = client_for(a["marketplace"], creds).test()
        sec.record_test(account_id, True, msg)
        return {"ok": True, "message": msg}
    except (MarketplaceError, Exception) as e:
        sec.record_test(account_id, False, str(e))
        return {"ok": False, "message": str(e)}


def _run_sync(run_id: int, account: dict, creds: dict):
    try:
        rows = client_for(account["marketplace"], creds).fetch_all_listings()
        res = inventory.store_remote_listings(account["id"], rows, "api")
        status, msg, n = "done", f"{res['rows']} listings, {res['matched']} newly matched", res["rows"]
    except Exception as e:  # noqa: BLE001 — report any failure to the UI
        status, msg, n = "failed", str(e)[:500], 0
    with get_conn() as c:
        c.execute("UPDATE sync_runs SET status=?, message=?, row_count=?, finished_at=datetime('now') WHERE id=?",
                  (status, msg, n, run_id))


@router.post("/accounts/{account_id}/sync")
def sync_inventory(account_id: int):
    """Pull every listing from the marketplace API. Runs in the background (Amazon reports take minutes)."""
    a = _account(account_id)
    creds = sec.get_credentials(account_id)
    if a["marketplace"] == "meesho":
        raise HTTPException(400, "Meesho has no self-service API — upload the Inventory file from the Supplier Panel")
    if not creds:
        raise HTTPException(400, "Save credentials first")
    with get_conn() as c:
        if c.execute("SELECT 1 FROM sync_runs WHERE account_id=? AND status='running'", (account_id,)).fetchone():
            raise HTTPException(409, "A sync is already running for this account")
        run_id = c.execute("INSERT INTO sync_runs (account_id, kind, status) VALUES (?, 'inventory_api', 'running')",
                           (account_id,)).lastrowid
    threading.Thread(target=_run_sync, args=(run_id, a, creds), daemon=True).start()
    return {"run_id": run_id, "status": "running"}


@router.post("/accounts/{account_id}/inventory-file")
async def upload_inventory(account_id: int, file: UploadFile = File(...)):
    _account(account_id)
    try:
        rows = inventory.parse_inventory_file(file.filename or "file.xlsx", await file.read())
    except Exception as e:
        raise HTTPException(400, f"Could not read this file: {e}")
    res = inventory.store_remote_listings(account_id, rows, "file")
    with get_conn() as c:
        c.execute("INSERT INTO sync_runs (account_id, kind, status, message, row_count, finished_at) "
                  "VALUES (?, 'inventory_file', 'done', ?, ?, datetime('now'))",
                  (account_id, f"{file.filename}: {res['rows']} rows, {res['matched']} matched", res["rows"]))
    return res


@router.get("/accounts/{account_id}/remote-listings")
def remote_listings(account_id: int, only: str = "all", q: str = ""):
    sql = ("SELECT r.id, r.remote_sku, r.listing_ref, r.listing_id, r.title, r.price, r.mrp, r.stock, r.status, "
           "r.image, r.product_id, r.match_method, r.source, r.synced_at, p.sku AS product_sku "
           "FROM remote_listings r LEFT JOIN products p ON p.id=r.product_id WHERE r.account_id=?")
    args: list = [account_id]
    if only == "unmatched":
        sql += " AND r.product_id IS NULL"
    elif only == "matched":
        sql += " AND r.product_id IS NOT NULL"
    if q:
        sql += " AND (r.remote_sku LIKE ? OR r.title LIKE ? OR r.listing_ref LIKE ?)"
        args += [f"%{q}%"] * 3
    with get_conn() as c:
        return rows_to_dicts(c.execute(sql + " ORDER BY r.product_id IS NOT NULL, r.remote_sku LIMIT 2000", args))


class LinkIn(BaseModel):
    product_id: int


class CreateIn(BaseModel):
    sku: str | None = None


@router.post("/remote-listings/{remote_id}/link")
def link(remote_id: int, body: LinkIn):
    try:
        inventory.link(remote_id, body.product_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


@router.post("/remote-listings/{remote_id}/unlink")
def unlink(remote_id: int):
    inventory.unlink(remote_id)
    return {"ok": True}


@router.post("/remote-listings/{remote_id}/create-product")
def create_product(remote_id: int, body: CreateIn):
    try:
        return {"product_id": inventory.create_product_from(remote_id, body.sku)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/accounts/{account_id}/create-all-unmatched")
def create_all_unmatched(account_id: int):
    with get_conn() as c:
        ids = [r["id"] for r in c.execute(
            "SELECT id FROM remote_listings WHERE account_id=? AND product_id IS NULL", (account_id,))]
    created, skipped = 0, []
    for rid in ids:
        try:
            inventory.create_product_from(rid)
            created += 1
        except ValueError as e:
            skipped.append(str(e))
    # other accounts may now match the new products
    with get_conn() as c:
        others = [r["id"] for r in c.execute("SELECT id FROM accounts WHERE id<>?", (account_id,))]
    for aid in others:
        inventory.auto_match(aid)
    return {"created": created, "skipped": skipped[:20]}


@router.post("/accounts/{account_id}/rematch")
def rematch(account_id: int):
    return {"matched": inventory.auto_match(account_id)}
