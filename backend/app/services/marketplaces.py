"""Marketplace API clients.

Amazon: Selling Partner API (private app, self-authorized). India uses the EU endpoint.
Flipkart: Seller API v3 with a Self Access Application (client-credentials OAuth).
Meesho: no self-service API — inventory comes in via the Supplier Panel download (see inventory.py).
"""

import csv
import gzip
import io
import time

import requests

TIMEOUT = 60


class MarketplaceError(RuntimeError):
    pass


def _check(resp: requests.Response, what: str):
    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except ValueError:
            detail = resp.text[:500]
        raise MarketplaceError(f"{what} failed ({resp.status_code}): {detail}")
    return resp


# --------------------------------------------------------------------------- Amazon

class AmazonClient:
    LWA_URL = "https://api.amazon.com/auth/o2/token"
    ENDPOINT = "https://sellingpartnerapi-eu.amazon.com"     # Amazon.in is served from the EU region
    MARKETPLACE_IN = "A21TJRUUN4KGV"

    REQUIRED = ("client_id", "client_secret", "refresh_token")

    def __init__(self, creds: dict, session: requests.Session | None = None):
        missing = [k for k in self.REQUIRED if not creds.get(k)]
        if missing:
            raise MarketplaceError("Missing Amazon credentials: " + ", ".join(missing))
        self.creds = creds
        self.marketplace_id = creds.get("marketplace_id") or self.MARKETPLACE_IN
        self.s = session or requests.Session()
        self._token, self._token_exp = None, 0

    def token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        r = _check(self.s.post(self.LWA_URL, data={
            "grant_type": "refresh_token", "refresh_token": self.creds["refresh_token"],
            "client_id": self.creds["client_id"], "client_secret": self.creds["client_secret"],
        }, timeout=TIMEOUT), "Amazon login (LWA)")
        body = r.json()
        self._token, self._token_exp = body["access_token"], time.time() + int(body.get("expires_in", 3600))
        return self._token

    def _req(self, method, path, **kw):
        headers = {"x-amz-access-token": self.token(), "content-type": "application/json"}
        for attempt in range(4):
            r = self.s.request(method, self.ENDPOINT + path, headers=headers, timeout=TIMEOUT, **kw)
            if r.status_code == 429 and attempt < 3:      # throttled
                time.sleep(2 ** attempt * 2)
                continue
            return _check(r, f"Amazon {method} {path.split('?')[0]}").json()

    def test(self) -> str:
        data = self._req("GET", "/sellers/v1/marketplaceParticipations")
        names = [p["marketplace"]["name"] for p in data.get("payload", []) if p.get("marketplace")]
        return "Connected. Marketplaces: " + (", ".join(names) or "none")

    def fetch_all_listings(self, poll_seconds=15, max_wait=900) -> list[dict]:
        """GET_MERCHANT_LISTINGS_ALL_DATA: every SKU incl. inactive / zero stock."""
        rep = self._req("POST", "/reports/2021-06-30/reports", json={
            "reportType": "GET_MERCHANT_LISTINGS_ALL_DATA", "marketplaceIds": [self.marketplace_id]})
        report_id, waited = rep["reportId"], 0
        while True:
            st = self._req("GET", f"/reports/2021-06-30/reports/{report_id}")
            status = st.get("processingStatus")
            if status == "DONE":
                break
            if status in ("CANCELLED", "FATAL"):
                raise MarketplaceError(f"Amazon listings report {status.lower()}")
            if waited >= max_wait:
                raise MarketplaceError("Amazon listings report is taking too long; try again later")
            time.sleep(poll_seconds)
            waited += poll_seconds
        doc = self._req("GET", f"/reports/2021-06-30/documents/{st['reportDocumentId']}")
        raw = _check(self.s.get(doc["url"], timeout=TIMEOUT), "Amazon report download").content
        if doc.get("compressionAlgorithm") == "GZIP":
            raw = gzip.decompress(raw)
        return parse_amazon_listings_report(raw)

    def get_listing(self, sku: str, seller_id: str) -> dict:
        from urllib.parse import quote
        return self._req("GET", f"/listings/2021-08-01/items/{seller_id}/{quote(sku, safe='')}"
                                f"?marketplaceIds={self.marketplace_id}"
                                f"&includedData=summaries,attributes,issues,offers,fulfillmentAvailability")

    def product_type_schema(self, product_type: str) -> dict:
        meta = self._req("GET", f"/definitions/2020-09-01/productTypes/{product_type}"
                                f"?marketplaceIds={self.marketplace_id}&requirements=LISTING&locale=en_IN")
        link = meta.get("schema", {}).get("link", {}).get("resource")
        meta["json_schema"] = self.s.get(link, timeout=TIMEOUT).json() if link else None
        return meta

    def search_product_types(self, keywords: str) -> list[dict]:
        data = self._req("GET", f"/definitions/2020-09-01/productTypes?marketplaceIds={self.marketplace_id}"
                                f"&keywords={requests.utils.quote(keywords)}")
        return data.get("productTypes", [])


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def parse_amazon_listings_report(raw: bytes) -> list[dict]:
    reader = csv.DictReader(io.StringIO(_decode(raw)), delimiter="\t")
    out = []
    for r in reader:
        sku = (r.get("seller-sku") or "").strip()
        if not sku:
            continue
        qty = _num(r.get("quantity"))
        out.append({
            "remote_sku": sku, "listing_ref": (r.get("asin1") or "").strip() or None,
            "listing_id": (r.get("listing-id") or "").strip() or None,
            "title": (r.get("item-name") or "").strip() or None, "price": _num(r.get("price")), "mrp": None,
            "stock": int(qty) if qty is not None else None, "status": (r.get("status") or "").strip() or None,
            "image": (r.get("image-url") or "").strip() or None, "raw": r,
        })
    return out


# --------------------------------------------------------------------------- Flipkart

class FlipkartClient:
    TOKEN_URL = "https://api.flipkart.net/oauth-service/oauth/token"
    BASE = "https://api.flipkart.net/sellers"
    REQUIRED = ("client_id", "client_secret")
    STATES = ("ACTIVE", "INACTIVE", "READY_FOR_ACTIVATION", "INACTIVATED_BY_FLIPKART")

    def __init__(self, creds: dict, session: requests.Session | None = None):
        missing = [k for k in self.REQUIRED if not creds.get(k)]
        if missing:
            raise MarketplaceError("Missing Flipkart credentials: " + ", ".join(missing))
        self.creds = creds
        self.s = session or requests.Session()
        self._token, self._token_exp = None, 0

    def token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        r = _check(self.s.get(self.TOKEN_URL, params={"grant_type": "client_credentials", "scope": "Seller_Api"},
                              auth=(self.creds["client_id"], self.creds["client_secret"]), timeout=TIMEOUT),
                   "Flipkart login")
        body = r.json()
        self._token, self._token_exp = body["access_token"], time.time() + int(body.get("expires_in", 3600))
        return self._token

    def _req(self, method, path, **kw):
        headers = {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json"}
        for attempt in range(4):
            r = self.s.request(method, self.BASE + path, headers=headers, timeout=TIMEOUT, **kw)
            if r.status_code == 429 and attempt < 3:
                time.sleep(2 ** attempt * 2)
                continue
            return _check(r, f"Flipkart {method} {path}").json()

    def test(self) -> str:
        self.token()
        data = self._req("POST", "/listings/v3/product/search", json={"batchNo": 0, "internalState": "ACTIVE"})
        return f"Connected. Active listings: {data.get('totalListingsCount', 'unknown')}"

    def fetch_all_listings(self) -> list[dict]:
        out: dict[str, dict] = {}
        for state in self.STATES:
            batch = 0
            while True:
                data = self._req("POST", "/listings/v3/product/search", json={"batchNo": batch, "internalState": state})
                rows = data.get("listingData") or []
                for item in rows:
                    out[item["sku"]] = parse_flipkart_search_item(item)
                if len(rows) < 20 or batch > 2000:
                    break
                batch += 1
        self._add_stock(out)
        return list(out.values())

    def _add_stock(self, listings: dict[str, dict]):
        """Search results carry no stock; fetch it 10 SKUs at a time from listing details."""
        skus = list(listings)
        for i in range(0, len(skus), 10):
            chunk = skus[i:i + 10]
            try:
                data = self._req("GET", "/listings/v3/" + ",".join(requests.utils.quote(s, safe="") for s in chunk))
            except MarketplaceError:
                continue
            for sku, info in (data.get("available") or {}).items():
                if sku in listings:
                    locs = info.get("locations") or []
                    stock = sum(int(l.get("inventory") or 0) for l in locs) if locs else None
                    listings[sku]["stock"] = stock
                    tax = info.get("tax") or {}
                    listings[sku]["raw"]["tax"] = tax


def parse_flipkart_search_item(item: dict) -> dict:
    desc = item.get("product_description") or {}
    return {
        "remote_sku": item["sku"], "listing_ref": item.get("productId"), "listing_id": item.get("listingId"),
        "title": item.get("product_name"), "price": _num(desc.get("ssp")), "mrp": _num(desc.get("mrp")),
        "stock": None, "status": item.get("status"), "image": item.get("product_image_url"), "raw": item,
    }


def client_for(marketplace: str, creds: dict):
    if marketplace == "amazon":
        return AmazonClient(creds)
    if marketplace == "flipkart":
        return FlipkartClient(creds)
    raise MarketplaceError("Meesho has no self-service API. Use 'Upload inventory file' instead.")


CREDENTIAL_FIELDS = {
    "amazon": [
        {"key": "client_id", "label": "LWA Client ID", "secret": False},
        {"key": "client_secret", "label": "LWA Client Secret", "secret": True},
        {"key": "refresh_token", "label": "Refresh token (from 'Authorize app')", "secret": True},
        {"key": "seller_id", "label": "Merchant token / Seller ID", "secret": False},
    ],
    "flipkart": [
        {"key": "client_id", "label": "Application ID", "secret": False},
        {"key": "client_secret", "label": "Application Secret", "secret": True},
    ],
    "meesho": [],
}
