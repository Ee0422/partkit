"""Projects: the parts one board uses, and (if you want) its own library.

A project starts empty, from templates (kits), or as a copy of another
project. Adding a part to a project adds it to that project only. By
default a project uses your main library. Tick "own library" and PartKit
writes the project's parts into the project's own .SchLib/.PcbLib, and
"Update project library" sends only the parts it doesn't have yet.
"""

from __future__ import annotations

import json
import os
import re
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

    @property
    def schlib(self) -> str:
        return str(Path(self.folder) / f"{_safe(self.name)}.SchLib")

    @property
    def pcblib(self) -> str:
        return str(Path(self.folder) / f"{_safe(self.name)}.PcbLib")

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


def create(lib: Library, name: str, templates: list[str] | None = None, copy_of: str = "",
           own_library: bool = False, folder: str = "") -> Project:
    """A new project, empty, from templates, or as a copy of another project's parts list."""
    name = name.strip()
    if not name:
        raise ValueError("A project needs a name.")
    if get(lib, name):
        raise ValueError(f"There's already a project called {name!r}.")
    proj = Project(name, own_library=own_library, folder=folder or default_folder(lib, name),
                   templates=list(templates or []))
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
    job = lib.write_sync_job(parts=ready, dst=(proj.schlib, proj.pcblib), kind=f"project:{proj.name}")
    return job, waiting


def record_written(lib: Library, name: str, mpns: list[str]) -> None:
    """PartKit Sync reported these parts written into the project's library."""
    proj = get(lib, name)
    if proj is None:
        return
    for m in mpns:
        if m not in proj.in_library:
            proj.in_library.append(m)
    save(lib, proj)
