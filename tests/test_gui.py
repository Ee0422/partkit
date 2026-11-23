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
    win.lib.save(Part(mpn="X1", category="ICs", source="SnapMagic"))
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
