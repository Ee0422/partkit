"""Where to get CAD files (symbol, footprint, 3D) for a part.

The big providers (SnapMagic, SamacSys, Ultra Librarian) only hand out files
to signed-in users in a browser, so PartKit opens the part's page at your
first preferred provider. When you click Download there, the Downloads
watcher imports the file and attaches it to the part. If that provider
doesn't have it, "Try next" opens the next one in your order. Hunting (if
you turned it on) adds wider searches after your own list runs out.
"""

from __future__ import annotations

import urllib.parse
import webbrowser
from dataclasses import dataclass

from .config import Settings

PROVIDER_URLS: dict[str, str] = {
    "SnapMagic": "https://www.snapeda.com/search/?q={q}",
    "SamacSys": "https://componentsearchengine.com/search?term={q}",
    "UltraLibrarian": "https://app.ultralibrarian.com/search?queryText={q}",
}

# Wider searches used only when hunting is on and your providers came up empty.
HUNTING_URLS: dict[str, str] = {
    "DigiKey CAD models": "https://www.digikey.com/en/products/result?keywords={q}",
    "Mouser ECAD": "https://www.mouser.com/c/?q={q}",
    "Web search": "https://duckduckgo.com/?q={q}+altium+footprint+step",
}


@dataclass
class CadSource:
    name: str
    url: str
    hunting: bool = False


def cad_sources(mpn: str, settings: Settings, manufacturer_url: str = "") -> list[CadSource]:
    """Your providers in your order, then hunting sources if hunting is on."""
    q = urllib.parse.quote(mpn.strip())
    out: list[CadSource] = []
    for name in settings.providers:
        if name == "Manufacturer":
            if manufacturer_url:
                out.append(CadSource(name, manufacturer_url))
            continue
        tmpl = PROVIDER_URLS.get(name)
        if tmpl:
            out.append(CadSource(name, tmpl.format(q=q)))
    if settings.hunting in ("ask", "always"):
        out += [CadSource(n, t.format(q=q), hunting=True) for n, t in HUNTING_URLS.items()]
    return out


def open_source(src: CadSource, opener=webbrowser.open) -> None:
    opener(src.url)
