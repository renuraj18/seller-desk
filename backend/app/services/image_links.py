"""Image links made by a marketplace's own link generator (Meesho: "Image link Generator" / "Images Bulk Upload").
Meesho's Excel sheet only accepts such public links, so they are stored per saree and used for Image 1-4."""
import json
import re
from urllib.parse import urlparse

from ..db import get_conn, rows_to_dicts

MAX_LINKS = 8
URL_RE = re.compile(r"https?://[^\s,;\"'<>]+", re.I)
REFUSED_HOSTS = ("drive.google.com", "docs.google.com", "photos.google.com", "photos.app.goo.gl")


def clean_links(links: list[str]) -> list[str]:
    out = []
    for raw in links:
        u = str(raw).strip()
        if not u:
            continue
        p = urlparse(u)
        if p.scheme != "https" or not p.netloc:
            raise ValueError(f"'{u[:60]}' is not an https link")
        if any(p.netloc.endswith(h) for h in REFUSED_HOSTS):
            raise ValueError("Google Drive / Photos links are rejected by Meesho (QC error): use the Image link Generator")
        if u not in out:
            out.append(u)
    return out[:MAX_LINKS]


def get(product_ids: list[int], marketplace: str) -> dict[int, list[str]]:
    if not product_ids:
        return {}
    with get_conn() as c:
        rows = rows_to_dicts(c.execute(
            f"SELECT product_id, links FROM image_links WHERE marketplace=? AND product_id IN ({','.join('?' * len(product_ids))})",
            (marketplace, *product_ids)))
    return {r["product_id"]: json.loads(r["links"]) for r in rows}


def save(product_id: int, marketplace: str, links: list[str]) -> list[str]:
    links = clean_links(links)
    with get_conn() as c:
        if not c.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone():
            raise LookupError("Product not found")
        if links:
            c.execute("INSERT INTO image_links (product_id, marketplace, links) VALUES (?,?,?) ON CONFLICT(product_id, marketplace) "
                      "DO UPDATE SET links=excluded.links, updated_at=datetime('now')", (product_id, marketplace, json.dumps(links)))
        else:
            c.execute("DELETE FROM image_links WHERE product_id=? AND marketplace=?", (product_id, marketplace))
    return links


def parse(text: str, products: list[dict]) -> dict:
    """Turn pasted text into links per saree.
    - a line naming a SKU (alone, or before its links, or 'SKU <tab> link') starts that saree's list;
    - blocks of links without a SKU, separated by a blank line, go to `products` in the order given."""
    by_sku = {p["sku"].lower(): p["id"] for p in products}
    result: dict[int, list[str]] = {}
    current: int | None = None
    anonymous: list[list[str]] = [[]]
    unmatched: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            if anonymous[-1]:
                anonymous.append([])
            current = None if current is None else current
            continue
        urls = URL_RE.findall(s)
        head = URL_RE.sub(" ", s).strip(" \t:,;-=>|").lower()
        hit = next((pid for sku, pid in by_sku.items() if head == sku or head.startswith(sku + " ") or head.endswith(" " + sku)), None)
        if hit is None and head:
            hit = by_sku.get(head)
        if hit is not None:
            current = hit
            result.setdefault(hit, [])
        elif head and not urls:
            unmatched.append(s)
            continue
        for u in urls:
            if current is not None:
                result[current].append(u)
            else:
                anonymous[-1].append(u)
    blocks = [b for b in anonymous if b]
    order = [p["id"] for p in products if p["id"] not in result]
    for pid, block in zip(order, blocks):
        result[pid] = block
    leftover = len(blocks) - len(order)
    return {"links": {pid: clean_links(v) for pid, v in result.items() if v}, "unmatched_lines": unmatched,
            "extra_blocks": max(0, leftover), "missing_blocks": max(0, len(order) - len(blocks))}
