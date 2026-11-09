from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import get_conn
from ..services import order_sync, uploads as svc

router = APIRouter(tags=["uploads"])


# ---------------------------------------------------------------- from the extension

class ClaimIn(BaseModel):
    firm_id: int


@router.post("/api/ext/upload/claim")
def claim(b: ClaimIn):
    return svc.claim(b.firm_id)


class UpdateIn(BaseModel):
    job_id: int
    status: str
    message: str | None = Field(None, max_length=400)
    detail: dict | None = None


@router.post("/api/ext/upload/update")
def update(b: UpdateIn):
    if b.status not in ("filled", "submitted", "failed"):
        raise HTTPException(400, "The extension can only report filled, submitted or failed")
    try:
        return svc.update(b.job_id, b.status, b.message, b.detail)
    except LookupError as e:
        raise HTTPException(404, str(e))


class AddUrlIn(BaseModel):
    url: str = Field(max_length=2000)


@router.put("/api/ext/accounts/{account_id}/add-catalog-url")
def set_add_url(account_id: int, b: AddUrlIn):
    """The user taught the extension an account's add-catalog page ("Use this page for new catalog")."""
    with get_conn() as c:
        try:
            order_sync.check_page_url(c, account_id, b.url)
        except ValueError as e:
            raise HTTPException(400, str(e))
        c.execute("UPDATE accounts SET add_catalog_url=? WHERE id=?", (b.url, account_id))
    return {"ok": True}


# ---------------------------------------------------------------- Seller Desk screens

class QueueIn(BaseModel):
    product_ids: list[int] = Field(min_length=1, max_length=500)
    account_ids: list[int] = Field(min_length=1, max_length=20)


@router.post("/api/uploads/queue")
def queue(b: QueueIn):
    return svc.queue(b.product_ids, b.account_ids)


@router.get("/api/uploads")
def jobs():
    return svc.listing()


class SettingsIn(BaseModel):
    auto_submit: bool | None = None
    paused: bool | None = None


@router.put("/api/uploads/settings")
def settings(b: SettingsIn):
    if b.auto_submit is not None:
        svc.set_auto_submit(b.auto_submit)
    if b.paused is not None:
        svc.set_paused(b.paused)
    return {"auto_submit": svc.auto_submit(), "paused": svc.paused()}


class StatusIn(BaseModel):
    status: str


@router.post("/api/uploads/{job_id}/status")
def set_status(job_id: int, b: StatusIn):
    """The user's own marks: submitted (they sent it on the portal), cancelled, or queued again."""
    try:
        if b.status == "queued":
            svc.retry(job_id)
        elif b.status in ("submitted", "cancelled", "failed"):
            svc.update(job_id, b.status, "Marked by you" if b.status != "cancelled" else None)
        else:
            raise HTTPException(400, "Unknown status")
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


@router.put("/api/accounts/{account_id}/add-catalog-url")
def clear_add_url(account_id: int, b: AddUrlIn):
    return set_add_url(account_id, b)


@router.delete("/api/accounts/{account_id}/add-catalog-url")
def delete_add_url(account_id: int):
    with get_conn() as c:
        c.execute("UPDATE accounts SET add_catalog_url=NULL WHERE id=?", (account_id,))
    return {"ok": True}
