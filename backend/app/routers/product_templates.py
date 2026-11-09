from typing import Literal

from fastapi import APIRouter, HTTPException

from ..db import get_conn, row_to_dict, rows_to_dicts
from ..fields import PRODUCT_FIELD_KEYS

router = APIRouter(prefix="/api", tags=["product_templates"])

# Fields that can be set from a template (exclude SKU, images, name, parent_sku)
TEMPLATE_FIELDS = {
    "fabric", "saree_type", "pattern", "work", "border", "pallu", "occasion",
    "saree_length_m", "blouse_piece", "blouse_length_m", "blouse_fabric", "blouse_color",
    "wash_care", "net_weight_g", "pkg_weight_g", "pkg_length_cm", "pkg_breadth_cm", "pkg_height_cm",
    "hsn", "gst_rate", "mrp", "selling_price", "cost_price", "packaging_cost",
    "country_of_origin", "manufacturer_details", "packer_details",
    "description", "keywords", "brand"
}

@router.get("/product-templates")
def list_templates():
    with get_conn() as c:
        rows = c.execute(
            "SELECT * FROM product_templates WHERE active=1 ORDER BY name"
        )
        return rows_to_dicts(rows)

@router.get("/product-templates/match")
def match_template(fabric: str = "", saree_type: str = ""):
    """Find matching template based on fabric and saree_type"""
    with get_conn() as c:
        query = "SELECT * FROM product_templates WHERE active=1"
        params = []
        
        if fabric:
            query += " AND (match_fabric LIKE ? OR match_fabric = '' OR match_fabric IS NULL)"
            params.append(f"%{fabric}%")
        if saree_type:
            query += " AND (match_saree_type LIKE ? OR match_saree_type = '' OR match_saree_type IS NULL)"
            params.append(f"%{saree_type}%")
        
        query += " ORDER BY name"
        rows = c.execute(query, params)
        return rows_to_dicts(rows)

@router.get("/product-templates/{template_id}")
def get_template(template_id: int):
    with get_conn() as c:
        row = c.execute("SELECT * FROM product_templates WHERE id=?", (template_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Template not found")
        return row_to_dict(row)

@router.post("/product-templates")
def create_template(data: dict):
    # Filter only allowed fields
    template_data = {k: v for k, v in data.items() if k in TEMPLATE_FIELDS or k in ("name", "match_fabric", "match_saree_type", "active")}
    if not template_data.get("name"):
        raise HTTPException(400, "Template name is required")
    
    with get_conn() as c:
        # Check name uniqueness
        if c.execute("SELECT 1 FROM product_templates WHERE name=?", (template_data["name"],)).fetchone():
            raise HTTPException(400, "A template with this name already exists")
        
        cols = ", ".join(template_data.keys())
        placeholders = ", ".join("?" * len(template_data))
        cur = c.execute(f"INSERT INTO product_templates ({cols}) VALUES ({placeholders})", tuple(template_data.values()))
        template_id = cur.lastrowid
        # Fetch within the same transaction
        row = c.execute("SELECT * FROM product_templates WHERE id=?", (template_id,)).fetchone()
        if not row:
            raise HTTPException(500, "Failed to create template")
        return row_to_dict(row)

@router.put("/product-templates/{template_id}")
def update_template(template_id: int, data: dict):
    template_data = {k: v for k, v in data.items() if k in TEMPLATE_FIELDS or k in ("name", "match_fabric", "match_saree_type", "active")}
    if not template_data:
        raise HTTPException(400, "No valid fields to update")
    
    with get_conn() as c:
        # Check name uniqueness if changed
        if "name" in template_data:
            if c.execute("SELECT 1 FROM product_templates WHERE name=? AND id<>?", (template_data["name"], template_id)).fetchone():
                raise HTTPException(400, "A template with this name already exists")
        
        sets = ", ".join(f"{k}=?" for k in template_data)
        c.execute(f"UPDATE product_templates SET {sets}, updated_at=datetime('now') WHERE id=?", (*template_data.values(), template_id))
        return get_template(template_id)

@router.delete("/product-templates/{template_id}")
def delete_template(template_id: int):
    with get_conn() as c:
        c.execute("DELETE FROM product_templates WHERE id=?", (template_id,))
    return {"ok": True}

@router.post("/product-templates/{template_id}/apply")
def apply_template(template_id: int, data: dict):
    """Apply a template to product data (for preview or pre-fill)"""
    with get_conn() as c:
        template = c.execute("SELECT * FROM product_templates WHERE id=? AND active=1", (template_id,)).fetchone()
        if not template:
            raise HTTPException(404, "Template not found")
    
    # Merge template with provided data (data takes precedence)
    template_dict = row_to_dict(template)
    merged = {}
    for key in TEMPLATE_FIELDS:
        if key in data and data[key] not in (None, ""):
            merged[key] = data[key]
        elif template_dict.get(key) not in (None, ""):
            merged[key] = template_dict[key]
    
    return {"template": template_dict, "merged": merged}