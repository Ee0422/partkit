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
    stage: str = "Review"
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
    notes: list[str] = field(default_factory=list)
    updated: float = 0.0

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

    def undo(self, mpn: str) -> Part | None:
        """Restore the previous saved version of a part. Returns it, or None."""
        stem = self._part_path(mpn).stem
        hist = sorted((self.root / "partkit-data" / "history").glob(f"{stem}.*.json"),
                      key=lambda p: int(p.name.split(".")[-2]))
        if not hist:
            return None
        last = hist[-1]
        os.replace(last, self._part_path(mpn))
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
        if part.source != "PartKit" and not (part.symbol and part.footprint):
            raise KeyError(f"{mpn} has no symbol or footprint yet. Get its CAD files first "
                           "(Search > Get CAD files, or import a download).")
        part.stage = "Released"
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
    def write_sync_job(self) -> Path | None:
        """Write the job PartKit Sync runs inside Altium. Returns its path, or None if nothing to do.

        Plain 'KEY=VALUE' lines grouped in [PART]...[END] blocks, so the
        DelphiScript side can read it with a TStringList and no parser.
        """
        pending = [p for p in self.parts() if p.needs_sync or (self.settings.skip_review and p.stage == "Review")]
        if not pending:
            return None
        lines = ["# PartKit sync job", f"LIBRARY_ROOT={self.root.resolve()}"]
        from .passives import footprints_needed  # local import: passives imports this module

        for fp in footprints_needed(pending):
            lines.append("[FOOTPRINT]")
            lines.append(f"PCBLIB={_generic_pcblib()}")
            for k, v in fp.items():
                lines.append(f"{k.upper()}={v}")
            lines.append("[END]")
        for p in pending:
            lines.append("[PART]")
            stage = "Released" if self.settings.skip_review and p.stage == "Review" else p.stage
            for k, v in (
                ("MPN", p.mpn), ("STAGE", stage), ("CATEGORY", p.category),
                ("SRC_SCHLIB", p.schlib), ("SRC_SYMBOL", p.symbol),
                ("SRC_PCBLIB", p.pcblib), ("SRC_FOOTPRINT", p.footprint),
                ("DST_SCHLIB", p.target_schlib), ("DST_PCBLIB", p.target_pcblib),
                ("STEP", p.step), ("MODEL3D", p.model_3d_source),
                ("BOX_MM", ",".join(f"{x:g}" for x in p.box_mm)),
                ("COMPONENT_NAME", F.display_name(p.params, p.category) or p.mpn),
                ("GENERIC", "1" if p.source == "PartKit" else "0"),
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
        path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8-sig")
        _point_altium_at(path)
        return path

    def read_sync_result(self) -> list[str]:
        """Apply the result file PartKit Sync writes ('OK=<mpn>' / 'FAIL=<mpn>|reason')."""
        path = self.root / "partkit-data" / "sync" / "sync-result.txt"
        if not path.exists():
            return []
        messages = []
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("OK="):
                part = self.get(line[3:].strip())
                if part:
                    part.needs_sync = False
                    self.save(part)
                    messages.append(f"{part.mpn}: synced")
            elif line.startswith("FAIL="):
                mpn, _, why = line[5:].partition("|")
                messages.append(f"{mpn.strip()}: failed ({why.strip()})")
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


def _generic_pcblib() -> str:
    from .passives import GENERIC_PCBLIB

    return GENERIC_PCBLIB


def _clean(v) -> str:
    return str(v).replace("\r", " ").replace("\n", " ").strip()
