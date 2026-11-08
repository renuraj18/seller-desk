"""Learn a marketplace form from one live listing.

The seller opens the edit page of a product that is already live (ideally the top seller), the extension reads
every field's label and current value, and `propose` works out which Seller Desk value each field holds. The
accepted mappings are stored in `form_fields` and used for every later fill; re-run it whenever a form changes."""

import difflib
import re

from ..db import get_conn, rows_to_dicts
from ..fields import guess_source, normalise

LONG_TEXT = 25
# when several sources hold the same value, prefer the more specific one
PRIORITY_LAST = ("const.", "listing.stock", "product.stock_qty")


def _text(v) -> str:
    s = re.sub(r"\s+", " ", str(v if v is not None else "")).strip().lower()
    return re.sub(r"(?<=\d)\.0+$", "", s)


def _num(v):
    s = str(v if v is not None else "").replace(",", "")
    if not re.fullmatch(r"\s*[₹$]?\s*-?\d+(\.\d+)?\s*", s):
        return None
    return float(re.sub(r"[^0-9.\-]", "", s))


def _same(form_value, sd_value) -> bool:
    a, b = _text(form_value), _text(sd_value)
    if not a or not b:
        return False
    if a == b:
        return True
    na, nb = _num(form_value), _num(sd_value)
    if na is not None and nb is not None:
        return na == nb
    if len(a) >= LONG_TEXT and len(b) >= LONG_TEXT:
        if a.startswith(b[:LONG_TEXT * 2]) or b.startswith(a[:LONG_TEXT * 2]):
            return True
        return difflib.SequenceMatcher(None, a[:400], b[:400]).ratio() >= 0.9
    return False


def _rank(source: str) -> int:
    return 1 if source.startswith(PRIORITY_LAST) else 0


def propose(values: dict, fields: list[dict]) -> list[dict]:
    """values: source key -> Seller Desk value for the chosen product/account.
    fields: [{label, value, kind, options}] captured from the live form."""
    out, seen = [], set()
    for f in fields:
        label = str(f.get("label") or "").strip()
        norm = normalise(label)
        if not norm or norm in seen or norm.startswith("search") or f.get("kind") == "file":
            continue
        seen.add(norm)
        form_value = str(f.get("value") or "").strip()
        options = f.get("options") or []
        guess, _ = guess_source(label)
        row = {"label": label, "label_norm": norm, "kind": f.get("kind") or "text", "form_value": form_value,
               "source": "", "value": None, "value_map": {}, "confidence": "empty", "reason": "", "alternatives": [],
               "accept": False}
        if not form_value:
            row["reason"] = "Empty on the live listing"
            if guess:
                row.update(source=guess, confidence="label", reason="Empty on the live listing; label suggests this")
            out.append(row)
            continue
        matches = sorted((s for s, v in values.items() if _same(form_value, v)), key=lambda s: (_rank(s), s))
        if guess in matches:
            row.update(source=guess, confidence="high", reason="Label and value both match", accept=True)
        elif matches:
            row.update(source=matches[0], confidence="medium" if len(matches) == 1 else "ambiguous",
                       reason="Value matches" if len(matches) == 1 else "Several sources hold this value; check it",
                       alternatives=matches[1:5], accept=True)
        elif guess and guess in values:
            row.update(source=guess, confidence="label", accept=True,
                       reason=f"Label matches, but the form has “{form_value[:40]}” and Seller Desk has “{str(values[guess])[:40]}”")
            if options or row["kind"] in ("select", "combo", "click"):
                row["value_map"] = {str(values[guess]): form_value}
                row["reason"] += "; saved as a translation"
        elif guess:
            row.update(source=guess, confidence="label", accept=False,
                       reason="Label matches, but Seller Desk has no value for it on this product")
        else:
            row.update(source="const.custom", value=form_value, confidence="fixed",
                       reason="Not found in Seller Desk; use only if every listing gets this value")
        out.append(row)
    return out


def top_sellers(marketplace: str, limit: int = 5) -> dict:
    """Best-selling products on this marketplace (by units in imported orders), each with the account it sells on most."""
    with get_conn() as c:
        rows = rows_to_dicts(c.execute(
            "SELECT o.product_id, o.account_id, SUM(o.qty) AS sold FROM orders o JOIN accounts a ON a.id=o.account_id "
            "WHERE a.marketplace=? AND a.active=1 AND o.product_id IS NOT NULL "
            "AND COALESCE(o.status,'') NOT IN ('cancelled','rto','customer_return') "
            "GROUP BY o.product_id, o.account_id", (marketplace,)))
        by_product: dict = {}
        for r in rows:
            e = by_product.setdefault(r["product_id"], {"product_id": r["product_id"], "sold": 0, "best": 0, "account_id": None})
            e["sold"] += r["sold"] or 0
            if (r["sold"] or 0) > e["best"]:
                e["best"], e["account_id"] = r["sold"] or 0, r["account_id"]
        ranked = sorted(by_product.values(), key=lambda e: -e["sold"])[:limit]
        source = "orders"
        if not ranked:     # no orders imported yet: fall back to products already listed on this marketplace
            source = "listed"
            ranked = [{"product_id": r["product_id"], "account_id": r["account_id"], "sold": 0} for r in rows_to_dicts(c.execute(
                "SELECT l.product_id, l.account_id FROM listings l JOIN accounts a ON a.id=l.account_id "
                "WHERE a.marketplace=? AND a.active=1 AND l.status NOT IN ('draft') "
                "ORDER BY l.last_exported_at DESC LIMIT ?", (marketplace, limit)))]
        out = []
        for e in ranked:
            p = c.execute("SELECT id, sku, name, color FROM products WHERE id=?", (e["product_id"],)).fetchone()
            a = c.execute("SELECT id, name FROM accounts WHERE id=?", (e["account_id"],)).fetchone()
            if p and a:
                out.append({"product_id": p["id"], "sku": p["sku"], "name": p["name"], "color": p["color"],
                            "account_id": a["id"], "account_name": a["name"], "sold": e["sold"]})
    return {"source": source, "candidates": out}
