"""Analyse a marketplace bulk-listing template (Amazon flat file .xlsm/.xlsx, Flipkart .xls/.xlsx,
Meesho .xlsx), auto-map its columns to product data, and write filled rows back into the same
workbook so formatting, dropdowns and macros survive.
"""

import re
import shutil
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter, range_boundaries

from ..fields import guess_source, normalise
from .ai_writer import content_for_export
from .pricing import account_price, account_sku

SKIP_SHEET_WORDS = ("instruction", "valid value", "definition", "example", "readme", "help", "guide",
                    "dropdown", "lookup", "browse", "image", "icon", "sample", "data validation")
NON_DATA_HINTS = ("mandatory", "optional", "required", "example", "e.g", "eg:", "please", "enter ",
                  "select ", "accepted", "maximum", "minimum", "characters", "description")


# ---------------------------------------------------------------- loading

def convert_xls_to_xlsx(src: Path) -> Path:
    """Flipkart sometimes ships .xls. openpyxl can't read it, so copy the values into a new .xlsx."""
    import xlrd
    book = xlrd.open_workbook(str(src))
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for sh in book.sheets():
        ws = wb.create_sheet(sh.name[:31])
        for r in range(sh.nrows):
            for c in range(sh.ncols):
                v = sh.cell_value(r, c)
                if v not in ("", None):
                    ws.cell(row=r + 1, column=c + 1, value=v)
    dst = src.with_suffix(".xlsx")
    wb.save(dst)
    return dst


def load_workbook(path: Path, read_only=False):
    keep_vba = path.suffix.lower() == ".xlsm"
    return openpyxl.load_workbook(path, keep_vba=keep_vba, read_only=read_only, data_only=False)


# ---------------------------------------------------------------- analysis

def _row_values(ws, row, max_col):
    return [ws.cell(row=row, column=c).value for c in range(1, max_col + 1)]


def _score_header_row(values) -> tuple[float, int]:
    mapped, nonempty = 0, 0
    for v in values:
        if v is None or str(v).strip() == "":
            continue
        nonempty += 1
        if len(str(v)) > 80:     # instructions, not headers
            continue
        src, _ = guess_source(v)
        if src:
            mapped += 1
    return mapped + nonempty * 0.05, nonempty


def _looks_like_non_data(values) -> bool:
    texts = [str(v) for v in values if v not in (None, "")]
    if not texts:
        return False
    long = sum(1 for t in texts if len(t) > 35)
    hints = sum(1 for t in texts if any(h in t.lower() for h in NON_DATA_HINTS))
    return long / len(texts) > 0.4 or hints / len(texts) > 0.3


def _sheet_dims(ws):
    return min(ws.max_row or 1, 5000), min(ws.max_column or 1, 400)


def detect_layout(wb) -> dict:
    """Find the sheet + header row with the most recognisable columns."""
    best = None
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        if any(w in ws.title.lower() for w in SKIP_SHEET_WORDS):
            continue
        max_row, max_col = _sheet_dims(ws)
        for r in range(1, min(max_row, 15) + 1):
            score, nonempty = _score_header_row(_row_values(ws, r, max_col))
            if nonempty < 3:
                continue
            # ties go to the later row in the same sheet, earlier sheet across sheets
            if best is None or score > best["score"] + 1e-9 or \
                    (abs(score - best["score"]) < 1e-9 and ws.title == best["sheet"]):
                best = {"sheet": ws.title, "header_row": r, "score": score}
    if best is None:
        ws = wb.worksheets[0]
        return {"sheet": ws.title, "header_row": 1, "data_start_row": 2}
    ws = wb[best["sheet"]]
    max_row, max_col = _sheet_dims(ws)
    # Amazon flat files: a human label row is followed by the attribute-name row the feed reads.
    nxt_score, nxt_nonempty = _score_header_row(_row_values(ws, best["header_row"] + 1, max_col))
    if nxt_nonempty >= 3 and nxt_score >= best["score"] * 0.6 and nxt_score >= 3:
        best["header_row"] += 1
    start = best["header_row"] + 1
    while start <= best["header_row"] + 6 and _looks_like_non_data(_row_values(ws, start, max_col)):
        start += 1
    return {"sheet": best["sheet"], "header_row": best["header_row"], "data_start_row": start}


def _resolve_validation_values(wb, ws, formula: str) -> list[str]:
    if not formula:
        return []
    f = formula.strip()
    if f.startswith('"') and f.endswith('"'):
        return [x.strip() for x in f.strip('"').split(",") if x.strip()]
    if f.upper().startswith("INDIRECT") or "OFFSET" in f.upper():
        return []
    f = f.lstrip("=")
    target_ws, ref = ws, f
    if "!" not in f and f in wb.defined_names:
        dests = list(wb.defined_names[f].destinations)
        if not dests:
            return []
        sheet_name, ref = dests[0]
        if sheet_name not in wb.sheetnames:
            return []
        target_ws = wb[sheet_name]
    elif "!" in f:
        sheet_name, ref = f.rsplit("!", 1)
        sheet_name = sheet_name.strip("'")
        if sheet_name not in wb.sheetnames:
            return []
        target_ws = wb[sheet_name]
    try:
        min_col, min_row, max_col, max_row = range_boundaries(ref.replace("$", ""))
    except ValueError:
        return []
    values = []
    for row in target_ws.iter_rows(min_row=min_row, max_row=min(max_row, min_row + 2000),
                                   min_col=min_col, max_col=max_col, values_only=True):
        for v in row:
            if v not in (None, ""):
                values.append(str(v).strip())
    return values


def column_dropdowns(wb, ws, data_start_row: int) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    try:
        validations = ws.data_validations.dataValidation
    except AttributeError:
        return out
    for dv in validations:
        if dv.type != "list":
            continue
        values = _resolve_validation_values(wb, ws, dv.formula1)
        if not values:
            continue
        for rng in str(dv.sqref).split():
            try:
                min_col, min_row, max_col, max_row = range_boundaries(rng)
            except ValueError:
                continue
            if max_row is not None and max_row < data_start_row:
                continue
            for c in range(min_col, (max_col or min_col) + 1):
                out.setdefault(c, values)
    return out


def analyse(path: Path, sheet: str | None = None, header_row: int | None = None,
            data_start_row: int | None = None) -> dict:
    wb = load_workbook(path)
    layout = detect_layout(wb) if not sheet else {"sheet": sheet, "header_row": header_row or 1,
                                                    "data_start_row": data_start_row or (header_row or 1) + 1}
    if sheet and header_row and data_start_row:
        layout.update(header_row=header_row, data_start_row=data_start_row)
    ws = wb[layout["sheet"]]
    _, max_col = _sheet_dims(ws)
    drops = column_dropdowns(wb, ws, layout["data_start_row"])
    # A label row sits above Amazon's attribute-name row; show it as a friendlier caption
    label_row = layout["header_row"] - 1 if layout["header_row"] > 1 else None
    columns, mapping = [], {}
    for c in range(1, max_col + 1):
        header = ws.cell(row=layout["header_row"], column=c).value
        if header in (None, ""):
            continue
        letter = get_column_letter(c)
        label = ws.cell(row=label_row, column=c).value if label_row else None
        caption = str(label).strip() if label and len(str(label)) < 80 else None
        src, _ = guess_source(header)
        if not src and caption:
            src, _ = guess_source(caption)
        columns.append({"index": c, "letter": letter, "header": str(header).strip(), "label": caption,
                        "allowed": drops.get(c, [])[:500]})
        mapping[letter] = {"source": src or "", "value": "", "value_map": {}}
    return {
        "sheet_name": layout["sheet"], "header_row": layout["header_row"],
        "data_start_row": layout["data_start_row"], "sheets": wb.sheetnames,
        "columns": columns, "mapping": mapping,
    }


# ---------------------------------------------------------------- filling

def _fmt_number(v):
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


CONSTANTS = {"const.free_size": "Free Size", "const.one": 1, "const.saree": "Saree"}


def resolve_value(source: str, const_value, product: dict, account: dict, listing: dict | None,
                  generated: dict):
    if not source:
        return None
    if source == "const.custom":
        return const_value
    if source == "const.women":
        return "Women"
    if source in CONSTANTS:
        return CONSTANTS[source]
    if source.startswith("firm."):
        return account.get(f"firm_{source[5:]}")
    if source.startswith("product."):
        return _fmt_number(product.get(source[8:]))
    if source.startswith("image."):
        i = int(source.split(".")[1]) - 1
        imgs = product.get("images") or []
        return imgs[i] if i < len(imgs) else None
    if source.startswith("gen."):
        key = source[4:]
        if key.startswith("bullet_"):
            i = int(key.split("_")[1]) - 1
            return generated["bullets"][i] if i < len(generated["bullets"]) else None
        return generated.get(key)
    if source == "listing.sku":
        return account_sku(product, account, listing)
    if source == "listing.parent_sku":
        parent = product.get("parent_sku")
        return f"{account.get('sku_prefix') or ''}{parent}" if parent else None
    if source == "listing.price":
        return _fmt_number(account_price(product, account, listing))
    if source == "listing.return_price":
        # Meesho "Wrong/Defective Returns Price": selling price minus the account's offset (default ₹30)
        price = account_price(product, account, listing)
        if price is None:
            return None
        less = account.get("return_price_less")
        less = 30 if less is None else less
        return _fmt_number(max(0.0, float(price) - float(less)))
    if source == "listing.mrp":
        return _fmt_number((listing or {}).get("mrp") or product.get("mrp"))
    if source == "listing.stock":
        v = (listing or {}).get("stock_qty")
        return v if v is not None else product.get("stock_qty")
    if source == "listing.brand":
        return account.get("brand") or product.get("brand")
    if source == "listing.ref":
        return (listing or {}).get("listing_ref")
    return None


def _match_allowed(value, allowed: list[str]):
    """Snap a value to the template's dropdown list. Returns (value, ok)."""
    if value is None or not allowed:
        return value, True
    sval = str(_fmt_number(value)).strip()
    if sval in allowed:
        return sval, True
    low = {a.lower(): a for a in allowed}
    if sval.lower() in low:
        return low[sval.lower()], True
    norm = {normalise(a): a for a in allowed}
    if normalise(sval) in norm:
        return norm[normalise(sval)], True
    # numeric dropdowns, e.g. GST "5" vs "5%" / "GST_5"
    num = re.sub(r"[^0-9.]", "", sval)
    if num:
        for a in allowed:
            if re.sub(r"[^0-9.]", "", a) == num and num:
                return a, True
    return value, False


def fill(profile: dict, products: list[dict], account: dict, listings: dict[int, dict],
         out_dir: Path) -> tuple[Path, list[dict]]:
    src_path = Path(profile["stored_path"])
    suffix = src_path.suffix.lower()
    out_name = (f"{account['marketplace']}_{re.sub(r'[^A-Za-z0-9]+', '-', account['name'])}_"
                f"{re.sub(r'[^A-Za-z0-9]+', '-', profile['name'])}_{datetime.now():%Y%m%d-%H%M%S}{suffix}")
    out_path = out_dir / out_name
    shutil.copyfile(src_path, out_path)
    wb = load_workbook(out_path)
    ws = wb[profile["sheet_name"]]
    allowed_by_letter = {c["letter"]: c.get("allowed") or [] for c in profile["columns"]}
    header_by_letter = {c["letter"]: c.get("label") or c["header"] for c in profile["columns"]}
    warnings: list[dict] = []
    marketplace = account["marketplace"]
    brand = account.get("brand") or None

    for i, product in enumerate(products):
        row = profile["data_start_row"] + i
        listing = listings.get(product["id"])
        generated = content_for_export(product, marketplace, brand=brand,
                                       title_override=(listing or {}).get("title_override"))
        for letter, m in profile["mapping"].items():
            source = m.get("source")
            if not source:
                continue
            value = resolve_value(source, m.get("value"), product, account, listing, generated)
            vmap = m.get("value_map") or {}
            if value is not None and str(value) in vmap:
                value = vmap[str(value)]
            value, ok = _match_allowed(value, allowed_by_letter.get(letter, []))
            if not ok:
                warnings.append({"sku": product["sku"], "column": header_by_letter.get(letter, letter),
                                 "value": str(value), "issue": "not in dropdown list",
                                 "allowed_sample": allowed_by_letter[letter][:15]})
            ws[f"{letter}{row}"] = value
    wb.save(out_path)
    return out_path, warnings
