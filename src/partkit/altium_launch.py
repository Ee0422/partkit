"""Find Altium Designer and start PartKit Sync in it.

PartKit ships its Altium script inside the package. `copy_scripts` puts a
copy in a fixed folder (Documents/PartKit Scripts) so Altium always runs the
current version, and `start_sync` asks Altium to run it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from importlib import resources
from pathlib import Path

SCRIPT_FILES = ("PartKitSync.pas", "PartKitSync.PrjScr")


def default_scripts_dir() -> Path:
    return Path.home() / "Documents" / "PartKit Scripts"


def copy_scripts(dest: Path | None = None) -> Path:
    """Copy the bundled Altium script to dest (overwriting older copies). Returns the .PrjScr path."""
    dest = Path(dest or default_scripts_dir())
    dest.mkdir(parents=True, exist_ok=True)
    src = resources.files("partkit").joinpath("altium")
    for name in SCRIPT_FILES:
        (dest / name).write_bytes(src.joinpath(name).read_bytes())
    return dest / "PartKitSync.PrjScr"


def _version_key(p: Path) -> tuple:
    nums = re.findall(r"\d+", p.parent.name)
    return tuple(int(n) for n in nums) or (0,)


def find_altium(search_roots: list[Path] | None = None) -> Path | None:
    """Newest Altium Designer X2.exe, or None.

    Looks in the usual install folders, e.g. C:\\Program Files\\Altium\\AD26\\X2.exe.
    """
    env = os.environ.get("PARTKIT_ALTIUM")
    if env and Path(env).exists():
        return Path(env)
    roots = search_roots
    if roots is None:
        roots = [Path(os.environ.get(v, "")) / "Altium"
                 for v in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)") if os.environ.get(v)]
        roots.append(Path("C:/Program Files/Altium"))
    found = []
    for root in roots:
        if root.is_dir():
            found += [p for p in root.glob("*/X2.exe") if p.is_file()]
    if not found:
        return None
    return sorted(set(found), key=_version_key)[-1]


def sync_command(x2: Path, prjscr: Path) -> list[str]:
    """Altium's command-line form for running a script procedure."""
    run = f'-RScriptingSystem:RunScript(ProjectName="{prjscr}"|ProcName="PartKitSync.pas>Run")'
    return [str(x2), run]


def start_sync(prjscr: Path | None = None, x2: Path | None = None) -> tuple[bool, str]:
    """Ask Altium to run PartKit Sync. Returns (started, message for the user)."""
    prjscr = prjscr or copy_scripts()
    x2 = x2 or find_altium()
    manual = ("In Altium: File > Run Script > Browse, choose "
              f"{prjscr}, then pick Run.")
    if x2 is None:
        return False, "Altium Designer wasn't found automatically. " + manual
    if os.name != "nt":
        return False, manual
    try:
        subprocess.Popen(sync_command(x2, prjscr), close_fds=True)
    except OSError as e:
        return False, f"Couldn't start Altium ({e}). " + manual
    return True, ("Asked Altium to run PartKit Sync. If nothing happens within a minute, " + manual)


def scripts_are_current(dest: Path | None = None) -> bool:
    dest = Path(dest or default_scripts_dir())
    src = resources.files("partkit").joinpath("altium")
    for name in SCRIPT_FILES:
        f = dest / name
        if not f.exists() or f.read_bytes() != src.joinpath(name).read_bytes():
            return False
    return True


def remove_scripts(dest: Path | None = None) -> None:
    shutil.rmtree(Path(dest or default_scripts_dir()), ignore_errors=True)
