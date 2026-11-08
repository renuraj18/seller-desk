import re
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..db import EXPORT_DIR, UPLOAD_DIR, dump, get_conn, row_to_dict, rows_to_dicts
from ..services import template_filler as tf

router = APIRouter(prefix="/api", tags=["templates"])

ALLOWED_EXT = {".xlsx", ".xlsm", ".xls"}


class LayoutIn(BaseModel):
    sheet_name: str
    header_row: int
    data_start_row: int


class ProfileUpdate(BaseModel):
    name: str | None = None
    mapping: dict | None = None
    data_start_row: int | None = None


class ExportIn(BaseModel):
    account_id: int
    product_ids: list[int]
    mark_exported: bool = True


def _profile(c, pid):
    p = row_to_dict(c.execute("SELECT * FROM template_profiles WHERE id=?", (pid,)).fetchone())
    if not p:
        raise HTTPException(404, "Template not found")
    return p


@router.get("/templates")
def list_templates():
    with get_conn() as c:
        rows = rows_to_dicts(c.execute(
            "SELECT id, name, marketplace, original_filename, sheet_name, header_row, data_start_row, columns, "
            "mapping, created_at, updated_at FROM template_profiles ORDER BY marketplace, name"))
    for r in rows:
        r["column_count"] = len(r.pop("columns") or [])
        r["mapped_count"] = sum(1 for m in (r.pop("mapping") or {}).values() if m.get("source"))
    return rows


@router.post("/templates")
async def upload_template(file: UploadFile = File(...), name: str = Form(...),
                          marketplace: Literal["amazon", "flipkart", "meesho"] = Form(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, "Upload the .xlsx, .xlsm or .xls template downloaded from the seller panel")
    stored = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
    stored.write_bytes(await file.read())
    if ext == ".xls":
        stored = tf.convert_xls_to_xlsx(stored)
    try:
        info = tf.analyse(stored)
    except Exception as e:
        stored.unlink(missing_ok=True)
        raise HTTPException(400, f"Could not read this workbook: {e}")
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO template_profiles (name, marketplace, original_filename, stored_path, sheet_name, header_row, "
            "data_start_row, columns, mapping) VALUES (?,?,?,?,?,?,?,?,?)",
            (name, marketplace, file.filename, str(stored), info["sheet_name"], info["header_row"],
             info["data_start_row"], dump(info["columns"]), dump(info["mapping"])))
        p = _profile(c, cur.lastrowid)
    p["sheets"] = info["sheets"]
    p["converted_from_xls"] = ext == ".xls"
    return p


@router.get("/templates/{pid}")
def get_template(pid: int):
    with get_conn() as c:
        p = _profile(c, pid)
    try:
        import openpyxl
        wb = openpyxl.load_workbook(p["stored_path"], read_only=True)
        p["sheets"] = wb.sheetnames
        wb.close()
    except Exception:
        p["sheets"] = [p["sheet_name"]]
    return p


@router.put("/templates/{pid}")
def update_template(pid: int, body: ProfileUpdate):
    with get_conn() as c:
        p = _profile(c, pid)
        c.execute("UPDATE template_profiles SET name=?, mapping=?, data_start_row=?, updated_at=datetime('now') "
                  "WHERE id=?", (body.name or p["name"], dump(body.mapping if body.mapping is not None else p["mapping"]),
                                 body.data_start_row or p["data_start_row"], pid))
        return _profile(c, pid)


@router.post("/templates/{pid}/layout")
def relayout(pid: int, body: LayoutIn):
    """Change sheet / header row: re-reads the columns and keeps mappings for headers that still exist."""
    with get_conn() as c:
        p = _profile(c, pid)
        info = tf.analyse(Path(p["stored_path"]), body.sheet_name, body.header_row, body.data_start_row)
        old_by_header = {col["header"]: p["mapping"].get(col["letter"]) for col in p["columns"]}
        mapping = {}
        for col in info["columns"]:
            prev = old_by_header.get(col["header"])
            mapping[col["letter"]] = prev if prev and prev.get("source") else info["mapping"][col["letter"]]
        c.execute("UPDATE template_profiles SET sheet_name=?, header_row=?, data_start_row=?, columns=?, mapping=?, "
                  "updated_at=datetime('now') WHERE id=?",
                  (body.sheet_name, body.header_row, body.data_start_row, dump(info["columns"]), dump(mapping), pid))
        p = _profile(c, pid)
    p["sheets"] = info["sheets"]
    return p


@router.delete("/templates/{pid}")
def delete_template(pid: int):
    with get_conn() as c:
        p = _profile(c, pid)
        c.execute("DELETE FROM template_profiles WHERE id=?", (pid,))
    Path(p["stored_path"]).unlink(missing_ok=True)
    return {"ok": True}


@router.post("/templates/{pid}/export")
def export(pid: int, body: ExportIn):
    if not body.product_ids:
        raise HTTPException(400, "Select at least one product")
    with get_conn() as c:
        profile = _profile(c, pid)
        account = row_to_dict(c.execute(
            "SELECT a.*, f.name AS firm_name, f.address AS firm_address, f.pincode AS firm_pincode, f.gstin AS firm_gstin "
            "FROM accounts a JOIN firms f ON f.id=a.firm_id WHERE a.id=?", (body.account_id,)).fetchone())
        if not account:
            raise HTTPException(404, "Account not found")
        if account["marketplace"] != profile["marketplace"]:
            raise HTTPException(400, f"This is a {profile['marketplace']} template but the account is "
                                     f"{account['marketplace']}")
        marks = ",".join("?" * len(body.product_ids))
        products = rows_to_dicts(c.execute(f"SELECT * FROM products WHERE id IN ({marks}) ORDER BY sku",
                                           body.product_ids))
        listings = {l["product_id"]: l for l in rows_to_dicts(c.execute(
            f"SELECT * FROM listings WHERE account_id=? AND product_id IN ({marks})",
            (body.account_id, *body.product_ids)))}
        path, warnings = tf.fill(profile, products, account, listings, EXPORT_DIR)
        if body.mark_exported:
            for p in products:
                c.execute("INSERT INTO listings (product_id, account_id, status, last_exported_at) "
                          "VALUES (?,?,'exported',datetime('now')) ON CONFLICT(product_id, account_id) DO UPDATE SET "
                          "last_exported_at=datetime('now'), "
                          "status=CASE WHEN status IN ('draft','rejected') THEN 'exported' ELSE status END",
                          (p["id"], body.account_id))
        cur = c.execute("INSERT INTO exports (profile_id, account_id, product_count, file_path, warnings) "
                        "VALUES (?,?,?,?,?)", (pid, body.account_id, len(products), str(path), dump(warnings)))
        export_id = cur.lastrowid
    return {"export_id": export_id, "filename": path.name, "product_count": len(products), "warnings": warnings}


@router.get("/exports")
def list_exports():
    with get_conn() as c:
        rows = rows_to_dicts(c.execute(
            "SELECT e.id, e.product_count, e.file_path, e.created_at, e.warnings, t.name AS template_name, "
            "a.name AS account_name, a.marketplace FROM exports e LEFT JOIN template_profiles t ON t.id=e.profile_id "
            "LEFT JOIN accounts a ON a.id=e.account_id ORDER BY e.id DESC LIMIT 100"))
    for r in rows:
        r["filename"] = Path(r.pop("file_path") or "").name
        r["warning_count"] = len(r.pop("warnings") or [])
    return rows


@router.get("/exports/{export_id}/download")
def download_export(export_id: int):
    with get_conn() as c:
        row = c.execute("SELECT file_path FROM exports WHERE id=?", (export_id,)).fetchone()
    if not row or not Path(row["file_path"]).exists():
        raise HTTPException(404, "File not found")
    path = Path(row["file_path"])
    if path.resolve().parent != EXPORT_DIR.resolve() or not re.fullmatch(r"[\w.\-]+", path.name):
        raise HTTPException(400, "Invalid file")
    return FileResponse(path, filename=path.name)
