"""Import vendor CAD downloads (SnapMagic, SamacSys, Ultra Librarian, manufacturers).

Files are found by type wherever they sit in the zip, including zips inside
zips, so differing or changing vendor layouts still work. Every import lands
in the To check stage; nothing reaches your chosen libraries until approved.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable

from . import fields as F
from .altium_files import PcbLibInfo, SchLibInfo, embedded_models, extract_intlib_file, pcblib_info, schlib_info
from .library import Library, Part, safe_name

MAX_NESTING = 3
MAX_TOTAL_BYTES = 500 * 1024 * 1024  # refuse zip bombs

STEP_EXT = {".step", ".stp"}
INTLIB_EXT = {".intlib"}
DOWNLOAD_EXT = {".zip"} | INTLIB_EXT | STEP_EXT  # files the watcher and window accept
CAD_EXT = {".schlib", ".pcblib", ".intlib"} | STEP_EXT

_PREFIXES = re.compile(r"^(lib_|ul_|ul-|snapeda_|snapmagic_|samacsys_)", re.IGNORECASE)
_SUFFIXES = re.compile(r"([_-](altium|ad|altium_designer|lib|library|cad|3d))+$|\s*\(\d+\)$", re.IGNORECASE)


class ImportProblem(Exception):
    """A download PartKit could not import, with a plain-language explanation."""


@dataclass
class Found:
    schlibs: list[Path] = field(default_factory=list)
    pcblibs: list[Path] = field(default_factory=list)
    intlibs: list[Path] = field(default_factory=list)
    steps: list[Path] = field(default_factory=list)
    datasheets: list[Path] = field(default_factory=list)
    other: list[Path] = field(default_factory=list)

    @property
    def has_altium(self) -> bool:
        return bool(self.schlibs or self.pcblibs or self.intlibs)


@dataclass
class ImportResult:
    part: Part
    provider: str
    messages: list[str]
    replaced_existing: bool = False


# ---------------- extraction ----------------

def _safe_extract(zf: zipfile.ZipFile, dest: Path, budget: list[int]) -> None:
    dest = dest.resolve()
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = PurePosixPath(info.filename.replace("\\", "/"))
        if name.is_absolute() or ".." in name.parts:
            continue  # zip-slip: never write outside dest
        budget[0] -= info.file_size
        if budget[0] < 0:
            raise ImportProblem("This zip is far larger than any CAD download; PartKit stopped to be safe.")
        target = (dest / Path(*name.parts)).resolve()
        if dest not in target.parents:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)


def extract_all(zip_path: Path, dest: Path) -> None:
    """Extract a zip and any zips inside it (up to MAX_NESTING levels)."""
    budget = [MAX_TOTAL_BYTES]
    try:
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract(zf, dest, budget)
    except zipfile.BadZipFile as e:
        raise ImportProblem(f"{zip_path.name} is not a readable zip file.") from e
    for level in range(MAX_NESTING):
        nested = [p for p in dest.rglob("*") if p.is_file() and p.suffix.lower() == ".zip"]
        if not nested:
            break
        for z in nested:
            sub = z.with_suffix("")
            sub = sub.with_name(sub.name + "_unzipped")
            try:
                with zipfile.ZipFile(z) as zf:
                    _safe_extract(zf, sub, budget)
            except zipfile.BadZipFile:
                pass
            z.unlink()


def scan(folder: Path) -> Found:
    found = Found()
    for p in sorted(folder.rglob("*")):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext == ".schlib":
            found.schlibs.append(p)
        elif ext == ".pcblib":
            found.pcblibs.append(p)
        elif ext == ".intlib":
            found.intlibs.append(p)
        elif ext in STEP_EXT:
            found.steps.append(p)
        elif ext == ".pdf":
            found.datasheets.append(p)
        else:
            found.other.append(p)
    return found


def _prefer_altium(paths: list[Path]) -> Path | None:
    """When several candidates exist, prefer ones in an 'Altium' folder."""
    if not paths:
        return None
    ranked = sorted(paths, key=lambda p: (0 if "altium" in str(p).lower() else 1, len(p.parts), p.name))
    return ranked[0]


def detect_provider(zip_name: str, found: Found) -> str:
    text = (zip_name + " " + " ".join(str(p) for p in found.other + found.schlibs + found.pcblibs)).lower()
    if "samacsys" in text or "componentsearchengine" in text or zip_name.lower().startswith("lib_"):
        return "SamacSys"
    if "ultralibrarian" in text or "ultra librarian" in text or zip_name.lower().startswith(("ul_", "ul-")):
        return "UltraLibrarian"
    if "snapeda" in text or "snapmagic" in text:
        return "SnapMagic"
    return "Manufacturer/other"


def guess_mpn_from_name(name: str) -> str:
    stem = Path(name).stem
    stem = _PREFIXES.sub("", stem)
    prev = None
    while prev != stem:
        prev = stem
        stem = _SUFFIXES.sub("", stem)
    return stem.strip(" _-")


def _looks_like_ultralibrarian_script(found: Found) -> bool:
    for p in found.other:
        if p.suffix.lower() in {".pas", ".prjscr"}:
            return True
        if p.suffix.lower() == ".txt" and p.stat().st_size < 5_000_000:
            head = p.read_bytes()[:4000].decode("latin-1", "ignore").lower()
            if "ultra librarian" in head or "ultralibrarian" in head:
                return True
    return False


# ---------------- import ----------------

def _vendor_params(info: SchLibInfo | None, symbol: str) -> dict[str, str]:
    if not info:
        return {}
    raw = info.parameters.get(symbol) or (next(iter(info.parameters.values())) if info.parameters else {})
    out = {}
    for k, v in raw.items():
        if v and v != "*" and k.strip().lower() not in F.VENDOR_LINK_FIELDS:
            out[F.normalise_field(k)] = v
    return out


def import_zip(lib: Library, zip_path: Path, mpn: str | None = None, category: str | None = None,
               archive: bool = True, expected: str = "",
               confirm: Callable[[str, str], bool] | None = None) -> ImportResult:
    """Import a CAD download into To check.

    expected: the part you clicked Get CAD files for. The download becomes that part when
    the number inside it matches, or when confirm(number_in_file, expected) says yes.
    """
    zip_path = Path(zip_path)
    messages: list[str] = []
    with tempfile.TemporaryDirectory(prefix="partkit-") as tmp:
        work = Path(tmp)
        if zip_path.suffix.lower() in INTLIB_EXT:  # e.g. SnapMagic's single-file Altium download
            shutil.copy2(zip_path, work / zip_path.name)
        else:
            extract_all(zip_path, work)
        found = scan(work)
        if found.intlibs and not (found.schlibs and found.pcblibs):
            for i, il in enumerate(found.intlibs):
                try:
                    extract_intlib_file(il, work / "_intlib" / str(i))
                except Exception as e:  # noqa: BLE001 - explain instead of crashing
                    messages.append(f"Could not unpack {il.name} ({e}).")
            found = scan(work)
            found.intlibs = []
            if not (found.schlibs or found.pcblibs):
                raise ImportProblem(
                    f"PartKit couldn't unpack the integrated library in {zip_path.name}. In Altium, open it "
                    "and choose Extract Sources, or download the part again in the Altium .SchLib/.PcbLib format."
                )
        provider = detect_provider(zip_path.name, found)

        if not found.has_altium:
            if found.steps and not found.schlibs:
                target = mpn or guess_mpn_from_name(zip_path.name)
                if lib.get(target):
                    return attach_step(lib, target, found.steps[0], provider=provider)
            if _looks_like_ultralibrarian_script(found):
                raise ImportProblem(
                    "This is an Ultra Librarian download in its script format. PartKit Sync can run "
                    "it inside Altium; for now, download the part from another provider in your list, "
                    "or open the script in Altium (File > Run Script)."
                )
            raise ImportProblem(
                f"No Altium files (.SchLib, .PcbLib or .IntLib) were found in {zip_path.name}. "
                "Check that you chose the Altium format when downloading."
            )

        schlib = _prefer_altium(found.schlibs)
        pcblib = _prefer_altium(found.pcblibs)
        intlib = _prefer_altium(found.intlibs)
        step = _prefer_altium(found.steps)

        s_info: SchLibInfo | None = None
        p_info: PcbLibInfo | None = None
        if schlib:
            try:
                s_info = schlib_info(schlib)
            except Exception as e:  # noqa: BLE001 - vendor files vary; explain instead of crashing
                messages.append(f"Could not read symbol names from {schlib.name} ({e}); Altium will check it.")
        if pcblib:
            try:
                p_info = pcblib_info(pcblib)
            except Exception as e:  # noqa: BLE001
                messages.append(f"Could not read footprint names from {pcblib.name} ({e}); Altium will check it.")

        symbol = (s_info.symbols[0] if s_info and s_info.symbols else "")
        footprint = (p_info.footprints[0] if p_info and p_info.footprints else "")
        if s_info and len(s_info.symbols) > 1:
            messages.append(f"{schlib.name} holds {len(s_info.symbols)} symbols; using {symbol!r}.")
        if p_info and len(p_info.footprints) > 1:
            messages.append(f"{pcblib.name} holds {len(p_info.footprints)} footprints; using {footprint!r}.")

        if provider == "Manufacturer/other" and s_info:
            keys = " ".join(k.lower() for ps in s_info.parameters.values() for k in ps)
            if "snapeda" in keys or "snapmagic" in keys:
                provider = "SnapMagic"
        params = _vendor_params(s_info, symbol)
        in_file = (params.get("Manufacturer Part Number") or guess_mpn_from_name(zip_path.name)
                   or symbol or zip_path.stem).strip()
        if not mpn and expected:
            from .waiting import same_number

            if same_number(in_file, expected) or (confirm is not None and confirm(in_file, expected)):
                mpn = expected
        mpn = (mpn or in_file).strip()
        params["Manufacturer Part Number"] = mpn

        existing = lib.get(mpn)
        was_starter = existing is not None and existing.source == "PartKit"  # from older PartKit versions
        part = existing or Part(mpn=mpn)
        if category:
            part.category = category
        elif not existing:
            part.category = F.DEFAULT_CATEGORY
            messages.append("Category set to Misc; choose the right one before approving.")
        if category or was_starter:
            # vendor files go to the category's own libraries, not the old generic libraries
            part.target_schlib, part.target_pcblib = lib.settings.target_libs(part.category)
        for k, v in params.items():
            part.params.setdefault(k, v)
        part.stage = "To check"
        part.source = provider

        review = lib.root / "Review" / safe_name(mpn)
        if review.exists():
            shutil.rmtree(review)
        review.mkdir(parents=True)
        base = safe_name(mpn)
        if schlib:
            shutil.copy2(schlib, review / f"{base}.SchLib")
            part.schlib = f"Review/{base}/{base}.SchLib"
        if pcblib:
            shutil.copy2(pcblib, review / f"{base}.PcbLib")
            part.pcblib = f"Review/{base}/{base}.PcbLib"
        if intlib and not (schlib and pcblib):
            shutil.copy2(intlib, review / f"{base}.IntLib")
            part.schlib = part.schlib or f"Review/{base}/{base}.IntLib"
            part.pcblib = part.pcblib or f"Review/{base}/{base}.IntLib"
            messages.append("This download is an integrated library; PartKit Sync extracts it inside Altium.")
        part.symbol = symbol or part.symbol
        part.footprint = footprint or part.footprint
        if found.datasheets and not part.params.get("Datasheet"):
            shutil.copy2(found.datasheets[0], review / found.datasheets[0].name)
            part.params["Datasheet"] = f"Review/{base}/{found.datasheets[0].name}"

        if not step and pcblib and p_info and p_info.embedded_models:
            try:  # keep a .step copy of the embedded model too, so it can be reused
                models = embedded_models(pcblib)
            except Exception:  # noqa: BLE001
                models = []
            if models:
                step = work / "_embedded" / (Path(models[0][0]).stem + ".step")
                step.parent.mkdir(exist_ok=True)
                step.write_bytes(models[0][1])
        _set_3d(lib, part, p_info, step, messages)

        if archive:
            arch = lib.root / "Archive" / zip_path.name
            if zip_path.resolve() != arch.resolve():
                if arch.exists():
                    arch = arch.with_name(f"{arch.stem}-{base}{arch.suffix}")
                shutil.copy2(zip_path, arch)

        lib.save(part)
        messages.append(f"{mpn} imported from {provider} into To check ({part.model_3d} 3D model).")
        return ImportResult(part=part, provider=provider, messages=messages, replaced_existing=existing is not None)


def _set_3d(lib: Library, part: Part, p_info: PcbLibInfo | None, step: Path | None, messages: list[str]) -> None:
    """The three cases: model inside the PcbLib, a separate .step, or none at all."""
    base = safe_name(part.mpn)
    if step:  # always keep a .step copy so it can be reused or swapped
        dest = lib.root / "3D" / f"{base}{step.suffix.lower()}"
        shutil.copy2(step, dest)
        part.step = f"3D/{dest.name}"
    if p_info and p_info.embedded_models > 0:
        part.model_3d, part.model_3d_source = "Full", "embedded"
        messages.append("3D model is already inside the footprint.")
    elif step:
        part.model_3d, part.model_3d_source = "Full", "external"
        messages.append("3D model came as a separate file; PartKit Sync will place it on the footprint.")
    else:
        part.model_3d, part.model_3d_source = "Simple", "box"
        messages.append("No 3D model in this download; a simple 3D box will be added. "
                        "Drop a .step file on the part to replace it.")


def attach_step(lib: Library, mpn: str, step: Path, provider: str = "manual") -> ImportResult:
    """Attach a separately downloaded 3D model to a part that is already in the library."""
    part = lib.get(mpn)
    if part is None:
        raise ImportProblem(f"No part {mpn!r} to attach this 3D model to.")
    dest = lib.root / "3D" / f"{safe_name(mpn)}{Path(step).suffix.lower()}"
    shutil.copy2(step, dest)
    part.step = f"3D/{dest.name}"
    part.model_3d, part.model_3d_source = "Full", "external"
    part.box_mm = []
    if part.stage == "Ready":
        part.needs_sync = True
    lib.save(part)
    return ImportResult(part=part, provider=provider,
                        messages=[f"3D model attached to {mpn}; PartKit Sync will place it on the footprint."])


def looks_like_cad_download(path: Path) -> bool:
    """Cheap check used by the Downloads watcher before importing."""
    path = Path(path)
    if path.suffix.lower() in STEP_EXT | INTLIB_EXT:
        return True
    if path.suffix.lower() != ".zip":
        return False
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n.lower() for n in zf.namelist()]
    except (zipfile.BadZipFile, OSError):
        return False
    return any(Path(n).suffix in CAD_EXT or n.endswith(".zip") for n in names)
