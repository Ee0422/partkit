"""Make new parts from parts you have already checked.

Every 0603 resistor uses the same footprint, so once one is checked in
Altium, the next value only needs a new part number. "New value" copies the
symbol, footprint and 3D model; "new part from this footprint" copies only
the footprint and 3D model and takes the symbol from any part you choose.
Either way the new part waits in Review until you approve it.
"""

from __future__ import annotations

from .library import Library, Part
from .search import apply_offers
from .suppliers import Offer

# Spec fields that belong to the package, not the value, so a copy keeps them.
PACKAGE_FIELDS = ("Size", "Package", "Height", "Technology", "Mounting", "Pitch", "Pins", "Rows", "Series")


class ReuseProblem(Exception):
    """Why a part can't be used as the starting point, in plain words."""


def _check_source(part: Part | None, what: str) -> Part:
    if part is None:
        raise ReuseProblem(f"{what} isn't in your library.")
    if part.source == "PartKit":
        raise ReuseProblem(f"{part.mpn} is an old PartKit starter part whose footprint was never checked.")
    if not part.footprint or not part.pcblib:
        raise ReuseProblem(f"{part.mpn} has no footprint yet. Get its CAD files first.")
    if part.stage != "Released":
        raise ReuseProblem(f"Approve {part.mpn} first, so only checked parts are copied.")
    return part


def _new_part(lib: Library, mpn: str, offers: list[Offer], category: str) -> Part:
    mpn = (offers[0].mpn if offers and offers[0].mpn else mpn).strip()
    if not mpn:
        raise ReuseProblem("Give the new part's manufacturer part number, or pick one from the search.")
    if lib.get(mpn):
        raise ReuseProblem(f"{mpn} is already in your library.")
    return Part(mpn=mpn, category=category, stage="Review")


def new_value(lib: Library, source_mpn: str, mpn: str = "", offers: list[Offer] | None = None) -> Part:
    """A new part with the same symbol, footprint and 3D model as a checked one."""
    src = _check_source(lib.get(source_mpn), source_mpn)
    if not src.symbol:
        raise ReuseProblem(f"{src.mpn} has no symbol yet.")
    offers = offers or []
    part = _new_part(lib, mpn, offers, src.category)
    _copy_footprint(src, part)
    part.schlib, part.symbol = src.schlib, src.symbol
    for k in PACKAGE_FIELDS:
        if src.params.get(k):
            part.params[k] = src.params[k]
    part.params["Manufacturer Part Number"] = part.mpn
    apply_offers(part, offers)
    part.notes.append(f"Symbol, footprint and 3D model copied from {src.mpn}")
    lib.save(part)
    return part


def new_from_footprint(lib: Library, source_mpn: str, mpn: str, offers: list[Offer] | None = None,
                       symbol_from: str = "", category: str = "") -> Part:
    """A new part on a checked footprint; its symbol comes from `symbol_from` (any part) if given."""
    src = _check_source(lib.get(source_mpn), source_mpn)
    offers = offers or []
    part = _new_part(lib, mpn, offers, category or src.category)
    _copy_footprint(src, part)
    if symbol_from:
        sym = lib.get(symbol_from)
        if sym is None or not sym.symbol:
            raise ReuseProblem(f"{symbol_from} has no symbol to copy.")
        part.schlib, part.symbol = sym.schlib, sym.symbol
        part.notes.append(f"Symbol copied from {sym.mpn}: check its pins match the new part's datasheet")
    else:
        part.notes.append("No symbol yet: import one, or copy one from another part")
    for k in ("Size", "Package", "Height", "Mounting", "Pitch", "Pins", "Rows"):
        if src.params.get(k):
            part.params[k] = src.params[k]
    part.params["Manufacturer Part Number"] = part.mpn
    apply_offers(part, offers)
    part.notes.append(f"Footprint and 3D model copied from {src.mpn}")
    lib.save(part)
    return part


def _copy_footprint(src: Part, part: Part) -> None:
    part.pcblib, part.footprint = src.pcblib, src.footprint
    part.step, part.model_3d, part.model_3d_source = src.step, src.model_3d, src.model_3d_source
    part.box_mm = list(src.box_mm)
    part.target_schlib, part.target_pcblib = src.target_schlib, src.target_pcblib
    part.source = src.source
    part.copied_from = src.mpn


def value_query_text(src: Part, value: str) -> str:
    """The search to run for a new value: the value plus the source part's size and spec."""
    p = src.params
    bits = [value.strip()]
    if p.get("Size"):
        bits.append(p["Size"])
    if src.category == "Resistors" and p.get("Tolerance", "").endswith("%"):
        bits.append(p["Tolerance"])
    if src.category.startswith("Capacitors"):
        for k in ("Voltage Rating", "Dielectric"):
            if p.get(k):
                bits.append(p[k])
    return " ".join(bits)


def can_search_by_value(part: Part) -> bool:
    """Resistors and ceramic capacitors can be found at JLCPCB by value."""
    return part.category in ("Resistors", "Capacitors")
