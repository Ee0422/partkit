"""Kits: named groups of parts you use together, such as "USB-C power input".

A kit only lists part numbers and quantities, so a part fixed in the library
is fixed in every kit. Starting a project from one or more kits gives a
combined parts list, shown in PartKit and saved as a CSV file Excel opens.
"""

from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .library import Library, Part

BOM_COLUMNS = ["Quantity", "Value", "Description", "Manufacturer", "Manufacturer Part Number",
               "Supplier 1", "Supplier Part Number 1", "Supplier 2", "Supplier Part Number 2",
               "Footprint", "Category", "Stage", "From kits"]


@dataclass
class KitItem:
    mpn: str
    qty: int = 1


@dataclass
class Kit:
    name: str
    items: list[KitItem] = field(default_factory=list)
    notes: str = ""

    def add(self, mpn: str, qty: int = 1) -> None:
        for it in self.items:
            if it.mpn == mpn:
                it.qty = qty
                return
        self.items.append(KitItem(mpn, qty))

    def remove(self, mpn: str) -> None:
        self.items = [it for it in self.items if it.mpn != mpn]


def _kits_dir(lib: Library) -> Path:
    d = lib.root / "partkit-data" / "kits"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(lib: Library, name: str) -> Path:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name.strip()).rstrip(". ") or "kit"
    return _kits_dir(lib) / f"{safe}.json"


def kits(lib: Library) -> list[Kit]:
    out = []
    for p in sorted(_kits_dir(lib).glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        out.append(Kit(d["name"], [KitItem(**i) for i in d.get("items", [])], d.get("notes", "")))
    return out


def get(lib: Library, name: str) -> Kit | None:
    return next((k for k in kits(lib) if k.name.lower() == name.strip().lower()), None)


def save(lib: Library, kit: Kit) -> None:
    if not kit.name.strip():
        raise ValueError("A kit needs a name.")
    path = _path(lib, kit.name)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(kit), indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def delete(lib: Library, name: str) -> bool:
    kit = get(lib, name)
    if kit is None:
        return False
    _path(lib, kit.name).unlink()
    return True


def add_parts(lib: Library, name: str, mpns: list[str], qty: int = 1) -> Kit:
    """Add parts to a kit, making the kit if it doesn't exist yet."""
    kit = get(lib, name) or Kit(name.strip())
    for m in mpns:
        if lib.get(m) is None:
            raise KeyError(f"No part {m!r} in the library")
        kit.add(m, qty)
    save(lib, kit)
    return kit


@dataclass
class BomLine:
    part: Part | None
    mpn: str
    qty: int
    kits: list[str]

    @property
    def warning(self) -> str:
        if self.part is None:
            return "Not in the library any more"
        if self.part.stage == "Obsolete":
            return "Obsolete: pick a replacement"
        if self.part.stage == "Review":
            return "Still in Review: approve it before use"
        return ""


def project_bom(lib: Library, names: list[str]) -> list[BomLine]:
    """One line per part across the chosen kits, with quantities added up."""
    lines: dict[str, BomLine] = {}
    for name in names:
        kit = get(lib, name)
        if kit is None:
            raise KeyError(f"No kit called {name!r}")
        for it in kit.items:
            line = lines.get(it.mpn)
            if line is None:
                line = lines[it.mpn] = BomLine(lib.get(it.mpn), it.mpn, 0, [])
            line.qty += it.qty
            if kit.name not in line.kits:
                line.kits.append(kit.name)
    return sorted(lines.values(), key=lambda l: ((l.part.category if l.part else "~"), l.mpn))


def bom_row(line: BomLine) -> dict[str, str]:
    p = line.part
    params = p.bom_params() if p else {}
    row = {c: params.get(c, "") for c in BOM_COLUMNS}
    row.update({"Quantity": str(line.qty), "Manufacturer Part Number": line.mpn,
                "Footprint": p.footprint if p else "", "Category": p.category if p else "",
                "Stage": (p.stage if p else "Missing"), "From kits": ", ".join(line.kits)})
    if line.warning:
        row["Stage"] += f" ({line.warning})"
    return row


def write_csv(lines: list[BomLine], path: Path) -> Path:
    """Save the parts list as CSV. utf-8-sig so Excel shows Ω and µ correctly."""
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=BOM_COLUMNS)
        w.writeheader()
        for line in lines:
            w.writerow(bom_row(line))
    return path
