import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from partkit import gui  # noqa: E402
from partkit.library import Library, Part  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app, lib, monkeypatch, tmp_path):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(gui, "copy_scripts", lambda *a, **k: tmp_path / "PartKitSync.PrjScr")
    w = gui.MainWindow(lib.root)
    yield w
    w.close()


def test_library_table_and_filters(win):
    win.lib.save(Part(mpn="LM358DR", category="ICs", footprint="SOIC8", params={"Value": "LM358"}))
    win.lib.save(Part(mpn="NE555DR", category="ICs", footprint="SOIC8"))
    win.refresh_library()
    assert win.parts_table.rowCount() == 2
    win.search.setText("lm358")
    assert win.parts_table.rowCount() == 1


def test_approve_and_set_category(win):
    win.lib.save(Part(mpn="X1", category="ICs", source="SnapMagic", symbol="X", footprint="SO8"))
    win.refresh_library()
    win.parts_table.selectRow(0)
    win.approve()
    assert win.lib.get("X1").stage == "Ready"
    win.parts_table.selectRow(0)
    win.set_category("Power")
    p = win.lib.get("X1")
    assert p.category == "Power" and p.target_schlib == "Libraries/Power.SchLib"


def test_settings_round_trip(win):
    win.hunting.setCurrentText("ask")
    win.targets.item(list(gui.F.CATEGORIES).index("ICs"), 1).setText("My ICs.SchLib")
    win.save_settings()
    s = Library(win.lib.root).settings
    assert s.hunting == "ask" and s.target_libs("ICs")[0] == "My ICs.SchLib"


def test_test_mode_switches_library(win):
    win.test_box.setChecked(True)
    assert win.lib.root.name.endswith("(Test)")
    win.test_box.setChecked(False)
    assert not win.lib.root.name.endswith("(Test)")


def test_health_check_and_sync(win, monkeypatch):
    win.lib.save(Part(mpn="Y1", stage="Ready", needs_sync=True))
    win.run_check()
    assert win.health_table.rowCount() > 0
    calls = []
    monkeypatch.setattr(gui, "start_sync", lambda prjscr: (calls.append(prjscr), (True, "ok"))[1])
    win.sync()
    assert calls and (win.lib.root / "partkit-data/sync/pending-sync.txt").exists()


def test_setup_dialog_creates_library(app, tmp_path, monkeypatch):
    monkeypatch.setattr(gui, "copy_scripts", lambda *a, **k: None)
    monkeypatch.setattr(gui, "remember_library_path", lambda p: None)
    d = gui.SetupDialog(folder=tmp_path / "New Library")
    lib = d.run_setup()
    assert (lib.root / "partkit-settings.toml").exists() and lib.parts() == []


def test_find_parts_add_and_get_cad(win, monkeypatch, tmp_path):
    from partkit import providers
    from partkit.search import SearchResult
    from partkit.suppliers import Offer

    opened = []
    monkeypatch.setattr(providers, "open_source", lambda src, opener=None: opened.append(src.name))
    monkeypatch.setattr(win, "toggle_watch", lambda on: None)
    offer = Offer("Mouser", "603-RC0603FR-071KL", "RC0603FR-071KL", manufacturer="YAGEO",
                  description="Thick Film Resistors - SMD 1K OHM 1%", stock=10, price_breaks=[(1, 0.1)],
                  category="Thick Film Resistors - SMD", specs={"Resistance": "1 kOhms", "Case Code - in": "0603"})
    win.search_box.setText("RC0603FR-071KL")
    win.show_results(SearchResult(mpn="RC0603FR-071KL", offers=[offer]))
    assert win.results.rowCount() == 1
    win.lib.settings.providers = ["SnapMagic", "SamacSys"]
    win.get_cad(next_=False)
    win.get_cad(next_=True)
    assert opened == ["SnapMagic", "SamacSys"] and not win.next_btn.isEnabled()
    # nothing is added until the download arrives; the supplier part waits for it
    from partkit import waiting

    assert win.lib.get("RC0603FR-071KL") is None
    entry = waiting.current(win.lib)
    assert entry["mpn"] == "RC0603FR-071KL" and waiting.offers_of(entry)[0].supplier_pn == "603-RC0603FR-071KL"


def test_search_messages_without_keys(win):
    from partkit.search import SearchResult

    win.show_results(SearchResult(mpn="X", messages=["Add a free API key in Settings for: DigiKey."]))
    assert "API key" in win.search_msg.text() and win.results.rowCount() == 0


def test_get_cad_works_without_any_supplier_keys(win, monkeypatch):
    from partkit import providers

    opened = []
    monkeypatch.setattr(providers, "open_source", lambda src, opener=None: opened.append(src.url))
    monkeypatch.setattr(win, "toggle_watch", lambda on: None)
    win.search_box.setText("LM358DR")
    win.add_cat.setCurrentText("ICs")
    win.get_cad(next_=False)
    from partkit import waiting

    entry = waiting.current(win.lib)
    assert entry["mpn"] == "LM358DR" and entry["category"] == "ICs" and win.lib.get("LM358DR") is None
    assert "LM358DR" in opened[0]


def test_key_fields_only_for_suppliers_in_the_list(win):
    win.lib.settings.suppliers = ["JLCPCB", "Mouser"]
    win.load_settings()
    form = win.settings_form
    assert form.isRowVisible(win.key_rows["Mouser"]) and not form.isRowVisible(win.key_rows["DigiKey"])


def test_value_results_one_row_per_part_with_filters(win, monkeypatch):
    from partkit.search import SearchResult
    from partkit.suppliers import Offer
    from partkit.valuesearch import parse

    spec = {"Resistance": "1kΩ", "Package / Case": "0603", "Tolerance": "1%", "Power": "0.1W"}
    offers = [Offer("JLCPCB", "C1", "BASIC1K", stock=100, status="Basic", category="Chip Resistor", specs=spec),
              Offer("LCSC", "C1", "BASIC1K", stock=100, category="Chip Resistor", specs=spec),
              Offer("JLCPCB", "C2", "EXT1K", stock=5, status="Extended", category="Chip Resistor", specs=spec),
              Offer("JLCPCB", "C3", "GONE1K", stock=0, status="Extended", category="Chip Resistor", specs=spec)]
    win.lib.settings.suppliers = ["JLCPCB", "LCSC"]
    win.show_results(SearchResult(mpn="1k 0603", offers=offers, query=parse("1k 0603")))
    assert win.results.rowCount() == 2  # C1 merged, C3 out of stock hidden
    cols = {win.results.horizontalHeaderItem(c).text(): c for c in range(win.results.columnCount())}
    assert win.results.item(0, cols["Sold by"]).text() == "JLCPCB, LCSC"
    assert win.results.item(0, cols["Value"]).text() == "1kΩ"
    win.jlc_type.setCurrentText("Basic only")
    assert win.results.rowCount() == 1 and win.results.item(0, 0).text() == "BASIC1K"
    win.jlc_type.setCurrentText("Extended only")
    assert win.results.rowCount() == 1 and win.results.item(0, 0).text() == "EXT1K"
    win.jlc_type.setCurrentText("Basic and Extended")
    win.narrow.setText("ext")
    assert win.results.rowCount() == 1 and win.results.item(0, 0).text() == "EXT1K"
    win.narrow.setText("")
    win.results.selectRow(1)
    monkeypatch.setattr(win, "toggle_watch", lambda on: None)
    from partkit import providers, waiting

    monkeypatch.setattr(providers, "open_source", lambda src, opener=None: None)
    win.get_cad(next_=False)
    entry = waiting.current(win.lib)
    assert entry["mpn"] == win.results.item(1, 0).text()
    assert [o.supplier for o in waiting.offers_of(entry)] == ["JLCPCB", "LCSC"]


def test_i_buy_from_setting(win):
    win.buy_from.setCurrentText("JLCPCB")
    win.also_check.setCurrentText("Mouser")
    assert win.settings_form.isRowVisible(win.key_rows["Mouser"])
    win.save_settings()
    assert Library(win.lib.root).settings.suppliers == ["JLCPCB", "Mouser"]
    win.also_check.setCurrentText("None")
    win.save_settings()
    assert Library(win.lib.root).settings.suppliers == ["JLCPCB"]
    assert not win.settings_form.isRowVisible(win.key_rows["Mouser"])


def test_remove_old_starter_parts_button(win):
    win.lib.save(Part(mpn="OLD1", category="Resistors", source="PartKit"))
    win.remove_starter()
    assert win.lib.get("OLD1") is None


def test_new_value_dialog_and_favourites(win, monkeypatch):
    from partkit import search
    from partkit.search import SearchResult
    from test_reuse_kits import J47, checked_10k

    checked_10k(win.lib)
    win.refresh_library()
    seen = []
    monkeypatch.setattr(search, "find_any", lambda q, s, http=None: (seen.append(q), SearchResult(mpn=q, offers=[J47]))[1])
    win.parts_table.selectRow(0)
    win.toggle_favourite()
    assert win.lib.get("RC0603FR-0710KL").favourite and win.parts_table.item(0, 1).text() == "★"
    d = gui.ReuseDialog(win, win.lib, win.lib.get("RC0603FR-0710KL"), "value")
    d.text.setText("4.7k")
    d.search()
    assert seen == ["4.7k 0603 1%"] and d.table.rowCount() == 1
    d.create()
    assert d.created is None  # nothing is picked for you
    d.table.selectRow(0)
    assert "C23162" in d.choice.text() and "Basic" in d.choice.text()
    d.create()
    assert d.created.mpn == "0603WAF4701T5E" and d.created.footprint == "RESC1608X55N"
    win.fav_only.setChecked(True)
    win.refresh_library()
    assert win.parts_table.rowCount() == 1


def test_kits_tab(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    from partkit import kits
    from test_reuse_kits import checked_10k

    checked_10k(win.lib)
    win.refresh_library()
    win.parts_table.selectRow(0)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("Power input", True))
    win.add_to_kit()
    assert kits.get(win.lib, "Power input").items[0].mpn == "RC0603FR-0710KL"
    win.kit_list.item(0).setSelected(True)
    assert win.kit_table.rowCount() == 1
    win.kit_table.selectRow(0)
    win.kit_qty.setValue(4)
    win.set_kit_qty()
    assert win.kit_table.item(0, 1).text() == "4"
    out = tmp_path / "p.csv"
    win.save_kit_bom(str(out))
    assert "RC0603FR-0710KL" in out.read_text(encoding="utf-8-sig")


def test_footprint_dialog_warns_on_package_mismatch(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from partkit import search
    from partkit.search import SearchResult
    from partkit.suppliers import Offer

    win.lib.save(Part(mpn="AP2112K-3.3TRG1", category="Power", stage="Ready", source="SnapMagic", symbol="A",
                      schlib="Review/a/a.SchLib", pcblib="Review/a/a.PcbLib", footprint="SOT-23-5",
                      params={"Package": "SOT-23-5"}))
    wrong = Offer("JLCPCB", "C9", "XC6206P332MR", stock=10, status="Basic", specs={"Package / Case": "SOT-23-3"})
    monkeypatch.setattr(search, "find_any", lambda q, s, http=None: SearchResult(mpn=q, offers=[wrong]))
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: (asked.append(a[2]), QMessageBox.No)[1])
    d = gui.ReuseDialog(win, win.lib, win.lib.get("AP2112K-3.3TRG1"), "footprint")
    d.text.setText("XC6206P332MR")
    d.search()
    d.table.selectRow(0)
    d.create()
    assert d.created is None and "SOT-23-3" in asked[0]
    d.table.clearSelection()
    d.text.setText("ME6211C33M5G")
    d.create()
    assert "without supplier details" in asked[1] and d.created is None


def test_projects_tab_and_add_to_project(win, monkeypatch):
    from partkit import projects
    from test_projects import ready

    ready(win.lib, "10K")
    ready(win.lib, "330R")
    projects.create(win.lib, "Board", own_library=True)
    win.refresh_all()
    win.parts_table.selectRow(0)

    class FakeDialog:
        def __init__(self, *a):
            from PySide6.QtWidgets import QComboBox
            self.project, self.template = QComboBox(), QComboBox()
            self.project.addItem("Board")
            self.template.addItem("No, this project only")

        def exec(self):
            return gui.QDialog.Accepted

    monkeypatch.setattr(gui, "AddToProjectDialog", FakeDialog)
    win.add_to_project()
    win.project_list.item(0).setSelected(True)
    assert win.kit_table.rowCount() == 1 and not win.proj_lib_box.isHidden()
    assert "1 new part" in win.proj_status.text()
    calls = []
    monkeypatch.setattr(gui, "start_sync", lambda prjscr: (calls.append(prjscr), (True, "ok"))[1])
    win.update_project_library()
    assert calls


def test_send_button_counts_changes(win):
    win.lib.save(Part(mpn="Z1", stage="Ready", needs_sync=True))
    win.refresh_library()
    assert win.sync_btn.text() == "Send to Altium (1)"


def test_new_project_dialog_picks_existing_library_folder(win, monkeypatch, tmp_path):
    from partkit import projects

    (tmp_path / "STM32.SchLib").write_bytes(b"x")
    (tmp_path / "STM32.PcbLib").write_bytes(b"x")
    (tmp_path / "Old.PcbLib").write_bytes(b"x")
    real = gui.NewProjectDialog
    shown = []

    def fake_dialog(*a):
        d = real(*a)
        d.name.setText("Board")
        assert d.picker.set_path(str(tmp_path))
        shown.append(d.picker.result.text())
        d.exec = lambda: gui.QDialog.Accepted
        return d

    monkeypatch.setattr(gui, "NewProjectDialog", fake_dialog)
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("STM32.PcbLib", True)))
    win.new_project()
    proj = projects.get(win.lib, "Board")
    assert proj.own_library and proj.schlib.endswith("STM32.SchLib") and proj.pcblib.endswith("STM32.PcbLib")
    assert "STM32.SchLib + STM32.PcbLib" in win.proj_folder.text()
    assert "STM32.SchLib" in shown[0] and "STM32.PcbLib" in shown[0] and "(new" not in shown[0]


def test_value_filters_fit_the_part_and_remember_my_usual(win, monkeypatch):
    from partkit import search
    from partkit.search import SearchResult

    seen = []

    def fake(text, settings, http=None, query=None):
        seen.append(query)
        return SearchResult(mpn=text, query=query)

    monkeypatch.setattr(search, "find_any", fake)
    import threading

    monkeypatch.setattr(threading, "Thread", lambda target, daemon: type("T", (), {"start": staticmethod(target)})())
    win.search_box.setText("100nF 0603 50V X7R")
    win.run_search()
    assert seen[-1].voltage == 50 and not win.value_filter_box.isHidden()
    assert win.f_diel.currentText() == "X7R" and win.f_power.isHidden() and not win.f_volt.isHidden()
    win.remember_usual()
    assert "voltage=50" in Library(win.lib.root).settings.usual_capacitor
    # next time only the value is typed: my usual is filled in
    win.search_box.setText("1uF")
    win.run_search()
    assert seen[-1].package == "0603" and seen[-1].dielectric == "X7R" and seen[-1].voltage == 50
    # a filter changed for one search searches again
    win.f_volt.setCurrentIndex(win.f_volt.findData(16.0))
    win._value_filter_changed()
    assert seen[-1].voltage == 16 and seen[-1].package == "0603"
    # part numbers hide the value filters
    win.search_box.setText("LM358DR")
    win.run_search()
    assert win.value_filter_box.isHidden()


def test_no_cad_files_uses_one_of_my_footprints(win, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    from partkit.search import SearchResult
    from test_reuse_kits import J47, checked_10k

    checked_10k(win.lib)
    win.show_results(SearchResult(mpn="x", offers=[J47]))
    win.results.selectRow(0)
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: (a[3][0], True)))
    made = []

    def fake_exec(d):
        made.append((d.src.mpn, d.text.text(), d.table.rowCount(), d._chosen() if hasattr(d, "_chosen") else None))
        return gui.QDialog.Rejected

    monkeypatch.setattr(gui.ReuseDialog, "exec", fake_exec)
    win.use_my_footprint()
    assert made and made[0][1] == J47.mpn and made[0][2] == 1
