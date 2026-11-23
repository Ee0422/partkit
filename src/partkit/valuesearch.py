"""Find resistors and capacitors by value, size and spec at JLCPCB.

Type what you'd write on a schematic, such as "1k 0603 1%" or
"100nF 0603 50V X7R", and PartKit lists the matching JLCPCB parts, Basic
parts first. It uses jlcsearch's resistor and capacitor lists, which carry
proper numbers (ohms, farads, volts), so a 68.1k part never shows up for 1k.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, replace

from .suppliers import Http, Offer, SupplierError, default_http

BASE = "https://jlcsearch.tscircuit.com"

_SIZE = re.compile(r"^(01005|0201|0402|0603|0805|1206|1210|1812|2010|2220|2512)$")
_DIELECTRIC = re.compile(r"^(C0G|NP0|COG|X5R|X6S|X7R|X7S|X7T|X8R|Y5V|Z5U)$", re.I)
_MULT = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3,
         "r": 1, "k": 1e3, "M": 1e6, "g": 1e9}
_WORDS_R = {"r", "res", "resistor", "resistors", "ohm", "ohms"}
_WORDS_C = {"c", "cap", "caps", "capacitor", "capacitors", "mlcc", "ceramic"}
_FILLER = {"smd", "chip", "thick", "film", "1/10w", "1/16w", "1/8w", "1/4w"}


@dataclass
class ValueQuery:
    kind: str                   # "R" or "C"
    value: float                # ohms or farads
    package: str = ""
    tolerance: float | None = None   # fraction: 0.01 = 1%
    voltage: float | None = None     # minimum volts
    power: float | None = None       # minimum watts
    dielectric: str = ""

    def describe(self) -> str:
        bits = [format_ohms(self.value) if self.kind == "R" else format_farads(self.value)]
        if self.package:
            bits.append(self.package)
        if self.tolerance is not None:
            bits.append(f"{self.tolerance * 100:g}%")
        if self.voltage is not None:
            bits.append(f"≥{self.voltage:g}V")
        if self.power is not None:
            bits.append(f"≥{self.power:g}W")
        if self.dielectric:
            bits.append(self.dielectric)
        return " ".join(bits)


# The filters the search tab shows for each kind, and the choices in them.
FILTER_FIELDS = {"R": ("package", "tolerance", "power"), "C": ("package", "voltage", "dielectric", "tolerance")}
SIZES = ("0201", "0402", "0603", "0805", "1206", "1210")
VOLTAGES = (6.3, 10, 16, 25, 50, 100)
DIELECTRICS = ("C0G", "X5R", "X7R")
TOLERANCES = {"R": (0.001, 0.01, 0.05), "C": (0.05, 0.1, 0.2)}
POWERS = (0.0625, 0.1, 0.125, 0.25, 0.5)


def filters_of(q: ValueQuery) -> dict:
    """The filter fields a query sets (only the ones that are set)."""
    return {f: getattr(q, f) for f in FILTER_FIELDS[q.kind] if getattr(q, f) not in (None, "")}


def with_filters(q: ValueQuery, filters: dict, only_unset: bool = False) -> ValueQuery:
    """The query with these filter fields; only_unset keeps what was typed (for 'my usual')."""
    changes = {}
    for f in FILTER_FIELDS[q.kind]:
        if f not in filters:
            continue
        if only_unset and getattr(q, f) not in (None, ""):
            continue
        changes[f] = filters[f] if filters[f] is not None else ("" if f in ("package", "dielectric") else None)
    return replace(q, **changes)


def encode_filters(filters: dict) -> str:
    """'package=0603;voltage=50' - how 'my usual' is kept in the settings file."""
    return ";".join(f"{k}={v}" for k, v in filters.items() if v not in (None, ""))


def decode_filters(text: str) -> dict:
    out: dict = {}
    for bit in (text or "").split(";"):
        k, _, v = bit.partition("=")
        k, v = k.strip(), v.strip()
        if not v:
            continue
        if k in ("package", "dielectric"):
            out[k] = v
        elif k in ("tolerance", "voltage", "power"):
            try:
                out[k] = float(v)
            except ValueError:
                pass
    return out


def format_ohms(v: float) -> str:
    for scale, p in ((1e6, "M"), (1e3, "k"), (1, "")):
        if v >= scale or scale == 1:
            return f"{v / scale:.4g}{p}Ω"
    return f"{v:g}Ω"


def format_farads(v: float) -> str:
    for scale, p in ((1e-6, "µ"), (1e-9, "n"), (1e-12, "p")):
        if v >= scale * 0.9999 or scale == 1e-12:
            return f"{v / scale:.4g}{p}F"
    return f"{v:g}F"


def _resistance(tok: str) -> float | None:
    """1k, 4k7, 4.7k, 10K, 1M, 100R, 0R, 47Ω, 220ohm, 100 (only with a resistor word)."""
    t = tok.replace("Ω", "").replace("ohms", "").replace("ohm", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([rRkKmM])(\d*)", t)
    if m:
        unit = m.group(2)
        mult = {"r": 1, "k": 1e3, "m": 1e6}[unit.lower()]
        if unit == "m":  # a lowercase m on a resistor means mega in practice (1m = 1M)
            mult = 1e6
        num = m.group(1) + ("." + m.group(3) if m.group(3) else "")
        return float(num) * mult
    if t != tok and re.fullmatch(r"\d+(?:\.\d+)?", t):  # "47Ω"
        return float(t)
    return None


def _capacitance(tok: str) -> float | None:
    """100nF, 100n, 0.1uF, 4u7, 10p, 1µF."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([pnuµμ])(\d*)[fF]?", tok)
    if not m:
        m2 = re.fullmatch(r"(\d+(?:\.\d+)?)([pnuµμ]?)[fF]", tok)
        if not m2 or not m2.group(2):
            return None
        return float(m2.group(1)) * _MULT[m2.group(2)]
    num = m.group(1) + ("." + m.group(3) if m.group(3) else "")
    return float(num) * _MULT[m.group(2)]


def parse(text: str) -> ValueQuery | None:
    """Read a value search, or return None if the text looks like a part number."""
    toks = [t for t in re.split(r"[\s,;]+", text.strip()) if t]
    if not toks or len(toks) > 8:
        return None
    kind = ""
    value = None
    q = ValueQuery(kind="", value=0)
    for tok in toks:
        low = tok.lower()
        if low in _WORDS_R:
            kind = kind or "R"
            continue
        if low in _WORDS_C:
            kind = kind or "C"
            continue
        if low in _FILLER:
            continue
        if _SIZE.match(tok):
            q.package = tok
            continue
        if _DIELECTRIC.match(tok):
            d = tok.upper()
            q.dielectric = "C0G" if d in ("NP0", "COG") else d
            kind = kind or "C"
            continue
        m = re.fullmatch(r"[±+]?(\d+(?:\.\d+)?)%", tok)
        if m:
            q.tolerance = float(m.group(1)) / 100
            continue
        m = re.fullmatch(r"(\d+(?:\.\d+)?)(k?)[vV]", tok)
        if m:
            q.voltage = float(m.group(1)) * (1000 if m.group(2) else 1)
            kind = kind or "C"
            continue
        m = re.fullmatch(r"(\d+(?:\.\d+)?)(m?)[wW]", tok)
        if m:
            q.power = float(m.group(1)) / (1000 if m.group(2) else 1)
            kind = kind or "R"
            continue
        c = _capacitance(tok)
        if c is not None and value is None:
            value, kind = c, "C"
            continue
        r = _resistance(tok)
        if r is not None and value is None:
            value, kind = r, kind or "R"
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", tok) and value is None:
            value = float(tok)  # a bare number: ohms, if a resistor word says so
            continue
        return None  # an unknown word: treat the whole thing as a part number
    if value is None or not kind:
        return None
    if kind == "C" and value >= 1e-3:  # "100" with "cap": nothing sensible
        return None
    q.kind, q.value = kind, value
    return q


# ---------------------------------------------------------------- jlcsearch

def _close(a: float | None, b: float, rel: float = 0.005) -> bool:
    return a is not None and abs(a - b) <= abs(b) * rel + 1e-15


def _f(v) -> float | None:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _status(row: dict) -> str:
    if row.get("is_basic"):
        return "Basic"
    if row.get("is_preferred"):
        return "Preferred"
    return "Extended"


def _offer(row: dict, kind: str) -> Offer:
    lcsc = str(row.get("lcsc", "")).strip()
    code = lcsc if lcsc.upper().startswith("C") else f"C{lcsc}"
    specs: dict[str, str] = {}
    if row.get("package"):
        specs["Package / Case"] = str(row["package"])
    tol = _f(row.get("tolerance_fraction"))
    if tol is not None:
        specs["Tolerance"] = f"{tol * 100:g}%"
    if kind == "R":
        if _f(row.get("resistance")) is not None:
            specs["Resistance"] = format_ohms(float(row["resistance"]))
        if _f(row.get("power_watts")) is not None:
            w = float(row["power_watts"])
            specs["Power"] = f"{w / 1000:g}W" if w >= 20 else f"{w:g}W"  # jlcsearch gives mW for some rows
        cat = "Chip Resistor - Surface Mount"
    else:
        if _f(row.get("capacitance_farads")) is not None:
            specs["Capacitance"] = format_farads(float(row["capacitance_farads"]))
        if _f(row.get("voltage_rating")) is not None:
            specs["Voltage Rating"] = f"{float(row['voltage_rating']):g}V"
        if row.get("temperature_coefficient"):
            specs["Temperature Coefficient"] = str(row["temperature_coefficient"])
        cat = "Multilayer Ceramic Capacitors MLCC - SMD/SMT"
    price = _f(row.get("price1"))
    return Offer(
        supplier="JLCPCB", supplier_pn=code, mpn=str(row.get("mfr", "") or ""),
        manufacturer=str(row.get("manufacturer", "") or ""),
        description=str(row.get("description", "") or ""),
        url=f"https://jlcpcb.com/partdetail/{code}",
        stock=int(row["stock"]) if _f(row.get("stock")) is not None else None,
        price_breaks=[(1, price)] if price is not None else [], currency="USD",
        status=_status(row), category=cat, specs=specs,
    )


def _matches(row: dict, q: ValueQuery) -> bool:
    if q.package and str(row.get("package", "")).strip() != q.package:
        return False
    if q.kind == "R":
        if row.get("is_potentiometer") or row.get("is_multi_resistor_chip"):
            return False
        if (_f(row.get("number_of_resistors")) or 1) > 1:
            return False
        if not _close(_f(row.get("resistance")), q.value):
            return False
        if q.power is not None:
            w = _f(row.get("power_watts"))
            if w is None:
                return False
            w = w / 1000 if w >= 20 else w
            if w + 1e-9 < q.power:
                return False
    else:
        if row.get("is_polarized"):
            return False
        if not _close(_f(row.get("capacitance_farads")), q.value, rel=0.01):
            return False
        if q.voltage is not None and (_f(row.get("voltage_rating")) or 0) + 1e-9 < q.voltage:
            return False
        if q.dielectric:
            tc = str(row.get("temperature_coefficient", "")).upper().replace("NP0", "C0G").replace("COG", "C0G")
            if q.dielectric not in tc:
                return False
    if q.tolerance is not None:
        t = _f(row.get("tolerance_fraction"))
        if t is None or t > q.tolerance + 1e-9:
            return False
    return True


def _rank(o: Offer) -> tuple:
    order = {"Basic": 0, "Preferred": 1, "Extended": 2}
    return (order.get(o.status, 3), -(o.stock or 0))


def by_value(q: ValueQuery, http: Http = default_http, limit: int = 50) -> list[Offer]:
    """JLCPCB parts that match the query, Basic first, then by stock.

    jlcsearch wants plain numbers (ohms, farads) and returns at most 100
    rows, so PartKit asks twice: once for Basic parts only, so they're never
    cut off, and once for everything.
    """
    if q.kind == "R":
        path, key = "/resistors/list.json", "resistors"
        params = {"resistance": f"{q.value:.6g}"}
    else:
        path, key = "/capacitors/list.json", "capacitors"
        params = {"capacitance": f"{q.value:.6g}"}
    if q.package:
        params["package"] = q.package
    rows: list[dict] = []
    seen: set[str] = set()
    for extra in ({"is_basic": "true"}, {}):
        r = http("GET", f"{BASE}{path}?{urllib.parse.urlencode({**params, **extra})}", {}, None)
        if not isinstance(r, dict):
            raise SupplierError("JLCPCB parts list sent an unexpected reply.")
        for row in r.get(key) or []:
            code = str(row.get("lcsc", ""))
            if code and code not in seen:
                seen.add(code)
                rows.append(row)
    if not any(_matches(row, q) for row in rows):
        rows = _from_text_search(q, http)  # same parts, read from the plain search instead
    out = [_offer(row, q.kind) for row in rows if _matches(row, q)]
    out = [o for o in out if o.supplier_pn != "C"]
    out.sort(key=_rank)
    return out[:limit]


def _from_text_search(q: ValueQuery, http: Http) -> list[dict]:
    """Back-up route: the plain search, with values read from each description."""
    from .search import _value  # local import: search imports suppliers too

    words = (format_ohms(q.value).replace("Ω", "") if q.kind == "R" else format_farads(q.value).replace("µ", "u"))
    text = " ".join(x for x in (words, q.package, "resistor" if q.kind == "R" else "capacitor") if x)
    r = http("GET", f"{BASE}/api/search?{urllib.parse.urlencode({'q': text, 'limit': '100', 'full': 'true'})}",
             {}, None)
    rows = []
    for c in (r.get("components") or []) if isinstance(r, dict) else []:
        d = str(c.get("description", ""))
        row = dict(c)
        m = re.search(r"±\s*([\d.]+)\s*%", d)
        if m:
            row["tolerance_fraction"] = float(m.group(1)) / 100
        if q.kind == "R":
            row["resistance"] = _value(d, r"ohms?|Ω|Ohm")
            pw = _value(d, r"W\b")
            row["power_watts"] = pw
        else:
            row["capacitance_farads"] = _value(d.replace("uF", "µF"), r"F\b")
            row["voltage_rating"] = _value(d, r"V\b")
            m = re.search(r"\b(C0G|NP0|X5R|X6S|X7R|X7S|X7T|X8R|Y5V)\b", d.upper())
            row["temperature_coefficient"] = m.group(1) if m else ""
        row["price1"] = c.get("price1", c.get("price"))
        rows.append(row)
    return rows
