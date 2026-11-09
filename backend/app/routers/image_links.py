from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import get_conn, rows_to_dicts
from ..services import image_links as svc

router = APIRouter(prefix="/api", tags=["image_links"])
Market = Literal["amazon", "flipkart", "meesho"]


@router.get("/image-links")
def list_links(marketplace: Market, product_ids: str):
    ids = [int(x) for x in product_ids.split(",") if x.strip().isdigit()][:500]
    return {"links": svc.get(ids, marketplace)}


class LinksIn(BaseModel):
    links: list[str] = Field(default=[], max_length=20)


@router.put("/products/{product_id}/image-links/{marketplace}")
def put_links(product_id: int, marketplace: Market, body: LinksIn):
    try:
        return {"links": svc.save(product_id, marketplace, body.links)}
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


class ParseIn(BaseModel):
    marketplace: Market
    product_ids: list[int] = Field(min_length=1, max_length=500)    # in the order headerless blocks should be matched
    text: str = Field(max_length=200000)
    save: bool = False


@router.post("/image-links/paste")
def paste(b: ParseIn):
    with get_conn() as c:
        rows = rows_to_dicts(c.execute(f"SELECT id, sku FROM products WHERE id IN ({','.join('?' * len(b.product_ids))})", tuple(b.product_ids)))
    by_id = {r["id"]: r for r in rows}
    ordered = [by_id[i] for i in b.product_ids if i in by_id]
    try:
        res = svc.parse(b.text, ordered)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if b.save:
        for pid, links in res["links"].items():
            svc.save(pid, b.marketplace, links)
    return {**res, "saved": b.save}
