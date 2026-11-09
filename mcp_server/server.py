"""Seller Desk MCP server: lets Claude do the groundwork for a new saree catalog.

Claude researches the marketplace (its own web search), then uses these tools to read the product master and the
marketplace rules, fill product attributes, save keyword sets and SEO content as DRAFTS, map template columns and
dry-run the template fill. It talks to the local Seller Desk app over HTTP (default http://127.0.0.1:8000).

What it deliberately cannot do: approve content, queue or submit uploads, change stock or orders, delete anything,
or read credentials. Those stay with you in Seller Desk."""
import os
import re

import httpx
from mcp.server.mcpserver import MCPServer

BASE_URL = os.environ.get("SELLER_DESK_URL", "http://127.0.0.1:8000").rstrip("/")
MARKETPLACES = ("amazon", "flipkart", "meesho")
LIVE = ("live", "exported")
REQUIRED = ["fabric", "saree_type", "color", "pattern", "occasion", "saree_length_m", "blouse_piece", "hsn",
            "gst_rate", "mrp", "selling_price", "net_weight_g"]
ALLOWED_VALUES_SHOWN = 40

_client = httpx.Client(base_url=BASE_URL, timeout=60)

mcp = MCPServer(
    "seller-desk",
    instructions=(
        "Seller Desk holds the saree product master, marketplace rules, keyword sets, SEO drafts and Excel upload "
        "templates for Amazon.in, Flipkart and Meesho. Use the `new_saree_catalog` prompt as the workflow. Research "
        "with your own web tools, then record what you found here. Everything you write is a draft or master data "
        "for the user to review: you cannot approve content or upload anything."))


class SellerDeskError(RuntimeError):
    pass


def api(method: str, path: str, json=None, params=None):
    try:
        r = _client.request(method, path, json=json, params=params)
    except httpx.HTTPError as e:
        raise SellerDeskError(f"Seller Desk is not reachable at {BASE_URL}. Start it (./start.sh) and retry. ({e})")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise SellerDeskError(f"Seller Desk said {r.status_code}: {detail}")
    return r.json()


def _market(m: str) -> str:
    m = (m or "").lower().strip()
    if m not in MARKETPLACES:
        raise SellerDeskError(f"marketplace must be one of {', '.join(MARKETPLACES)}")
    return m


# ------------------------------------------------------------------ read: the lay of the land

@mcp.tool()
def overview() -> dict:
    """Firms, accounts, upload templates and keyword sets in Seller Desk, and how many sarees exist."""
    return {
        "accounts": [{"id": a["id"], "name": a["name"], "marketplace": a["marketplace"], "firm": a.get("firm_name"),
                      "brand": a.get("brand"), "sku_prefix": a.get("sku_prefix")} for a in api("GET", "/api/accounts")],
        "upload_templates": api("GET", "/api/templates"),
        "keyword_sets": [k["name"] for k in api("GET", "/api/keyword-sets")],
        "product_templates": [{"id": t["id"], "name": t["name"], "fabric": t.get("match_fabric"),
                               "saree_type": t.get("match_saree_type")} for t in api("GET", "/api/product-templates")],
        "products": len(api("GET", "/api/products", params={"limit": 5000})),
    }


@mcp.tool()
def get_marketplace_rules(marketplace: str) -> dict:
    """Content limits (title length, bullets, search-term bytes), blocked words and the product fields Seller Desk
    can fill for a marketplace. Read this before writing any title or keywords."""
    m = _market(marketplace)
    ctx = api("GET", "/api/ext/context", params={"marketplace": m})
    blocked = [b for b in api("GET", "/api/blocked-terms") if b["marketplace"] in (m, "all")]
    limits = _limits(m)
    if m == "meesho":
        langs = api("GET", "/api/settings").get("meesho_languages") or "English"
        limits["description_languages"] = langs
        limits["description_tip"] = (
            f"Write it yourself (no Anthropic key is needed when you do it through this MCP). 900-1400 characters, hard limit 1400, "
            f"multilingual: English first, then ONE short sentence per language in its own script, in this order: {langs}. "
            "Structure: opening line (colour + design + saree type) / one or two short English sentences on colour, motif, border, "
            "pallu / one short sentence per language with the same message / 'Suitable for customers looking for: ...' with 6-8 "
            "English search phrases from the keyword set / then ' --- ' and 8-12 comma-separated keyword tags. "
            "Only facts from the product data; tell readers to check size and fabric in the listing details. No repeated sentences.")
    return {
        "marketplace": m,
        "limits": limits,
        "blocked_words": [{"term": b["term"], "replacement": b["replacement"] or "(removed)"} for b in blocked],
        "data_sources_templates_can_use": [{"key": s["key"], "label": s["label"], "group": s["group"]} for s in ctx["sources"]],
    }


def _limits(m: str) -> dict:
    # Mirrors backend/app/services/content.py MARKETPLACE_RULES; the seo_check tool always reports the live values.
    return {"amazon": {"title_max": 75, "highlights_max": 125, "search_terms_max_bytes": 249, "bullets": 5, "bullet_max": 255,
                       "title_banned_chars": "! $ ? _ { } ^ | ; : # < > * ~"},
            "flipkart": {"title_max": 100, "search_terms_max_bytes": 500, "bullets": 5, "bullet_max": 255},
            "meesho": {"title_max": 100, "search_terms_max_bytes": 500, "bullets": 5, "bullet_max": 255,
                       "description_max": 1400, "description_good_from": 900,
                       "description_tip": "Use 900-1400 characters in the seller's multilingual style: English sentences, then one short sentence per language set in Seller Desk Settings (default Tamil, Hindi, Telugu, Malayalam, Kannada), each in its own script, a 'Suitable for customers looking for: ...' sentence of search phrases, then ' --- ' and 8-12 comma-separated keyword tags. Only facts from the product data."}}[m]


@mcp.tool()
def list_products(query: str = "", limit: int = 50) -> list[dict]:
    """Search the product master by SKU, fabric, colour or type. Returns a short summary per saree."""
    rows = api("GET", "/api/products", params={"q": query, "limit": min(limit, 200)})
    return [{"id": p["id"], "sku": p["sku"], "parent_sku": p["parent_sku"], "name": p["name"], "fabric": p["fabric"],
             "color": p["color"], "saree_type": p["saree_type"], "mrp": p["mrp"], "selling_price": p["selling_price"],
             "listings": p["listing_count"]} for p in rows]


@mcp.tool()
def get_product(product_id: int) -> dict:
    """One saree with all attributes, its listings per account, the missing attributes, and its saved SEO drafts."""
    p = api("GET", f"/api/products/{product_id}")
    drafts = api("GET", f"/api/products/{product_id}/drafts")
    p["missing_attributes"] = [k for k in REQUIRED if p.get(k) in (None, "")] + ([] if p.get("images") else ["images"])
    p["seo_drafts"] = {m: {k: d.get(k) for k in ("title", "highlights", "bullets", "description", "search_terms", "approved", "score", "issues", "source", "saved")}
                       for m, d in drafts["drafts"].items()}
    p["keyword_set_matched"] = (drafts.get("keyword_set") or {}).get("name")
    return p


# ------------------------------------------------------------------ write: master data

PRODUCT_TEXT = ("sku parent_sku name brand fabric saree_type color secondary_color pattern work border pallu occasion "
                "blouse_piece blouse_fabric blouse_color wash_care hsn country_of_origin manufacturer_details "
                "packer_details description keywords").split()
PRODUCT_NUM = ("saree_length_m blouse_length_m net_weight_g pkg_weight_g pkg_length_cm pkg_breadth_cm pkg_height_cm "
               "gst_rate mrp selling_price cost_price packaging_cost stock_qty").split()


def _clean_fields(fields: dict) -> dict:
    bad = [k for k in fields if k not in PRODUCT_TEXT + PRODUCT_NUM + ["images"]]
    if bad:
        raise SellerDeskError(f"Unknown product field(s): {', '.join(bad)}. Allowed: {', '.join(PRODUCT_TEXT + PRODUCT_NUM + ['images'])}")
    return fields


@mcp.tool()
def create_product(sku: str, fields: dict) -> dict:
    """Create a new saree in the product master. `fields` uses Seller Desk's attribute names (fabric, saree_type, color,
    pattern, work, border, pallu, occasion, saree_length_m, blouse_piece, hsn, gst_rate, mrp, selling_price,
    net_weight_g, ... and images as a list of URLs). Sarees of one design share a parent_sku. Stock is left unset."""
    fields = _clean_fields({k: v for k, v in fields.items() if k not in ("sku", "stock_qty")})
    p = api("POST", "/api/products", json={"sku": sku, **fields})
    return {"id": p["id"], "sku": p["sku"], "next": "Use save_content_draft for each marketplace, then ask the user to review."}


@mcp.tool()
def update_product(product_id: int, fields: dict) -> dict:
    """Change attributes of a saree that is not yet listed anywhere. Refuses sarees that are live or exported on any
    account (the user must edit those) and never touches stock."""
    p = api("GET", f"/api/products/{product_id}")
    live = [f"{l['account_name']} ({l['status']})" for l in p["listings"] if l["status"] in LIVE]
    if live:
        raise SellerDeskError(f"{p['sku']} is already listed on {', '.join(live)}. Ask the user to change it in Seller Desk.")
    fields = _clean_fields({k: v for k, v in fields.items() if k not in ("sku", "stock_qty")})
    api("PUT", f"/api/products/{product_id}", json={"sku": p["sku"], **fields})
    return {"id": product_id, "updated": sorted(fields)}


@mcp.tool()
def match_product_template(fabric: str = "", saree_type: str = "") -> list[dict]:
    """Saved product templates (shared defaults like weight, HSN, GST, wash care) that fit a fabric and saree type.
    Use their values for create_product instead of guessing."""
    return api("GET", "/api/product-templates/match", params={"fabric": fabric, "saree_type": saree_type})


@mcp.tool()
def scan_template_variations(template_id: int) -> dict:
    """Look inside the variations folder saved on a product template and list the designs, colours and photo counts it
    holds (read only). Folder layouts: <folder>/<design>/<colour>/photos, <folder>/<colour>/photos, or photos named
    after their colour. Warnings flag unreadable colour names, duplicates and thin photo sets. The folder is the one the
    user saved on the template; you cannot point this anywhere else."""
    return api("GET", f"/api/product-templates/{template_id}/variations")


@mcp.tool()
def add_variations_from_template(template_id: int, parent_sku: str, design: str = "", colours: list[str] | None = None,
                                 attributes: dict | None = None) -> dict:
    """Create one saree per NEW colour found in the template's variations folder: the template's defaults (+ your
    `attributes` overrides), the colour from the folder name, the folder's photos copied into Seller Desk, SKU
    `<parent_sku>-<COLOUR>` and all sharing `parent_sku`. Colours the design already has are skipped, so it is safe to
    run again when new colours arrive. Pass `design` when the folder holds several designs and `colours` to add only some.
    Stock is not set. Run scan_template_variations first and fix its warnings."""
    return api("POST", f"/api/product-templates/{template_id}/variations/import", json={
        "parent_sku": parent_sku, "design": design or None, "colours": colours, "attributes": attributes or {}})


# ------------------------------------------------------------------ keywords and SEO

@mcp.tool()
def list_keyword_sets() -> list[dict]:
    """Saved keyword sets (primary, secondary and long-tail keywords per saree type)."""
    return api("GET", "/api/keyword-sets")


@mcp.tool()
def save_keyword_set(name: str, match_terms: str, primary_keywords: str, secondary_keywords: str = "",
                     long_tail: str = "", notes: str = "") -> dict:
    """Create or update the keyword set called `name`. All lists are comma separated. `match_terms` decides which sarees
    use it (words found in their fabric / type / name, e.g. "kanjivaram,kanchipuram"). Put where each keyword came from
    (e.g. "seen in top 10 Meesho titles, Nov 2026") in `notes`."""
    existing = next((k for k in api("GET", "/api/keyword-sets") if k["name"].lower() == name.lower()), None)
    body = dict(name=name, match_terms=match_terms, primary_keywords=primary_keywords,
                secondary_keywords=secondary_keywords, long_tail=long_tail, notes=notes)
    if existing:
        api("PUT", f"/api/keyword-sets/{existing['id']}", json=body)
        return {"id": existing["id"], "action": "updated"}
    return {"id": api("POST", "/api/keyword-sets", json=body)["id"], "action": "created"}


@mcp.tool()
def seo_check(product_id: int, marketplace: str, title: str, bullets: list[str], description: str,
              search_terms: str = "", highlights: str = "") -> dict:
    """Check content against the marketplace's limits, blocked words, attribute completeness and the keyword set,
    without saving. Returns the content as it would be after hard limits are applied, a 0-100 score and issues."""
    return api("POST", f"/api/products/{product_id}/seo-check/{_market(marketplace)}", json=dict(
        title=title, bullets=bullets, description=description, search_terms=search_terms, highlights=highlights))


@mcp.tool()
def save_content_draft(product_id: int, marketplace: str, title: str, bullets: list[str], description: str,
                       search_terms: str = "", highlights: str = "") -> dict:
    """Save SEO content as an UNAPPROVED draft for one marketplace. Limits and blocked words are enforced when saving.
    Only the user can approve it (Seller Desk → product → content). Only claims the product data supports: never invent
    material, origin or certifications."""
    m = _market(marketplace)
    saved = api("PUT", f"/api/products/{product_id}/drafts/{m}", json=dict(
        title=title, bullets=bullets, description=description, search_terms=search_terms, highlights=highlights,
        approved=False))
    return {"saved": True, "approved": False, "score": saved.get("score"), "issues": saved.get("issues"),
            "title": saved.get("title"), "title_length": len(saved.get("title") or "")}


# ------------------------------------------------------------------ Excel upload templates and form mappings

@mcp.tool()
def list_upload_templates(marketplace: str = "") -> list[dict]:
    """Marketplace Excel templates the user uploaded (the 'master template'), with how many columns are mapped."""
    rows = api("GET", "/api/templates")
    return [r for r in rows if not marketplace or r["marketplace"] == marketplace.lower()]


@mcp.tool()
def get_upload_template(template_id: int) -> dict:
    """Columns of an upload template with their allowed dropdown values and current mapping. `unmapped` lists the
    columns that still need a data source; use get_marketplace_rules for the available source keys."""
    t = api("GET", f"/api/templates/{template_id}")
    mapping = t.get("mapping") or {}
    cols = []
    for c in t.get("columns") or []:
        m = mapping.get(c["letter"]) or {}
        allowed = c.get("allowed") or []
        cols.append({"letter": c["letter"], "header": c["header"], "mapped_to": m.get("source") or None,
                     "fixed_value": m.get("value") or None, "value_map": m.get("value_map") or None,
                     "allowed_values": allowed[:ALLOWED_VALUES_SHOWN], "allowed_count": len(allowed)})
    return {"id": t["id"], "name": t["name"], "marketplace": t["marketplace"], "columns": cols,
            "unmapped": [c["letter"] + ": " + c["header"] for c in cols if not c["mapped_to"] and not c["fixed_value"]]}


@mcp.tool()
def set_template_mapping(template_id: int, mapping: dict) -> dict:
    """Map template columns. `mapping` is {column letter: {"source": key, "value": text for const.custom, "value_map":
    {your value: dropdown value}}}. Merges into the existing mapping (other columns stay). Dropdown columns must end up
    with values from their allowed list: use value_map to translate, and check with dry_run_template_fill."""
    t = api("GET", f"/api/templates/{template_id}")
    letters = {c["letter"] for c in t.get("columns") or []}
    unknown = [k for k in mapping if k not in letters]
    if unknown:
        raise SellerDeskError(f"No such column letter(s): {', '.join(unknown)}")
    for k, v in mapping.items():
        if not isinstance(v, dict) or not re.fullmatch(r"[a-z_.0-9]*", str(v.get("source") or "")):
            raise SellerDeskError(f"Column {k}: give {{'source': '<key>'}}")
    merged = {**(t.get("mapping") or {}), **mapping}
    api("PUT", f"/api/templates/{template_id}", json={"mapping": merged})
    return {"mapped_columns": len([m for m in merged.values() if m.get("source")]), "changed": sorted(mapping)}


@mcp.tool()
def fill_template(template_id: int, account_id: int, product_ids: list[int]) -> dict:
    """Fill the Excel template for these sarees (the real file the user uploads to the portal) and report warnings:
    missing values, values outside a dropdown's allowed list, over-long text. Fix every warning (data, mapping or
    content), then run it again. The file is saved in Seller Desk's exports (download link returned). It is NOT marked
    as exported: the user does that when they upload it. Use dry_run_template_fill as an alias."""
    res = api("POST", f"/api/templates/{template_id}/export", json={
        "account_id": account_id, "product_ids": product_ids, "mark_exported": False})
    return {"file": res["filename"], "products": res["product_count"], "warnings": res["warnings"],
            "download": f"{BASE_URL}/api/exports/{res['export_id']}/download",
            "next": "Fix any warnings and run again; when clean, tell the user to download the file and upload it on the portal."}


@mcp.tool()
def dry_run_template_fill(template_id: int, account_id: int, product_ids: list[int]) -> dict:
    """Same as fill_template: fills the template and reports warnings without marking anything exported."""
    return fill_template(template_id, account_id, product_ids)


@mcp.tool()
def import_meesho_image_links(product_ids: list[int], text: str) -> dict:
    """Store image links the user pasted from Meesho's Image link Generator. `text` holds one block of https links per
    saree (blank line between blocks, in the order of `product_ids`) or a SKU line before each saree's links. The
    first link is Image 1 (front). Google Drive links are refused. They fill Image 1-4 when the Meesho template is filled."""
    res = api("POST", "/api/image-links/paste", json={"marketplace": "meesho", "product_ids": product_ids, "text": text, "save": True})
    return {"saved_for": len(res["links"]), "missing_blocks": res["missing_blocks"], "extra_blocks": res["extra_blocks"],
            "ignored_lines": res["unmatched_lines"][:5]}


@mcp.tool()
def get_field_mappings(marketplace: str) -> list[dict]:
    """Form-field mappings the browser extension has learned or been taught for a marketplace (label → data source)."""
    return [f for f in api("GET", "/api/ext/fields") if f["marketplace"] == _market(marketplace)]


@mcp.tool()
def save_field_mapping(marketplace: str, label: str, source: str, value: str = "", value_map: dict | None = None) -> dict:
    """Teach the extension how to fill one form field on a marketplace's add-catalog page (shared by all accounts).
    `source` is a data source key from get_marketplace_rules, or "" to ignore the field."""
    return api("PUT", f"/api/ext/fields/{_market(marketplace)}", json={
        "label": label, "source": source, "value": value or None, "value_map": value_map or {}})


@mcp.tool()
def payload_preview(product_id: int, account_id: int) -> dict:
    """Exactly what the extension would type into the marketplace form for this saree on this account."""
    d = api("GET", "/api/ext/payload", params={"product_id": product_id, "account_id": account_id})
    return {"values": d["values"], "image_count": len(d["images"]), "content_source": d["content_source"]}


# ------------------------------------------------------------------ the workflow

@mcp.prompt()
def new_saree_catalog(marketplace: str, description: str) -> str:
    """Workflow for listing a new saree catalog: research, keywords, attributes, SEO drafts, template mapping."""
    return f"""Prepare a new saree catalog for {marketplace} in Seller Desk: {description}

1. Call overview and get_marketplace_rules('{marketplace}') for the limits, blocked words and data sources.
2. Research with your web tools: find the current best-selling sarees of this kind on {marketplace} (titles, price
   bands, colours, fabric terms, what buyers ask for). Note which keywords repeat across the top results.
3. match_product_template for defaults (weight, HSN, GST, wash care). Never invent facts about the product itself:
   only fabric, work and claims the user told you or the product data holds. Ask the user for anything missing.
4. save_keyword_set with primary, secondary and long-tail keywords and a note saying where they came from.
5. If a product template with a variations folder fits, scan_template_variations then add_variations_from_template to
   create every colour at once; otherwise create_product (or update_product for unlisted ones) with every attribute you can support; then get_product to see
   missing_attributes and ask the user for those and for photos.
6. For each marketplace write title, 5 bullets, description and search terms (for Meesho follow the description_tip in
   get_marketplace_rules: multilingual, up to 1400 characters); run seo_check, fix the issues, then
   save_content_draft. Stay inside the limits and avoid the blocked words.
7. get_upload_template for the template, set_template_mapping for unmapped columns, value_map for dropdowns, then
   fill_template and fix every warning until it is clean. Use payload_preview to check what the extension would type.
8. Report: what you created, keywords with sources, the remaining gaps, and that the drafts need the user's approval
   in Seller Desk. You cannot approve, queue or upload anything."""


if __name__ == "__main__":
    mcp.run()
