from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import get_conn, row_to_dict, rows_to_dicts
from ..services import ai_writer
from ..services import content as content_svc
from ..services import secrets as sec

router = APIRouter(prefix="/api", tags=["content"])

Market = Literal["amazon", "flipkart", "meesho"]


def _product(pid):
    with get_conn() as c:
        p = row_to_dict(c.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone())
    if not p:
        raise HTTPException(404, "Product not found")
    return p


@router.get("/products/{pid}/drafts")
def drafts(pid: int):
    p = _product(pid)
    saved = ai_writer.get_drafts(pid)
    out = {}
    kw = ai_writer.keyword_set_for(p)
    for m in ("amazon", "flipkart", "meesho"):
        d = saved.get(m)
        if not d:
            d = content_svc.generate_all(p, m)
            chk = content_svc.seo_check(d, p, m, ai_writer._split((kw or {}).get("primary_keywords")))
            d.update(score=chk["score"], issues=chk["issues"], saved=False)
        else:
            d["saved"] = True
        d["rules"] = content_svc.MARKETPLACE_RULES[m]
        out[m] = d
    return {"drafts": out, "keyword_set": kw, "ai_enabled": bool(sec.get_setting("anthropic_api_key_secret"))}


class DraftIn(BaseModel):
    title: str = ""
    highlights: str = ""
    bullets: list[str] = []
    description: str = ""
    search_terms: str = ""
    approved: bool = False


@router.put("/products/{pid}/drafts/{marketplace}")
def save(pid: int, marketplace: Market, body: DraftIn):
    p = _product(pid)
    d = ai_writer.enforce_rules(body.model_dump(), p, marketplace)
    d["source"] = "manual"
    return ai_writer.save_draft(p, marketplace, d, body.approved)


@router.post("/products/{pid}/drafts/{marketplace}/ai")
def ai_draft(pid: int, marketplace: Market):
    p = _product(pid)
    try:
        d = ai_writer.draft_with_ai(p, marketplace)
    except ai_writer.AIError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # API errors, rate limits
        raise HTTPException(502, f"AI drafting failed: {e}")
    return ai_writer.save_draft(p, marketplace, d)


class BulkAI(BaseModel):
    product_ids: list[int]
    marketplaces: list[Market]
    overwrite_approved: bool = False


@router.post("/drafts/ai-bulk")
def ai_bulk(body: BulkAI):
    done, failed = 0, []
    for pid in body.product_ids:
        p = _product(pid)
        existing = ai_writer.get_drafts(pid)
        for m in body.marketplaces:
            if existing.get(m, {}).get("approved") and not body.overwrite_approved:
                continue
            try:
                ai_writer.save_draft(p, m, ai_writer.draft_with_ai(p, m))
                done += 1
            except ai_writer.AIError as e:
                raise HTTPException(400, str(e))
            except Exception as e:  # keep going on single failures
                failed.append(f"{p['sku']} / {m}: {e}")
    return {"drafted": done, "failed": failed[:20]}


@router.delete("/products/{pid}/drafts/{marketplace}")
def reset(pid: int, marketplace: Market):
    with get_conn() as c:
        c.execute("DELETE FROM content_drafts WHERE product_id=? AND marketplace=?", (pid, marketplace))
    return {"ok": True}


# ---- keyword sets

class KeywordSetIn(BaseModel):
    name: str
    match_terms: str = ""
    primary_keywords: str = ""
    secondary_keywords: str = ""
    long_tail: str = ""
    notes: str = ""


@router.get("/keyword-sets")
def list_sets():
    with get_conn() as c:
        return rows_to_dicts(c.execute("SELECT * FROM keyword_sets ORDER BY name"))


@router.post("/keyword-sets")
def create_set(k: KeywordSetIn):
    with get_conn() as c:
        try:
            cur = c.execute("INSERT INTO keyword_sets (name, match_terms, primary_keywords, secondary_keywords, "
                            "long_tail, notes) VALUES (?,?,?,?,?,?)", tuple(k.model_dump().values()))
        except Exception as e:
            raise HTTPException(400, str(e))
        return row_to_dict(c.execute("SELECT * FROM keyword_sets WHERE id=?", (cur.lastrowid,)).fetchone())


@router.put("/keyword-sets/{sid}")
def update_set(sid: int, k: KeywordSetIn):
    with get_conn() as c:
        c.execute("UPDATE keyword_sets SET name=?, match_terms=?, primary_keywords=?, secondary_keywords=?, "
                  "long_tail=?, notes=? WHERE id=?", (*k.model_dump().values(), sid))
        return row_to_dict(c.execute("SELECT * FROM keyword_sets WHERE id=?", (sid,)).fetchone())


@router.delete("/keyword-sets/{sid}")
def delete_set(sid: int):
    with get_conn() as c:
        c.execute("DELETE FROM keyword_sets WHERE id=?", (sid,))
    return {"ok": True}


# ---- settings

class SettingsIn(BaseModel):
    anthropic_api_key: str | None = None
    ai_model: str | None = None


@router.get("/settings")
def get_settings():
    return {"anthropic_api_key": sec.mask(sec.get_setting("anthropic_api_key_secret")),
            "ai_model": sec.get_setting("ai_model") or ai_writer.DEFAULT_MODEL}


@router.put("/settings")
def put_settings(s: SettingsIn):
    if s.anthropic_api_key is not None and not s.anthropic_api_key.startswith("•"):
        sec.set_setting("anthropic_api_key_secret", s.anthropic_api_key.strip() or None)
    if s.ai_model:
        sec.set_setting("ai_model", s.ai_model.strip())
    return get_settings()
