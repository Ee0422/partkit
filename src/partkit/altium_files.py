"""Read names and facts out of Altium .SchLib and .PcbLib files.

Both are OLE compound files. PartKit only reads them; writing is left to
Altium itself (see partkit/altium/PartKitSync.pas), because only Altium can
write these files safely.

Every function here takes an "ole" object with the olefile.OleFileIO
interface (listdir, exists, openstream), so tests can pass a fake.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_LIBREF = re.compile(r"\|LibRef(\d+)=([^|\x00\r\n]*)", re.IGNORECASE)
_RECORD_SPLIT = re.compile(r"\|(?=[A-Za-z%][A-Za-z0-9_%.]*=)")
_NON_FOOTPRINT_STORAGES = {"library", "fileversioninfo", "sectionkeys"}


@dataclass
class SchLibInfo:
    symbols: list[str]
    # symbol name -> {parameter name: value} as stored in the vendor file
    parameters: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass
class PcbLibInfo:
    footprints: list[str]
    embedded_models: int  # STEP/3D models stored inside the PcbLib


def parse_records(raw: bytes) -> list[dict[str, str]]:
    """Split Altium's '|KEY=VALUE|KEY=VALUE' records into dicts.

    Records are length-prefixed and NUL-terminated; we are lenient and split
    on NULs, which is enough for reading.
    """
    text = raw.decode("latin-1")
    out = []
    for chunk in text.split("\x00"):
        if "|" not in chunk or "=" not in chunk:
            continue
        rec = {}
        body = chunk[chunk.index("|"):]
        for part in _RECORD_SPLIT.split(body):
            part = part.lstrip("|")
            if "=" in part:
                k, v = part.split("=", 1)
                rec[k.strip().upper()] = v.strip()
        if rec:
            out.append(rec)
    return out


def _read(ole, path: list[str]) -> bytes | None:
    if not ole.exists("/".join(path)):
        return None
    return ole.openstream(path).read()


def read_schlib(ole) -> SchLibInfo:
    header = _read(ole, ["FileHeader"]) or b""
    refs = sorted(
        ((int(i), name.strip()) for i, name in _LIBREF.findall(header.decode("latin-1"))),
        key=lambda t: t[0],
    )
    symbols = [n for _, n in refs if n]
    if not symbols:
        # Fallback: component storages, names truncated to 31 characters.
        symbols = sorted({p[0] for p in ole.listdir() if len(p) > 1 and p[0].lower() != "storage"})

    params: dict[str, dict[str, str]] = {}
    storages = {p[0] for p in ole.listdir() if len(p) > 1}
    for sym in symbols:
        storage = sym[:31]
        if storage not in storages:
            continue
        data = _read(ole, [storage, "Data"])
        if not data:
            continue
        p = {}
        for rec in parse_records(data):
            if rec.get("RECORD") == "41" and rec.get("NAME") and "TEXT" in rec:
                p[rec["NAME"]] = rec["TEXT"]
        if p:
            params[sym] = p
    return SchLibInfo(symbols=symbols, parameters=params)


def read_pcblib(ole) -> PcbLibInfo:
    entries = ole.listdir()
    storages = sorted({p[0] for p in entries if len(p) > 1 and p[0].lower() not in _NON_FOOTPRINT_STORAGES})
    footprints = []
    for st in storages:
        name = st
        raw = _read(ole, [st, "Parameters"])
        if raw:
            for rec in parse_records(raw):
                if rec.get("PATTERN"):
                    name = rec["PATTERN"]
                    break
        footprints.append(name)
    models = sum(
        1 for p in entries
        if len(p) == 3 and p[0].lower() == "library" and p[1].lower() == "models" and p[2].isdigit()
    )
    return PcbLibInfo(footprints=footprints, embedded_models=models)


def extract_embedded_models(ole) -> list[tuple[str, bytes]]:
    """STEP models stored inside a PcbLib, as (file name, STEP bytes).

    Altium keeps them zlib-compressed in Library/Models/<n>; their names are
    in Library/Models/Data. A model that can't be decompressed is skipped.
    """
    import zlib

    names = [r.get("NAME", "") for r in parse_records(_read(ole, ["Library", "Models", "Data"]) or b"")]
    idx = sorted(int(p[2]) for p in ole.listdir()
                 if len(p) == 3 and p[0].lower() == "library" and p[1].lower() == "models" and p[2].isdigit())
    out = []
    for i in idx:
        raw = _read(ole, ["Library", "Models", str(i)]) or b""
        try:
            data = zlib.decompress(raw)
        except zlib.error:
            continue
        name = names[i] if i < len(names) and names[i] else f"model{i}.step"
        out.append((name, data))
    return out


def embedded_models(path: Path) -> list[tuple[str, bytes]]:
    ole = open_ole(path)
    try:
        return extract_embedded_models(ole)
    finally:
        ole.close()


def open_ole(path: Path):
    import olefile

    return olefile.OleFileIO(str(path))


def schlib_info(path: Path) -> SchLibInfo:
    ole = open_ole(path)
    try:
        return read_schlib(ole)
    finally:
        ole.close()


def pcblib_info(path: Path) -> PcbLibInfo:
    ole = open_ole(path)
    try:
        return read_pcblib(ole)
    finally:
        ole.close()
