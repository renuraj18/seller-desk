"""Words a marketplace flags as look-alikes of authorised brands / restricted products.
Matched case-insensitively as whole words; swapped for the replacement, or removed when there is none."""

import re

from ..db import get_conn, rows_to_dicts

TEXT_KEYS = ("title", "highlights", "description", "search_terms")


def terms_for(marketplace: str) -> list[dict]:
    with get_conn() as c:
        return rows_to_dicts(c.execute(
            "SELECT term, replacement FROM blocked_terms WHERE marketplace IN ('all', ?) "
            "ORDER BY LENGTH(term) DESC", (marketplace,)))


def _pattern(term: str):
    return re.compile(r"(?<![A-Za-z0-9])" + r"\s+".join(re.escape(w) for w in term.split()) + r"(?![A-Za-z0-9])", re.I)


def _tidy(s: str) -> str:
    s = re.sub(r"\s+([,.;:|])", r"\1", s)
    s = re.sub(r"([,|])(\s*[,|])+", r"\1", s)
    return re.sub(r"[ \t]{2,}", " ", s).strip(" ,|-")


def _swap(text: str, terms: list[dict]) -> str:
    for t in terms:
        if t["term"].strip():
            text = _pattern(t["term"].strip()).sub(t.get("replacement") or "", text)
    return _tidy(text) if text else text


def find(content: dict, marketplace: str, terms: list[dict] | None = None) -> list[str]:
    """Blocked terms that still appear in the content."""
    terms = terms_for(marketplace) if terms is None else terms
    parts = [str(content.get(k) or "") for k in TEXT_KEYS] + [str(b) for b in content.get("bullets") or []]
    blob = "\n".join(parts)
    return [t["term"] for t in terms if t["term"].strip() and _pattern(t["term"].strip()).search(blob)]


def apply(content: dict, marketplace: str) -> dict:
    """Return the content with every blocked term swapped or removed (also key_features, which is derived from bullets)."""
    terms = terms_for(marketplace)
    if not terms:
        return content
    out = dict(content)
    for k in TEXT_KEYS + ("key_features",):
        if out.get(k):
            out[k] = _swap(str(out[k]), terms)
    if out.get("bullets"):
        out["bullets"] = [b for b in (_swap(str(b), terms) for b in out["bullets"]) if b]
    if out.get("title") is not None:
        out["title_length"] = len(out["title"])
    return out
