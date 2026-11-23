"""User settings, stored as a small TOML file inside the library folder."""

from __future__ import annotations

import os
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10
    import tomli as tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

SETTINGS_FILE = "partkit-settings.toml"

DEFAULT_SUPPLIERS = ["DigiKey", "Mouser", "Farnell", "LCSC"]
DEFAULT_PROVIDERS = ["SnapMagic", "SamacSys", "Manufacturer", "UltraLibrarian"]
HUNTING_MODES = ("off", "ask", "always")


LOCATION_FILE = Path.home() / ".partkit-library-location"


def default_library_path() -> Path:
    """The library folder chosen in setup, or Documents/PartKit Library."""
    try:
        saved = LOCATION_FILE.read_text(encoding="utf-8").strip()
        if saved:
            return Path(saved)
    except OSError:
        pass
    return Path.home() / "Documents" / "PartKit Library"


def remember_library_path(path: Path) -> None:
    try:
        LOCATION_FILE.write_text(str(Path(path).resolve()), encoding="utf-8")
    except OSError:
        pass


def default_downloads_path() -> Path:
    return Path.home() / "Downloads"


@dataclass
class Settings:
    suppliers: list[str] = field(default_factory=lambda: list(DEFAULT_SUPPLIERS))
    providers: list[str] = field(default_factory=lambda: list(DEFAULT_PROVIDERS))
    hunting: str = "off"
    skip_review: bool = False
    watch_folder: str = field(default_factory=lambda: str(default_downloads_path()))
    # Category -> {"schlib": "...", "pcblib": "..."}; paths relative to the library
    # folder or absolute. Categories not listed use Libraries/<Category>.SchLib/.PcbLib.
    targets: dict[str, dict[str, str]] = field(default_factory=dict)
    # Which regional site and currency supplier searches use.
    digikey_site: str = "US"
    digikey_currency: str = "USD"
    farnell_store: str = "uk.farnell.com"

    def target_libs(self, category: str) -> tuple[str, str]:
        t = self.targets.get(category, {})
        return (
            t.get("schlib", f"Libraries/{category}.SchLib"),
            t.get("pcblib", f"Libraries/{category}.PcbLib"),
        )

    def validate(self) -> None:
        if self.hunting not in HUNTING_MODES:
            raise ValueError(f"hunting must be one of {HUNTING_MODES}, got {self.hunting!r}")


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(type(v))


def dump_settings(s: Settings) -> str:
    data = asdict(s)
    targets = data.pop("targets")
    lines = [f"{k} = {_toml_value(v)}" for k, v in data.items()]
    for cat, t in sorted(targets.items()):
        lines.append("")
        lines.append(f"[targets.{_toml_value(cat)}]")
        for k, v in t.items():
            lines.append(f"{k} = {_toml_value(v)}")
    return "\n".join(lines) + "\n"


def load_settings(library: Path) -> Settings:
    path = Path(library) / SETTINGS_FILE
    if not path.exists():
        return Settings()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    known = {k: v for k, v in data.items() if k in Settings.__dataclass_fields__}
    s = Settings(**known)
    # suppliers/providers added in newer versions appear at the end of your list
    s.suppliers += [x for x in DEFAULT_SUPPLIERS if x not in s.suppliers]
    s.providers += [x for x in DEFAULT_PROVIDERS if x not in s.providers]
    s.validate()
    return s


def save_settings(library: Path, s: Settings) -> None:
    s.validate()
    path = Path(library) / SETTINGS_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(dump_settings(s), encoding="utf-8")
    os.replace(tmp, path)
