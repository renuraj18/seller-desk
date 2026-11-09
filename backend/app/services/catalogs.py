"""Split a design's colours into catalogs when a marketplace caps how many products one catalog may hold.

Meesho allows 9 products per catalog. A design with 12 colours becomes two catalogs on a Meesho account: the first
keeps the parent SKU (KOLAM), the second is KOLAM-2. The number is stored on the listing the first time it is needed,
so adding or deleting colours later never moves colours that are already placed."""
from ..db import row_to_dict, rows_to_dicts

LIMITS = {"meesho": 9}


def limit_for(marketplace: str) -> int | None:
    return LIMITS.get(marketplace)


def account_parent(parent: str | None, prefix: str | None, catalog_no: int | None) -> str | None:
    if not parent:
        return None
    suffix = f"-{catalog_no}" if catalog_no and catalog_no > 1 else ""
    return f"{prefix or ''}{parent}{suffix}"


def assign(c, account_id: int, product_ids: list[int]) -> None:
    """Make sure these sarees have a listing row on the account and a catalog number, filling catalogs up to the limit."""
    acc = row_to_dict(c.execute("SELECT marketplace FROM accounts WHERE id=?", (account_id,)).fetchone())
    lim = limit_for(acc["marketplace"]) if acc else None
    if not lim or not product_ids:
        return
    marks = ",".join("?" * len(product_ids))
    for pid in product_ids:
        c.execute("INSERT OR IGNORE INTO listings (product_id, account_id) VALUES (?,?)", (pid, account_id))
    parents = [r[0] for r in c.execute(f"SELECT DISTINCT parent_sku FROM products WHERE id IN ({marks}) AND parent_sku IS NOT NULL",
                                       tuple(product_ids))]
    for parent in parents:
        rows = rows_to_dicts(c.execute(
            "SELECT l.id, l.catalog_no FROM listings l JOIN products p ON p.id=l.product_id "
            "WHERE l.account_id=? AND p.parent_sku=? ORDER BY l.product_id", (account_id, parent)))
        counts: dict[int, int] = {}
        for r in rows:
            if r["catalog_no"]:
                counts[r["catalog_no"]] = counts.get(r["catalog_no"], 0) + 1
        for r in rows:
            if r["catalog_no"]:
                continue
            no = next((n for n in range(1, len(rows) + 2) if counts.get(n, 0) < lim))
            counts[no] = counts.get(no, 0) + 1
            c.execute("UPDATE listings SET catalog_no=? WHERE id=?", (no, r["id"]))


def catalog_of(c, product_id: int, account_id: int) -> tuple[int | None, list[int]]:
    """(catalog number, product ids in the same catalog on this account) for a saree, siblings included."""
    p = row_to_dict(c.execute("SELECT id, parent_sku FROM products WHERE id=?", (product_id,)).fetchone())
    if not p:
        return None, []
    if not p["parent_sku"]:
        return None, [product_id]
    siblings = [r["id"] for r in c.execute("SELECT id FROM products WHERE parent_sku=? ORDER BY sku", (p["parent_sku"],))]
    acc = row_to_dict(c.execute("SELECT marketplace FROM accounts WHERE id=?", (account_id,)).fetchone())
    if not acc or not limit_for(acc["marketplace"]):
        return None, siblings
    assign(c, account_id, siblings)
    mine = row_to_dict(c.execute("SELECT catalog_no FROM listings WHERE product_id=? AND account_id=?",
                                 (product_id, account_id)).fetchone())["catalog_no"]
    ids = [r["id"] for r in c.execute(
        "SELECT p.id FROM listings l JOIN products p ON p.id=l.product_id WHERE l.account_id=? AND p.parent_sku=? "
        "AND l.catalog_no=? ORDER BY p.sku", (account_id, p["parent_sku"], mine))]
    return mine, ids
