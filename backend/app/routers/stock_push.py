from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import get_conn, rows_to_dicts
from ..services import stock_push as svc
from ..services.pricing import account_sku
from .extension import _account

router = APIRouter(tags=["stock_push"])


# ---------------------------------------------------------------- from the extension

class ClaimIn(BaseModel):
    firm_id: int


@router.post("/api/ext/stockpush/claim")
def claim(b: ClaimIn):
    return svc.claim(b.firm_id)


@router.get("/api/ext/stockpush/targets")
def targets(account_id: int):
    """Listed sarees on this account and the stock the portal should show. Drafts and unknown stock are left out;
    negative master stock is sent as 0."""
    with get_conn() as c:
        acc = _account(c, account_id)
        rows = rows_to_dicts(c.execute(
            "SELECT p.id, p.sku, p.parent_sku, p.color, p.stock_qty, l.marketplace_sku, l.listing_ref, l.stock_qty AS seen "
            "FROM listings l JOIN products p ON p.id=l.product_id WHERE l.account_id=? AND l.status IN ('live','exported') "
            "AND p.stock_qty IS NOT NULL ORDER BY p.sku", (account_id,)))
    return [{"product_id": r["id"], "sku": r["sku"], "account_sku": account_sku(r, acc, {"marketplace_sku": r["marketplace_sku"]}),
             "listing_ref": r["listing_ref"], "target": max(0, r["stock_qty"]), "seen": r["seen"]} for r in rows]


class PageIn(BaseModel):
    account_id: int
    url: str = Field(max_length=2000)
    label: str | None = Field(None, max_length=120)


@router.post("/api/ext/stockpush/pages")
def add_page(b: PageIn):
    try:
        return {"id": svc.add_page(b.account_id, b.url, b.label)}
    except ValueError as e:
        raise HTTPException(400, str(e))


class ResultIn(BaseModel):
    run_id: int
    page_id: int
    state: str
    found: int = 0
    updated: int = 0
    failed: list[str] = []
    not_on_page: int = 0
    error: str | None = Field(None, max_length=300)


@router.post("/api/ext/stockpush/result")
def result(b: ResultIn):
    try:
        return svc.save_result(b.run_id, b.page_id, b.state, b.found, b.updated, b.failed[:20], b.not_on_page, b.error)
    except LookupError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


class FinishIn(BaseModel):
    run_id: int


@router.post("/api/ext/stockpush/finish")
def finish(b: FinishIn):
    try:
        return svc.finish(b.run_id)
    except LookupError as e:
        raise HTTPException(404, str(e))


# ---------------------------------------------------------------- Seller Desk screens

@router.get("/api/stockpush/status")
def status():
    return svc.status()


@router.post("/api/stockpush/now")
def now():
    return svc.request_now()


class SettingsIn(BaseModel):
    times: list[str] | None = None
    enabled: bool | None = None


@router.put("/api/stockpush/settings")
def settings(b: SettingsIn):
    try:
        return svc.configure(b.times, b.enabled)
    except ValueError as e:
        raise HTTPException(400, str(e))
