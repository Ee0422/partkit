import csv

import pytest

from partkit import kits, reuse
from partkit.library import Part
from partkit.suppliers import Offer


def checked_10k(lib, stage="Released"):
    p = Part(mpn="RC0603FR-0710KL", category="Resistors", stage=stage, source="SnapMagic",
             schlib="Review/RC0603FR-0710KL/RC0603FR-0710KL.SchLib", symbol="RC0603FR-0710KL",
             pcblib="Review/RC0603FR-0710KL/RC0603FR-0710KL.PcbLib", footprint="RESC1608X55N",
             model_3d="Full", model_3d_source="embedded", step="3D/RESC1608X55N.step",
             target_schlib="Libraries/Resistors.SchLib", target_pcblib="Libraries/Resistors.PcbLib",
             params={"Manufacturer": "YAGEO", "Resistance": "10kΩ", "Value": "10kΩ", "Size": "0603",
                     "Tolerance": "1%", "Power": "0.1W", "Description": "RES 10K OHM 1% 0603"})
    lib.save(p)
    return p


J47 = Offer("JLCPCB", "C23162", "0603WAF4701T5E", description="4.7kΩ ±1% 100mW 0603", status="Basic",
            category="Chip Resistor - Surface Mount",
            specs={"Resistance": "4.7kΩ", "Tolerance": "1%", "Power": "0.1W", "Package / Case": "0603"})


def test_new_value_copies_checked_cad_and_takes_new_specs(lib):
    checked_10k(lib)
    p = reuse.new_value(lib, "RC0603FR-0710KL", offers=[J47])
    assert p.mpn == "0603WAF4701T5E" and p.stage == "Review" and p.copied_from == "RC0603FR-0710KL"
    assert (p.symbol, p.footprint, p.step, p.model_3d_source) == ("RC0603FR-0710KL", "RESC1608X55N",
                                                                  "3D/RESC1608X55N.step", "embedded")
    assert p.params["Value"] == "4.7kΩ" and p.params["Supplier Part Number 1"] == "C23162"
    assert "Manufacturer" not in p.params or p.params["Manufacturer"] != "YAGEO"  # not carried over
    assert "10K" not in p.params.get("Description", "")
    assert p.target_schlib == "Libraries/Resistors.SchLib"
    lib.approve(p.mpn)
    job = lib.write_sync_job().read_text(encoding="utf-8-sig")
    assert "SRC_FOOTPRINT=RESC1608X55N" in job and "MPN=0603WAF4701T5E" in job


def test_only_checked_parts_can_be_copied(lib):
    checked_10k(lib, stage="Review")
    with pytest.raises(reuse.ReuseProblem, match="Approve"):
        reuse.new_value(lib, "RC0603FR-0710KL", offers=[J47])
    lib.save(Part(mpn="OLD", source="PartKit", stage="Released", footprint="X", pcblib="y"))
    with pytest.raises(reuse.ReuseProblem, match="never checked"):
        reuse.new_value(lib, "OLD", mpn="NEW")
    with pytest.raises(reuse.ReuseProblem, match="isn't in your library"):
        reuse.new_value(lib, "NOPE", mpn="NEW")


def test_new_value_needs_a_new_part_number(lib):
    checked_10k(lib)
    with pytest.raises(reuse.ReuseProblem, match="already in your library"):
        reuse.new_value(lib, "RC0603FR-0710KL", mpn="RC0603FR-0710KL")
    with pytest.raises(reuse.ReuseProblem, match="part number"):
        reuse.new_value(lib, "RC0603FR-0710KL")


def test_value_query_uses_the_source_spec(lib):
    src = checked_10k(lib)
    assert reuse.value_query_text(src, "4.7k") == "4.7k 0603 1%"
    cap = Part(mpn="C1", category="Capacitors", params={"Size": "0603", "Voltage Rating": "50V", "Dielectric": "X7R"})
    assert reuse.value_query_text(cap, "1uF") == "1uF 0603 50V X7R"


def test_new_part_from_footprint_with_symbol_from_another_part(lib):
    lib.save(Part(mpn="AP2112K-3.3TRG1", category="Power", stage="Released", source="SnapMagic",
                  schlib="Review/a/a.SchLib", symbol="AP2112K", pcblib="Review/a/a.PcbLib", footprint="SOT-23-5",
                  model_3d="Full", model_3d_source="embedded", params={"Package": "SOT-23-5"}))
    lib.save(Part(mpn="RT9013-33GB", category="Power", stage="Released", source="SnapMagic",
                  schlib="Review/b/b.SchLib", symbol="RT9013", pcblib="Review/b/b.PcbLib", footprint="SOT23-5N"))
    p = reuse.new_from_footprint(lib, "AP2112K-3.3TRG1", "ME6211C33M5G", symbol_from="RT9013-33GB")
    assert (p.footprint, p.symbol, p.schlib) == ("SOT-23-5", "RT9013", "Review/b/b.SchLib")
    assert p.params["Package"] == "SOT-23-5" and any("check its pins" in n for n in p.notes)
    q = reuse.new_from_footprint(lib, "AP2112K-3.3TRG1", "XC6206P332MR")
    assert q.footprint == "SOT-23-5" and not q.symbol
    with pytest.raises(KeyError, match="no symbol or footprint"):
        lib.approve(q.mpn)


def test_favourites(lib):
    checked_10k(lib)
    assert lib.set_favourite("RC0603FR-0710KL").favourite
    assert not lib.set_favourite("RC0603FR-0710KL", False).favourite


def test_kits_combine_into_one_project_parts_list(lib, tmp_path):
    checked_10k(lib)
    lib.save(Part(mpn="CC0603KRX7R9BB104", category="Capacitors", stage="Released",
                  params={"Value": "100nF", "Supplier Part Number 1": "C14663"}))
    lib.save(Part(mpn="USB4105-GF-A", category="Connectors", stage="Obsolete"))
    kits.add_parts(lib, "USB-C power input", ["USB4105-GF-A", "RC0603FR-0710KL"])
    kits.add_parts(lib, "USB-C power input", ["CC0603KRX7R9BB104"], qty=2)
    kits.add_parts(lib, "ESP32 basics", ["CC0603KRX7R9BB104"], qty=3)
    assert [k.name for k in kits.kits(lib)] == ["ESP32 basics", "USB-C power input"]
    with pytest.raises(KeyError):
        kits.add_parts(lib, "X", ["NOT-A-PART"])
    lines = kits.project_bom(lib, ["USB-C power input", "ESP32 basics"])
    by = {l.mpn: l for l in lines}
    assert by["CC0603KRX7R9BB104"].qty == 5 and by["CC0603KRX7R9BB104"].kits == ["USB-C power input", "ESP32 basics"]
    assert "Obsolete" in by["USB4105-GF-A"].warning
    out = kits.write_csv(lines, tmp_path / "parts.csv")
    rows = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    cap = next(r for r in rows if r["Manufacturer Part Number"] == "CC0603KRX7R9BB104")
    assert cap["Quantity"] == "5" and cap["Supplier Part Number 1"] == "C14663" and cap["Value"] == "100nF"
    assert kits.delete(lib, "ESP32 basics") and lib.get("CC0603KRX7R9BB104")
