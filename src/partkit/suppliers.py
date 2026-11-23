"""Look parts up at DigiKey, Mouser and Farnell through their free APIs.

Each supplier turns its own reply into the same `Offer`, so the rest of
PartKit never cares where data came from. Network calls go through one
`http` function that tests replace with recorded replies.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

from . import credentials

USER_AGENT = "PartKit (https://github.com/Ee0422/partkit)"

# http(method, url, headers, body) -> parsed JSON. Raises SupplierError.
Http = Callable[[str, str, dict, "bytes | None"], dict]


class SupplierError(Exception):
    """A supplier lookup that failed, with a plain-language reason."""


@dataclass
class Offer:
    supplier: str
    supplier_pn: str
    mpn: str
    manufacturer: str = ""
    description: str = ""
    datasheet: str = ""
    url: str = ""
    stock: int | None = None
    price_breaks: list[tuple[int, float]] = field(default_factory=list)
    currency: str = ""
    status: str = ""  # e.g. Active, Obsolete, Not For New Designs
    category: str = ""  # the supplier's own category name
    specs: dict[str, str] = field(default_factory=dict)  # supplier's parameter names

    def unit_price(self, qty: int = 1) -> float | None:
        best = None
        for q, p in sorted(self.price_breaks):
            if q <= qty:
                best = p
        if best is None and self.price_breaks:
            best = sorted(self.price_breaks)[0][1]
        return best


def default_http(method: str, url: str, headers: dict, body: bytes | None = None) -> dict:
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"User-Agent": USER_AGENT, "Accept": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        if e.code in (401, 403):
            raise SupplierError("the API key was refused; check it in Settings") from e
        if e.code == 429:
            raise SupplierError("too many searches today; the free limit resets tomorrow") from e
        raise SupplierError(f"the supplier answered with error {e.code} {detail}".strip()) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SupplierError("couldn't reach the supplier; check your internet connection") from e
    except json.JSONDecodeError as e:
        raise SupplierError("the supplier sent an answer PartKit couldn't read") from e


def _num(v) -> int | None:
    try:
        return int(float(str(v).replace(",", "").split()[0]))
    except (ValueError, IndexError):
        return None


def _price(v) -> float | None:
    """'$0.10', 'RM 0,45', '1,234.50' -> float."""
    t = "".join(c for c in str(v) if c.isdigit() or c in ".,")
    if "," in t and "." in t:
        t = t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


# ---------------------------------------------------------------- DigiKey (API v4)

class DigiKey:
    name = "DigiKey"
    TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"
    SEARCH_URL = "https://api.digikey.com/products/v4/search/keyword"

    def __init__(self, http: Http = default_http, keys: dict | None = None,
                 site: str = "US", currency: str = "USD"):
        self.http = http
        self.keys = keys if keys is not None else credentials.all_for(self.name)
        self.site, self.currency = site, currency
        self._token: tuple[str, float] | None = None

    def _bearer(self) -> str:
        if self._token and self._token[1] > time.time() + 30:
            return self._token[0]
        body = urllib.parse.urlencode({
            "client_id": self.keys.get("client_id", ""), "client_secret": self.keys.get("client_secret", ""),
            "grant_type": "client_credentials",
        }).encode()
        r = self.http("POST", self.TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, body)
        tok = r.get("access_token")
        if not tok:
            raise SupplierError("DigiKey didn't accept the client ID and secret; check them in Settings")
        self._token = (tok, time.time() + float(r.get("expires_in", 600)))
        return tok

    def search(self, mpn: str, limit: int = 10) -> list[Offer]:
        headers = {
            "Authorization": f"Bearer {self._bearer()}",
            "X-DIGIKEY-Client-Id": self.keys.get("client_id", ""),
            "X-DIGIKEY-Locale-Site": self.site, "X-DIGIKEY-Locale-Currency": self.currency,
            "Content-Type": "application/json",
        }
        body = json.dumps({"Keywords": mpn, "Limit": limit}).encode()
        r = self.http("POST", self.SEARCH_URL, headers, body)
        products = list(r.get("ExactMatches") or []) + list(r.get("Products") or [])
        out, seen = [], set()
        for p in products:
            mfr_pn = p.get("ManufacturerProductNumber", "")
            variations = p.get("ProductVariations") or [{}]
            # cut tape is what people buy for prototypes; list it first
            variations = sorted(variations, key=lambda v: "Cut Tape" not in str((v.get("PackageType") or {}).get("Name", "")))
            v = variations[0]
            dk_pn = v.get("DigiKeyProductNumber", "")
            if (mfr_pn, dk_pn) in seen:
                continue
            seen.add((mfr_pn, dk_pn))
            desc = p.get("Description") or {}
            out.append(Offer(
                supplier=self.name, supplier_pn=dk_pn, mpn=mfr_pn,
                manufacturer=(p.get("Manufacturer") or {}).get("Name", ""),
                description=desc.get("ProductDescription", "") or desc.get("DetailedDescription", ""),
                datasheet=p.get("DatasheetUrl", "") or "", url=p.get("ProductUrl", "") or "",
                stock=_num(p.get("QuantityAvailable")),
                price_breaks=[(int(b.get("BreakQuantity", 0)), float(b.get("UnitPrice", 0)))
                              for b in v.get("StandardPricing") or []],
                currency=self.currency,
                status=(p.get("ProductStatus") or {}).get("Status", ""),
                category=(p.get("Category") or {}).get("Name", ""),
                specs={q.get("ParameterText", ""): q.get("ValueText", "")
                       for q in p.get("Parameters") or [] if q.get("ParameterText")},
            ))
        return out


# ---------------------------------------------------------------- Mouser

class Mouser:
    name = "Mouser"
    SEARCH_URL = "https://api.mouser.com/api/v1/search/partnumber"

    def __init__(self, http: Http = default_http, keys: dict | None = None):
        self.http = http
        self.keys = keys if keys is not None else credentials.all_for(self.name)

    def search(self, mpn: str, limit: int = 10) -> list[Offer]:
        url = self.SEARCH_URL + "?" + urllib.parse.urlencode({"apiKey": self.keys.get("api_key", "")})
        body = json.dumps({"SearchByPartRequest": {"mouserPartNumber": mpn, "partSearchOptions": "Exact"}}).encode()
        r = self.http("POST", url, {"Content-Type": "application/json"}, body)
        errors = r.get("Errors") or []
        if errors:
            msg = "; ".join(str(e.get("Message", e)) for e in errors)
            raise SupplierError(f"Mouser said: {msg}")
        out = []
        for p in ((r.get("SearchResults") or {}).get("Parts") or [])[:limit]:
            breaks, cur = [], ""
            for b in p.get("PriceBreaks") or []:
                price = _price(b.get("Price", ""))
                if price is not None:
                    breaks.append((int(b.get("Quantity", 0)), price))
                    cur = b.get("Currency", cur)
            out.append(Offer(
                supplier=self.name, supplier_pn=p.get("MouserPartNumber", ""),
                mpn=p.get("ManufacturerPartNumber", ""), manufacturer=p.get("Manufacturer", ""),
                description=p.get("Description", ""), datasheet=p.get("DataSheetUrl", "") or "",
                url=p.get("ProductDetailUrl", "") or "",
                stock=_num(p.get("AvailabilityInStock") or p.get("Availability")),
                price_breaks=breaks, currency=cur, status=p.get("LifecycleStatus") or "",
                category=p.get("Category", ""),
                specs={a.get("AttributeName", ""): a.get("AttributeValue", "")
                       for a in p.get("ProductAttributes") or [] if a.get("AttributeName")},
            ))
        return out


# ---------------------------------------------------------------- Farnell / element14

class Farnell:
    name = "Farnell"
    SEARCH_URL = "https://api.element14.com/catalog/products"

    def __init__(self, http: Http = default_http, keys: dict | None = None, store: str = "uk.farnell.com"):
        self.http = http
        self.keys = keys if keys is not None else credentials.all_for(self.name)
        self.store = store

    def search(self, mpn: str, limit: int = 10) -> list[Offer]:
        q = {
            "term": f"manuPartNum:{mpn}", "storeInfo.id": self.store,
            "resultsSettings.offset": "0", "resultsSettings.numberOfResults": str(limit),
            "resultsSettings.responseGroup": "large", "callInfo.responseDataFormat": "json",
            "callInfo.apiKey": self.keys.get("api_key", ""),
        }
        r = self.http("GET", self.SEARCH_URL + "?" + urllib.parse.urlencode(q), {}, None)
        ret = r.get("manufacturerPartNumberSearchReturn") or r.get("keywordSearchReturn") or {}
        out = []
        for p in ret.get("products") or []:
            sheets = p.get("datasheets") or []
            out.append(Offer(
                supplier=self.name, supplier_pn=str(p.get("sku", "")),
                mpn=p.get("translatedManufacturerPartNumber", ""), manufacturer=p.get("brandName", ""),
                description=p.get("displayName", ""), datasheet=(sheets[0].get("url", "") if sheets else ""),
                url=f"https://{self.store}/{p.get('sku', '')}",
                stock=_num((p.get("stock") or {}).get("level")),
                price_breaks=[(int(b.get("from", 0)), float(b.get("cost", 0))) for b in p.get("prices") or []],
                status=p.get("productStatus", ""),
                specs={a.get("attributeLabel", ""): a.get("attributeValue", "")
                       for a in p.get("attributes") or [] if a.get("attributeLabel")},
            ))
        return out


# ---------------------------------------------------------------- JLCPCB (no key needed)

class JLCPCB:
    """JLCPCB/LCSC parts through jlcsearch, an open, key-free mirror of JLCPCB's parts list.

    JLCPCB's own API needs an approved application, so this gives JLCPCB
    users their LCSC part numbers (C-numbers), stock and Basic/Extended
    status without any sign-up. It's run by the tscircuit project.
    """

    name = "JLCPCB"
    SEARCH_URL = "https://jlcsearch.tscircuit.com/api/search"

    def __init__(self, http: Http = default_http, keys: dict | None = None):
        self.http = http

    def search(self, mpn: str, limit: int = 10) -> list[Offer]:
        q = urllib.parse.urlencode({"q": mpn, "limit": str(limit), "full": "true"})
        r = self.http("GET", f"{self.SEARCH_URL}?{q}", {}, None)
        out = []
        for c in r.get("components") or []:
            lcsc = str(c.get("lcsc", "")).strip()
            if not lcsc:
                continue
            code = lcsc if lcsc.upper().startswith("C") else f"C{lcsc}"
            basic = c.get("is_basic", c.get("basic"))
            preferred = c.get("is_preferred", c.get("preferred"))
            status = "Basic" if basic else ("Preferred" if preferred else ("Extended" if basic is not None else ""))
            price = _price(c.get("price", "")) if not isinstance(c.get("price"), (int, float)) else float(c["price"])
            out.append(Offer(
                supplier=self.name, supplier_pn=code, mpn=str(c.get("mfr", "")),
                manufacturer=str(c.get("manufacturer", "") or ""),
                description=str(c.get("description", "") or ""),
                datasheet=str(c.get("datasheet", "") or ""),
                url=f"https://jlcpcb.com/partdetail/{code}",
                stock=_num(c.get("stock")),
                price_breaks=[(1, price)] if price is not None else [], currency="USD",
                status=status, category=str(c.get("category", "") or c.get("subcategory", "") or ""),
                specs={"Package / Case": str(c.get("package", ""))} if c.get("package") else {},
            ))
        return out


SUPPLIERS: dict[str, type] = {"DigiKey": DigiKey, "Mouser": Mouser, "Farnell": Farnell, "JLCPCB": JLCPCB}
NO_KEY_NEEDED = {"JLCPCB"}

# Suppliers PartKit can link to but not search (no free public API).
LINK_ONLY: dict[str, str] = {
    "LCSC": "https://www.lcsc.com/search?q={mpn}",
}


def supplier_link(name: str, mpn: str) -> str:
    q = urllib.parse.quote(mpn)
    return {
        "DigiKey": f"https://www.digikey.com/en/products/result?keywords={q}",
        "Mouser": f"https://www.mouser.com/c/?q={q}",
        "Farnell": f"https://uk.farnell.com/search?st={q}",
        "JLCPCB": f"https://jlcpcb.com/parts/componentSearch?searchTxt={q}",
        **{k: v.format(mpn=q) for k, v in LINK_ONLY.items()},
    }.get(name, "")
