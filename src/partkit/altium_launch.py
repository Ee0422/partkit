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


def sync_command(x2: Path, prjscr: Path) -> str:
    """Altium's command line for running a script procedure.

    Returned as one string: Windows passes it to Altium exactly as written.
    (Passing a list made Python escape the quotes, and Altium then couldn't
    find the script and showed an empty "Select Item To Run" box.)
    """
    return (f'"{x2}" -RScriptingSystem:RunScript('
            f'ProjectName="{prjscr}"|ProcName="PartKitSync.pas>Run")')


def altium_running() -> bool:
    """True if Altium Designer (X2.exe) is already open."""
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq X2.exe", "/NH"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "x2.exe" in out.lower()


def manual_steps(prjscr: Path) -> str:
    return (f"In Altium: File > Run Script > Browse, choose {prjscr}, then pick Run. "
            "After the first time it stays in the Run Script list, so it's two clicks.")


def start_sync(prjscr: Path | None = None, x2: Path | None = None) -> tuple[bool, str]:
    """Ask Altium to run PartKit Sync. Returns (started, message for the user).

    If Altium is already open, PartKit doesn't start a second copy (Altium
    can't hand a script to a running window); it says how to run it there.
    """
    prjscr = prjscr or copy_scripts()
    manual = manual_steps(prjscr)
    if os.name != "nt":
        return False, manual
    if altium_running():
        return False, "Altium is already open, so PartKit didn't start another copy. " + manual
    x2 = x2 or find_altium()
    if x2 is None:
        return False, "Altium Designer wasn't found automatically. " + manual
    try:
        subprocess.Popen(sync_command(x2, prjscr), close_fds=True)
    except OSError as e:
        return False, f"Couldn't start Altium ({e}). " + manual
    return True, "Starting Altium and PartKit Sync. If nothing happens within a minute, " + manual


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
