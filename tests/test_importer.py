from partkit.library import Part
import zipfile

import pytest

from partkit.importer import (ImportProblem, guess_mpn_from_name, import_zip, looks_like_cad_download,
                              detect_provider, Found)

from conftest import make_zip


def test_guess_mpn_from_name():
    assert guess_mpn_from_name("LIB_TPS62130RGTR.zip") == "TPS62130RGTR"
    assert guess_mpn_from_name("ul_LM358DR.zip") == "LM358DR"
    assert guess_mpn_from_name("STM32F103C8T6_altium (1).zip") == "STM32F103C8T6"


def test_embedded_3d_model(lib, fake_altium, tmp_path):
    z = make_zip(tmp_path / "LIB_TPS62130RGTR.zip", {
        "TPS62130RGTR/Altium/TPS62130RGTR.SchLib": b"SYM:TPS62130;MPN:TPS62130RGTR",
        "TPS62130RGTR/Altium/TPS62130RGTR.PcbLib": b"FP:QFN16;MODELS:1",
        "TPS62130RGTR/KiCad/TPS62130RGTR.kicad_sym": b"ignored",
    })
    res = import_zip(lib, z, category="Power")
    p = res.part
    assert res.provider == "SamacSys"
    assert p.mpn == "TPS62130RGTR" and p.stage == "To check" and p.category == "Power"
    assert p.model_3d == "Full" and p.model_3d_source == "embedded"
    assert p.params["Manufacturer"] == "Texas Instruments"
    assert (lib.root / p.schlib).exists() and (lib.root / p.pcblib).exists()
    assert (lib.root / "Archive" / z.name).exists()
    assert p.target_schlib == "Libraries/Power.SchLib"


def test_separate_step_file_inside_nested_zip(lib, fake_altium, tmp_path):
    inner = make_zip(tmp_path / "inner.zip", {"3D/LM358DR.step": b"ISO-10303-21;"})
    z = make_zip(tmp_path / "LM358DR.zip", {
        "LM358DR.SchLib": b"SYM:LM358",
        "LM358DR.PcbLib": b"FP:SOIC8;MODELS:0",
        "models.zip": inner.read_bytes(),
    })
    p = import_zip(lib, z).part
    assert p.model_3d == "Full" and p.model_3d_source == "external"
    assert p.step == "3D/LM358DR.step" and (lib.root / p.step).exists()
    assert p.category == "Misc"


def test_no_3d_model_gets_simple_box(lib, fake_altium, tmp_path):
    z = make_zip(tmp_path / "ABC123.zip", {"ABC123.SchLib": b"SYM:ABC", "ABC123.PcbLib": b"FP:SOT23"})
    p = import_zip(lib, z, mpn="ABC123").part
    assert p.model_3d == "Simple" and p.model_3d_source == "box"
    assert any(i.problem == "3D model is Simple" for i in lib.health_check())


def test_separate_3d_download_attaches_to_existing_part(lib, fake_altium, tmp_path):
    z = make_zip(tmp_path / "ABC123.zip", {"ABC123.SchLib": b"SYM:ABC", "ABC123.PcbLib": b"FP:SOT23"})
    import_zip(lib, z, mpn="ABC123")
    z3d = make_zip(tmp_path / "ABC123_3d.zip", {"ABC123.stp": b"ISO-10303-21;"})
    p = import_zip(lib, z3d, mpn="ABC123").part
    assert p.model_3d == "Full" and p.model_3d_source == "external"


def test_zip_without_altium_files_explains(lib, tmp_path):
    z = make_zip(tmp_path / "part.zip", {"KiCad/part.kicad_mod": b"x"})
    with pytest.raises(ImportProblem, match="Altium format"):
        import_zip(lib, z)


def test_ultralibrarian_script_format_explains(lib, tmp_path):
    z = make_zip(tmp_path / "ul_X1.zip", {"Altium/UL_Import.pas": b"begin end."})
    with pytest.raises(ImportProblem, match="Ultra Librarian"):
        import_zip(lib, z)


def test_zip_slip_is_blocked(lib, fake_altium, tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../escape.txt", b"x")
        zf.writestr("E1.SchLib", b"SYM:E1")
        zf.writestr("E1.PcbLib", b"FP:E1")
    import_zip(lib, z, mpn="E1")
    assert not (tmp_path / "escape.txt").exists()


def test_reimport_from_archive_keeps_one_copy(lib, fake_altium, tmp_path):
    z = make_zip(tmp_path / "R1.zip", {"R1.SchLib": b"SYM:R1", "R1.PcbLib": b"FP:R1"})
    import_zip(lib, z, mpn="R1")
    res = import_zip(lib, lib.root / "Archive" / "R1.zip", mpn="R1")
    assert res.replaced_existing
    assert len(list((lib.root / "Archive").iterdir())) == 1


def test_looks_like_cad_download(tmp_path):
    good = make_zip(tmp_path / "a.zip", {"x/a.PcbLib": b"1"})
    bad = make_zip(tmp_path / "b.zip", {"photo.jpg": b"1"})
    assert looks_like_cad_download(good)
    assert not looks_like_cad_download(bad)


def test_detect_provider_by_name():
    assert detect_provider("ul_LM358.zip", Found()) == "UltraLibrarian"
    assert detect_provider("snapeda_LM358.zip", Found()) == "SnapMagic"


def test_embedded_model_also_saved_as_step(lib, fake_altium, tmp_path):
    z = make_zip(tmp_path / "Q1.zip", {"Q1.SchLib": b"SYM:Q1", "Q1.PcbLib": b"FP:SOT23;MODELS:1"})
    p = import_zip(lib, z, mpn="Q1").part
    assert p.model_3d_source == "embedded" and p.step == "3D/Q1.step"
    assert (lib.root / p.step).read_bytes().startswith(b"ISO-10303-21")


# ---------------- .IntLib (SnapMagic single-file downloads) ----------------

from partkit import altium_files as AF
from conftest import FakeOle


def test_extract_intlib_recognises_contents_not_names():
    import zlib

    sch = AF.OLE_MAGIC + b"sch"
    pcb = AF.OLE_MAGIC + b"pcb"
    inner = {
        sch: FakeOle({("FileHeader",): b"|HEADER=Protel for Windows - Schematic Library Editor Binary File"}),
        pcb: FakeOle({("FileHeader",): b"PCB 6.0 Binary Library File"}),
    }
    ole = FakeOle({
        ("SchLib", "0"): zlib.compress(sch + b"\x00" * 32),
        ("PCBLib", "0"): b"\x10\x00\x00\x00" + zlib.compress(pcb + b"\x00" * 32),
        ("PCB3DLib", "0"): zlib.compress(b"ISO-10303-21;\nHEADER;" + b" " * 32),
        ("Version.Txt",): b"Version=1.1" + b" " * 16,
    })
    got = AF.extract_intlib(ole, open_bytes=lambda d: inner[d[: len(sch)]])
    assert sorted(k for k, _ in got) == ["pcblib", "schlib", "step"]


def test_import_intlib_file(tmp_path, lib, fake_altium, monkeypatch):
    from partkit import importer

    def fake_extract(path, dest):
        dest.mkdir(parents=True)
        (dest / "a.SchLib").write_bytes(b"SYM:RES;MPN:RC0603FR-071KL")
        (dest / "a.PcbLib").write_bytes(b"FP:RESC1608X55N;MODELS:1")
        return [dest / "a.SchLib", dest / "a.PcbLib"]

    monkeypatch.setattr(importer, "extract_intlib_file", fake_extract)
    f = tmp_path / "RC0603FR-071KL.IntLib"
    f.write_bytes(b"intlib")
    assert importer.looks_like_cad_download(f)
    res = importer.import_zip(lib, f)
    assert res.part.mpn == "RC0603FR-071KL"
    assert res.part.schlib.endswith(".SchLib") and res.part.pcblib.endswith(".PcbLib")
    assert res.part.model_3d_source == "embedded"
    assert (lib.root / "Archive" / f.name).exists()


def test_unreadable_intlib_explains(tmp_path, lib, fake_altium, monkeypatch):
    import pytest
    from partkit import importer

    monkeypatch.setattr(importer, "extract_intlib_file", lambda p, d: [])
    f = tmp_path / "X.IntLib"
    f.write_bytes(b"intlib")
    with pytest.raises(importer.ImportProblem, match="Extract Sources"):
        importer.import_zip(lib, f)


def test_vendor_import_of_starter_part_goes_to_category_library(tmp_path, lib, fake_altium):
    from partkit.importer import import_zip
    # an old starter part from earlier PartKit versions
    lib.save(Part(mpn="RC0603FR-071KL", category="Resistors", source="PartKit",
                  target_schlib="Libraries/Generic Passives.SchLib", target_pcblib="Libraries/Generic Passives.PcbLib"))
    z = make_zip(tmp_path / "RC0603FR-071KL.zip", {"a.SchLib": b"SYM:RC0603FR-071KL", "a.PcbLib": b"FP:RESC1607X60N"})
    part = import_zip(lib, z).part
    assert part.target_schlib == "Libraries/Resistors.SchLib"
    assert part.target_pcblib == "Libraries/Resistors.PcbLib"


def test_download_joins_the_part_you_clicked_get_cad_files_for(lib, fake_altium, tmp_path):
    from partkit import waiting
    from partkit.suppliers import Offer
    from partkit.watcher import import_download

    offer = Offer("JLCPCB", "C21190", "0603WAF1001T5E", manufacturer="UNI-ROYAL", status="Basic",
                  description="1kΩ ±1% 100mW 0603", category="Resistors", specs={"Resistance": "1kΩ"})
    waiting.remember(lib, "0603WAF1001T5E", [offer])
    # the provider's file says a slightly different number: you're asked, and say yes
    z = make_zip(tmp_path / "LIB_0603WAF1001.zip", {"a.SchLib": b"SYM:R;MPN:0603WAF1001", "a.PcbLib": b"FP:R0603"})
    asked = []
    res = import_download(lib, z, confirm=lambda f, e: (asked.append((f, e)), True)[1])
    p = lib.get("0603WAF1001T5E")
    assert asked == [("0603WAF1001", "0603WAF1001T5E")] and p.params["Supplier Part Number 1"] == "C21190"
    assert p.category == "Resistors" and p.target_schlib == "Libraries/Resistors.SchLib"
    assert waiting.current(lib) is None and any("supplier details" in m for m in res.messages)


def test_download_for_another_part_is_kept_apart(lib, fake_altium, tmp_path):
    from partkit import waiting
    from partkit.suppliers import Offer
    from partkit.watcher import import_download

    waiting.remember(lib, "LM358DR", [Offer("JLCPCB", "C7950", "LM358DR")])
    z = make_zip(tmp_path / "NE555.zip", {"a.SchLib": b"SYM:U;MPN:NE555DR", "a.PcbLib": b"FP:SO8"})
    res = import_download(lib, z)  # no one to ask (command line): kept apart, to be safe
    assert lib.get("NE555DR") and lib.get("LM358DR") is None
    assert waiting.current(lib)["mpn"] == "LM358DR" and "still waiting" in res.messages[-1]
    z2 = make_zip(tmp_path / "x.zip", {"a.SchLib": b"SYM:U;MPN:lm358-dr", "a.PcbLib": b"FP:SO8"})
    import_download(lib, z2)  # same number written differently: joined without asking
    assert lib.get("LM358DR").params["Supplier Part Number 1"] == "C7950"
