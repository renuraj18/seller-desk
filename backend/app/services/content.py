"""Rule-based listing content for sarees, tuned per marketplace.

No external AI calls: content is built from the product attributes so it is consistent across
6 accounts and never invents facts. Limits are kept in MARKETPLACE_RULES so they are easy to change
when a marketplace updates its policy.
"""

import re

MARKETPLACE_RULES = {
    # Amazon (from 27 Jul 2026): title <= 75 chars incl. spaces + searchable Item Highlights <= 125 chars
    "amazon": {"title_max": 75, "highlights_max": 125, "search_terms_max_bytes": 249, "bullets": 5,
               "bullet_max": 255},
    "flipkart": {"title_max": 100, "highlights_max": 0, "search_terms_max_bytes": 500, "bullets": 5,
                 "bullet_max": 255},
    "meesho": {"title_max": 100, "highlights_max": 0, "search_terms_max_bytes": 500, "bullets": 5,
               "bullet_max": 255},
}

# Amazon rejects titles containing these characters (plus pipes/semicolons/colons per title rules)
AMAZON_BANNED_CHARS = set("!$?_{}^¬¦~#<>*|;:")


def _v(p, key):
    val = p.get(key)
    if val is None:
        return ""
    if isinstance(val, float) and val.is_integer():
        val = int(val)
    return str(val).strip()


def _clean_spaces(s: str) -> str:
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s+([,)])", r"\1", s)
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"(,\s*)+", ", ", s)
    return s.strip(" ,-")


def _limit_word_repeats(title: str, max_repeats: int = 2) -> str:
    """Amazon: a word may not appear more than twice in a title (articles/prepositions excepted)."""
    allowed = {"a", "an", "and", "or", "for", "with", "of", "the", "in", "on", "by", "to", "&", "-", ","}
    counts: dict[str, int] = {}
    out = []
    for word in title.split(" "):
        k = re.sub(r"[^a-z0-9]", "", word.lower())
        if k and k not in allowed:
            counts[k] = counts.get(k, 0) + 1
            if counts[k] > max_repeats:
                continue
        out.append(word)
    return _clean_spaces(" ".join(out))


def _truncate_words(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,-(")


def _dedupe_phrase(*parts) -> list[str]:
    """Drop parts already contained in earlier parts (e.g. fabric 'Banarasi Silk' + type 'Banarasi')."""
    out: list[str] = []
    for p in parts:
        p = (p or "").strip()
        if not p:
            continue
        words = {w.lower() for w in p.split()}
        joined = {w.lower() for part in out for w in part.split()}
        if words <= joined:
            continue
        # a later, more specific part replaces an earlier one it contains ("Kanjivaram" -> "Kanjivaram Silk")
        out = [o for o in out if not {w.lower() for w in o.split()} <= words]
        out.append(p)
    return out


def _blouse_phrase(p) -> str:
    b = _v(p, "blouse_piece").lower()
    if not b or "without" in b or b in ("no", "n", "false", "0"):
        return ""
    if "running" in b:
        return "with Running Blouse"
    if "stitched" in b and "un" not in b:
        return "with Stitched Blouse"
    return "with Blouse Piece"


def generate_title(p: dict, marketplace: str, brand: str | None = None) -> str:
    brand = (brand or _v(p, "brand")).strip()
    fabric, stype, color = _v(p, "fabric"), _v(p, "saree_type"), _v(p, "color")
    pattern, work, occasion = _v(p, "pattern"), _v(p, "work"), _v(p, "occasion")
    if stype.lower() in ("regular", "solid", "printed"):
        stype_main = ""
    else:
        stype_main = stype
    core = " ".join(_dedupe_phrase(stype_main, fabric)) + " Saree"
    blouse = _blouse_phrase(p)
    limit = MARKETPLACE_RULES[marketplace]["title_max"]

    if marketplace == "amazon":
        # 75 chars: Brand + Women's + weave/fabric + Saree + blouse; colour if it still fits.
        # Everything else goes to Item Highlights.
        title = f"{brand} Women's {core} {blouse}"
        if color and len(title) + len(color) + 2 <= limit:
            title = f"{brand} Women's {color} {core} {blouse}"
        title = "".join(ch for ch in title if ch not in AMAZON_BANNED_CHARS)
        title = _limit_word_repeats(_clean_spaces(title))
        if len(title) > limit:                     # drop the blouse phrase before cutting words
            title = _clean_spaces(f"{brand} Women's {core}")
    elif marketplace == "meesho":
        # Meesho: descriptive, no brand needed
        title = " ".join(_dedupe_phrase(color, pattern, work)) + f" {core} {blouse}"
    else:
        # Flipkart builds the display title from brand + attributes; this goes into model/style name
        title = " ".join(_dedupe_phrase(pattern, stype_main, fabric)) + " Saree"
        if _v(p, "name"):
            title = f"{_v(p, 'name')} {title}"
            title = " ".join(_dedupe_phrase(*title.split()))
    return _truncate_words(_clean_spaces(title), limit)


def generate_bullets(p: dict) -> list[str]:
    fabric, stype, color = _v(p, "fabric"), _v(p, "saree_type"), _v(p, "color")
    saree_len, blouse_len = _v(p, "saree_length_m"), _v(p, "blouse_length_m")
    bullets = []

    if fabric:
        b = f"FABRIC: {fabric} saree"
        if stype and stype.lower() not in fabric.lower():
            b += f" in {stype} style"
        bullets.append(b + ".")

    size = []
    if saree_len:
        size.append(f"Saree length {saree_len} m")
    blouse = _v(p, "blouse_piece")
    if blouse and "without" not in blouse.lower():
        bl = f"{blouse}"
        if blouse_len:
            bl += f" of {blouse_len} m"
        if _v(p, "blouse_fabric"):
            bl += f" in {_v(p, 'blouse_fabric')}"
        if _v(p, "blouse_color"):
            bl += f" ({_v(p, 'blouse_color')})"
        size.append(bl)
    elif blouse:
        size.append("Comes without blouse piece")
    if size:
        bullets.append("SIZE: " + "; ".join(size) + ".")

    design = []
    if color:
        design.append(f"{color} colour" + (f" with {_v(p, 'secondary_color')}" if _v(p, "secondary_color") else ""))
    for label, key in (("pattern", "pattern"), ("work", "work"), ("border", "border"), ("pallu", "pallu")):
        if _v(p, key):
            val = _v(p, key)
            design.append(val if label in val.lower() else f"{val} {label}")
    if design:
        bullets.append("DESIGN: " + ", ".join(design) + ".")

    if _v(p, "occasion"):
        bullets.append(f"OCCASION: Ideal for {_v(p, 'occasion').lower()} wear; pair with traditional jewellery "
                       f"for a complete ethnic look.")
    if _v(p, "wash_care"):
        bullets.append(f"CARE: {_v(p, 'wash_care')}.")
    if len(bullets) < 5 and _v(p, "country_of_origin"):
        bullets.append(f"ORIGIN: Made in {_v(p, 'country_of_origin')}.")
    return bullets[:5]


def generate_description(p: dict, brand: str | None = None) -> str:
    if _v(p, "description"):
        return _v(p, "description")
    brand = (brand or _v(p, "brand")).strip()
    fabric, stype, color = _v(p, "fabric"), _v(p, "saree_type"), _v(p, "color")
    core = " ".join(_dedupe_phrase(color, stype if stype.lower() not in ("regular",) else "", fabric)) or "This"
    s = [f"Drape elegance with this {core} saree" + (f" from {brand}" if brand else "") + "."]
    det = [x for x in (_v(p, "pattern"), _v(p, "work")) if x]
    if det:
        s.append(f"It features {' and '.join(det).lower()}" +
                 (f", a {_v(p, 'border').lower()} border" if _v(p, "border") else "") +
                 (f" and a {_v(p, 'pallu').lower()} pallu" if _v(p, "pallu") else "") + ".")
    if _v(p, "saree_length_m"):
        s.append(f"The saree measures {_v(p, 'saree_length_m')} metres" +
                 (f" and comes with a {_v(p, 'blouse_length_m')} metre blouse piece"
                  if _v(p, "blouse_length_m") and "without" not in _v(p, "blouse_piece").lower() else "") + ".")
    if _v(p, "occasion"):
        s.append(f"A great choice for {_v(p, 'occasion').lower()} occasions.")
    if _v(p, "wash_care"):
        s.append(f"Care: {_v(p, 'wash_care')}.")
    return " ".join(s)


def generate_search_terms(p: dict, marketplace: str) -> str:
    fabric, stype, color, occ = (_v(p, k).lower() for k in ("fabric", "saree_type", "color", "occasion"))
    terms = [
        f"{fabric} saree", f"{stype} saree", "saree for women", "sari", "sarees for women latest design",
        f"{color} saree", f"{occ} saree", "ethnic wear", "saree with blouse piece", "traditional saree",
        f"{fabric} sari", "women saree",
    ]
    terms += [t.strip().lower() for t in _v(p, "keywords").split(",")]
    brand = _v(p, "brand").lower()
    seen, words = set(), []
    for t in terms:
        for w in t.split():
            if w and w not in seen and w != brand and len(w) > 1:
                seen.add(w)
                words.append(w)
    max_bytes = MARKETPLACE_RULES[marketplace]["search_terms_max_bytes"]
    out = ""
    for w in words:
        candidate = f"{out} {w}".strip()
        if len(candidate.encode("utf-8")) > max_bytes:
            break
        out = candidate
    return out


def generate_highlights(p: dict, marketplace: str) -> str:
    """Amazon Item Highlights: comma-separated searchable phrases, <= 125 chars."""
    limit = MARKETPLACE_RULES[marketplace]["highlights_max"]
    if not limit:
        return ""
    parts = _dedupe_phrase(
        _v(p, "pattern"), _v(p, "work"),
        f"{_v(p, 'border')} Border" if _v(p, "border") else "",
        f"{_v(p, 'occasion')} Wear" if _v(p, "occasion") else "",
        f"{_v(p, 'saree_length_m')} m Saree" if _v(p, "saree_length_m") else "",
        f"{_v(p, 'blouse_length_m')} m Blouse" if _v(p, "blouse_length_m") else "",
        _v(p, "wash_care"),
    )
    out = ""
    for part in parts:
        cand = f"{out}, {part}" if out else part
        if len(cand) > limit:
            break
        out = cand
    return "".join(ch for ch in out if ch not in "!$?_{}^¬¦")


def seo_check(content: dict, product: dict, marketplace: str, primary_keywords: list[str] | None = None) -> dict:
    """Score 0-100 with a list of issues to fix before export."""
    rules = MARKETPLACE_RULES[marketplace]
    issues, score = [], 100
    title = content.get("title") or ""

    def bad(points, msg):
        nonlocal score
        score -= points
        issues.append(msg)

    if not title:
        bad(40, "Title is empty")
    elif len(title) > rules["title_max"]:
        bad(25, f"Title is {len(title)} chars; limit is {rules['title_max']}")
    elif len(title) < min(40, rules["title_max"] - 20):
        bad(5, "Title is short — room for a key attribute")
    if marketplace == "amazon":
        if any(ch in AMAZON_BANNED_CHARS for ch in title):
            bad(15, "Title has characters Amazon rejects (! $ ? _ { } ^ | ; : etc.)")
        if title != _limit_word_repeats(title):
            bad(10, "A word appears more than twice in the title")
        hl = content.get("highlights") or ""
        if not hl:
            bad(10, "Item Highlights empty — 125 searchable characters unused")
        elif len(hl) > rules["highlights_max"]:
            bad(10, f"Item Highlights is {len(hl)} chars; limit is {rules['highlights_max']}")
        st = content.get("search_terms") or ""
        if len(st.encode()) > rules["search_terms_max_bytes"]:
            bad(10, f"Search terms are {len(st.encode())} bytes; limit is {rules['search_terms_max_bytes']}")
        brand = (product.get("brand") or "").lower()
        if brand and brand in st.lower().split():
            bad(5, "Remove the brand name from search terms")
    if primary_keywords:
        head = title[:45].lower()
        if not any(k.lower() in head for k in primary_keywords if k):
            bad(10, "Primary keyword not in the first 45 characters of the title")
    bullets = [b for b in (content.get("bullets") or []) if b]
    if len(bullets) < 5:
        bad(5, f"Only {len(bullets)} of 5 bullet points")
    if len(content.get("description") or "") < 150:
        bad(5, "Description under 150 characters")
    required = ["fabric", "saree_type", "color", "pattern", "occasion", "saree_length_m", "blouse_piece", "hsn",
                "gst_rate", "mrp", "selling_price", "net_weight_g"]
    missing = [k for k in required if product.get(k) in (None, "")]
    if missing:
        bad(min(30, 3 * len(missing)), "Missing attributes: " + ", ".join(missing))
    imgs = product.get("images") or []
    if len(imgs) < 4:
        bad(10, f"{len(imgs)} images — aim for 6+ (front, drape, pallu, border, blouse, close-up)")
    return {"score": max(0, score), "issues": issues}


def generate_all(p: dict, marketplace: str, brand: str | None = None, title_override: str | None = None) -> dict:
    title = title_override or generate_title(p, marketplace, brand)
    bullets = generate_bullets(p)
    out = {
        "marketplace": marketplace,
        "title": title,
        "title_length": len(title),
        "title_max": MARKETPLACE_RULES[marketplace]["title_max"],
        "highlights": generate_highlights(p, marketplace),
        "bullets": bullets,
        "key_features": " | ".join(b.split(": ", 1)[-1] for b in bullets),
        "description": generate_description(p, brand),
        "search_terms": generate_search_terms(p, marketplace),
        "source": "rules",
    }
    return out
