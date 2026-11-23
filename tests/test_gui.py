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
    assert win.lib.get("X1").stage == "Released"
    win.cat_choice.setCurrentText("Power")
    win.parts_table.selectRow(0)
    win.set_category()
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
    win.lib.save(Part(mpn="Y1", stage="Released", needs_sync=True))
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
    assert (lib.root / "partkit-settings.toml").exists() and len(lib.parts()) == 381


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
    win.add_result()
    p = win.lib.get("RC0603FR-071KL")
    assert p.category == "Resistors" and p.params["Supplier Part Number 1"] == "603-RC0603FR-071KL"
    win.lib.settings.providers = ["SnapMagic", "SamacSys"]
    win.get_cad(next_=False)
    win.get_cad(next_=True)
    assert opened == ["SnapMagic", "SamacSys"] and not win.next_btn.isEnabled()


def test_search_messages_without_keys(win):
    from partkit.search import SearchResult

    win.show_results(SearchResult(mpn="X", messages=["Add a free API key in Settings for: DigiKey."]))
    assert "API key" in win.search_msg.text() and win.results.rowCount() == 0
