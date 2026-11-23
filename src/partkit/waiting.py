"""The part you clicked Get CAD files for, waiting for its download.

Get CAD files doesn't add anything to My parts. It only remembers the
supplier part you picked (C-number, stock, Basic/Extended...). The next CAD
download that arrives is that part: when it's imported, the supplier details
are joined to it, so the part appears once, complete.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict
from pathlib import Path

from .library import Library
from .suppliers import Offer

MAX_AGE_S = 3 * 3600  # an old click shouldn't claim tomorrow's download


def _path(lib: Library) -> Path:
    return lib.root / "partkit-data" / "waiting-cad.json"


def remember(lib: Library, mpn: str, offers: list[Offer], category: str = "") -> None:
    p = _path(lib)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"mpn": mpn, "category": category or "", "time": time.time(),
                             "offers": [asdict(o) for o in offers]}, indent=2, ensure_ascii=False),
                 encoding="utf-8")


def current(lib: Library) -> dict | None:
    try:
        d = json.loads(_path(lib).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - d.get("time", 0) > MAX_AGE_S:
        return None
    return d


def clear(lib: Library) -> None:
    try:
        _path(lib).unlink()
    except OSError:
        pass


def offers_of(entry: dict) -> list[Offer]:
    out = []
    for o in entry.get("offers", []):
        o = dict(o)
        o["price_breaks"] = [tuple(x) for x in o.get("price_breaks", [])]
        out.append(Offer(**{k: v for k, v in o.items() if k in Offer.__dataclass_fields__}))
    return out


def same_number(a: str, b: str) -> bool:
    """RC0603FR-071KL and rc0603fr071kl are the same part number."""
    norm = lambda s: re.sub(r"[^A-Z0-9]", "", (s or "").upper())  # noqa: E731
    return bool(norm(a)) and norm(a) == norm(b)
