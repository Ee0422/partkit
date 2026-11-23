import os
import urllib.parse

import pytest

from partkit import search, valuesearch as V
from partkit.config import Settings
from partkit.suppliers import Offer

from test_search import FakeHttp

RES = {"resistors": [
    {"lcsc": 21190, "mfr": "0603WAF1001T5E", "package": "0603", "resistance": 1000, "tolerance_fraction": 0.01,
     "power_watts": 100, "stock": 30000000, "price1": 0.0006, "is_basic": True, "description": "1kΩ ±1% 100mW"},
    {"lcsc": 114762, "mfr": "RC0603FR-071KL", "package": "0603", "resistance": 1000, "tolerance_fraction": 0.01,
     "power_watts": 100, "stock": 450000, "price1": 0.0011, "is_basic": False},
    {"lcsc": 22790, "mfr": "0603WAF6812T5E", "package": "0603", "resistance": 68100, "tolerance_fraction": 0.01,
     "power_watts": 100, "stock": 9000, "price1": 0.0007, "is_basic": True},
    {"lcsc": 99, "mfr": "4D03WGJ0102T5E", "package": "0603", "resistance": 1000, "tolerance_fraction": 0.05,
     "number_of_resistors": 4, "stock": 100, "price1": 0.002, "is_basic": False},
    {"lcsc": 100, "mfr": "0603WAJ0102T5E", "package": "0603", "resistance": 1000, "tolerance_fraction": 0.05,
     "power_watts": 100, "stock": 90000000, "price1": 0.0005, "is_basic": True},
]}
CAPS = {"capacitors": [
    {"lcsc": 14663, "mfr": "CC0603KRX7R9BB104", "package": "0603", "capacitance_farads": 1e-7,
     "tolerance_fraction": 0.1, "voltage_rating": 50, "temperature_coefficient": "X7R", "stock": 50000000,
     "price1": 0.0016, "is_basic": True},
    {"lcsc": 1591, "mfr": "CL10B104KB8NNNC", "package": "0603", "capacitance_farads": 1e-7,
     "tolerance_fraction": 0.1, "voltage_rating": 16, "temperature_coefficient": "X7R", "stock": 900000,
     "price1": 0.0012, "is_basic": False},
    {"lcsc": 7, "mfr": "X", "package": "0603", "capacitance_farads": 1e-7, "voltage_rating": 50,
     "temperature_coefficient": "Y5V", "stock": 5, "price1": 0.001, "is_basic": False},
]}


@pytest.mark.parametrize("text,kind,value,extra", [
    ("1k 0603 1%", "R", 1000, {"package": "0603", "tolerance": 0.01}),
    ("4k7", "R", 4700, {}),
    ("100 resistor 0402", "R", 100, {"package": "0402"}),
    ("0R 0805", "R", 0, {"package": "0805"}),
    ("100nF 0603 50V X7R", "C", 1e-7, {"voltage": 50, "dielectric": "X7R"}),
    ("4u7 0805", "C", 4.7e-6, {}),
    ("22p NP0", "C", 22e-12, {"dielectric": "C0G"}),
])
def test_parse_values(text, kind, value, extra):
    q = V.parse(text)
    assert q.kind == kind and q.value == pytest.approx(value)
    for k, v in extra.items():
        assert getattr(q, k) == v


@pytest.mark.parametrize("text", ["RC0603FR-071KL", "LM358DR", "CL10B104KB8NNNC", "10", "usb c connector"])
def test_part_numbers_are_not_values(text):
    assert V.parse(text) is None


def test_resistor_value_search_is_exact_and_basic_first():
    http = FakeHttp({"resistors/list": RES})
    offers = V.by_value(V.parse("1k 0603 1%"), http)
    assert [o.supplier_pn for o in offers] == ["C21190", "C114762"]  # no 68.1k, no 5%, no array
    assert offers[0].status == "Basic" and offers[0].specs["Power"] == "0.1W"
    q = urllib.parse.parse_qs(urllib.parse.urlparse(http.calls[0][1]).query)
    assert q["package"] == ["0603"] and q["resistance"] == ["1000"] and q["is_basic"] == ["true"]


def test_capacitor_value_search_filters_voltage_and_dielectric():
    offers = V.by_value(V.parse("100nF 0603 25V X7R"), FakeHttp({"capacitors/list": CAPS}))
    assert [o.mpn for o in offers] == ["CC0603KRX7R9BB104"]
    assert offers[0].specs["Capacitance"] == "100nF" and offers[0].specs["Voltage Rating"] == "50V"


def test_falls_back_to_plain_search_when_the_list_ignores_the_value():
    plain = {"components": [{"lcsc": 14663, "mfr": "CC0603KRX7R9BB104", "package": "0603",
                             "description": "50V 100nF X7R ±10% 0603 Multilayer Ceramic Capacitors",
                             "stock": 5, "price": 0.0016, "is_basic": True}]}
    http = FakeHttp({"capacitors/list": {"capacitors": []}, "api/search": plain})
    offers = V.by_value(V.parse("100nF 0603 X7R"), http)
    assert [o.supplier_pn for o in offers] == ["C14663"]


def test_find_any_and_one_row_per_part():
    s = Settings(suppliers=["JLCPCB", "LCSC"])
    res = search.find_any("1k 0603 1%", s, http=FakeHttp({"resistors/list": RES}))
    assert res.query is not None and "Basic" in res.messages[0]
    rows = search.merge_rows(res.offers, s.suppliers)
    assert rows[0].sold_by == ["JLCPCB", "LCSC"] and rows[0].value() == "1kΩ" and rows[0].category == "Resistors"
    offers = search.offers_for(rows[0], s.suppliers)
    assert [(o.supplier, o.supplier_pn) for o in offers] == [("JLCPCB", "C21190"), ("LCSC", "C21190")]


def test_jlcpcb_and_lcsc_results_merge():
    a = Offer("JLCPCB", "C1", "M1", status="Basic")
    b = Offer("LCSC", "C1", "M1")
    c = Offer("Mouser", "603-M1", "M1")
    rows = search.merge_rows([a, b, c], ["JLCPCB", "LCSC", "Mouser"])
    assert len(rows) == 2 and rows[0].sold_by == ["JLCPCB", "LCSC"] and rows[1].sold_by == ["Mouser"]


def test_clear_message_when_not_in_jlcpcb():
    res = search.find("RC0603FR-0710KL", Settings(suppliers=["JLCPCB"]), http=FakeHttp({"jlcsearch": {"components": []}}))
    assert any("isn't in JLCPCB's parts list" in m and "1k 0603 1%" in m for m in res.messages)


def test_added_resistor_waits_for_cad_files(lib):
    rows = search.merge_rows(V.by_value(V.parse("1k 0603"), FakeHttp({"resistors/list": RES})), ["JLCPCB"])
    p = search.add_from_search(lib, rows[0].mpn, search.offers_for(rows[0], ["JLCPCB"]))
    assert p.params["Supplier Part Number 1"] == "C100" and p.params["Size"] == "0603"
    assert p.stage == "To check" and not p.footprint and p.target_schlib == "Libraries/Resistors.SchLib"


@pytest.mark.skipif(not os.environ.get("PARTKIT_LIVE"), reason="talks to jlcsearch; set PARTKIT_LIVE=1")
@pytest.mark.parametrize("text", ["1k 0603 1%", "100nF 0603 50V X7R", "10uF 0805"])
def test_live_value_search(text):
    offers = V.by_value(V.parse(text))
    print(text, len(offers), [(o.supplier_pn, o.mpn, o.status, o.specs) for o in offers[:3]])
    assert offers, f"no JLCPCB parts for {text}"
    assert offers[0].status == "Basic", f"no Basic part first for {text}"


def test_my_usual_fills_only_what_was_not_typed():
    usual = V.decode_filters(V.encode_filters({"package": "0603", "voltage": 50.0, "dielectric": "X7R"}))
    q = V.with_filters(V.parse("100nF 0805"), usual, only_unset=True)
    assert (q.package, q.voltage, q.dielectric) == ("0805", 50.0, "X7R")
    q = V.with_filters(q, {"package": None, "voltage": 16.0, "dielectric": None, "tolerance": None})
    assert (q.package, q.voltage, q.dielectric) == ("", 16.0, "")
