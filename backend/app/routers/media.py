"""Product photos stored on this PC, folder import into designs + colour variants, AI attribute detection."""

import base64
import json
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..db import DATA_DIR, get_conn, row_to_dict
from ..fields import PRODUCT_FIELD_KEYS
from ..services import ai_writer
from ..services.secrets import get_setting
from .products import upsert

router = APIRouter(tags=["media"])

MEDIA_DIR = DATA_DIR / "media"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE = 20 * 1024 * 1024


def media_path(url: str) -> Path | None:
    """/media/<name> → file on disk (or None if it isn't one of ours)."""
    m = re.fullmatch(r"(?:https?://[^/]+)?/media/([A-Za-z0-9_\-]+\.(?:jpg|jpeg|png|webp))", url or "")
    if not m:
        return None
    p = MEDIA_DIR / m.group(1)
    return p if p.exists() else None


@router.get("/media/{name}")
def get_media(name: str):
    if not re.fullmatch(r"[A-Za-z0-9_\-]+\.(jpg|jpeg|png|webp)", name):
        raise HTTPException(404)
    p = MEDIA_DIR / name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "max-age=31536000, immutable"})


@router.post("/api/media")
async def upload_media(files: list[UploadFile] = File(...)):
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in IMAGE_EXT:
            continue
        data = await f.read()
        if len(data) > MAX_IMAGE:
            raise HTTPException(400, f"{f.filename} is larger than 20 MB")
        name = f"{uuid.uuid4().hex}{'.jpg' if ext == '.jpeg' else ext}"
        (MEDIA_DIR / name).write_bytes(data)
        out.append({"filename": f.filename, "url": f"/media/{name}"})
    return out


# ------------------------------------------------------------------ folder import

class VariantIn(BaseModel):
    sku: str
    color: str | None = None
    images: list[str] = []
    stock_qty: int | None = None
    attributes: dict = {}          # per-variant overrides (pattern, border… from AI or the user)


class DesignIn(BaseModel):
    parent_sku: str
    attributes: dict = {}          # shared by all variants (fabric, type, price, mrp, cost, hsn…)
    variants: list[VariantIn]


class FolderImportIn(BaseModel):
    designs: list[DesignIn]
    account_ids: list[int] = []    # queue the new sarees on these accounts


@router.post("/api/products/import-designs")
def import_designs(body: FolderImportIn):
    created, updated, errors = [], 0, []
    with get_conn() as c:
        for d in body.designs:
            shared = {k: v for k, v in d.attributes.items() if k in PRODUCT_FIELD_KEYS and k not in ("sku", "images")}
            multi = len(d.variants) > 1
            for v in d.variants:
                if not v.sku.strip():
                    errors.append(f"{d.parent_sku}: a variant has no SKU")
                    continue
                data = {**shared, **{k: val for k, val in v.attributes.items() if k in PRODUCT_FIELD_KEYS},
                        "sku": v.sku.strip(), "images": v.images,
                        "parent_sku": d.parent_sku.strip() if multi else (shared.get("parent_sku") or None)}
                if v.color:
                    data["color"] = v.color
                if v.stock_qty is not None:
                    data["stock_qty"] = v.stock_qty
                exists = c.execute("SELECT id FROM products WHERE sku=?", (data["sku"],)).fetchone()
                pid = upsert(c, data)
                if exists:
                    updated += 1
                else:
                    created.append(pid)
                for aid in body.account_ids:
                    c.execute("INSERT OR IGNORE INTO listings (product_id, account_id) VALUES (?,?)", (pid, aid))
    return {"created": len(created), "updated": updated, "errors": errors}


# ------------------------------------------------------------------ AI: read attributes from a photo

DETECT_PROMPT = """You are cataloguing a saree for Indian marketplaces from its photo.
Describe only what is clearly visible. Reply with JSON only:
{"color": "main body colour, one or two words (e.g. Maroon, Bottle Green)",
 "secondary_color": "border/pallu colour or empty",
 "pattern": one of ["Woven Design","Printed","Embroidered","Solid/Plain","Checked","Striped","Floral Print","Zari Work","Self Design","Embellished","Dyed"],
 "work": "e.g. Zari Work, Thread Work, Stone Work, Sequins, or empty",
 "border": "short description, e.g. Contrast Zari Border, or empty",
 "pallu": "short description, e.g. Rich Zari Pallu, or empty",
 "fabric_guess": "fabric if the look makes it fairly clear (e.g. Silk, Cotton, Georgette, Organza), else empty",
 "saree_type_guess": "weave/style if clearly recognisable (e.g. Kanjivaram, Banarasi), else empty",
 "photo_notes": "one short line on photo quality for marketplaces (background, lighting, cropping)"}"""


class DetectIn(BaseModel):
    image_url: str


@router.post("/api/ai/detect-attributes")
def detect_attributes(body: DetectIn):
    p = media_path(body.image_url)
    if not p:
        raise HTTPException(400, "Only photos uploaded to Seller Desk can be analysed")
    key = get_setting("anthropic_api_key_secret")
    if not key:
        raise HTTPException(400, "Add your Anthropic API key in Settings to detect attributes from photos")
    import anthropic
    media_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}[p.suffix]
    data = p.read_bytes()
    if len(data) > 5 * 1024 * 1024:
        data, media_type = _shrink(p), "image/jpeg"
    try:
        msg = anthropic.Anthropic(api_key=key).messages.create(
            model=get_setting("ai_model") or ai_writer.DEFAULT_MODEL, max_tokens=500,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                             "data": base64.b64encode(data).decode()}},
                {"type": "text", "text": DETECT_PROMPT}]}])
    except Exception as e:
        raise HTTPException(502, f"AI request failed: {e}")
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    try:
        return ai_writer._parse_json(text)
    except (ai_writer.AIError, json.JSONDecodeError):
        raise HTTPException(502, "AI reply could not be read; try again")


def _shrink(p: Path) -> bytes:
    """Claude accepts images up to 5 MB: resize big phone photos."""
    import io

    from PIL import Image
    im = Image.open(p).convert("RGB")
    im.thumbnail((2000, 2000))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


# ------------------------------------------------------------------ variants of an existing product

class AddVariants(BaseModel):
    colors: list[str]


@router.get("/api/products/{pid}/variants")
def variants(pid: int):
    with get_conn() as c:
        p = row_to_dict(c.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone())
        if not p:
            raise HTTPException(404, "Product not found")
        if not p.get("parent_sku"):
            return [p]
        from ..db import rows_to_dicts
        return rows_to_dicts(c.execute("SELECT * FROM products WHERE parent_sku=? ORDER BY sku", (p["parent_sku"],)))


@router.post("/api/products/{pid}/variants")
def add_variants(pid: int, body: AddVariants):
    """Create colour variants of a saree: same design attributes, new colour, own SKU, no images yet."""
    with get_conn() as c:
        p = row_to_dict(c.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone())
        if not p:
            raise HTTPException(404, "Product not found")
        parent = p.get("parent_sku") or p["sku"]
        if not p.get("parent_sku"):
            c.execute("UPDATE products SET parent_sku=? WHERE id=?", (parent, pid))
        base = {k: v for k, v in p.items() if k in PRODUCT_FIELD_KEYS and k not in ("sku", "images", "color",
                                                                                  "secondary_color", "stock_qty")}
        made = []
        for color in [x.strip() for x in body.colors if x.strip()]:
            sku = f"{parent}-{re.sub(r'[^A-Za-z0-9]+', '', color).upper()[:10]}"
            if c.execute("SELECT 1 FROM products WHERE sku=?", (sku,)).fetchone():
                continue
            made.append(upsert(c, {**base, "sku": sku, "color": color, "parent_sku": parent, "images": []}))
    return {"created": len(made), "parent_sku": parent}
