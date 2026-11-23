"""Generic passives: shared symbols and footprints, parts identified by full spec.

Two 0603 100 nF capacitors at 16 V X5R and 50 V X7R are different parts with
different MPNs, so every row carries the full spec. Footprints are shared per
size and height class (IPC-7351B names), because a 10 uF 0805 capacitor is
much taller than a 100 nF one even though the pads are the same.

The starter-pack MPNs follow the manufacturers' published part-number
schemes. They are marked unverified until checked against a supplier with
`partkit verify` (needs supplier API keys, milestone 3).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources

from .library import Library, Part

SIZES = {"0402": "1005", "0603": "1608", "0805": "2012"}
BODY_MM = {"0402": (1.0, 0.5), "0603": (1.6, 0.8), "0805": (2.0, 1.25)}

RESISTOR_HEIGHT_MM = {"0402": 0.40, "0603": 0.55, "0805": 0.70}
# Capacitor height classes (max body height, mm) per size.
CAP_HEIGHT_CLASSES = {"0402": (0.55,), "0603": (0.55, 0.90), "0805": (0.70, 0.95, 1.40)}

GENERIC_SCHLIB = "Libraries/Generic Passives.SchLib"
GENERIC_PCBLIB = "Libraries/Generic Passives.PcbLib"

E24 = (1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0,
       3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1)

# Land pattern per size (IPC-7351B nominal-density values, mm): pad length (X),
# pad width (Y), pad centre distance from origin. Starting values; check them
# against your board house's rules before a production run.
LAND_MM = {"0402": (0.59, 0.64, 0.485), "0603": (0.80, 0.95, 0.825), "0805": (1.025, 1.40, 0.9125)}

RES_POWER = {"0402": ("1/16W", "0.063W"), "0603": ("1/10W", "0.1W"), "0805": ("1/8W", "0.125W")}


def resistor_footprint(size: str) -> str:
    return f"RESC{SIZES[size]}X{round(RESISTOR_HEIGHT_MM[size] * 100)}N"


def capacitor_footprint(size: str, height_mm: float) -> str:
    """Smallest height class that fits the part (nominal height plus 0.1 mm tolerance)."""
    need = height_mm + 0.1
    classes = CAP_HEIGHT_CLASSES[size]
    cls = next((c for c in classes if c >= need - 1e-9), classes[-1])
    return f"CAPC{SIZES[size]}X{round(cls * 100)}N"


def format_ohms(ohms: float) -> str:
    """10000 -> '10k', 4700 -> '4.7k', 0 -> '0'."""
    if ohms == 0:
        return "0"
    for div, unit in ((1e6, "M"), (1e3, "k"), (1, "")):
        if ohms >= div:
            v = ohms / div
            return (f"{v:.2f}".rstrip("0").rstrip(".")) + unit
    return f"{ohms:g}"


def yageo_value_code(ohms: float) -> str:
    """YAGEO RC series value code: 10R, 4K7, 10K, 1M, 0R."""
    if ohms == 0:
        return "0R"
    for div, unit in ((1e6, "M"), (1e3, "K"), (1, "R")):
        if ohms >= div:
            v = round(ohms / div, 3)
            s = f"{v:g}"
            return s.replace(".", unit) if "." in s else s + unit
    raise ValueError(ohms)


def yageo_rc_mpn(size: str, ohms: float) -> str:
    tol = "J" if ohms == 0 else "F"
    return f"RC{size}{tol}R-07{yageo_value_code(ohms)}L"


def e24_values(lo: float = 10.0, hi: float = 1e6) -> list[float]:
    vals = []
    decade = 1.0
    while decade <= hi:
        for m in E24:
            v = round(m * decade, 6)
            if lo <= v <= hi:
                vals.append(v)
        decade *= 10
    return vals


@dataclass
class PassiveSpec:
    kind: str          # "R" or "C"
    value: str         # "10k", "100nF"
    size: str          # "0603"
    tolerance: str
    voltage: str = ""
    dielectric: str = ""
    power: str = ""
    height_mm: float = 0.0


def resistor_part(size: str, ohms: float) -> Part:
    value = format_ohms(ohms)
    tol = "Jumper" if ohms == 0 else "1%"
    frac, watts = RES_POWER[size]
    desc = ("RES 0 OHM JUMPER " if ohms == 0 else f"RES {value.upper()} OHM 1% {frac} ") + size
    params = {
        "Manufacturer": "YAGEO",
        "Manufacturer Part Number": yageo_rc_mpn(size, ohms),
        "Description": desc,
        "Value": f"{value}Ω" if ohms else "0Ω",
        "Package": size,
        "Supplier 1": "DigiKey",
        "Resistance": f"{value}Ω",
        "Tolerance": tol,
        "Power": watts,
        "Size": size,
        "Technology": "Thick Film",
        "Height": f"{RESISTOR_HEIGHT_MM[size]:.2f}mm",
    }
    l, w = BODY_MM[size]
    return Part(
        mpn=params["Manufacturer Part Number"], category="Resistors", stage="Released", params=params,
        source="PartKit", schlib=GENERIC_SCHLIB, symbol="Resistor", pcblib=GENERIC_PCBLIB,
        footprint=resistor_footprint(size), model_3d="Full", model_3d_source="generated",
        box_mm=[l, w, RESISTOR_HEIGHT_MM[size]],
        target_schlib=GENERIC_SCHLIB, target_pcblib=GENERIC_PCBLIB, needs_sync=True,
        notes=["Starter pack: MPN unverified until checked with a supplier"],
    )


def starter_capacitors() -> list[dict]:
    data = resources.files("partkit").joinpath("data/starter_capacitors.json").read_text(encoding="utf-8")
    return json.loads(data)


def capacitor_part(row: dict) -> Part:
    size = row["size"]
    h = float(row["height_mm"])
    params = {
        "Manufacturer": row["manufacturer"],
        "Manufacturer Part Number": row["mpn"],
        "Description": f"CAP CER {row['capacitance'].upper()} {row['voltage']} {row['dielectric']} {size}",
        "Value": row["capacitance"],
        "Package": size,
        "Supplier 1": "DigiKey",
        "Capacitance": row["capacitance"],
        "Voltage Rating": row["voltage"],
        "Dielectric": row["dielectric"],
        "Tolerance": row["tolerance"],
        "Size": size,
        "Height": f"{h:.2f}mm",
    }
    l, w = BODY_MM[size]
    return Part(
        mpn=row["mpn"], category="Capacitors", stage="Released", params=params, source="PartKit",
        schlib=GENERIC_SCHLIB, symbol="Capacitor", pcblib=GENERIC_PCBLIB,
        footprint=capacitor_footprint(size, h), model_3d="Full", model_3d_source="generated",
        box_mm=[l, w, h], target_schlib=GENERIC_SCHLIB, target_pcblib=GENERIC_PCBLIB, needs_sync=True,
        notes=["Starter pack: MPN unverified until checked with a supplier"],
    )


def starter_pack(sizes: tuple[str, ...] = ("0402", "0603", "0805")) -> list[Part]:
    parts = [resistor_part(s, 0) for s in sizes]
    for s in sizes:
        parts += [resistor_part(s, v) for v in e24_values()]
    parts += [capacitor_part(r) for r in starter_capacitors() if r["size"] in sizes]
    return parts


def install_starter_pack(lib: Library, sizes: tuple[str, ...] = ("0402", "0603", "0805")) -> tuple[int, int]:
    """Add starter passives that are not in the library yet. Returns (added, skipped)."""
    added = skipped = 0
    for part in starter_pack(sizes):
        if lib.find_same_spec(part):
            skipped += 1
            continue
        lib.save(part)
        added += 1
    return added, skipped


def footprints_needed(parts: list[Part]) -> list[dict]:
    """Generic footprints PartKit Sync must create, with body size for the 3D model."""
    seen: dict[str, dict] = {}
    for p in parts:
        if p.pcblib != GENERIC_PCBLIB:
            continue
        size = p.params.get("Size", "")
        l, w = BODY_MM.get(size, (0, 0))
        h = float(p.params.get("Height", "0mm").rstrip("m") or 0)
        cur = seen.get(p.footprint)
        if cur is None or h > cur["height_mm"]:
            pad_l, pad_w, pad_x = LAND_MM[size]
            seen[p.footprint] = {"name": p.footprint, "size": size, "length_mm": l, "width_mm": w,
                                 "height_mm": h, "kind": "R" if p.category == "Resistors" else "C",
                                 "pad_l_mm": pad_l, "pad_w_mm": pad_w, "pad_x_mm": pad_x}
    return sorted(seen.values(), key=lambda d: d["name"])
