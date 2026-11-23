from partkit.altium_files import parse_records, read_pcblib, read_schlib

from conftest import FakeOle


def rec(text: str) -> bytes:
    body = text.encode("latin-1") + b"\x00"
    return len(body).to_bytes(4, "little") + body


def test_parse_records_splits_keys():
    r = parse_records(rec("|RECORD=41|NAME=Manufacturer|TEXT=YAGEO|OWNERINDEX=0"))
    assert r == [{"RECORD": "41", "NAME": "Manufacturer", "TEXT": "YAGEO", "OWNERINDEX": "0"}]


def test_read_schlib_names_and_parameters():
    long_name = "TPS62130RGTR_with_a_very_long_symbol_name"
    ole = FakeOle({
        ("FileHeader",): rec(f"|HEADER=Protel for Windows - Schematic Library Editor Binary File Version 5.0|COMPCOUNT=1|LibRef0={long_name}|CompDescr0=Buck"),
        (long_name[:31], "Data"): rec("|RECORD=1|LIBREFERENCE=x") + rec("|RECORD=41|NAME=Manufacturer_Part_Number|TEXT=TPS62130RGTR"),
    })
    info = read_schlib(ole)
    assert info.symbols == [long_name]
    assert info.parameters[long_name]["Manufacturer_Part_Number"] == "TPS62130RGTR"


def test_read_pcblib_full_name_and_embedded_models():
    ole = FakeOle({
        ("Library", "Data"): rec("|HEADER=PCB 6.0 Binary Library File"),
        ("Library", "Models", "Data"): rec("|EMBED=TRUE|NAME=part.step"),
        ("Library", "Models", "0"): b"zlib-data",
        ("FileVersionInfo", "Data"): b"",
        ("QFN50P300X300X100-17N", "Data"): b"",
        ("QFN50P300X300X100-17N", "Parameters"): rec("|PATTERN=QFN50P300X300X100-17N-full-name|HEIGHT=1mm"),
    })
    info = read_pcblib(ole)
    assert info.footprints == ["QFN50P300X300X100-17N-full-name"]
    assert info.embedded_models == 1


def test_read_pcblib_without_models():
    ole = FakeOle({("Library", "Data"): b"", ("SOIC8", "Data"): b""})
    info = read_pcblib(ole)
    assert info.footprints == ["SOIC8"]
    assert info.embedded_models == 0


def test_extract_embedded_models():
    import zlib
    from partkit.altium_files import extract_embedded_models

    ole = FakeOle({
        ("Library", "Models", "Data"): rec("|EMBED=TRUE|NAME=QFN16.step"),
        ("Library", "Models", "0"): zlib.compress(b"ISO-10303-21;DATA"),
    })
    assert extract_embedded_models(ole) == [("QFN16.step", b"ISO-10303-21;DATA")]


def test_utf8_text_is_repaired():
    from partkit.altium_files import parse_records

    rec = parse_records("|RECORD=1|COMPONENTDESCRIPTION=1 kOhms ±1%".encode("utf-8"))[0]
    assert rec["COMPONENTDESCRIPTION"] == "1 kOhms ±1%"
    assert parse_records("|NAME=10µF".encode("latin-1"))[0]["NAME"] == "10µF"
