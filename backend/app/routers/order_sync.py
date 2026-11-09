import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import get_conn
from ..services import daily_check
from ..services import order_sync as svc
from ..services.secrets import get_setting

router = APIRouter(tags=["order_sync"])


# ---------------------------------------------------------------- from the extension

class ClaimIn(BaseModel):
    firm_id: int


@router.post("/api/ext/sync/claim")
def claim(b: ClaimIn):
    return svc.claim(b.firm_id)


class PageIn(BaseModel):
    account_id: int
    url: str = Field(max_length=2000)
    status: str | None = None
    tab_label: str | None = Field(None, max_length=80)
    label: str | None = Field(None, max_length=120)


@router.post("/api/ext/sync/pages")
def add_page(p: PageIn):
    """The user taught the extension an order page ("Add to daily sync")."""
    with get_conn() as c:
        try:
            svc.check_page_url(c, p.account_id, p.url)
        except ValueError as e:
            raise HTTPException(400, str(e))
        c.execute("INSERT INTO sync_pages (account_id, url, status, tab_label, label) VALUES (?,?,?,?,?) "
                  "ON CONFLICT(account_id, url) DO UPDATE SET status=excluded.status, tab_label=excluded.tab_label, "
                  "label=excluded.label", (p.account_id, p.url, p.status or None, p.tab_label or None, p.label))
        return {"id": c.execute("SELECT id FROM sync_pages WHERE account_id=? AND url=?", (p.account_id, p.url)).fetchone()[0]}


class RowIn(BaseModel):
    order_id: str
    sub_order_id: str | None = ""
    sku: str | None = None
    order_date: str | None = None
    status_text: str | None = None
    sale_amount: float | None = None
    awb: str | None = None


class ResultIn(BaseModel):
    run_id: int
    page_id: int
    state: str
    rows: list[RowIn] = []
    error: str | None = None
    tab_hint: str | None = None


@router.post("/api/ext/sync/result")
def result(b: ResultIn):
    try:
        return svc.save_result(b.run_id, b.page_id, b.state, [r.model_dump() for r in b.rows], b.error, b.tab_hint)
    except LookupError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


class FinishIn(BaseModel):
    run_id: int


@router.post("/api/ext/sync/finish")
def finish(b: FinishIn):
    try:
        res = svc.finish(b.run_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
    from ..services import stock_push
    stock_push.request_after_orders(res["firm_id"])      # orders may have changed master stock: push it to the portals
    if not res["others_pending"] and get_setting("agent_summary_after_sync", "1") == "1":
        from ..services import agents  # the agents write the summary in the background; the numbers never wait on them
        threading.Thread(target=agents.daily_summary, daemon=True).start()
    return res


# ---------------------------------------------------------------- Seller Desk screens

@router.get("/api/sync/status")
def status():
    return svc.status()


@router.post("/api/sync/now")
def sync_now():
    return svc.request_now()


class TimesIn(BaseModel):
    times: list[str]


@router.put("/api/sync/times")
def set_times(b: TimesIn):
    try:
        return {"times": svc.set_times(b.times)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/sync/pages/{page_id}")
def delete_page(page_id: int):
    with get_conn() as c:
        c.execute("DELETE FROM sync_pages WHERE id=?", (page_id,))
    return {"ok": True}


@router.get("/api/daily-check")
def daily():
    return daily_check.report()
