import os
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")  # never touch a real password store

import io
import zipfile
from pathlib import Path

import pytest

from partkit import importer
from partkit.altium_files import PcbLibInfo, SchLibInfo
from partkit.library import Library


class FakeOle:
    """Minimal stand-in for olefile.OleFileIO: {('A','B'): bytes}."""

    def __init__(self, streams: dict[tuple[str, ...], bytes]):
        self.streams = streams

    def listdir(self):
        return [list(k) for k in self.streams]

    def exists(self, path: str):
        return tuple(path.split("/")) in self.streams

    def openstream(self, path):
        return io.BytesIO(self.streams[tuple(path)])


@pytest.fixture
def lib(tmp_path) -> Library:
    return Library.init(tmp_path / "lib")


def make_zip(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


@pytest.fixture
def fake_altium(monkeypatch):
    """Replace the OLE readers so fake .SchLib/.PcbLib bytes can be used.

    The fake file content decides what is 'inside':
      b"SYM:<name>;MPN:<mpn>"   for a SchLib
      b"FP:<name>;MODELS:<n>"   for a PcbLib
    """

    def fake_sch(path):
        d = dict(kv.split(":", 1) for kv in Path(path).read_bytes().decode().split(";") if ":" in kv)
        params = {"Manufacturer_Part_Number": d["MPN"], "Manufacturer_Name": "Texas Instruments"} if "MPN" in d else {}
        return SchLibInfo(symbols=[d["SYM"]], parameters={d["SYM"]: params} if params else {})

    def fake_pcb(path):
        d = dict(kv.split(":", 1) for kv in Path(path).read_bytes().decode().split(";") if ":" in kv)
        return PcbLibInfo(footprints=[d["FP"]], embedded_models=int(d.get("MODELS", 0)))

    monkeypatch.setattr(importer, "schlib_info", fake_sch)
    monkeypatch.setattr(importer, "pcblib_info", fake_pcb)
    monkeypatch.setattr(importer, "embedded_models", lambda path: [("x.step", b"ISO-10303-21;")])
