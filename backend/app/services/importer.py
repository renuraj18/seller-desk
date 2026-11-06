"""Bulk import/export of the saree product master (CSV or Excel)."""

import io
import json
import re

import openpyxl
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from ..fields import NUMERIC_FIELDS, PRODUCT_FIELDS, normalise

IMAGE_COLS = [f"image_{i}" for i in range(1, 9)]
EXPORT_KEYS = [f["key"] for f in PRODUCT_FIELDS if f["key"] != "images"] + IMAGE_COLS


def import_template_bytes(products: list[dict] | None = None) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Products"
    labels = {f["key"]: f["label"] for f in PRODUCT_FIELDS}
    header_fill = PatternFill("solid", fgColor="1F4E46")
    for c, key in enumerate(EXPORT_KEYS, start=1):
        cell = ws.cell(row=1, column=c, value=key)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        lab = ws.cell(row=2, column=c, value=labels.get(key, key.replace("_", " ").title()))
        lab.font = Font(italic=True, color="666666")
        lab.alignment = Alignment(wrap_text=True)
        ws.column_dimensions[cell.column_letter].width = 22
    ws.freeze_panes = "B3"
    # dropdown hints for fields that have suggested options
    opt_ws = wb.create_sheet("Options")
    col = 1
    for f in PRODUCT_FIELDS:
        if not f.get("options"):
            continue
        opt_ws.cell(row=1, column=col, value=f["key"]).font = Font(bold=True)
        for r, o in enumerate(f["options"], start=2):
            opt_ws.cell(row=r, column=col, value=o)
        letter = openpyxl.utils.get_column_letter(col)
        target = openpyxl.utils.get_column_letter(EXPORT_KEYS.index(f["key"]) + 1)
        dv = DataValidation(type="list", formula1=f"Options!${letter}$2:${letter}${len(f['options']) + 1}",
                            allow_blank=True, showErrorMessage=False)  # suggestions, free text allowed
        ws.add_data_validation(dv)
        dv.add(f"{target}3:{target}5000")
        col += 1
    for r, p in enumerate(products or [], start=3):
        imgs = p.get("images") or []
        for c, key in enumerate(EXPORT_KEYS, start=1):
            if key in IMAGE_COLS:
                i = IMAGE_COLS.index(key)
                val = imgs[i] if i < len(imgs) else None
            else:
                val = p.get(key)
            ws.cell(row=r, column=c, value=val)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _column_lookup():
    lookup = {}
    for f in PRODUCT_FIELDS:
        for name in [f["key"], f["label"], *f.get("synonyms", [])]:
            lookup.setdefault(normalise(name), f["key"])
    for i, k in enumerate(IMAGE_COLS, start=1):
        lookup[normalise(k)] = k
        lookup[normalise(f"image {i}")] = k
    return lookup


def parse_upload(filename: str, data: bytes) -> tuple[list[dict], list[str]]:
    if filename.lower().endswith(".csv"):
        df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)
    else:
        df = pd.read_excel(io.BytesIO(data), dtype=str, keep_default_na=False, sheet_name=0)
    lookup = _column_lookup()
    colmap = {c: lookup.get(normalise(c)) for c in df.columns}
    unknown = [c for c, k in colmap.items() if not k]
    rows, errors = [], []
    for idx, rec in df.iterrows():
        values = {colmap[c]: str(v).strip() for c, v in rec.items() if colmap.get(c)}
        sku = values.get("sku", "")
        # skip our own label row and blank rows
        if not sku or sku.lower() == "sku":
            continue
        product: dict = {}
        images = []
        for key, val in values.items():
            if key in IMAGE_COLS:
                if val:
                    images.append(val)
                continue
            if key == "images":
                images.extend(u for u in re.split(r"[\n,]+", val) if u.strip())
                continue
            if val == "":
                product[key] = None
                continue
            if key in NUMERIC_FIELDS:
                try:
                    num = float(re.sub(r"[^0-9.\-]", "", val))
                    product[key] = int(num) if key == "stock_qty" else num
                except ValueError:
                    errors.append(f"Row {idx + 2}: '{val}' is not a number for {key}")
                    product[key] = None
            else:
                product[key] = val
        product["images"] = images
        rows.append(product)
    if unknown:
        errors.insert(0, "Ignored columns: " + ", ".join(map(str, unknown)))
    return rows, errors


def to_db_values(product: dict) -> dict:
    out = {}
    for k, v in product.items():
        out[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
    return out
