from partkit import passives as P
from partkit.library import Part


def test_yageo_codes():
    assert P.yageo_rc_mpn("0603", 10_000) == "RC0603FR-0710KL"
    assert P.yageo_rc_mpn("0402", 4_700) == "RC0402FR-074K7L"
    assert P.yageo_rc_mpn("0805", 100) == "RC0805FR-07100RL"
    assert P.yageo_rc_mpn("0603", 1_000_000) == "RC0603FR-071ML"
    assert P.yageo_rc_mpn("0603", 0) == "RC0603JR-070RL"
    assert P.yageo_rc_mpn("0603", 1_500) == "RC0603FR-071K5L"


def test_e24_range():
    vals = P.e24_values()
    assert vals[0] == 10 and vals[-1] == 1_000_000 and len(vals) == 121


def test_capacitor_height_classes():
    assert P.capacitor_footprint("0805", 0.85) == "CAPC2012X95N"
    assert P.capacitor_footprint("0805", 1.25) == "CAPC2012X140N"
    assert P.capacitor_footprint("0603", 0.8) == "CAPC1608X90N"
    assert P.capacitor_footprint("0402", 0.5) == "CAPC1005X55N"


def test_same_size_capacitors_are_different_parts():
    caps = [P.capacitor_part(r) for r in P.starter_capacitors()]
    c0603_100n = [c for c in caps if c.params["Size"] == "0603" and c.params["Capacitance"] == "100nF"]
    c0402_100n = [c for c in caps if c.params["Size"] == "0402" and c.params["Capacitance"] == "100nF"]
    assert c0603_100n[0].params["Voltage Rating"] == "50V"
    assert c0402_100n[0].params["Voltage Rating"] == "16V"
    assert len({c.mpn for c in caps}) == len(caps)


def test_starter_pack_install_is_idempotent(lib):
    added, skipped = P.install_starter_pack(lib)
    assert added == 3 * 122 + len(P.starter_capacitors()) and skipped == 0
    added2, skipped2 = P.install_starter_pack(lib)
    assert added2 == 0 and skipped2 == added


def test_spec_match_finds_existing_passive(lib):
    lib.save(P.resistor_part("0603", 10_000))
    other = Part(mpn="ERJ-3EKF1002V", category="Resistors",
                 params={"Resistance": "10kΩ", "Tolerance": "1%", "Power": "0.1W", "Size": "0603",
                         "Technology": "Thick Film", "Height": "0.55mm"})
    assert lib.find_same_spec(other).mpn == "RC0603FR-0710KL"


def test_footprints_needed_uses_tallest_part():
    fps = P.footprints_needed(P.starter_pack())
    names = {f["name"] for f in fps}
    assert {"RESC1608X55N", "CAPC2012X140N", "CAPC2012X95N"} <= names
