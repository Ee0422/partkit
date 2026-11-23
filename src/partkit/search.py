"""Find a part at your preferred suppliers and fill in its details.

`find` asks each supplier you have set up, in your order, and keeps going
past one that fails. `apply_offers` writes what was found into a part:
manufacturer, description, datasheet, supplier part numbers for the BOM,
and the specs that tell same-size parts apart (voltage, dielectric...).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import credentials
from . import fields as F
from .config import Settings
from .library import Library, Part
from .suppliers import NO_KEY_NEEDED, SUPPLIERS, Http, Offer, SupplierError, default_http


@dataclass
class SearchResult:
    mpn: str
    offers: list[Offer] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    not_set_up: list[str] = field(default_factory=list)

    @property
    def exact(self) -> list[Offer]:
        key = _norm(self.mpn)
        return [o for o in self.offers if _norm(o.mpn) == key]

    def best(self) -> list[Offer]:
        """One offer per supplier, exact MPN matches first, in your supplier order."""
        pool = self.exact or self.offers
        out, seen = [], set()
        for o in pool:
            if o.supplier not in seen:
                out.append(o)
                seen.add(o.supplier)
        return out


def _norm(mpn: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", mpn.upper())


def make_client(name: str, settings: Settings, http: Http = default_http):
    if name == "DigiKey":
        return SUPPLIERS[name](http=http, site=settings.digikey_site, currency=settings.digikey_currency)
    if name == "Farnell":
        return SUPPLIERS[name](http=http, store=settings.farnell_store)
    return SUPPLIERS[name](http=http)


def find(mpn: str, settings: Settings, http: Http = default_http, clients: dict | None = None) -> SearchResult:
    res = SearchResult(mpn=mpn.strip())
    for name in settings.suppliers:
        if name not in SUPPLIERS:
            continue  # link-only suppliers such as LCSC
        if clients and name in clients:
            client = clients[name]
        elif name in NO_KEY_NEEDED or credentials.is_set_up(name):
            client = make_client(name, settings, http)
        else:
            res.not_set_up.append(name)
            continue
        try:
            found = client.search(res.mpn)
        except SupplierError as e:
            res.messages.append(f"{name}: {e}")
            continue
        res.offers += found
        if not found:
            res.messages.append(f"{name}: no match for {res.mpn}")
    if res.not_set_up and not res.offers:
        if len(res.not_set_up) == len([n for n in settings.suppliers if n in SUPPLIERS and n not in NO_KEY_NEEDED]):
            res.messages.append(
                "No supplier keys set up, and that's fine: click Get CAD files to fetch the part. "
                "(Optional: a free Mouser key also fills in supplier numbers, stock and price.)")
        else:
            res.messages.append("Not searched (no key yet, optional): " + ", ".join(res.not_set_up) + ".")
    return res


# ---------------------------------------------------------------- specs

_SPEC_NAMES: dict[str, str] = {
    "resistance": "Resistance",
    "tolerance": "Tolerance",
    "power (watts)": "Power", "power rating": "Power", "power": "Power",
    "capacitance": "Capacitance",
    "voltage - rated": "Voltage Rating", "voltage rating": "Voltage Rating",
    "voltage rating - dc": "Voltage Rating", "voltage rating dc": "Voltage Rating", "rated voltage": "Voltage Rating",
    "dielectric": "Dielectric", "temperature characteristic": "Dielectric", "dielectric characteristic": "Dielectric",
    "package / case": "Size", "package/case": "Size", "case code - in": "Size", "case/package": "Size",
    "size / dimension": "Size",
    "height - seated (max)": "Height", "thickness (max)": "Height", "height": "Height",
    "inductance": "Inductance",
    "current rating (amps)": "Rated Current", "current rating": "Rated Current", "rated current": "Rated Current",
    "current - saturation (isat)": "Saturation Current", "saturation current": "Saturation Current",
    "dc resistance (dcr)": "DCR", "dc resistance": "DCR", "dc resistance max": "DCR",
    "shielding": "Shielding",
    "impedance @ frequency": "Impedance at 100MHz",
    "frequency": "Frequency", "load capacitance": "Load Capacitance", "frequency stability": "Stability",
    "pitch": "Pitch", "pitch - mating": "Pitch",
    "number of positions": "Pins", "number of contacts": "Pins", "number of rows": "Rows",
    "mounting type": "Mounting", "mounting style": "Mounting", "series": "Series",
    "voltage - supply": "Supply Voltage", "supply voltage": "Supply Voltage",
    "voltage - dc reverse (vr) (max)": "Reverse Voltage",
    "current - average rectified (io)": "Forward Current",
    "voltage - forward (vf) (max) @ if": "Forward Voltage",
    "fet type": "Type", "transistor type": "Type", "diode type": "Type",
    "drain to source voltage (vdss)": "Vds/Vce", "current - continuous drain (id) @ 25°c": "Id/Ic",
    "rds on (max) @ id, vgs": "Rds(on)", "color": "Colour",
    "composition": "Technology", "technology": "Technology",
}

_SIZE = re.compile(r"\b(01005|0201|0402|0603|0805|1206|1210|1812|2010|2220|2512)\b")
_PREFIX = {"": 1, "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3,
           "M": 1e6, "G": 1e9}


def _value(text: str, unit_words: str) -> float | None:
    m = re.search(r"([\d.]+)\s*([pnuµμmkKMG]?)\s*(?:" + unit_words + r")", text)
    if not m:
        return None
    try:
        return float(m.group(1)) * _PREFIX[m.group(2)]
    except (ValueError, KeyError):
        return None


def _fmt(v: float, unit: str, prefixes: list[tuple[str, float]]) -> str:
    for p, scale in prefixes:
        if v >= scale * 0.9999 or scale == prefixes[-1][1]:
            n = v / scale
            return f"{n:.3g}{p}{unit}"
    return f"{v:g}{unit}"


def format_resistance(text: str) -> str:
    v = _value(text, r"ohms?|Ω|Ohm")
    if v is None:
        return text.strip()
    if v == 0:
        return "0Ω"
    return _fmt(v, "Ω", [("M", 1e6), ("k", 1e3), ("", 1)])


def format_capacitance(text: str) -> str:
    v = _value(text.replace("uF", "µF"), r"F")
    if v is None:
        return text.strip()
    return _fmt(v, "F", [("µ", 1e-6), ("n", 1e-9), ("p", 1e-12)])


def _clean_spec(field_name: str, value: str) -> str:
    v = (value or "").strip()
    if not v or v in ("-", "--"):
        return ""
    if field_name == "Resistance":
        return format_resistance(v)
    if field_name == "Capacitance":
        return format_capacitance(v)
    if field_name == "Tolerance":
        m = re.search(r"([\d.]+)\s*%", v)
        return f"{m.group(1)}%" if m else v
    if field_name in ("Voltage Rating", "Supply Voltage", "Reverse Voltage", "Vds/Vce"):
        m = re.search(r"([\d.]+)\s*(k?V)", v)
        return f"{m.group(1)}{m.group(2)}" if m and "-" not in v.split("V")[0] else v
    if field_name == "Power":
        m = re.search(r"([\d.]+)\s*(m?W)\b", v)
        if not m:
            return v
        watts = float(m.group(1)) / (1000 if m.group(2) == "mW" else 1)
        return f"{watts:g}W"  # same form as the starter pack: 0.1W
    if field_name == "Size":
        m = _SIZE.search(v)
        return m.group(1) if m else v
    if field_name == "Dielectric":
        m = re.search(r"\b(C0G|NP0|X5R|X6S|X7R|X7S|X7T|X8R|Y5V|Z5U)\b", v.upper())
        return ("C0G" if m.group(1) == "NP0" else m.group(1)) if m else v
    return v


def specs_for(offer: Offer, category: str) -> dict[str, str]:
    wanted = set(F.category_fields(category))
    out: dict[str, str] = {}
    for name, value in offer.specs.items():
        key = name.strip().lower()
        field_name = _SPEC_NAMES.get(key)
        if key == "temperature coefficient":  # X7R on capacitors, ±100ppm on resistors
            field_name = "Dielectric" if category.startswith("Capacitors") else "TCR"
        if key == "ratings" and "AEC-Q200" in value.upper():
            field_name, value = "AEC-Q200", "Yes"
        if field_name and field_name in wanted and field_name not in out:
            cleaned = _clean_spec(field_name, value)
            if cleaned:
                out[field_name] = cleaned
    if "Size" in wanted and "Size" not in out:
        m = _SIZE.search(offer.description)
        if m:
            out["Size"] = m.group(1)
    return out


# ---------------------------------------------------------------- category

_CATEGORY_WORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Ferrite Beads", ("ferrite",)),
    ("Capacitors Polarized", ("aluminum electrolytic", "aluminium electrolytic", "tantalum", "polymer capacitor",
                              "electrolytic")),
    ("Capacitors", ("capacitor", "cap cer", "mlcc")),
    ("Resistors", ("resistor", "res smd", "res ")),
    ("Inductors", ("inductor", "choke")),
    ("LEDs", ("led", "light emitting")),
    ("Diodes", ("diode", "rectifier", "zener", "tvs", "schottky")),
    ("Transistors", ("mosfet", "transistor", "bjt", "igbt")),
    ("Crystals", ("crystal", "oscillator", "resonator")),
    ("Connectors", ("connector", "header", "terminal block", "receptacle", "socket")),
    ("Power", ("regulator", "dc dc", "dc-dc", "converter", "pmic", "ldo", "power management")),
    ("ICs", ("ic ", "integrated", "amplifier", "microcontroller", "mcu", "logic", "interface", "sensor",
             "memory", "driver", "comparator", "adc", "dac")),
]


def guess_category(offers: list[Offer]) -> str:
    for o in offers:
        text = f" {o.category} {o.description} ".lower()
        for cat, words in _CATEGORY_WORDS:
            # match at a word start, so "resistor" also finds "Resistors"
            if any(re.search(r"(?<![a-z])" + re.escape(w.strip()) + (r"" if len(w.strip()) > 3 else r"(?![a-z])"), text)
                   for w in words):
                return cat
    return ""


# ---------------------------------------------------------------- write into a part

def apply_offers(part: Part, offers: list[Offer], overwrite: bool = False) -> list[str]:
    """Fill a part from supplier offers (best first). Returns what changed, for the log."""
    changed: list[str] = []
    if not offers:
        return changed

    def put(key: str, value: str) -> None:
        if value and (overwrite or not part.params.get(key)) and part.params.get(key) != value:
            part.params[key] = value
            changed.append(key)

    first = offers[0]
    put("Manufacturer", first.manufacturer)
    put("Manufacturer Part Number", first.mpn or part.mpn)
    put("Description", first.description)
    put("Datasheet", next((o.datasheet for o in offers if o.datasheet), ""))
    for i, o in enumerate(offers[:2], start=1):
        if overwrite or not part.params.get(f"Supplier Part Number {i}"):
            put(f"Supplier {i}", o.supplier)
            put(f"Supplier Part Number {i}", o.supplier_pn)
    if part.category in (F.DEFAULT_CATEGORY, "") or not part.category:
        cat = guess_category(offers)
        if cat:
            part.category = cat
            changed.append("Category")
    for o in offers:
        for k, v in specs_for(o, part.category).items():
            put(k, v)
    if part.category == "Resistors" and part.params.get("Resistance"):
        put("Value", part.params["Resistance"])
    elif part.category.startswith("Capacitors") and part.params.get("Capacitance"):
        put("Value", part.params["Capacitance"])
    status = next((o.status for o in offers if o.status), "")
    if status and status.lower() not in ("active", "new product", "new", "basic", "preferred", "extended"):
        note = f"Supplier status: {status}"
        if note not in part.notes:
            part.notes.append(note)
            changed.append("Note")
    return changed


def add_from_search(lib: Library, mpn: str, offers: list[Offer], category: str | None = None) -> Part:
    """Create (or update) a part from search results. It waits in Review until CAD files arrive."""
    best = offers[0].mpn if offers and offers[0].mpn else mpn
    part = lib.get(best) or Part(mpn=best, stage="Review")
    if category:
        part.category = category
    apply_offers(part, offers)
    if not part.category:
        part.category = F.DEFAULT_CATEGORY
    if not part.target_schlib:
        part.target_schlib, part.target_pcblib = lib.settings.target_libs(part.category)
    if part.source in ("", "unknown"):
        part.source = "search"
    lib.save(part)
    return part
