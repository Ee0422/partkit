import json
import urllib.parse

import pytest

from partkit import credentials, providers, search
from partkit.config import Settings, load_settings, save_settings
from partkit.library import Part
from partkit.suppliers import JLCPCB, DigiKey, Farnell, Mouser, Offer, SupplierError

# Replies shaped like the real APIs (trimmed).
DIGIKEY = {
    "Products": [{
        "ManufacturerProductNumber": "CL10B104KB8NNNC",
        "Manufacturer": {"Name": "Samsung Electro-Mechanics"},
        "Description": {"ProductDescription": "CAP CER 0.1UF 50V X7R 0603"},
        "DatasheetUrl": "https://example.com/cl10.pdf",
        "ProductUrl": "https://www.digikey.com/p/1276-1000-1-ND",
        "QuantityAvailable": 1234567,
        "ProductStatus": {"Status": "Active"},
        "Category": {"Name": "Ceramic Capacitors"},
        "ProductVariations": [
            {"DigiKeyProductNumber": "1276-1000-2-ND", "PackageType": {"Name": "Tape & Reel (TR)"},
             "StandardPricing": [{"BreakQuantity": 4000, "UnitPrice": 0.005}]},
            {"DigiKeyProductNumber": "1276-1000-1-ND", "PackageType": {"Name": "Cut Tape (CT)"},
             "StandardPricing": [{"BreakQuantity": 1, "UnitPrice": 0.1}, {"BreakQuantity": 10, "UnitPrice": 0.05}]},
        ],
        "Parameters": [
            {"ParameterText": "Capacitance", "ValueText": "0.1 µF"},
            {"ParameterText": "Voltage - Rated", "ValueText": "50V"},
            {"ParameterText": "Temperature Coefficient", "ValueText": "X7R"},
            {"ParameterText": "Tolerance", "ValueText": "±10%"},
            {"ParameterText": "Package / Case", "ValueText": "0603 (1608 Metric)"},
            {"ParameterText": "Thickness (Max)", "ValueText": "0.035\" (0.90mm)"},
        ],
    }],
}

MOUSER = {"Errors": [], "SearchResults": {"Parts": [{
    "MouserPartNumber": "603-RC0603FR-071KL", "ManufacturerPartNumber": "RC0603FR-071KL",
    "Manufacturer": "YAGEO", "Description": "Thick Film Resistors - SMD 1K OHM 1%",
    "DataSheetUrl": "https://example.com/yageo.pdf", "ProductDetailUrl": "https://www.mouser.com/x",
    "AvailabilityInStock": "512000", "LifecycleStatus": None, "Category": "Thick Film Resistors - SMD",
    "PriceBreaks": [{"Quantity": 1, "Price": "$0.10", "Currency": "USD"},
                    {"Quantity": 100, "Price": "$0.012", "Currency": "USD"}],
    "ProductAttributes": [{"AttributeName": "Resistance", "AttributeValue": "1 kOhms"},
                          {"AttributeName": "Tolerance", "AttributeValue": "1 %"},
                          {"AttributeName": "Power Rating", "AttributeValue": "100 mW (1/10 W)"},
                          {"AttributeName": "Case Code - in", "AttributeValue": "0603"}],
}]}}

FARNELL = {"manufacturerPartNumberSearchReturn": {"numberOfResults": 1, "products": [{
    "sku": "9330380", "displayName": "SMD Chip Resistor, 1 kohm, ± 1%, 100 mW, 0603",
    "translatedManufacturerPartNumber": "RC0603FR-071KL", "brandName": "YAGEO",
    "datasheets": [{"url": "https://example.com/f.pdf"}], "stock": {"level": 40000},
    "prices": [{"from": 1, "to": 9, "cost": 0.08}], "productStatus": "STOCKED",
    "attributes": [{"attributeLabel": "Resistance", "attributeValue": "1kohm"}],
}]}}


class FakeHttp:
    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        for key, reply in self.replies.items():
            if key in url:
                if isinstance(reply, Exception):
                    raise reply
                return reply
        raise AssertionError(url)


def test_digikey_parses_and_prefers_cut_tape():
    http = FakeHttp({"oauth2/token": {"access_token": "T", "expires_in": 600}, "search/keyword": DIGIKEY})
    offers = DigiKey(http=http, keys={"client_id": "id", "client_secret": "s"}).search("CL10B104KB8NNNC")
    o = offers[0]
    assert o.supplier_pn == "1276-1000-1-ND" and o.manufacturer.startswith("Samsung")
    assert o.unit_price(1) == 0.1 and o.stock == 1234567
    method, url, headers, body = http.calls[1]
    assert headers["Authorization"] == "Bearer T" and json.loads(body)["Keywords"] == "CL10B104KB8NNNC"


def test_mouser_and_farnell_parse():
    m = Mouser(http=FakeHttp({"api.mouser.com": MOUSER}), keys={"api_key": "k"}).search("RC0603FR-071KL")[0]
    assert m.supplier_pn == "603-RC0603FR-071KL" and m.unit_price(1) == 0.10 and m.stock == 512000
    http = FakeHttp({"element14": FARNELL})
    f = Farnell(http=http, keys={"api_key": "k"}, store="my.element14.com").search("RC0603FR-071KL")[0]
    assert f.supplier_pn == "9330380" and f.datasheet.endswith("f.pdf")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(http.calls[0][1]).query)
    assert q["storeInfo.id"] == ["my.element14.com"] and q["term"] == ["manuPartNum:RC0603FR-071KL"]


def test_mouser_errors_become_friendly():
    reply = {"Errors": [{"Message": "Invalid unique identifier."}], "SearchResults": None}
    with pytest.raises(SupplierError, match="Invalid unique identifier"):
        Mouser(http=FakeHttp({"mouser": reply}), keys={"api_key": "bad"}).search("X")


def test_find_uses_order_skips_failures_and_lists_missing_keys():
    class Broken:
        def search(self, mpn):
            raise SupplierError("couldn't reach the supplier")

    class Fine:
        def search(self, mpn):
            return [Offer("Mouser", "603-X", "RC0603FR-071KL")]

    s = Settings(suppliers=["DigiKey", "Mouser", "Farnell", "LCSC"])
    res = search.find("RC0603FR-071KL", s, clients={"DigiKey": Broken(), "Mouser": Fine()})
    assert [o.supplier for o in res.best()] == ["Mouser"]
    assert any("DigiKey" in m for m in res.messages)
    assert res.not_set_up == ["Farnell"]  # LCSC has no API and isn't listed


def test_specs_and_values_are_cleaned():
    dk = DigiKey(http=FakeHttp({"token": {"access_token": "T"}, "keyword": DIGIKEY}),
                 keys={"client_id": "a", "client_secret": "b"}).search("x")[0]
    specs = search.specs_for(dk, "Capacitors")
    assert specs == {"Capacitance": "100nF", "Voltage Rating": "50V", "Dielectric": "X7R",
                     "Tolerance": "10%", "Size": "0603", "Height": "0.035\" (0.90mm)"}
    assert search.format_resistance("4.7 kOhms") == "4.7kΩ"
    assert search.format_resistance("0 Ohms") == "0Ω"
    assert search.format_capacitance("10 pF") == "10pF"
    assert search.format_capacitance("1 uF") == "1µF"


def test_apply_offers_fills_bom_and_guesses_category():
    m = Mouser(http=FakeHttp({"mouser": MOUSER}), keys={"api_key": "k"}).search("x")[0]
    f = Farnell(http=FakeHttp({"element14": FARNELL}), keys={"api_key": "k"}).search("x")[0]
    p = Part(mpn="RC0603FR-071KL")
    search.apply_offers(p, [m, f])
    assert p.category == "Resistors"
    assert p.params["Supplier 1"] == "Mouser" and p.params["Supplier Part Number 1"] == "603-RC0603FR-071KL"
    assert p.params["Supplier 2"] == "Farnell" and p.params["Supplier Part Number 2"] == "9330380"
    assert p.params["Resistance"] == "1kΩ" and p.params["Value"] == "1kΩ"
    assert p.params["Tolerance"] == "1%" and p.params["Size"] == "0603"
    assert p.params["Power"] == "0.1W"  # Mouser writes "100 mW (1/10 W)"
    assert p.params["Manufacturer"] == "YAGEO"


def test_add_from_search_then_approve_needs_cad(lib):
    m = Mouser(http=FakeHttp({"mouser": MOUSER}), keys={"api_key": "k"}).search("x")[0]
    p = search.add_from_search(lib, "RC0603FR-071KL", [m])
    assert p.stage == "To check" and p.target_schlib == "Libraries/Resistors.SchLib" and p.source == "search"
    with pytest.raises(KeyError, match="no symbol or footprint"):
        lib.approve("RC0603FR-071KL")


def test_cad_sources_follow_order_and_hunting():
    s = Settings(providers=["SamacSys", "Manufacturer", "SnapMagic"], hunting="off")
    names = [c.name for c in providers.cad_sources("LM358DR", s)]
    assert names == ["SamacSys", "SnapMagic"]  # no manufacturer page known yet
    s.hunting = "ask"
    srcs = providers.cad_sources("LM358DR", s, manufacturer_url="https://ti.com/lm358")
    assert [c.name for c in srcs][:3] == ["SamacSys", "Manufacturer", "SnapMagic"]
    assert all(c.hunting for c in srcs[3:]) and len(srcs) > 3


def test_credentials_from_environment(monkeypatch):
    monkeypatch.setenv("PARTKIT_MOUSER_API_KEY", "abc")
    assert credentials.get("Mouser", "api_key") == "abc"
    assert credentials.is_set_up("Mouser")
    monkeypatch.delenv("PARTKIT_DIGIKEY_CLIENT_ID", raising=False)
    monkeypatch.setattr(credentials, "_keyring", lambda: None)
    assert not credentials.is_set_up("DigiKey")


def test_settings_keep_your_suppliers_and_drop_unknown_ones(tmp_path):
    save_settings(tmp_path, Settings(suppliers=["Mouser", "Nope"]))
    assert load_settings(tmp_path).suppliers == ["Mouser"]
    save_settings(tmp_path, Settings(suppliers=[]))
    assert load_settings(tmp_path).suppliers == ["JLCPCB"]


def test_no_keys_at_all_is_fine(monkeypatch):
    monkeypatch.setattr(credentials, "is_set_up", lambda name: False)
    # only suppliers that need keys, so the test never touches the network
    res = search.find("LM358DR", Settings(suppliers=["DigiKey", "Mouser"]))
    assert any("that's fine" in m and "Get CAD files" in m for m in res.messages)


JLC = {"components": [
    {"lcsc": 21190, "mfr": "0603WAF1001T5E", "package": "0603", "description": "1kΩ ±1% 100mW",
     "stock": 30000000, "price": "0.0006", "is_basic": True},
    {"lcsc": 114762, "mfr": "RC0603FR-071KL", "package": "0603", "description": "1kΩ ±1% 100mW Thick Film Resistor",
     "stock": 450000, "price": 0.0011, "is_basic": False},
]}


def test_jlcpcb_needs_no_key_and_gives_c_numbers():
    http = FakeHttp({"jlcsearch": JLC})
    res = search.find("RC0603FR-071KL", Settings(suppliers=["JLCPCB", "Mouser"]), http=http)
    assert [(o.supplier, o.supplier_pn, o.status) for o in res.exact] == [("JLCPCB", "C114762", "Extended")]
    q = urllib.parse.parse_qs(urllib.parse.urlparse(http.calls[0][1]).query)
    assert q["q"] == ["RC0603FR-071KL"]
    p = Part(mpn="RC0603FR-071KL", category="Resistors")
    search.apply_offers(p, res.best())
    assert p.params["Supplier 1"] == "JLCPCB" and p.params["Supplier Part Number 1"] == "C114762"
    assert p.params["Size"] == "0603" and not p.notes
    basic = JLCPCB(http=FakeHttp({"jlcsearch": JLC})).search("x")[0]
    assert basic.status == "Basic" and basic.unit_price(1) == 0.0006


def test_lcsc_uses_the_same_free_search():
    res = search.find("RC0603FR-071KL", Settings(suppliers=["LCSC"]), http=FakeHttp({"jlcsearch": JLC}))
    o = res.exact[0]
    assert (o.supplier, o.supplier_pn) == ("LCSC", "C114762") and "lcsc.com" in o.url and res.not_set_up == []
