"""AI-drafted listing content (Claude API), always passed through the same marketplace rules
and SEO check as rule-based content. Falls back to rules when no API key is set.
"""

import json
import re

from ..db import dump, get_conn, row_to_dict, rows_to_dicts
from . import blocked
from . import content as content_svc
from .secrets import get_setting

DEFAULT_MODEL = "claude-sonnet-5-5"

PRODUCT_KEYS = ["sku", "name", "brand", "fabric", "saree_type", "color", "secondary_color", "pattern", "work",
                "border", "pallu", "occasion", "saree_length_m", "blouse_piece", "blouse_length_m", "blouse_fabric",
                "blouse_color", "wash_care", "net_weight_g", "country_of_origin", "keywords", "description"]

SYSTEM = """You write Indian e-commerce listings for sarees that rank well and convert.
Rules you must follow:
- Use ONLY facts given in the product data. Never invent fabric, work, size, purity ("pure silk", "handloom",
  "silk mark"), certifications, discounts or delivery promises.
- No promotional claims (best, top quality, 100%, free shipping, sale, offer) and no ALL CAPS words in titles.
- Write natural English that shoppers in India search with (saree, sari, women, wedding, festive, etc.).
- Return ONLY a JSON object, no markdown."""

MARKETPLACE_BRIEF = {
    "amazon": """Amazon.in (policy from 27 July 2026):
- "title": max 75 characters INCLUDING spaces. Pattern: Brand + Women's + [weave/fabric] + Saree + [blouse info or colour].
  Put the primary keyword in the first 45 characters. No ! $ ? _ { } ^ ¬ ¦ | ; : characters. No word more than twice.
- "highlights": Item Highlights, max 125 characters, comma-separated searchable phrases (colour, pattern, work,
  border, occasion, saree/blouse length) that are NOT already in the title.
- "bullets": exactly 5, each 120-220 characters, starting with a short UPPERCASE label then a colon
  (FABRIC:, SIZE:, DESIGN:, OCCASION:, CARE:).
- "description": 400-1000 characters, plain text paragraphs.
- "search_terms": max 240 bytes, lowercase words separated by spaces, synonyms and long-tail words NOT already in
  the title, no brand names, no ASINs, no repeated words, no commas.""",
    "flipkart": """Flipkart:
- "title": a 40-90 character model/style name made of the most important attributes (Flipkart builds the display
  title from brand + attributes, so this is used as the model name).
- "highlights": "" (empty).
- "bullets": exactly 5 key features, each under 120 characters, no labels.
- "description": 400-1000 characters.
- "search_terms": comma-separated keywords, up to 450 characters.""",
    "meesho": """Meesho:
- "title": product name, 50-100 characters, descriptive: colour + work/pattern + fabric + "Saree" + blouse info.
  No brand needed.
- "highlights": "" (empty).
- "bullets": exactly 5 short selling points under 100 characters.
- "description": 300-800 characters, simple English.
- "search_terms": comma-separated keywords, up to 450 characters.""",
}


class AIError(RuntimeError):
    pass


def keyword_set_for(product: dict) -> dict | None:
    hay = " ".join(str(product.get(k) or "") for k in ("fabric", "saree_type", "name")).lower()
    with get_conn() as c:
        sets = rows_to_dicts(c.execute("SELECT * FROM keyword_sets"))
    best, best_len = None, 0
    for s in sets:
        for term in (s.get("match_terms") or "").split(","):
            t = term.strip().lower()
            if t and t in hay and len(t) > best_len:
                best, best_len = s, len(t)
    return best


def _split(s):
    return [x.strip() for x in re.split(r"[,\n]", s or "") if x.strip()]


def _client():
    key = get_setting("anthropic_api_key_secret")
    if not key:
        raise AIError("Add your Anthropic API key in Settings to use AI drafting")
    import anthropic
    return anthropic.Anthropic(api_key=key)


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise AIError("AI reply was not JSON")
    return json.loads(text[start:end + 1])


def enforce_rules(draft: dict, product: dict, marketplace: str) -> dict:
    """Hard limits applied after the AI (or a person) writes the content."""
    rules = content_svc.MARKETPLACE_RULES[marketplace]
    title = re.sub(r"\s+", " ", str(draft.get("title") or "")).strip()
    if marketplace == "amazon":
        title = "".join(ch for ch in title if ch not in content_svc.AMAZON_BANNED_CHARS)
        title = content_svc._limit_word_repeats(title)
    title = content_svc._truncate_words(title, rules["title_max"])
    hl = str(draft.get("highlights") or "").strip()
    if rules["highlights_max"]:
        hl = content_svc._truncate_words(hl, rules["highlights_max"]).rstrip(",")
    else:
        hl = ""
    bullets = [content_svc._truncate_words(str(b).strip(), rules["bullet_max"])
               for b in (draft.get("bullets") or []) if str(b).strip()][:5]
    st = str(draft.get("search_terms") or "").strip()
    if marketplace == "amazon":
        brand = (product.get("brand") or "").lower()
        seen, words = set(), []
        for w in re.split(r"[\s,]+", st.lower()):
            if w and w not in seen and w != brand:
                seen.add(w)
                words.append(w)
        st = ""
        for w in words:
            cand = f"{st} {w}".strip()
            if len(cand.encode()) > rules["search_terms_max_bytes"]:
                break
            st = cand
    else:
        st = st[:450]
    return blocked.apply({"title": title, "highlights": hl, "bullets": bullets,
                          "description": str(draft.get("description") or "").strip(), "search_terms": st}, marketplace)


def draft_with_ai(product: dict, marketplace: str, brand: str | None = None, model: str | None = None) -> dict:
    kw = keyword_set_for(product)
    data = {k: product.get(k) for k in PRODUCT_KEYS if product.get(k) not in (None, "")}
    if brand:
        data["brand"] = brand
    prompt = [f"Marketplace brief:\n{MARKETPLACE_BRIEF[marketplace]}",
              f"Product data (the only facts you may use):\n{json.dumps(data, ensure_ascii=False, indent=1)}"]
    if kw:
        prompt.append("Keyword plan for this saree type:\n"
                      f"- primary (title): {kw.get('primary_keywords') or '-'}\n"
                      f"- secondary (highlights/bullets): {kw.get('secondary_keywords') or '-'}\n"
                      f"- long tail (search terms): {kw.get('long_tail') or '-'}")
    prompt.append('Reply with JSON: {"title": "", "highlights": "", "bullets": ["", "", "", "", ""], '
                  '"description": "", "search_terms": ""}')
    client = _client()
    msg = client.messages.create(
        model=model or get_setting("ai_model") or DEFAULT_MODEL, max_tokens=1500, system=SYSTEM,
        messages=[{"role": "user", "content": "\n\n".join(prompt)}])
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    draft = enforce_rules(_parse_json(text), product, marketplace)
    draft["source"] = "ai"
    return draft


def save_draft(product: dict, marketplace: str, draft: dict, approved: bool = False) -> dict:
    kw = keyword_set_for(product)
    check = content_svc.seo_check(draft, product, marketplace, _split((kw or {}).get("primary_keywords")))
    with get_conn() as c:
        c.execute(
            "INSERT INTO content_drafts (product_id, marketplace, title, highlights, bullets, description, search_terms, "
            "source, approved, score, issues, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now')) "
            "ON CONFLICT(product_id, marketplace) DO UPDATE SET title=excluded.title, highlights=excluded.highlights, "
            "bullets=excluded.bullets, description=excluded.description, search_terms=excluded.search_terms, "
            "source=excluded.source, approved=excluded.approved, score=excluded.score, issues=excluded.issues, "
            "updated_at=excluded.updated_at",
            (product["id"], marketplace, draft.get("title"), draft.get("highlights"), dump(draft.get("bullets") or []),
             draft.get("description"), draft.get("search_terms"), draft.get("source") or "manual", int(approved),
             check["score"], dump(check["issues"])))
        return row_to_dict(c.execute("SELECT * FROM content_drafts WHERE product_id=? AND marketplace=?",
                                     (product["id"], marketplace)).fetchone())


def get_drafts(product_id: int) -> dict:
    with get_conn() as c:
        rows = rows_to_dicts(c.execute("SELECT * FROM content_drafts WHERE product_id=?", (product_id,)))
    return {r["marketplace"]: r for r in rows}


def content_for_export(product: dict, marketplace: str, brand: str | None = None,
                       title_override: str | None = None) -> dict:
    """Saved draft (AI or edited) wins over rule-based content."""
    gen = content_svc.generate_all(product, marketplace, brand=brand, title_override=title_override)
    d = get_drafts(product["id"]).get(marketplace) if product.get("id") else None
    if d:
        for k in ("title", "highlights", "description", "search_terms"):
            if d.get(k):
                gen[k] = d[k]
        if d.get("bullets"):
            gen["bullets"] = d["bullets"]
            gen["key_features"] = " | ".join(b.split(": ", 1)[-1] for b in d["bullets"])
        if title_override:
            gen["title"] = title_override
        gen["source"] = d.get("source")
    return blocked.apply(gen, marketplace)
