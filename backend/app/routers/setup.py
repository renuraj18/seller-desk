from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import get_conn, row_to_dict, rows_to_dicts

router = APIRouter(prefix="/api", tags=["setup"])


class FirmIn(BaseModel):
    name: str
    gstin: str | None = None
    state: str | None = None
    address: str | None = None


class AccountIn(BaseModel):
    firm_id: int
    marketplace: Literal["amazon", "flipkart", "meesho"]
    name: str
    seller_id: str | None = None
    brand: str | None = None
    sku_prefix: str | None = ""
    price_markup_pct: float = 0
    price_add: float = 0
    price_round_to: int = 0
    active: bool = True
    notes: str | None = None


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
            cur = c.execute("INSERT INTO firms (name, gstin, state, address) VALUES (?,?,?,?)",
                            (f.name, f.gstin, f.state, f.address))
        except Exception as e:
            raise HTTPException(400, f"Could not save firm: {e}")
        return row_to_dict(c.execute("SELECT * FROM firms WHERE id=?", (cur.lastrowid,)).fetchone())


@router.put("/firms/{firm_id}")
def update_firm(firm_id: int, f: FirmIn):
    with get_conn() as c:
        c.execute("UPDATE firms SET name=?, gstin=?, state=?, address=? WHERE id=?",
                  (f.name, f.gstin, f.state, f.address, firm_id))
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
    vals = (a.firm_id, a.marketplace, a.name, a.seller_id, a.brand, a.sku_prefix or "", a.price_markup_pct,
            a.price_add, a.price_round_to, int(a.active), a.notes)
    try:
        if account_id:
            c.execute("UPDATE accounts SET firm_id=?, marketplace=?, name=?, seller_id=?, brand=?, sku_prefix=?, "
                      "price_markup_pct=?, price_add=?, price_round_to=?, active=?, notes=? WHERE id=?",
                      (*vals, account_id))
            return account_id
        cur = c.execute("INSERT INTO accounts (firm_id, marketplace, name, seller_id, brand, sku_prefix, "
                        "price_markup_pct, price_add, price_round_to, active, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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
