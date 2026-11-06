import math


def round_price(price: float, round_to: int | None) -> float:
    if price is None:
        return None
    if not round_to:
        return round(price, 2)
    if round_to == 9:            # 1213 -> 1219, 1250 -> 1259
        return float(math.ceil((price + 1) / 10) * 10 - 1)
    return float(math.ceil(price / round_to) * round_to)


def account_price(product: dict, account: dict, listing: dict | None = None) -> float | None:
    """Listing override > account rule applied to the product's base selling price."""
    if listing and listing.get("price") is not None:
        return listing["price"]
    base = product.get("selling_price")
    if base is None:
        return None
    pct = account.get("price_markup_pct") or 0
    add = account.get("price_add") or 0
    return round_price(base * (1 + pct / 100) + add, account.get("price_round_to") or 0)


def account_sku(product: dict, account: dict, listing: dict | None = None) -> str:
    if listing and listing.get("marketplace_sku"):
        return listing["marketplace_sku"]
    return f"{account.get('sku_prefix') or ''}{product['sku']}"
