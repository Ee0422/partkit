"""The PartKit library: folders, the master parts list, stages and sync jobs.

The master list is one small JSON file per part in partkit-data/parts/, so
any change is easy to see, back up or undo. Altium never reads these files;
PartKit Sync (an Altium script) reads the sync job PartKit writes and puts
symbols, footprints, 3D models and parameters into the .SchLib/.PcbLib files.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import fields as F
from .config import Settings, load_settings, save_settings

FOLDERS = ("Libraries", "3D", "Review", "Archive", "partkit-data/parts",
           "partkit-data/history", "partkit-data/sync")


def safe_name(mpn: str) -> str:
    """A file-system safe version of an MPN ('LM317/T' -> 'LM317_T')."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", mpn.strip())
    return s.rstrip(". ") or "part"


@dataclass
class Part:
    mpn: str
    category: str = F.DEFAULT_CATEGORY
    stage: str = F.TO_CHECK
    params: dict[str, str] = field(default_factory=dict)
    source: str = "unknown"            # SnapMagic, SamacSys, UltraLibrarian, PartKit, ...
    schlib: str = ""                   # path relative to library root
    symbol: str = ""
    pcblib: str = ""
    footprint: str = ""
    step: str = ""                     # path relative to library root, if any
    model_3d: str = "None"             # Full / Simple / None
    model_3d_source: str = "none"      # embedded / external / hunted / box / none
    box_mm: list[float] = field(default_factory=list)  # [length, width, height] for a Simple box
    target_schlib: str = ""
    target_pcblib: str = ""
    needs_sync: bool = False
    favourite: bool = False            # starred: shown first when picking parts
    copied_from: str = ""              # MPN whose checked symbol/footprint this part reuses
    notes: list[str] = field(default_factory=list)
    updated: float = 0.0

    def __post_init__(self):
        self.stage = F.OLD_STAGE_NAMES.get(self.stage, self.stage)

    def bom_params(self) -> dict[str, str]:
        """Every parameter written onto the Altium symbol, standard names first."""
        out = {k: self.params.get(k, "") for k in F.BOM_FIELDS}
        out["Manufacturer Part Number"] = out["Manufacturer Part Number"] or self.mpn
        for k in F.category_fields(self.category):
            if self.params.get(k):
                out[k] = self.params[k]
        for k, v in self.params.items():
            out.setdefault(k, v)
        out["Category"] = self.category
        out["PartKit Status"] = self.stage
        out["3D Model"] = self.model_3d
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "Part":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class Issue:
    mpn: str
    problem: str
    fix: str


class Library:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.settings: Settings = load_settings(self.root)

    # ---------- setup ----------
    @classmethod
    def init(cls, root: Path, settings: Settings | None = None) -> "Library":
        root = Path(root)
        for f in FOLDERS:
            (root / f).mkdir(parents=True, exist_ok=True)
        if settings is not None or not (root / "partkit-settings.toml").exists():
            save_settings(root, settings or Settings())
        return cls(root)

    def save_settings(self) -> None:
        save_settings(self.root, self.settings)

    @property
    def parts_dir(self) -> Path:
        return self.root / "partkit-data" / "parts"

    # ---------- parts ----------
    def _part_path(self, mpn: str) -> Path:
        return self.parts_dir / f"{safe_name(mpn)}.json"

    def get(self, mpn: str) -> Part | None:
        p = self._part_path(mpn)
        if not p.exists():
            return None
        return Part.from_dict(json.loads(p.read_text(encoding="utf-8")))

    def parts(self) -> list[Part]:
        out = []
        for p in sorted(self.parts_dir.glob("*.json")):
            out.append(Part.from_dict(json.loads(p.read_text(encoding="utf-8"))))
        return out

    def save(self, part: Part) -> None:
        if part.stage not in F.STAGES:
            raise ValueError(f"unknown stage {part.stage!r}")
        if part.model_3d not in F.MODEL_3D_STATES:
            raise ValueError(f"unknown 3D state {part.model_3d!r}")
        path = self._part_path(part.mpn)
        if path.exists():  # keep the previous version for undo
            hist = self.root / "partkit-data" / "history" / f"{path.stem}.{time.time_ns()}.json"
            shutil.copy2(path, hist)
        part.updated = time.time()
        if not part.target_schlib or not part.target_pcblib:
            s, p = self.settings.target_libs(part.category)
            part.target_schlib = part.target_schlib or s
            part.target_pcblib = part.target_pcblib or p
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(part), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    def set_favourite(self, mpn: str, on: bool = True) -> Part:
        part = self._require(mpn)
        part.favourite = on
        self.save(part)
        return part

    def remove_starter_parts(self) -> int:
        """Take out the unchecked starter passives older PartKit versions added. Returns how many.

        Each one is kept in partkit-data/history, so nothing is lost for good.
        """
        removed = 0
        for part in self.parts():
            if part.source != "PartKit":
                continue
            path = self._part_path(part.mpn)
            hist = self.root / "partkit-data" / "history" / f"{path.stem}.removed.{time.time_ns()}.json"
            shutil.move(str(path), hist)
            removed += 1
        return removed

    def delete_part(self, mpn: str, from_altium: bool = False) -> Part:
        """Take a part out of PartKit, its templates and its projects. `partkit undo` brings it back.

        With from_altium, the next Send also removes its symbol from your main library
        (the footprint stays: other parts may use it).
        """
        from . import kits, projects  # local import: they import this module

        part = self._require(mpn)
        path = self._part_path(part.mpn)
        hist = self.root / "partkit-data" / "history" / f"{path.stem}.deleted.{time.time_ns()}.json"
        shutil.move(str(path), hist)
        for kit in kits.kits(self):
            if any(it.mpn == part.mpn for it in kit.items):
                kit.remove(part.mpn)
                kits.save(self, kit)
        for proj in projects.projects(self):
            if proj.has(part.mpn):
                proj.remove(part.mpn)
                if part.mpn in proj.in_library:
                    proj.in_library.remove(part.mpn)
                projects.save(self, proj)
        removals = [r for r in self.pending_removals() if r["mpn"] != part.mpn]
        if from_altium and part.target_schlib:
            removals.append({"mpn": part.mpn, "name": F.display_name(part.params, part.category) or part.mpn,
                             "schlib": part.target_schlib, "pcblib": part.target_pcblib})
        self._save_removals(removals)
        return part

    def _removals_path(self) -> Path:
        return self.root / "partkit-data" / "sync" / "pending-removals.json"

    def pending_removals(self) -> list[dict]:
        """Deleted parts whose symbols the next Send takes out of your main library."""
        try:
            return json.loads(self._removals_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _save_removals(self, removals: list[dict]) -> None:
        path = self._removals_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(removals, indent=2, ensure_ascii=False), encoding="utf-8")

    def undo(self, mpn: str) -> Part | None:
        """Restore the previous saved version of a part. Returns it, or None."""
        stem = self._part_path(mpn).stem
        hist = sorted((self.root / "partkit-data" / "history").glob(f"{stem}.*.json"),
                      key=lambda p: int(p.name.split(".")[-2]))
        if not hist:
            return None
        last = hist[-1]
        os.replace(last, self._part_path(mpn))
        if ".deleted." in last.name:  # undoing a delete: don't remove it from Altium after all
            self._save_removals([r for r in self.pending_removals() if r["mpn"] != mpn])
        return self.get(mpn)

    def find_same_spec(self, part: Part) -> Part | None:
        """Another part with the same MPN, or (for passives) the same full spec."""
        same = self.get(part.mpn)
        if same:
            return same
        keys = F.category_fields(part.category)
        if not keys or part.category not in ("Capacitors", "Resistors"):
            return None
        want = {k: part.params.get(k) for k in keys if part.params.get(k)}
        if not want:
            return None
        for other in self.parts():
            if other.category == part.category and all(other.params.get(k) == v for k, v in want.items()):
                return other
        return None

    # ---------- stages ----------
    def approve(self, mpn: str) -> Part:
        part = self._require(mpn)
        if part.source == "PartKit":
            raise KeyError(f"{mpn} is an old PartKit starter part whose footprint was never checked. "
                           "Remove it (partkit remove-starter) and add a checked part instead.")
        if not (part.symbol and part.footprint):
            raise KeyError(f"{mpn} has no symbol or footprint yet. Get its CAD files first "
                           "(Search > Get CAD files, or import a download).")
        part.stage = F.READY
        part.needs_sync = True
        self.save(part)
        return part

    def mark_obsolete(self, mpn: str, reason: str = "") -> Part:
        part = self._require(mpn)
        part.stage = "Obsolete"
        part.needs_sync = True
        if reason:
            part.notes.append(f"Obsolete: {reason}")
        self.save(part)
        return part

    def _require(self, mpn: str) -> Part:
        part = self.get(mpn)
        if part is None:
            raise KeyError(f"No part {mpn!r} in the library")
        return part

    # ---------- health check ----------
    def health_check(self) -> list[Issue]:
        issues: list[Issue] = []
        for part in self.parts():
            if part.source == "PartKit":
                issues.append(Issue(part.mpn, "Old PartKit starter part (footprint never checked)",
                                    "Click 'Remove old starter parts' (or run partkit remove-starter), then add a checked part"))
                continue
            bp = part.bom_params()
            missing = [f for f in F.REQUIRED_FOR_BOM if not bp.get(f)]
            if missing:
                issues.append(Issue(part.mpn, "Missing BOM fields: " + ", ".join(missing),
                                    "Fill them in, or add supplier API keys so PartKit can"))
            for label, rel in (("symbol library", part.schlib), ("footprint library", part.pcblib)):
                if rel and not (self.root / rel).exists():
                    issues.append(Issue(part.mpn, f"The {label} file is missing: {rel}",
                                        "Re-import the part from the Archive folder"))
            if not part.symbol:
                issues.append(Issue(part.mpn, "No symbol", "Import a CAD zip for this part"))
            if not part.footprint:
                issues.append(Issue(part.mpn, "No footprint", "Import a CAD zip for this part"))
            if part.step and not (self.root / part.step).exists():
                issues.append(Issue(part.mpn, f"3D model file is missing: {part.step}",
                                    "Drop a .step file on the part to replace it"))
            if part.model_3d != "Full":
                issues.append(Issue(part.mpn, f"3D model is {part.model_3d}",
                                    "Drop a .step file on the part to replace it"))
        return issues

    # ---------- sync job for Altium ----------
    def pending_changes(self) -> list[Part]:
        """Parts waiting for Send to Altium (main library)."""
        return [p for p in self.parts() if p.needs_sync or (self.settings.skip_review and p.stage == F.TO_CHECK)]

    def send_count(self) -> int:
        """Everything the next Send does: main library changes, deletions and new project-library parts."""
        from . import projects

        return len(self.pending_changes()) + len(self.pending_removals()) + sum(
            len(projects.missing_from_library(self, pr)[0]) for pr in projects.projects(self) if pr.own_library)

    def nothing_to_send_reason(self) -> str:
        """Why Send found nothing to do: parts that can't go yet, or plain 'up to date'."""
        from . import projects

        uses: dict[str, list[str]] = {}
        for pr in projects.projects(self):
            for it in pr.items:
                uses.setdefault(it.mpn, []).append(pr.name)
        waiting = [p for p in self.parts() if p.stage == F.TO_CHECK]
        waiting.sort(key=lambda p: (p.mpn not in uses, p.mpn))
        if not waiting:
            return "Your Altium libraries are already up to date."
        lines = []
        for p in waiting[:5]:
            where = f" (in {', '.join(uses[p.mpn])})" if p.mpn in uses else ""
            lines.append(f"{p.mpn}{where} is still To check.")
        if len(waiting) > 5:
            lines.append(f"...and {len(waiting) - 5} more.")
        return ("Nothing to send yet. Only Ready parts go into Altium.\n\n" + "\n".join(lines)
                + "\n\nSelect them in My parts and press Mark Ready, then Send again.")

    def write_sync_job(self, parts: list[Part] | None = None, dst: tuple[str, str] | None = None,
                       kind: str = "main", prjpcb: str = "") -> Path | None:
        """Write the job PartKit Sync runs inside Altium. Returns its path, or None if nothing to do.

        With no parts given this is Send: main library changes, deletions, and the parts
        each project library doesn't have yet, all in one job.

        Plain 'KEY=VALUE' lines grouped in [PART]...[END] blocks, so the
        DelphiScript side can read it with a TStringList and no parser.
        FOR= says where a block's result belongs; PartKit Sync echoes it back.
        """
        entries = [(p, dst, kind, prjpcb) for p in (self.pending_changes() if parts is None else parts)]
        removals = []
        if parts is None:
            from . import projects

            removals = self.pending_removals()
            for pr in projects.projects(self):
                if pr.own_library:
                    entries += [(p, (pr.schlib, pr.pcblib), f"project:{pr.name}", pr.prjpcb)
                                for p in projects.missing_from_library(self, pr)[0]]
        if not entries and not removals:
            return None
        lines = ["# PartKit sync job", f"LIBRARY_ROOT={self.root.resolve()}"]
        for r in removals:
            lines += ["[PART]", "ACTION=REMOVE", "FOR=remove", f"MPN={_clean(r['mpn'])}",
                      f"COMPONENT_NAME={_clean(r['name'])}", f"DST_SCHLIB={_clean(r['schlib'])}",
                      f"DST_PCBLIB={_clean(r.get('pcblib', ''))}", "[END]"]
        for p, d, for_, prj in entries:
            lines.append("[PART]")
            stage = F.READY if self.settings.skip_review and p.stage == F.TO_CHECK else p.stage
            for k, v in (
                ("FOR", for_), ("PRJPCB", prj), ("INSTALL", "1" if for_ == "main" else "0"),
                ("MPN", p.mpn), ("STAGE", stage), ("CATEGORY", p.category),
                ("SRC_SCHLIB", p.schlib), ("SRC_SYMBOL", p.symbol),
                ("SRC_PCBLIB", p.pcblib), ("SRC_FOOTPRINT", p.footprint),
                ("DST_SCHLIB", d[0] if d else p.target_schlib),
                ("DST_PCBLIB", d[1] if d else p.target_pcblib),
                ("STEP", p.step), ("MODEL3D", p.model_3d_source),
                ("BOX_MM", ",".join(f"{x:g}" for x in p.box_mm)),
                ("COMPONENT_NAME", F.display_name(p.params, p.category) or p.mpn),
                ("GENERIC", "0"),
                ("DESIGNATOR", F.DESIGNATOR_PREFIX.get(p.category, "U") + "?"),
            ):
                lines.append(f"{k}={_clean(v)}")
            comment = p.params.get("Value") or p.mpn
            lines.append(f"COMMENT={_clean(comment)}")
            lines.append(f"DESCRIPTION={_clean(p.params.get('Description', ''))}")
            for k, v in p.bom_params().items():
                lines.append(f"PARAM={_clean(k)}|{_clean(v)}")
            lines.append("[END]")
        path = self.root / "partkit-data" / "sync" / "pending-sync.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8-sig")
        # for older PartKit Sync scripts that don't echo FOR= back
        (path.parent / "pending-kind.txt").write_text(kind, encoding="utf-8")
        _point_altium_at(path)
        return path

    def sync_result_waiting(self) -> bool:
        return (self.root / "partkit-data" / "sync" / "sync-result.txt").exists()

    def read_sync_result(self) -> list[str]:
        """Apply the result file PartKit Sync writes.

        Lines are 'OK=<mpn>' or 'FAIL=<mpn>|reason', each after a 'FOR=<where>' line
        (main, remove, or project:<name>) when the script is new enough to write it.
        """
        path = self.root / "partkit-data" / "sync" / "sync-result.txt"
        if not path.exists():
            return []
        messages = []
        kind_file = path.parent / "pending-kind.txt"
        where = kind_file.read_text(encoding="utf-8").strip() if kind_file.exists() else "main"
        written: dict[str, list[str]] = {}
        removed: list[str] = []
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("FOR="):
                where = line[4:].strip() or "main"
            elif line.startswith("OK="):
                mpn = line[3:].strip()
                if where == "remove":
                    removed.append(mpn)
                    messages.append(f"{mpn}: removed from your library")
                    continue
                part = self.get(mpn)
                if part and where == "main":
                    part.needs_sync = False
                    self.save(part)
                if where.startswith("project:"):
                    written.setdefault(where[len("project:"):], []).append(mpn)
                    messages.append(f"{mpn}: written into project {where[len('project:'):]}")
                elif part:
                    messages.append(f"{part.mpn}: synced")
            elif line.startswith("FAIL="):
                mpn, _, why = line[5:].partition("|")
                messages.append(f"{mpn.strip()}: failed ({why.strip()})")
        if written:
            from . import projects  # local import: projects imports this module

            for name, mpns in written.items():
                projects.record_written(self, name, mpns)
        if removed:
            self._save_removals([r for r in self.pending_removals() if r["mpn"] not in removed])
        path.rename(path.with_name(f"sync-result.{time.time_ns()}.txt"))
        return messages


def _point_altium_at(job: Path) -> None:
    """Tell PartKit Sync (in Altium) where the current job is, so it needn't ask."""
    base = os.environ.get("ProgramData")
    if os.name != "nt" or not base:
        return
    try:
        d = Path(base) / "PartKit"
        d.mkdir(parents=True, exist_ok=True)
        (d / "current-job.txt").write_text(str(job.resolve()), encoding="utf-8")
    except OSError:
        pass  # Sync falls back to asking for the file


def _clean(v) -> str:
    return str(v).replace("\r", " ").replace("\n", " ").strip()
