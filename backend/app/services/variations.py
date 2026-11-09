"""Read a folder of colour variations and turn it into sarees.

Layouts understood (the first that fits):
  folder/<design>/<colour>/photos      several designs, a subfolder per colour
  folder/<colour>/photos               the folder itself is one design, a subfolder per colour
  folder/<colour>_1.jpg, <colour>_2.jpg   one design, photos named after their colour
Photos are copied into Seller Desk's own media folder; the originals are never changed or moved."""
import re
import shutil
import uuid
from pathlib import Path

from ..db import get_conn, row_to_dict

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE = 20 * 1024 * 1024
MAX_PHOTOS = 12
GENERIC = {"image", "img", "photo", "pic", "picture", "front", "back", "main", "dsc", "screenshot", "whatsapp image"}


def resolve_dir(raw: str) -> Path:
    p = Path(raw).expanduser()
    if not p.is_absolute():
        raise ValueError("Give the full folder path, for example /Users/you/Sarees/Kanjivaram")
    p = p.resolve()
    if not p.is_dir():
        raise ValueError(f"No folder at {p}")
    return p


def _natural(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _photos(folder: Path, root: Path) -> list[Path]:
    out = []
    for f in sorted(folder.iterdir(), key=lambda x: _natural(x.name)):
        if f.name.startswith(".") or f.suffix.lower() not in IMAGE_EXT or not f.is_file():
            continue
        r = f.resolve()
        if root not in r.parents:          # a link pointing outside the folder is ignored
            continue
        out.append(f)
    return out


def _subdirs(folder: Path) -> list[Path]:
    return [d for d in sorted(folder.iterdir(), key=lambda x: _natural(x.name))
            if d.is_dir() and not d.name.startswith(".") and not d.is_symlink()]


def colour_from(name: str) -> str | None:
    s = re.sub(r"[_\-.]+", " ", Path(name).stem if Path(name).suffix.lower() in IMAGE_EXT else name)
    s = re.sub(r"\(\d+\)", " ", s)
    s = re.sub(r"^\s*\d+\s+", "", s)           # "01 maroon"
    s = re.sub(r"\s+\d+\s*$", "", s)           # "maroon 2"
    s = re.sub(r"\s+", " ", s).strip()
    if not s or s.isdigit() or s.lower() in GENERIC or re.fullmatch(r"(img|dsc|image)\s*\d*", s.lower()):
        return None
    return s.title()


def _flat_variants(folder: Path, root: Path) -> list[dict]:
    groups: dict[str, dict] = {}
    for f in _photos(folder, root):
        c = colour_from(f.name)
        g = groups.setdefault((c or "").lower(), {"colour": c, "folder": str(folder), "images": []})
        g["images"].append(f)
    return list(groups.values())


def scan(raw_dir: str) -> dict:
    root = resolve_dir(raw_dir)
    designs, loose = [], []
    own = _flat_variants(root, root)
    if own:
        designs.append({"design": root.name, "variants": own})
    for sub in _subdirs(root):
        inner = [d for d in _subdirs(sub) if _photos(d, root)]
        if inner:                                           # sub is a design with colour subfolders
            vs = [{"colour": colour_from(d.name), "folder": str(d), "images": _photos(d, root)} for d in inner]
            vs += _flat_variants(sub, root)
            designs.append({"design": sub.name, "variants": vs})
        else:
            imgs = _photos(sub, root)
            if imgs:
                loose.append({"colour": colour_from(sub.name), "folder": str(sub), "images": imgs})
    if loose:
        existing = next((d for d in designs if d["design"] == root.name), None)
        if existing:
            existing["variants"] += loose
        else:
            designs.append({"design": root.name, "variants": loose})
    warnings = []
    for d in designs:
        seen = set()
        for v in d["variants"]:
            key = (v["colour"] or "").lower()
            if not v["colour"]:
                warnings.append(f"{d['design']}: a folder/photo group has no readable colour name ({Path(v['folder']).name})")
            elif key in seen:
                warnings.append(f"{d['design']}: colour {v['colour']} appears twice")
            seen.add(key)
            if len(v["images"]) < 4:
                warnings.append(f"{d['design']} / {v['colour'] or Path(v['folder']).name}: only {len(v['images'])} photo(s); marketplaces like 6+")
            if len(v["images"]) > MAX_PHOTOS:
                warnings.append(f"{d['design']} / {v['colour']}: {len(v['images'])} photos, the first {MAX_PHOTOS} will be used")
    if not designs:
        warnings.append("No photos (jpg, png, webp) found in this folder")
    return {"folder": str(root), "designs": designs, "warnings": warnings}


def _public(scanned: dict) -> dict:
    return {"folder": scanned["folder"], "warnings": scanned["warnings"], "designs": [
        {"design": d["design"], "variants": [
            {"colour": v["colour"], "photos": len(v["images"]), "first_photo": Path(v["images"][0]).name, "folder": v["folder"]}
            for v in d["variants"]]} for d in scanned["designs"]]}


def _template(template_id: int) -> dict:
    with get_conn() as c:
        t = row_to_dict(c.execute("SELECT * FROM product_templates WHERE id=?", (template_id,)).fetchone())
    if not t:
        raise LookupError("Template not found")
    if not t.get("variations_dir"):
        raise ValueError("This template has no variations folder. Set one on the Product templates page.")
    return t


def scan_for_template(template_id: int) -> dict:
    t = _template(template_id)
    return {"template": t["name"], **_public(scan(t["variations_dir"]))}


def _code(colour: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", colour.upper())[:8] or "VAR"


def _copy_photos(files: list[Path]) -> list[str]:
    from ..routers.media import MEDIA_DIR
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    urls = []
    for f in files[:MAX_PHOTOS]:
        if f.stat().st_size > MAX_IMAGE:
            continue
        ext = ".jpg" if f.suffix.lower() == ".jpeg" else f.suffix.lower()
        name = f"{uuid.uuid4().hex}{ext}"
        shutil.copyfile(f, MEDIA_DIR / name)
        urls.append(f"/media/{name}")
    return urls


def import_for_template(template_id: int, parent_sku: str, design: str | None, colours: list[str] | None,
                        overrides: dict, account_ids: list[int]) -> dict:
    from ..fields import PRODUCT_FIELD_KEYS
    from ..routers.product_templates import TEMPLATE_FIELDS
    from ..routers.products import upsert
    t = _template(template_id)
    scanned = scan(t["variations_dir"])
    designs = scanned["designs"]
    if design:
        designs = [d for d in designs if d["design"].lower() == design.lower()]
        if not designs:
            raise ValueError(f"No design folder called {design}. Found: {', '.join(d['design'] for d in scanned['designs']) or 'none'}")
    if len(designs) != 1:
        raise ValueError("The folder holds " + (f"{len(designs)} designs ({', '.join(d['design'] for d in designs)}); say which with `design`."
                                                 if designs else "no photos."))
    parent = parent_sku.strip()
    want = {c.lower() for c in colours} if colours else None
    base = {k: v for k, v in t.items() if k in TEMPLATE_FIELDS and v not in (None, "") and k != "keywords"}
    base.update({k: v for k, v in overrides.items() if k in PRODUCT_FIELD_KEYS and k not in ("sku", "images", "stock_qty", "parent_sku", "color")})
    created, skipped = [], []
    with get_conn() as c:
        have = {(r["color"] or "").lower() for r in c.execute("SELECT color FROM products WHERE parent_sku=?", (parent,))}
        for v in designs[0]["variants"]:
            if not v["colour"]:
                skipped.append({"folder": Path(v["folder"]).name, "reason": "No readable colour in the name: rename the folder or photos"})
                continue
            if want is not None and v["colour"].lower() not in want:
                continue
            if v["colour"].lower() in have:
                skipped.append({"colour": v["colour"], "reason": f"{parent} already has this colour"})
                continue
            sku, n = f"{parent}-{_code(v['colour'])}", 1
            while c.execute("SELECT 1 FROM products WHERE sku=?", (sku,)).fetchone():
                n += 1
                sku = f"{parent}-{_code(v['colour'])}{n}"
            images = _copy_photos(v["images"])
            pid = upsert(c, {**base, "sku": sku, "parent_sku": parent, "color": v["colour"],
                             "name": base.get("name") or f"{parent} {v['colour']}", "images": images})
            for aid in account_ids:
                c.execute("INSERT OR IGNORE INTO listings (product_id, account_id) VALUES (?,?)", (pid, aid))
            have.add(v["colour"].lower())
            created.append({"product_id": pid, "sku": sku, "colour": v["colour"], "photos": len(images)})
    return {"parent_sku": parent, "created": created, "skipped": skipped, "warnings": scanned["warnings"],
            "note": "Stock is left empty. Set it in Inventory."}
