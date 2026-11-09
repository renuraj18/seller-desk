from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import get_conn, row_to_dict, rows_to_dicts

router = APIRouter(prefix="/api", tags=["setup"])


class FirmIn(BaseModel):
    name: str
    gstin: str | None = None
    state: str | None = None
    address: str | None = None
    pincode: str | None = None
    # OpenClaw browser profile the marketplace agents use for this firm's seller panels
    browser_profile: str | None = Field(None, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")


class AccountIn(BaseModel):
    firm_id: int
    marketplace: Literal["amazon", "flipkart", "meesho"]
    name: str
    seller_id: str | None = None
    store_name: str | None = None
    brand: str | None = None
    sku_prefix: str | None = ""
    price_markup_pct: float = 0
    price_add: float = 0
    price_round_to: int = 0
    return_price_less: float = 30
    active: bool = True
    notes: str | None = None
    # text that appears only in this account's seller-panel address (e.g. Meesho's "3ylgo"); used for live reads
    panel_match: str | None = Field(None, max_length=100)


@router.get("/firms")
def list_firms():
    with get_conn() as c:
        return rows_to_dicts(c.execute(
            "SELECT f.*, (SELECT COUNT(*) FROM accounts a WHERE a.firm_id = f.id) AS account_count "
            "FROM firms f ORDER BY name"))


@router.post("/firms")
def create_firm(f: FirmIn):
    with get_conn() as c:
        try:
            cur = c.execute("INSERT INTO firms (name, gstin, state, address, pincode, browser_profile) "
                            "VALUES (?,?,?,?,?,?)", (f.name, f.gstin, f.state, f.address, f.pincode, f.browser_profile))
        except Exception as e:
            raise HTTPException(400, f"Could not save firm: {e}")
        return row_to_dict(c.execute("SELECT * FROM firms WHERE id=?", (cur.lastrowid,)).fetchone())


@router.put("/firms/{firm_id}")
def update_firm(firm_id: int, f: FirmIn):
    with get_conn() as c:
        c.execute("UPDATE firms SET name=?, gstin=?, state=?, address=?, pincode=?, browser_profile=? WHERE id=?",
                  (f.name, f.gstin, f.state, f.address, f.pincode, f.browser_profile, firm_id))
        return row_to_dict(c.execute("SELECT * FROM firms WHERE id=?", (firm_id,)).fetchone())


@router.delete("/firms/{firm_id}")
def delete_firm(firm_id: int):
    with get_conn() as c:
        c.execute("DELETE FROM firms WHERE id=?", (firm_id,))
    return {"ok": True}


ACCOUNT_SQL = ("SELECT a.*, f.name AS firm_name, "
               "(SELECT COUNT(*) FROM listings l WHERE l.account_id = a.id) AS listing_count "
               "FROM accounts a JOIN firms f ON f.id = a.firm_id")


@router.get("/accounts")
def list_accounts():
    with get_conn() as c:
        return rows_to_dicts(c.execute(ACCOUNT_SQL + " ORDER BY f.name, a.marketplace, a.name"))


def _save_account(c, a: AccountIn, account_id: int | None = None):
    vals = (a.firm_id, a.marketplace, a.name, a.seller_id, a.store_name, a.brand, a.sku_prefix or "", a.price_markup_pct,
            a.price_add, a.price_round_to, a.return_price_less, int(a.active), a.notes,
            (a.panel_match or "").strip() or None)
    try:
        if account_id:
            c.execute("UPDATE accounts SET firm_id=?, marketplace=?, name=?, seller_id=?, store_name=?, brand=?, sku_prefix=?, "
                      "price_markup_pct=?, price_add=?, price_round_to=?, return_price_less=?, active=?, notes=?, panel_match=? "
                      "WHERE id=?",
                      (*vals, account_id))
            return account_id
        cur = c.execute("INSERT INTO accounts (firm_id, marketplace, name, seller_id, store_name, brand, sku_prefix, "
                        "price_markup_pct, price_add, price_round_to, return_price_less, active, notes, panel_match) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        vals)
        return cur.lastrowid
    except Exception as e:
        raise HTTPException(400, f"Could not save account: {e}")


@router.post("/accounts")
def create_account(a: AccountIn):
    with get_conn() as c:
        aid = _save_account(c, a)
        return row_to_dict(c.execute(ACCOUNT_SQL + " WHERE a.id=?", (aid,)).fetchone())


@router.put("/accounts/{account_id}")
def update_account(account_id: int, a: AccountIn):
    with get_conn() as c:
        _save_account(c, a, account_id)
        return row_to_dict(c.execute(ACCOUNT_SQL + " WHERE a.id=?", (account_id,)).fetchone())


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int):
    with get_conn() as c:
        c.execute("DELETE FROM accounts WHERE id=?", (account_id,))
    return {"ok": True}
