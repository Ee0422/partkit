"""Projects: the parts one board uses, and (if you want) its own library.

A project starts empty, from templates (kits), or as a copy of another
project. Adding a part to a project adds it to that project only. By
default a project uses your main library. Choose a library folder and
PartKit writes the project's parts into that folder's .SchLib/.PcbLib (the
ones already there, whatever they're called, or new ones named after the
project), and "Update project library" sends only the parts it doesn't
have yet.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import fields as F
from . import kits
from .kits import BomLine, KitItem
from .library import Library, Part


@dataclass
class Project:
    name: str
    items: list[KitItem] = field(default_factory=list)
    own_library: bool = False
    folder: str = ""                 # where the project's own library lives
    in_library: list[str] = field(default_factory=list)  # MPNs already written there
    templates: list[str] = field(default_factory=list)   # the templates it started from
    schlib_file: str = ""            # file names inside folder (or full paths); "" = named after the project
    pcblib_file: str = ""
    prjpcb: str = ""                 # the Altium project (.PrjPcb) this board's library belongs to
    written_at: dict[str, float] = field(default_factory=dict)  # MPN -> when PartKit Sync wrote it there

    @property
    def schlib(self) -> str:
        return str(Path(self.folder) / (self.schlib_file or f"{_safe(self.name)}.SchLib"))

    @property
    def pcblib(self) -> str:
        return str(Path(self.folder) / (self.pcblib_file or f"{_safe(self.name)}.PcbLib"))

    def has(self, mpn: str) -> bool:
        return any(it.mpn == mpn for it in self.items)

    def add(self, mpn: str, qty: int = 1) -> None:
        for it in self.items:
            if it.mpn == mpn:
                it.qty = qty
                return
        self.items.append(KitItem(mpn, qty))

    def remove(self, mpn: str) -> None:
        self.items = [it for it in self.items if it.mpn != mpn]


def _safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name.strip()).rstrip(". ") or "project"


def _dir(lib: Library) -> Path:
    d = lib.root / "partkit-data" / "projects"
    d.mkdir(parents=True, exist_ok=True)
    return d


def projects(lib: Library) -> list[Project]:
    out = []
    for p in sorted(_dir(lib).glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        d["items"] = [KitItem(**i) for i in d.get("items", [])]
        out.append(Project(**{k: v for k, v in d.items() if k in Project.__dataclass_fields__}))
    return out


def get(lib: Library, name: str) -> Project | None:
    return next((p for p in projects(lib) if p.name.lower() == name.strip().lower()), None)


def save(lib: Library, project: Project) -> None:
    path = _dir(lib) / f"{_safe(project.name)}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(project), indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def delete(lib: Library, name: str) -> bool:
    p = get(lib, name)
    if p is None:
        return False
    (_dir(lib) / f"{_safe(p.name)}.json").unlink()
    return True


def default_folder(lib: Library, name: str) -> str:
    return str(lib.root / "Projects" / _safe(name))


def libraries_in(folder: str | Path) -> tuple[list[str], list[str]]:
    """The .SchLib and .PcbLib file names already in a folder (not its subfolders)."""
    d = Path(folder)
    if not d.is_dir():
        return [], []
    files = sorted(p.name for p in d.iterdir() if p.is_file())
    return ([f for f in files if f.lower().endswith(".schlib")],
            [f for f in files if f.lower().endswith(".pcblib")])


def use_folder(proj: Project, folder: str | Path, schlib: str = "", pcblib: str = "") -> Project:
    """Point a project at a library folder.

    If the folder holds exactly one .SchLib (or .PcbLib), that file is used whatever it's
    called. With none, a new one named after the project is made there. With several, pass
    the one to use, or ValueError says which to choose from.
    """
    schs, pcbs = libraries_in(folder)
    chosen = []
    for kind, given, found in (("SchLib", schlib, schs), ("PcbLib", pcblib, pcbs)):
        if given:
            chosen.append(Path(given).name)
        elif len(found) == 1:
            chosen.append(found[0])
        elif not found:
            chosen.append("")
        else:
            raise ValueError(f"{folder} has {len(found)} .{kind} files ({', '.join(found)}). Choose one.")
    proj.folder = str(folder)
    proj.schlib_file, proj.pcblib_file = chosen
    proj.prjpcb = ""
    proj.own_library = True
    proj.written_at = {}
    proj.in_library = []  # PartKit doesn't know what's in a library it hasn't written; send everything once
    return proj


def libraries_in_prjpcb(prjpcb: str | Path) -> tuple[list[str], list[str]]:
    """Full paths of the .SchLib and .PcbLib files an Altium project (.PrjPcb) contains.

    A .PrjPcb is a text file with one DocumentPath= line per document, relative to
    the project's folder.
    """
    prj = Path(prjpcb)
    schs, pcbs = [], []
    text = prj.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip().lower() != "documentpath" or not value.strip():
            continue
        doc = value.strip().replace("\\", "/")
        full = Path(doc) if re.match(r"^[A-Za-z]:/|^/", doc) else prj.parent / doc
        if doc.lower().endswith(".schlib"):
            schs.append(str(full))
        elif doc.lower().endswith(".pcblib"):
            pcbs.append(str(full))
    return schs, pcbs


def use_prjpcb(proj: Project, prjpcb: str | Path, schlib: str = "", pcblib: str = "") -> Project:
    """Point a project at an Altium project and the libraries already in it.

    One .SchLib (or .PcbLib) in the project: that one is used. None: a new one named
    after the Altium project is made next to it. Several: pass the one to use, or
    ValueError says which to choose from.
    """
    prj = Path(prjpcb)
    if not prj.is_file():
        raise ValueError(f"{prj} wasn't found.")
    schs, pcbs = libraries_in_prjpcb(prj)
    chosen = []
    for kind, given, found in (("SchLib", schlib, schs), ("PcbLib", pcblib, pcbs)):
        if given:
            chosen.append(str(given))
        elif len(found) == 1:
            chosen.append(found[0])
        elif not found:
            chosen.append(str(prj.with_suffix("." + kind)))
        else:
            names = ", ".join(Path(f).name for f in found)
            raise ValueError(f"{prj.name} has {len(found)} .{kind} files ({names}). Choose one.")
    proj.folder = str(prj.parent)
    proj.schlib_file, proj.pcblib_file = chosen  # full paths; Path(folder) / full path keeps the full path
    proj.prjpcb = str(prj)
    proj.own_library = True
    proj.in_library = []
    proj.written_at = {}
    return proj


def _only_prjpcb(folder: Path) -> Path | None:
    found = sorted(folder.glob("*.PrjPcb")) if folder.is_dir() else []
    return found[0] if len(found) == 1 else None


def library_choices(path: str | Path) -> tuple[list[str], list[str]]:
    """The .SchLib and .PcbLib files (full paths) to choose from for what was picked:
    an Altium project, or a folder (its one Altium project if it has exactly one, else the
    libraries lying in it). Empty lists mean PartKit makes new ones."""
    p = Path(path)
    if p.is_dir() and _only_prjpcb(p):
        p = _only_prjpcb(p)
    if p.suffix.lower() == ".prjpcb":
        return libraries_in_prjpcb(p)
    schs, pcbs = libraries_in(p)
    return [str(p / f) for f in schs], [str(p / f) for f in pcbs]


def planned_libraries(path: str | Path, name: str, schlib: str = "", pcblib: str = "") -> tuple[str, str]:
    """Where the parts would go, without changing anything (to show before you press OK)."""
    proj = Project(name or "project")
    use_file(proj, path, schlib, pcblib)
    return proj.schlib, proj.pcblib


def use_file(proj: Project, path: str | Path, schlib: str = "", pcblib: str = "") -> Project:
    """Point a project at what the person picked: an Altium project, a library file, or a folder.

    A folder holding exactly one Altium project counts as that project.
    """
    p = Path(path)
    if p.is_dir() and _only_prjpcb(p):
        p = _only_prjpcb(p)
    if p.suffix.lower() == ".prjpcb":
        return use_prjpcb(proj, p, schlib, pcblib)
    if p.suffix.lower() == ".schlib":
        return use_folder(proj, p.parent, schlib or p.name, pcblib)
    if p.suffix.lower() == ".pcblib":
        return use_folder(proj, p.parent, schlib, pcblib or p.name)
    return use_folder(proj, p, schlib, pcblib)


def create(lib: Library, name: str, templates: list[str] | None = None, copy_of: str = "",
           own_library: bool = False, folder: str = "", schlib: str = "", pcblib: str = "") -> Project:
    """A new project, empty, from templates, or as a copy of another project's parts list.

    Give a folder, a .SchLib/.PcbLib or an Altium project (.PrjPcb) to have the project use
    its own library there (see use_file).
    """
    name = name.strip()
    if not name:
        raise ValueError("A project needs a name.")
    if get(lib, name):
        raise ValueError(f"There's already a project called {name!r}.")
    proj = Project(name, own_library=own_library, folder=default_folder(lib, name),
                   templates=list(templates or []))
    if folder:
        use_file(proj, folder, schlib, pcblib)
    if copy_of:
        src = get(lib, copy_of)
        if src is None:
            raise KeyError(f"No project called {copy_of!r}")
        for it in src.items:
            proj.add(it.mpn, it.qty)
    for t in templates or []:
        kit = kits.get(lib, t)
        if kit is None:
            raise KeyError(f"No template called {t!r}")
        for it in kit.items:
            existing = next((x for x in proj.items if x.mpn == it.mpn), None)
            proj.add(it.mpn, (existing.qty if existing else 0) + it.qty)
    save(lib, proj)
    return proj


def add_parts(lib: Library, name: str, mpns: list[str], qty: int = 1, also_template: str = "") -> Project:
    """Add parts to one project only (and, if asked, to a template too)."""
    proj = get(lib, name)
    if proj is None:
        raise KeyError(f"No project called {name!r}")
    for m in mpns:
        if lib.get(m) is None:
            raise KeyError(f"No part {m!r} in the library")
        if not proj.has(m):
            proj.add(m, qty)
    save(lib, proj)
    if also_template:
        kits.add_parts(lib, also_template, mpns, qty)
    return proj


def parts_list(lib: Library, proj: Project) -> list[BomLine]:
    lines = [BomLine(lib.get(it.mpn), it.mpn, it.qty, [proj.name]) for it in proj.items]
    return sorted(lines, key=lambda l: ((l.part.category if l.part else "~"), l.mpn))


def missing_from_library(lib: Library, proj: Project) -> tuple[list[Part], list[str]]:
    """Ready parts the project's library doesn't have yet, and the ones that can't go yet (with why)."""
    ready, waiting = [], []
    for it in proj.items:
        if it.mpn in proj.in_library:
            continue
        p = lib.get(it.mpn)
        if p is None:
            waiting.append(f"{it.mpn}: not in your library any more")
        elif p.stage != F.READY:
            waiting.append(f"{it.mpn}: {p.stage}, so it can't go into a library yet")
        else:
            ready.append(p)
    return ready, waiting


def write_update_job(lib: Library, proj: Project, everything: bool = False) -> tuple[Path | None, list[str]]:
    """Sync job that writes the project's missing parts (or all of them) into its own library."""
    if not proj.own_library:
        raise ValueError(f"{proj.name} uses your main library. Tick 'own library' first.")
    ready, waiting = missing_from_library(lib, proj)
    if everything:
        ready = [p for p in (lib.get(it.mpn) for it in proj.items) if p and p.stage == F.READY]
    Path(proj.folder).mkdir(parents=True, exist_ok=True)
    job = lib.write_sync_job(parts=ready, dst=(proj.schlib, proj.pcblib), kind=f"project:{proj.name}",
                             prjpcb=proj.prjpcb)
    return job, waiting


def record_written(lib: Library, name: str, mpns: list[str]) -> None:
    """PartKit Sync reported these parts written into the project's library."""
    proj = get(lib, name)
    if proj is None:
        return
    for m in mpns:
        if m not in proj.in_library:
            proj.in_library.append(m)
        proj.written_at[m] = time.time()
    save(lib, proj)


def changed_since_written(lib: Library, proj: Project) -> list[str]:
    """Parts in the project's library that you've changed in PartKit since they were written there."""
    out = []
    for m in proj.in_library:
        p = lib.get(m)
        if p and m in proj.written_at and p.updated > proj.written_at[m] + 1:
            out.append(m)
    return out
