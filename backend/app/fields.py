"""Single source of truth for saree product fields and for the "sources" a marketplace
template column can be filled from. Synonyms are used to auto-map template headers.

Synonyms are compared after normalisation (lowercase, bracket content removed, only a-z0-9 kept).
"""

import re

# Product master fields: key, label, type, group, synonyms (header names seen in templates)
PRODUCT_FIELDS = [
    # --- Basics
    dict(key="sku", label="SKU", type="text", group="Basics", required=True,
         synonyms=["sku", "item_sku", "seller sku", "seller sku id", "sku id", "contribution_sku", "product sku",
                   "product id / style id", "style id", "style code"]),
    dict(key="parent_sku", label="Parent SKU (variants)", type="text", group="Basics",
         synonyms=["parent_sku", "parent sku", "parent sku id"]),
    dict(key="name", label="Style name", type="text", group="Basics",
         help="Short internal / model name, e.g. 'Kanchi Zari Butta'. Titles are generated from attributes.",
         synonyms=["model name", "style name", "model_name", "model"]),
    dict(key="brand", label="Brand", type="text", group="Basics",
         synonyms=["brand", "brand_name", "brand name"]),
    # --- Saree attributes
    dict(key="fabric", label="Saree fabric", type="text", group="Saree",
         options=["Art Silk", "Banarasi Silk", "Chiffon", "Cotton", "Cotton Silk", "Crepe", "Georgette",
                  "Kanjivaram Silk", "Linen", "Net", "Organza", "Pure Silk", "Satin", "Silk Blend",
                  "Soft Silk", "Tussar Silk", "Viscose"],
         synonyms=["fabric", "saree fabric", "fabric type", "fabric_type", "material", "material_type",
                   "material type", "outer material"]),
    dict(key="saree_type", label="Saree type / weave", type="text", group="Saree",
         options=["Banarasi", "Bandhani", "Chanderi", "Kanjivaram", "Kota Doria", "Leheriya", "Mysore Silk",
                  "Paithani", "Patola", "Pochampally", "Printed", "Regular", "Solid", "Tant"],
         synonyms=["saree type", "sareetype", "weave type", "weave", "style", "type"]),
    dict(key="color", label="Colour", type="text", group="Saree",
         synonyms=["color", "colour", "color_name", "color name", "primary color", "primary colour",
                   "saree color", "saree colour", "color_map", "color family"]),
    dict(key="secondary_color", label="Secondary colour", type="text", group="Saree",
         synonyms=["secondary color", "secondary colour", "border color", "border colour"]),
    dict(key="pattern", label="Pattern", type="text", group="Saree",
         options=["Woven Design", "Printed", "Embroidered", "Solid/Plain", "Checked", "Striped", "Floral Print",
                  "Zari Work", "Self Design", "Embellished", "Dyed"],
         synonyms=["pattern", "pattern_type", "pattern type", "print or pattern type", "pattern name",
                   "print type", "design"]),
    dict(key="work", label="Work / embellishment", type="text", group="Saree",
         synonyms=["ornamentation", "ornamentation type", "embellishment", "embellishment feature", "work",
                   "work type", "embroidery type"]),
    dict(key="border", label="Border", type="text", group="Saree",
         synonyms=["border", "border type", "border details", "border style"]),
    dict(key="pallu", label="Pallu", type="text", group="Saree",
         synonyms=["pallu", "pallu details", "pallu type"]),
    dict(key="occasion", label="Occasion", type="text", group="Saree",
         options=["Casual", "Festive", "Party", "Wedding", "Traditional", "Office"],
         synonyms=["occasion", "occasion_type", "occasion type", "event"]),
    dict(key="saree_length_m", label="Saree length (m)", type="number", group="Saree",
         synonyms=["saree length", "sareelength", "saree length in metres", "length", "item_length"]),
    dict(key="blouse_piece", label="Blouse piece", type="text", group="Blouse",
         options=["Unstitched Blouse Piece", "Running Blouse", "Separate Blouse Piece", "Without Blouse"],
         synonyms=["blouse", "blouse piece", "with blouse piece", "blouse included", "blouse type"]),
    dict(key="blouse_length_m", label="Blouse length (m)", type="number", group="Blouse",
         synonyms=["blouse length", "blouselength", "blouse length in metres"]),
    dict(key="blouse_fabric", label="Blouse fabric", type="text", group="Blouse",
         synonyms=["blouse fabric", "blouse material"]),
    dict(key="blouse_color", label="Blouse colour", type="text", group="Blouse",
         synonyms=["blouse color", "blouse colour"]),
    dict(key="wash_care", label="Wash care", type="text", group="Saree",
         options=["Dry Clean Only", "Hand Wash", "Machine Wash", "Gentle Wash"],
         synonyms=["wash care", "care instructions", "care_instructions", "wash_care", "care instruction"]),
    # --- Shipping
    dict(key="net_weight_g", label="Net weight (g)", type="number", group="Shipping",
         synonyms=["net weight", "net weight (gms)", "net weight gms", "item_weight", "item weight", "weight",
                   "net quantity"]),
    dict(key="pkg_weight_g", label="Package weight (g)", type="number", group="Shipping",
         synonyms=["package weight", "package_weight", "shipping weight", "packed weight"]),
    dict(key="pkg_length_cm", label="Package length (cm)", type="number", group="Shipping",
         synonyms=["package length", "package_length", "package_length_cm"]),
    dict(key="pkg_breadth_cm", label="Package breadth (cm)", type="number", group="Shipping",
         synonyms=["package breadth", "package width", "package_width", "package_breadth"]),
    dict(key="pkg_height_cm", label="Package height (cm)", type="number", group="Shipping",
         synonyms=["package height", "package_height"]),
    # --- Tax & price
    dict(key="hsn", label="HSN code", type="text", group="Tax & price",
         help="Common saree HSN: 5007 silk, 5208 cotton, 5407 synthetic. Confirm with your CA.",
         synonyms=["hsn", "hsn code", "hsn id", "hsn_code", "hsncode"]),
    dict(key="gst_rate", label="GST %", type="number", group="Tax & price",
         synonyms=["gst", "gst %", "gst percent", "gst rate", "gstrate", "tax rate"]),
    dict(key="mrp", label="MRP", type="number", group="Tax & price",
         synonyms=["mrp", "maximum retail price", "maximum_retail_price", "list price", "list_price"]),
    dict(key="selling_price", label="Base selling price", type="number", group="Tax & price",
         help="Base price incl. GST. Each account can apply its own markup.", synonyms=[]),
    dict(key="cost_price", label="Cost price", type="number", group="Tax & price",
         help="Your purchase / making cost. Used for P&L.", synonyms=[]),
    dict(key="packaging_cost", label="Packaging cost", type="number", group="Tax & price", synonyms=[]),
    dict(key="stock_qty", label="Stock qty", type="number", group="Tax & price",
         synonyms=["quantity", "stock", "inventory", "stock qty", "available quantity", "fulfillment availability"]),
    # --- Compliance
    dict(key="country_of_origin", label="Country of origin", type="text", group="Compliance",
         synonyms=["country of origin", "country_of_origin", "countryoforigin"]),
    dict(key="manufacturer_details", label="Manufacturer details", type="textarea", group="Compliance",
         synonyms=["manufacturer details", "manufacturer", "manufacturer name", "manufacturer_contact_information",
                   "manufacturer name and address"]),
    dict(key="packer_details", label="Packer details", type="textarea", group="Compliance",
         synonyms=["packer details", "packer", "packer_contact_information", "packer name and address"]),
    # --- Content
    dict(key="description", label="Description (optional — auto-generated if blank)", type="textarea",
         group="Content", synonyms=[]),
    dict(key="keywords", label="Extra keywords (comma separated)", type="text", group="Content", synonyms=[]),
    dict(key="images", label="Image URLs (one per line)", type="images", group="Content", synonyms=[]),
]

PRODUCT_FIELD_KEYS = [f["key"] for f in PRODUCT_FIELDS]
NUMERIC_FIELDS = {f["key"] for f in PRODUCT_FIELDS if f["type"] == "number"}

# Extra sources available when mapping template columns (generated or account-specific values)
EXTRA_SOURCES = [
    dict(key="gen.title", label="Generated title", group="Generated",
         synonyms=["item_name", "product name", "product title", "title", "listing title"]),
    dict(key="gen.highlights", label="Item Highlights (Amazon, 125 chars)", group="Generated",
         synonyms=["item highlights", "item_highlights", "item highlight", "item_highlight"]),
    dict(key="gen.description", label="Generated description", group="Generated",
         synonyms=["product_description", "description", "product description", "long description"]),
    *[dict(key=f"gen.bullet_{i}", label=f"Bullet point {i}", group="Generated",
           synonyms=[f"bullet_point{i}", f"bullet point {i}", f"bulletpoint{i}", f"key feature {i}",
                     f"key features {i}"])
      for i in range(1, 6)],
    dict(key="gen.key_features", label="Key features (bullets joined)", group="Generated",
         synonyms=["key features", "highlights"]),
    dict(key="gen.search_terms", label="Search keywords", group="Generated",
         synonyms=["generic_keywords", "generic keywords", "search terms", "search keywords", "keywords",
                   "search_terms"]),
    dict(key="listing.sku", label="Account SKU (marketplace SKU or prefix+SKU)", group="Account", synonyms=[]),
    dict(key="listing.price", label="Account selling price", group="Account",
         synonyms=["standard_price", "your price", "your selling price", "selling price", "meesho price",
                   "price", "purchasable offer"]),
    dict(key="listing.return_price", label="Wrong/defective return price (= selling price)", group="Account",
         synonyms=["wrong/defective returns price", "wrong defective returns price", "returns price"]),
    dict(key="listing.mrp", label="Account MRP", group="Account", synonyms=[]),
    dict(key="listing.stock", label="Account stock", group="Account", synonyms=[]),
    dict(key="listing.brand", label="Account brand", group="Account", synonyms=[]),
    dict(key="listing.ref", label="ASIN / FSN / listing ID", group="Account",
         synonyms=["asin", "fsn", "listing id", "flipkart serial number"]),
    *[dict(key=f"image.{i}", label=f"Image {i}", group="Images",
           synonyms=([f"image {i}", f"image{i}", f"image url {i}", f"other_image_url{i - 1}",
                      f"other image url{i - 1}", f"other_image_locator_{i - 1}"]
                     + (["main_image_url", "main image", "main image url", "image 1 (front)", "main_product_image_locator"]
                        if i == 1 else [])))
      for i in range(1, 9)],
    dict(key="const.women", label="'Women' (ideal for / gender)", group="Constant",
         synonyms=["ideal for", "department_name", "department", "target_gender", "target gender", "gender"]),
    dict(key="const.custom", label="Custom value…", group="Constant", synonyms=[]),
]


def normalise(text) -> str:
    s = str(text or "").lower()
    s = re.sub(r"\[[^\]]*\]", "", s)          # amazon: item_name[marketplace_id=...]#1.value
    s = re.sub(r"\(.*?mandatory.*?\)|\(.*?optional.*?\)", "", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    s = re.sub(r"value$", "", s) if len(s) > 8 else s
    return s


def all_sources() -> list[dict]:
    product_sources = [dict(key=f"product.{f['key']}", label=f["label"], group="Product",
                            synonyms=f.get("synonyms", []))
                       for f in PRODUCT_FIELDS if f["key"] not in ("images", "description", "keywords", "sku")]
    return EXTRA_SOURCES + product_sources


def _synonym_index():
    idx = []
    for src in all_sources():
        for syn in src["synonyms"]:
            n = normalise(syn)
            if n:
                idx.append((n, src["key"]))
    # SKU column should use the account SKU
    for syn in next(f for f in PRODUCT_FIELDS if f["key"] == "sku")["synonyms"]:
        idx.append((normalise(syn), "listing.sku"))
    return idx


_SYNONYMS = _synonym_index()


def guess_source(header) -> tuple[str | None, float]:
    """Return (source_key, score) for a template header. Exact match wins; otherwise the longest
    synonym (>=5 chars) contained in the header."""
    h = normalise(header)
    if not h:
        return None, 0
    best, best_score = None, 0.0
    for syn, key in _SYNONYMS:
        if h == syn:
            score = 100 + len(syn)
        elif len(syn) >= 5 and syn in h:
            score = len(syn) * (len(syn) / len(h))   # prefer synonyms covering most of the header
        else:
            continue
        if score > best_score:
            best, best_score = key, score
    if best_score and best_score < 2.5:
        return None, 0
    return best, best_score
