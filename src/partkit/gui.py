"""PartKit desktop window (PySide6).

Five screens over the same engine the command line uses:
Find parts, Library, Import, Health check and Settings, plus a one-screen
first-run setup.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
    QMenu, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QToolButton, QVBoxLayout,
    QWidget,
)

from . import __version__
from . import fields as F
from .altium_launch import copy_scripts, start_sync
from .config import HUNTING_MODES, default_library_path, remember_library_path
from .importer import DOWNLOAD_EXT, STEP_EXT, ImportProblem, attach_step, import_zip
from .library import Library


def test_library_path(real: Path) -> Path:
    return real.with_name(real.name + " (Test)")


# ---------------------------------------------------------------- helpers

def _table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    t.horizontalHeader().setStretchLastSection(True)
    t.setSortingEnabled(True)
    return t


def _set_rows(t: QTableWidget, rows: list[list[str]], keep_order: bool = False) -> None:
    """Fill a table. Column 0 remembers each row's position in `rows`, even after the user sorts.

    keep_order shows rows in the order given (best first) until the user clicks a column.
    """
    t.setSortingEnabled(False)
    t.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            item = QTableWidgetItem(str(v))
            if c == 0:
                item.setData(Qt.UserRole, r)
            t.setItem(r, c, item)
    if keep_order:
        t.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
    t.setSortingEnabled(True)
    t.resizeColumnsToContents()


class Bridge(QObject):
    """Carries messages from background threads (Downloads watcher, searches) to the window."""
    message = Signal(str)
    searched = Signal(object)


# ---------------------------------------------------------------- first-run setup

class SetupDialog(QDialog):
    """One screen, good defaults, one Start button."""

    def __init__(self, parent=None, folder: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("Set up PartKit")
        self.folder = QLineEdit(str(folder or default_library_path()))
        browse = QPushButton("Change…")
        browse.clicked.connect(self._browse)
        intro = QLabel("PartKit keeps your parts in one library folder that every Altium project can use.\n"
                       "The defaults below are fine for most people. Press Start.")
        intro.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(self.folder)
        row.addWidget(browse)
        lay = QVBoxLayout(self)
        lay.addWidget(intro)
        lay.addWidget(QLabel("Library folder"))
        lay.addLayout(row)
        buttons = QDialogButtonBox()
        start = buttons.addButton("Start", QDialogButtonBox.AcceptRole)
        start.setDefault(True)
        buttons.addButton(QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Library folder", self.folder.text())
        if d:
            self.folder.setText(d)

    def run_setup(self) -> Library:
        lib = Library.init(Path(self.folder.text()))
        remember_library_path(lib.root)
        copy_scripts()
        return lib


FIRST_STEPS = (
    "Your library is ready. Three steps to your first part:\n\n"
    "1. Find parts: search a part number, or a value like 1k 0603 1%. Pick one, click Add to library, "
    "then Get CAD files and download it (PartKit imports it by itself).\n\n"
    "2. My parts: check the symbol and footprint, then click Mark Ready.\n\n"
    "3. Click Send to Altium (top right). PartKit writes the part into your Altium libraries, "
    "also while Altium is open.\n\n"
    "Projects and templates are optional: use them when you start a board.")


# ---------------------------------------------------------------- reuse a checked part

class ReuseDialog(QDialog):
    """New value from a checked part, or a new part on its footprint."""

    def __init__(self, parent, lib: Library, src, mode: str):
        from .reuse import can_search_by_value

        super().__init__(parent)
        self.lib, self.src, self.mode = lib, src, mode
        self.created = None
        self.rows = []
        self.by_value = mode == "value" and can_search_by_value(src)
        what = "New value from" if mode == "value" else "New part on the footprint of"
        self.setWindowTitle(f"{what} {src.mpn}")
        lay = QVBoxLayout(self)
        copies = ("symbol, footprint and 3D model" if mode == "value" else "footprint and 3D model")
        intro = QLabel(f"Copies the checked {copies} of {src.mpn} ({src.footprint}). "
                       + ("Type the new value: PartKit adds the size and spec and lists JLCPCB parts."
                          if self.by_value else "Type the new part's manufacturer part number and search, "
                          "or just type it and press Create."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        row = QHBoxLayout()
        self.text = QLineEdit()
        self.text.setPlaceholderText("e.g. 4.7k" if self.by_value and src.category == "Resistors" else
                                     "e.g. 1uF" if self.by_value else "Manufacturer part number")
        self.text.returnPressed.connect(self.search)
        go = QPushButton("Search")
        go.clicked.connect(self.search)
        row.addWidget(self.text)
        row.addWidget(go)
        lay.addLayout(row)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        filters = QHBoxLayout()
        self.jlc_type = QComboBox()
        self.jlc_type.addItems(["Basic and Extended", "Basic only", "Extended only"])
        self.only_stock = QCheckBox("In stock only")
        self.only_stock.setChecked(True)
        self.jlc_type.currentTextChanged.connect(self.show_rows)
        self.only_stock.toggled.connect(self.show_rows)
        for wdg in (QLabel("JLCPCB type:"), self.jlc_type, self.only_stock):
            filters.addWidget(wdg)
        filters.addStretch()
        lay.addLayout(filters)
        self.table = _table(["MPN", "Value", "Size", "Tolerance", "Power / Voltage", "Dielectric", "JLCPCB type",
                             "Stock", "Price @1 (USD)", "Supplier PN"])
        self.table.itemSelectionChanged.connect(self.show_choice)
        lay.addWidget(self.table)
        self.choice = QLabel("Click the part you want in the list.")
        self.choice.setWordWrap(True)
        lay.addWidget(self.choice)
        form = QFormLayout()
        self.symbol_from = QComboBox()
        self.category = QComboBox()
        if mode == "footprint":
            self.symbol_from.addItem("None yet (I'll add one)")
            for p in lib.parts():
                if p.symbol and p.source != "PartKit" and p.mpn != src.mpn:
                    self.symbol_from.addItem(p.mpn)
            self.category.addItems(list(F.CATEGORIES))
            self.category.setCurrentText(src.category)
            form.addRow("Symbol from", self.symbol_from)
            form.addRow("Category", self.category)
        lay.addLayout(form)
        buttons = QDialogButtonBox()
        create = buttons.addButton("Create part", QDialogButtonBox.AcceptRole)
        buttons.addButton(QDialogButtonBox.Cancel)
        create.clicked.connect(self.create)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.resize(900, 500)

    def query(self) -> str:
        from .reuse import value_query_text

        t = self.text.text().strip()
        return value_query_text(self.src, t) if self.by_value and t else t

    def search(self):
        from .search import SearchResult, find_any, merge_rows

        q = self.query()
        if not q:
            return
        self.msg.setText(f"Searching for {q}…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = find_any(q, self.lib.settings)
        except Exception as e:  # noqa: BLE001 - never let a search crash the window
            res = SearchResult(mpn=q, messages=[f"Search failed: {e}"])
        finally:
            QApplication.restoreOverrideCursor()
        self.rows = merge_rows(res.exact or res.offers, self.lib.settings.suppliers)
        self.show_rows()
        self.msg.setText("\n".join(res.messages) or (f"{len(self.rows)} found." if self.rows else "No results."))

    def _passes(self, r) -> bool:
        kind = self.jlc_type.currentText()
        if kind == "Basic only" and r.offer.status != "Basic":
            return False
        if kind == "Extended only" and r.offer.status not in ("Extended", "Preferred"):
            return False
        return not (self.only_stock.isChecked() and r.offer.stock is not None and r.offer.stock <= 0)

    def show_rows(self, *_):
        self.visible = [r for r in self.rows if self._passes(r)]
        table = []
        for r in self.visible:
            o = r.offer
            price = o.unit_price(1)
            table.append([r.mpn, r.value(), r.specs.get("Size", ""), r.specs.get("Tolerance", ""), r.rating(),
                          r.specs.get("Dielectric", ""), o.status if "JLCPCB" in r.sold_by else "",
                          "" if o.stock is None else f"{o.stock:,}", "" if price is None else f"{price:g}",
                          o.supplier_pn])
        _set_rows(self.table, table, keep_order=True)  # nothing pre-picked: you choose
        self.show_choice()

    def chosen(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if rows:
            idx = self.table.item(rows[0], 0).data(Qt.UserRole)
            if idx is not None and idx < len(getattr(self, "visible", [])):
                return self.visible[idx]
        return None

    def show_choice(self):
        r = self.chosen()
        if r is None:
            self.choice.setText("Click the part you want in the list." if self.rows else "")
            return
        o = r.offer
        stock = "stock unknown" if o.stock is None else f"{o.stock:,} in stock"
        kind = f", {o.status}" if o.status else ""
        self.choice.setText(f"Creating {o.mpn} ({o.supplier_pn}{kind}, {stock}).")

    def create(self):
        from .reuse import ReuseProblem, new_from_footprint, new_value
        from .search import offers_for

        from .reuse import package_warning

        row = self.chosen()
        if row is None and self.by_value:
            QMessageBox.information(self, "PartKit", "Search, then click the part you want in the list.")
            return
        offers = offers_for(row, self.lib.settings.suppliers) if row else []
        typed = "" if self.by_value else self.text.text().strip()
        warn = package_warning(self.src, row.offer if row else None)
        if not row and typed:
            warn = (f"{typed} will be added without supplier details (no supplier part number, stock or "
                    "price). Search first to fill them in.")
        if warn and QMessageBox.question(self, "PartKit", warn + "\n\nCreate it anyway?") != QMessageBox.Yes:
            return
        try:
            if self.mode == "value":
                self.created = new_value(self.lib, self.src.mpn, typed, offers)
            else:
                sym = self.symbol_from.currentText()
                self.created = new_from_footprint(self.lib, self.src.mpn, typed, offers,
                                                  symbol_from="" if sym.startswith("None") else sym,
                                                  category=self.category.currentText())
        except ReuseProblem as e:
            QMessageBox.information(self, "PartKit", str(e))
            return
        self.accept()


class NewProjectDialog(QDialog):
    def __init__(self, parent, templates: list[str], projects: list[str]):
        super().__init__(parent)
        self.setWindowTitle("New project")
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. Motor driver v2")
        form.addRow("Project name", self.name)
        self.start = QComboBox()
        self.start.addItems(["Empty", "From templates", "Copy of another project"])
        form.addRow("Start", self.start)
        self.tpl = QListWidget()
        self.tpl.setSelectionMode(QAbstractItemView.MultiSelection)
        self.tpl.addItems(templates)
        self.tpl.setMaximumHeight(110)
        form.addRow("Templates", self.tpl)
        self.copy = QComboBox()
        self.copy.addItems(projects)
        form.addRow("Copy of", self.copy)
        row = QHBoxLayout()
        self.lib_folder = QLineEdit()
        self.lib_folder.setReadOnly(True)
        self.lib_folder.setPlaceholderText("Empty: use my main library")
        self.lib_folder.setToolTip("Choose your board's Altium project (.PrjPcb).\n"
                                   "PartKit adds parts to the .SchLib/.PcbLib already in it,\n"
                                   "or makes new ones next to it if it has none.")
        choose = QPushButton("Choose…")
        choose.clicked.connect(self._choose_folder)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.lib_folder.clear)
        for wdg in (self.lib_folder, choose, clear):
            row.addWidget(wdg)
        form.addRow("Altium project (optional)", row)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.start.currentTextChanged.connect(self._mode)
        self._mode()

    def _choose_folder(self):
        f, _ = QFileDialog.getOpenFileName(self, "Your board's Altium project (or its library)",
                                           self.lib_folder.text(),
                                           "Altium project or library (*.PrjPcb *.SchLib *.PcbLib)")
        if f:
            self.lib_folder.setText(f)
            if not self.name.text().strip():
                self.name.setText(Path(f).stem)

    def _mode(self, *_):
        self.tpl.setEnabled(self.start.currentText() == "From templates")
        self.copy.setEnabled(self.start.currentText().startswith("Copy") and self.copy.count() > 0)

    def templates(self) -> list[str]:
        if self.start.currentText() != "From templates":
            return []
        return [i.text() for i in self.tpl.selectedItems()]

    def copy_of(self) -> str:
        return self.copy.currentText() if self.start.currentText().startswith("Copy") else ""


class AddToProjectDialog(QDialog):
    def __init__(self, parent, projects: list[str], templates: list[str]):
        super().__init__(parent)
        self.setWindowTitle("Add to project")
        form = QFormLayout(self)
        self.project = QComboBox()
        self.project.addItems(projects)
        form.addRow("Project", self.project)
        self.template = QComboBox()
        self.template.addItems(["No, this project only"] + templates)
        form.addRow("Also add to a template?", self.template)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


# ---------------------------------------------------------------- main window

class MainWindow(QMainWindow):
    def __init__(self, root: Path):
        super().__init__()
        self.real_root = Path(root)
        self.test_mode = False
        self.lib = Library(self.real_root)
        self.bridge = Bridge()
        self.bridge.message.connect(self.log)
        self.bridge.searched.connect(self.show_results)
        self.observer = None
        self.offers = []
        self.cad_list = []
        self.cad_index = -1

        self.setWindowTitle(f"PartKit {__version__}")
        self.resize(1100, 700)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._search_tab(), "Find parts")
        self.tabs.addTab(self._library_tab(), "My parts")
        self.tabs.addTab(self._projects_tab(), "Projects")
        self.tabs.addTab(self._settings_tab(), "Settings")
        self._health_window()

        top = QHBoxLayout()
        self.mode_label = QLabel()
        self.sync_btn = QPushButton("Send to Altium")
        self.sync_btn.setToolTip("Write approved parts into your Altium libraries (runs PartKit Sync)")
        self.sync_btn.clicked.connect(self.sync)
        top.addWidget(self.mode_label)
        top.addStretch()
        top.addWidget(self.sync_btn)
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.addLayout(top)
        lay.addWidget(self.tabs)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(90)
        self.log_box.setPlaceholderText("Messages from PartKit appear here.")
        lay.addWidget(self.log_box)
        self.setCentralWidget(central)
        self.setAcceptDrops(True)
        self.result_timer = QTimer(self)
        self.result_timer.setInterval(2000)
        self.result_timer.timeout.connect(self.check_sync_result)
        self.result_timer.start()
        self.refresh_all()

    # ----- library switching (test mode)
    def set_test_mode(self, on: bool):
        self.test_mode = on
        root = test_library_path(self.real_root) if on else self.real_root
        if not (root / "partkit-settings.toml").exists():
            Library.init(root)
        self.lib = Library(root)
        self.refresh_all()

    def refresh_all(self):
        self.mode_label.setText(
            ("TEST MODE: " if self.test_mode else "") + f"Library: {self.lib.root}")
        self.mode_label.setStyleSheet("color: #c05000; font-weight: bold;" if self.test_mode else "")
        self.refresh_library()
        self.refresh_kits()
        self.load_settings()

    def log(self, msg: str):
        self.log_box.append(msg)
        self.statusBar().showMessage(msg, 8000)
        self.refresh_library()

    # ----- Find parts tab
    RESULT_COLUMNS = ["MPN", "Value", "Size", "Tolerance", "Power / Voltage", "Dielectric", "JLCPCB type",
                      "Stock", "Price @1 (USD)", "Sold by", "Supplier PN", "Manufacturer", "Description"]

    def _search_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Part number (CL10B104KB8NNNC) or value (1k 0603 1%, 100nF 0603 50V X7R)")
        self.search_box.returnPressed.connect(self.run_search)
        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.run_search)
        row.addWidget(self.search_box)
        row.addWidget(self.search_btn)
        lay.addLayout(row)
        self.search_msg = QLabel(FIRST_STEPS.split("\n\n", 1)[1].rsplit("\n\n", 1)[0]
                                 if not self.lib.parts() else
                                 "Type a part number, or a resistor or capacitor value to see JLCPCB parts.")
        self.search_msg.setWordWrap(True)
        lay.addWidget(self.search_msg)
        filters = QHBoxLayout()
        self.jlc_type = QComboBox()
        self.jlc_type.addItems(["Basic and Extended", "Basic only", "Extended only"])
        self.jlc_type.setToolTip("Basic parts are always loaded on JLCPCB's machines: no extra fee.\n"
                                   "Extended parts are loaded by hand for your order: about US$3 extra per part type.\n"
                                 "'Preferred' parts count as Extended here.")
        self.only_stock = QCheckBox("In stock only")
        self.only_stock.setChecked(True)
        self.only_supplier = QComboBox()
        self.only_supplier.addItem("All suppliers")
        self.narrow = QLineEdit()
        self.narrow.setPlaceholderText("Narrow results by typing, e.g. YAGEO or 1%")
        self.only_stock.toggled.connect(self.apply_filters)
        self.jlc_type.currentTextChanged.connect(self.apply_filters)
        self.only_supplier.currentTextChanged.connect(self.apply_filters)
        self.narrow.textChanged.connect(self.apply_filters)
        for wdg in (QLabel("JLCPCB type:"), self.jlc_type, self.only_stock, QLabel("Show:"), self.only_supplier, self.narrow):
            filters.addWidget(wdg)
        lay.addLayout(filters)
        self.results = _table(self.RESULT_COLUMNS)
        self.results.horizontalHeaderItem(6).setToolTip(self.jlc_type.toolTip())
        lay.addWidget(self.results)
        row = QHBoxLayout()
        self.add_cat = QComboBox()
        self.add_cat.addItems(["Let PartKit guess"] + list(F.CATEGORIES))
        add = QPushButton("Add to library")
        add.setToolTip("Fills Manufacturer, Description, Datasheet, supplier numbers and specs")
        add.clicked.connect(self.add_result)
        cad = QPushButton("Get CAD files")
        cad.setToolTip("Opens your first preferred provider; your download is imported automatically")
        cad.clicked.connect(self.get_cad_first)
        self.next_btn = QPushButton("Not there? Try next provider")
        self.next_btn.clicked.connect(self.get_cad_next)
        self.next_btn.setEnabled(False)
        page = QPushButton("Open supplier page")
        page.clicked.connect(self.open_supplier_page)
        for b in (QLabel("Category:"), self.add_cat, add, cad, self.next_btn, page):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        imp = QHBoxLayout()
        self.watch_box = QCheckBox("Import CAD downloads from my Downloads folder automatically")
        self.watch_box.toggled.connect(self.toggle_watch)
        choose = QPushButton("Import a download…")
        choose.setToolTip("A .zip, .IntLib or .step file. You can also drop files anywhere on this window.")
        choose.clicked.connect(self.choose_zip)
        imp.addWidget(self.watch_box)
        imp.addWidget(choose)
        imp.addStretch()
        lay.addLayout(imp)
        self.rows = []
        return w

    def run_search(self):
        text = self.search_box.text().strip()
        if not text:
            return
        self.search_btn.setEnabled(False)
        self.search_msg.setText(f"Searching for {text}…")
        settings = self.lib.settings
        import threading

        from .search import find_any

        def work():
            try:
                res = find_any(text, settings)
            except Exception as e:  # noqa: BLE001 - never let a search crash the window
                from .search import SearchResult

                res = SearchResult(mpn=text, messages=[f"Search failed: {e}"])
            self.bridge.searched.emit(res)

        threading.Thread(target=work, daemon=True).start()

    def show_results(self, res):
        from .search import merge_rows

        self.search_btn.setEnabled(True)
        self.last_search = res
        offers = res.exact or res.offers
        self.offers = offers
        self.rows = merge_rows(offers, self.lib.settings.suppliers)
        names = sorted({n for r in self.rows for n in r.sold_by})
        current = self.only_supplier.currentText()
        self.only_supplier.blockSignals(True)
        self.only_supplier.clear()
        self.only_supplier.addItems(["All suppliers"] + [f"{n} only" for n in names])
        if current in [self.only_supplier.itemText(i) for i in range(self.only_supplier.count())]:
            self.only_supplier.setCurrentText(current)
        self.only_supplier.blockSignals(False)
        self.result_messages = list(res.messages)
        self.apply_filters()
        self.cad_list, self.cad_index = [], -1
        self.next_btn.setEnabled(False)

    def _row_passes(self, r) -> bool:
        kind = self.jlc_type.currentText()
        if kind == "Basic only" and r.offer.status != "Basic":
            return False
        if kind == "Extended only" and r.offer.status not in ("Extended", "Preferred"):
            return False
        if self.only_stock.isChecked() and r.offer.stock is not None and r.offer.stock <= 0:
            return False
        sup = self.only_supplier.currentText()
        if sup.endswith(" only") and sup[:-5] not in r.sold_by:
            return False
        words = self.narrow.text().lower().split()
        if words:
            hay = " ".join([r.mpn, r.offer.manufacturer, r.offer.description, r.offer.supplier_pn,
                            *r.specs.values()]).lower()
            if not all(w in hay for w in words):
                return False
        return True

    def apply_filters(self, *_):
        self.visible = [r for r in getattr(self, "rows", []) if self._row_passes(r)]
        table = []
        for r in self.visible:
            o = r.offer
            price = o.unit_price(1)
            table.append([r.mpn, r.value(), r.specs.get("Size", ""), r.specs.get("Tolerance", ""), r.rating(),
                          r.specs.get("Dielectric", ""), o.status if "JLCPCB" in r.sold_by else "",
                          "" if o.stock is None else f"{o.stock:,}",
                          "" if price is None else f"{price:g}", ", ".join(r.sold_by), o.supplier_pn,
                          o.manufacturer, o.description])
        _set_rows(self.results, table, keep_order=True)
        msgs = list(getattr(self, "result_messages", []))
        res = getattr(self, "last_search", None)
        if self.rows and res is not None and res.query is None:
            msgs.insert(0, f"Found {len(self.rows)} part(s) for {res.mpn}.")
        hidden = len(self.rows) - len(self.visible)
        if hidden:
            msgs.append(f"{hidden} more hidden by the filters above.")
        self.search_msg.setText("\n".join(msgs) or (f"No results for {res.mpn}." if res else ""))

    def _selected_row(self):
        rows = sorted({i.row() for i in self.results.selectedIndexes()})
        if rows:
            idx = self.results.item(rows[0], 0).data(Qt.UserRole)
            if idx is not None and idx < len(self.visible):
                return self.visible[idx]
        return None

    def _search_mpn(self) -> str:
        r = self._selected_row()
        if r:
            return r.mpn
        visible = getattr(self, "visible", [])
        if visible and getattr(self, "last_search", None) is not None and self.last_search.query is None:
            return visible[0].mpn
        text = self.search_box.text().strip()
        from .valuesearch import parse

        return "" if parse(text) else text

    def add_result(self):
        from .search import add_from_search, offers_for

        r = self._selected_row()
        if r is None and getattr(self, "last_search", None) is not None and self.last_search.query is None:
            r = (getattr(self, "visible", []) or [None])[0]
        mpn = r.mpn if r else self._search_mpn()
        if not mpn:
            QMessageBox.information(self, "PartKit", "Pick a part in the results first.")
            return
        # without supplier results the part is added with just its MPN; the CAD file fills in the rest
        offers = offers_for(r, self.lib.settings.suppliers) if r else []
        cat = self.add_cat.currentText()
        part = add_from_search(self.lib, mpn, offers, category=None if cat.startswith("Let") else cat)
        self.log(f"{part.mpn} added to My parts (To check) as {part.category}. Click 'Get CAD files' next.")

    # bound methods, not lambdas: a lambda holding the window keeps it alive past Qt's shutdown
    def get_cad_first(self):
        self.get_cad(next_=False)

    def get_cad_next(self):
        self.get_cad(next_=True)

    def get_cad(self, next_: bool):
        from .providers import cad_sources, open_source

        mpn = self._search_mpn()
        if not mpn:
            QMessageBox.information(self, "PartKit", "Pick a part in the results first.")
            return
        if not next_ or not self.cad_list:
            datasheet = next((o.datasheet for o in self.offers if o.mpn == mpn and o.datasheet), "")
            self.cad_list = cad_sources(mpn, self.lib.settings, manufacturer_url=datasheet)
            self.cad_index = -1
        self.cad_index += 1
        if self.cad_index >= len(self.cad_list):
            hint = "" if self.lib.settings.hunting != "off" else \
                " Turn on hunting in Settings to search wider."
            QMessageBox.information(self, "PartKit", f"No more providers to try for {mpn}.{hint}")
            self.next_btn.setEnabled(False)
            return
        src = self.cad_list[self.cad_index]
        if not self.lib.get(mpn):
            self.add_result()
        if hasattr(self, "watch_box") and not self.watch_box.isChecked():
            self.watch_box.setChecked(True)  # so the download imports by itself
        open_source(src)
        self.next_btn.setEnabled(self.cad_index + 1 < len(self.cad_list))
        self.log(f"Opened {src.name}{' (hunting)' if src.hunting else ''} for {mpn}. Download the Altium "
                 "files there; PartKit imports them from your Downloads folder.")

    def open_supplier_page(self):
        import webbrowser

        from .suppliers import supplier_link

        r = self._selected_row()
        if r and r.offer.url:
            webbrowser.open(r.offer.url)
            return
        name = self.lib.settings.suppliers[0] if self.lib.settings.suppliers else "JLCPCB"
        mpn = self._search_mpn()
        if mpn:
            webbrowser.open(supplier_link(name, mpn))

    # ----- Library tab
    def _library_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by MPN, value or footprint…")
        self.search.textChanged.connect(self.refresh_library)
        self.stage_filter = QComboBox()
        self.stage_filter.addItems(["All stages", *F.STAGES])
        self.stage_filter.currentIndexChanged.connect(self.refresh_library)
        self.cat_filter = QComboBox()
        self.cat_filter.addItems(["All categories", *F.CATEGORIES])
        self.cat_filter.currentIndexChanged.connect(self.refresh_library)
        self.fav_only = QCheckBox("★ Favourites only")
        self.fav_only.toggled.connect(self.refresh_library)
        filters.addWidget(self.search, 3)
        filters.addWidget(self.stage_filter, 1)
        filters.addWidget(self.cat_filter, 1)
        filters.addWidget(self.fav_only)
        lay.addLayout(filters)

        self.parts_table = _table(["MPN", "★", "Category", "Stage", "Value", "Size", "3D", "Footprint",
                                   "Goes into"])
        self.parts_table.doubleClicked.connect(self.show_details)
        lay.addWidget(self.parts_table)

        actions = QHBoxLayout()
        ready = QPushButton("Mark Ready ✓")
        ready.setToolTip("You've checked the symbol and footprint: the part can go into your libraries")
        ready.clicked.connect(self.approve)
        to_proj = QPushButton("Add to project…")
        to_proj.setToolTip("Add the selected parts to one project's parts list")
        to_proj.clicked.connect(self.add_to_project)
        more = QToolButton()
        more.setText("More ▾")
        more.setPopupMode(QToolButton.InstantPopup)
        more.setMenu(self._part_menu())
        self.problems_btn = QPushButton("")
        self.problems_btn.setFlat(True)
        self.problems_btn.setStyleSheet("color: #c05000;")
        self.problems_btn.setToolTip("BOM gaps, missing files, simple 3D models")
        self.problems_btn.clicked.connect(self.show_problems)
        for wdg in (ready, to_proj, more):
            actions.addWidget(wdg)
        actions.addStretch()
        actions.addWidget(self.problems_btn)
        lay.addLayout(actions)
        self.parts_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.parts_table.customContextMenuRequested.connect(self._part_context_menu)
        return w

    def _part_menu(self) -> QMenu:
        """Everything you can do with a part, besides the three main buttons. Also the right-click menu."""
        m = QMenu(self)
        for text, tip, fn in (
                ("Mark Ready ✓", "", self.approve),
                ("Add to project…", "", self.add_to_project),
                (None, None, None),
                ("★ Favourite on/off", "Favourites are listed first", self.toggle_favourite),
                ("New value from this part…", "Same symbol, footprint and 3D model; only the value, part "
                 "number and supplier change. No download.", self.new_value),
                ("New part from this footprint…", "Same footprint and 3D model; the symbol comes from any "
                 "part you choose.", self.new_from_footprint),
                ("Add to template…", "Templates are groups of parts you start projects from, e.g. "
                 "'USB-C power input'", self.add_to_kit),
                (None, None, None),
                ("Attach 3D model…", "", self.attach_3d),
                ("Re-import from Archive…", "Import a download again without downloading it", self.reimport),
                ("Mark obsolete", "Keep it for old boards, but don't use it in new ones", self.obsolete),
                ("Delete…", "Take it out of PartKit (Undo brings it back)", self.delete_parts),
                (None, None, None),
                ("Undo last change", "", self.undo),
                ("Details", "", self.show_details)):
            if text is None:
                m.addSeparator()
                continue
            a = m.addAction(text)
            a.setToolTip(tip)
            a.triggered.connect(fn)
        cats = m.addMenu("Set category")
        for c in F.CATEGORIES:
            a = cats.addAction(c)
            a.setData(c)
        cats.triggered.connect(self._category_chosen)
        m.setToolTipsVisible(True)
        return m

    def _part_context_menu(self, pos):
        if self.parts_table.itemAt(pos) is not None:
            self._part_menu().exec(self.parts_table.viewport().mapToGlobal(pos))

    def _category_chosen(self, action):
        self.set_category(action.data())

    def refresh_library(self):
        if not hasattr(self, "parts_table"):
            return
        text = self.search.text().strip().lower()
        stage = self.stage_filter.currentText()
        cat = self.cat_filter.currentText()
        rows = []
        for p in sorted(self.lib.parts(), key=lambda p: (not p.favourite, p.category, p.mpn)):
            if self.fav_only.isChecked() and not p.favourite:
                continue
            if stage in F.STAGES and p.stage != stage:
                continue
            if cat in F.CATEGORIES and p.category != cat:
                continue
            hay = f"{p.mpn} {p.params.get('Value', '')} {p.footprint}".lower()
            if text and text not in hay:
                continue
            rows.append([p.mpn, "★" if p.favourite else "", p.category, p.stage, p.params.get("Value", ""),
                         p.params.get("Size", ""), p.model_3d, p.footprint, Path(p.target_schlib).stem])
        _set_rows(self.parts_table, rows, keep_order=True)
        n = self.lib.send_count()
        if hasattr(self, "sync_btn"):
            self.sync_btn.setText(f"Send to Altium ({n})" if n else "Send to Altium")
            self.sync_btn.setToolTip(f"{n} change{'s' if n != 1 else ''} waiting: new or changed parts, deleted "
                                     "parts and new project-library parts" if n else "Nothing waiting")
        if hasattr(self, "problems_btn"):
            k = len(self.lib.health_check())
            self.problems_btn.setText(f"⚠ {k} problem{'s' if k != 1 else ''}")
            self.problems_btn.setVisible(k > 0)

    def selected_mpns(self) -> list[str]:
        rows = sorted({i.row() for i in self.parts_table.selectedIndexes()})
        return [self.parts_table.item(r, 0).text() for r in rows]

    def _need_selection(self) -> list[str]:
        mpns = self.selected_mpns()
        if not mpns:
            QMessageBox.information(self, "PartKit", "Select one or more parts first.")
        return mpns

    def approve(self):
        for m in self._need_selection():
            p = self.lib.get(m)
            if p and p.category == F.DEFAULT_CATEGORY and p.source != "PartKit":
                if QMessageBox.question(self, "PartKit", f"{m} is still in category Misc. Mark it Ready anyway?") \
                        != QMessageBox.Yes:
                    continue
            try:
                self.lib.approve(m)
            except KeyError as e:
                QMessageBox.warning(self, "PartKit", str(e.args[0]))
        self.refresh_library()

    def set_category(self, cat: str):
        for m in self._need_selection():
            p = self.lib.get(m)
            p.category = cat
            p.target_schlib, p.target_pcblib = self.lib.settings.target_libs(cat)
            self.lib.save(p)
        self.refresh_library()

    def delete_parts(self):
        mpns = self._need_selection()
        if not mpns:
            return
        box = QMessageBox(self)
        box.setWindowTitle("PartKit")
        box.setText(f"Delete {', '.join(mpns)}?\n\nIt's taken out of PartKit and your templates and projects. "
                    "Undo last change brings it back.")
        also = QCheckBox("Also remove it from my Altium library on the next Send (the footprint stays)")
        box.setCheckBox(also)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        if box.exec() != QMessageBox.Yes:
            return
        for m in mpns:
            self.lib.delete_part(m, from_altium=also.isChecked())
            self.log(f"Deleted {m}." + (" Send to Altium removes it there too." if also.isChecked() else ""))
        self.refresh_all()

    def attach_3d(self):
        mpns = self._need_selection()
        if len(mpns) != 1:
            return
        f, _ = QFileDialog.getOpenFileName(self, "Choose a STEP model", str(Path.home() / "Downloads"),
                                           "STEP models (*.step *.stp)")
        if f:
            for msg in attach_step(self.lib, mpns[0], Path(f)).messages:
                self.log(msg)

    def obsolete(self):
        for m in self._need_selection():
            self.lib.mark_obsolete(m)
        self.refresh_library()

    def undo(self):
        for m in self._need_selection():
            self.log(f"{m} restored." if self.lib.undo(m) else f"Nothing to undo for {m}.")

    def toggle_favourite(self):
        mpns = self._need_selection()
        on = not all(self.lib.get(m).favourite for m in mpns)
        for m in mpns:
            self.lib.set_favourite(m, on)
        self.refresh_library()

    def _one_selected(self) -> str:
        mpns = self._need_selection()
        if len(mpns) > 1:
            QMessageBox.information(self, "PartKit", "Select just one part to start from.")
            return ""
        return mpns[0] if mpns else ""

    def new_value(self):
        self._reuse("value")

    def new_from_footprint(self):
        self._reuse("footprint")

    def _reuse(self, mode: str):
        from .reuse import ReuseProblem, _check_source

        mpn = self._one_selected()
        if not mpn:
            return
        try:
            src = _check_source(self.lib.get(mpn), mpn)
        except ReuseProblem as e:
            QMessageBox.information(self, "PartKit", str(e))
            return
        d = ReuseDialog(self, self.lib, src, mode)
        if d.exec() == QDialog.Accepted and d.created:
            self.log(f"{d.created.mpn} added to My parts, To check ({d.created.notes[-1].lower()}). Mark it Ready, then "
                     "Send to Altium.")

    def add_to_kit(self):
        from PySide6.QtWidgets import QInputDialog

        from . import kits

        mpns = self._need_selection()
        if not mpns:
            return
        names = [k.name for k in kits.kits(self.lib)]
        name, ok = QInputDialog.getItem(self, "Add to template", "Template (pick one, or type a new name):", names,
                                        0, True)
        if ok and name.strip():
            kit = kits.add_parts(self.lib, name, mpns)
            self.refresh_kits()
            self.log(f"Added {len(mpns)} part(s) to template '{kit.name}' ({len(kit.items)} parts in it now).")

    def show_details(self):
        mpns = self.selected_mpns()
        if not mpns:
            return
        p = self.lib.get(mpns[0])
        d = QDialog(self)
        d.setWindowTitle(p.mpn)
        t = _table(["Parameter", "Value"])
        _set_rows(t, [[k, v] for k, v in p.bom_params().items()])
        lay = QVBoxLayout(d)
        lay.addWidget(t)
        info = [f"Symbol: {p.symbol} → {p.target_schlib}", f"Footprint: {p.footprint} → {p.target_pcblib}",
                f"3D model: {p.model_3d} ({p.model_3d_source})"] + [f"Note: {n}" for n in p.notes]
        lay.addWidget(QLabel("\n".join(info)))
        d.resize(600, 500)
        d.exec()

    # ----- Projects tab (projects, and templates to start them from)
    def _projects_tab(self) -> QWidget:
        from PySide6.QtWidgets import QSpinBox

        w = QWidget()
        lay = QHBoxLayout(w)
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Projects</b>"))
        self.project_list = QListWidget()
        self.project_list.itemSelectionChanged.connect(self._project_picked)
        left.addWidget(self.project_list)
        row = QHBoxLayout()
        for text, fn in (("New project…", self.new_project), ("Delete", self.delete_project)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        left.addLayout(row)
        tl = QLabel("<b>Templates</b> (optional)")
        tl.setToolTip("Groups of parts you use together, e.g. 'USB-C power input'. Start a new project from one "
                      "or more templates. Select several to see them combined.")
        left.addWidget(tl)
        self.kit_list = QListWidget()
        self.kit_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.kit_list.itemSelectionChanged.connect(self._template_picked)
        left.addWidget(self.kit_list)
        row = QHBoxLayout()
        for text, fn in (("New template…", self.new_kit), ("Delete", self.delete_kit)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        left.addLayout(row)
        lay.addLayout(left, 1)

        right = QVBoxLayout()
        self.kit_title = QLabel("")
        self.kit_title.setWordWrap(True)
        right.addWidget(self.kit_title)
        self.kit_table = _table(["MPN", "Qty", "Value", "Description", "Supplier PN", "In project library", "Note"])
        right.addWidget(self.kit_table)
        row = QHBoxLayout()
        self.kit_qty = QSpinBox()
        self.kit_qty.setRange(1, 999)
        for wdg in (QLabel("Quantity:"), self.kit_qty):
            row.addWidget(wdg)
        for text, fn in (("Set quantity", self.set_kit_qty), ("Remove", self.remove_from_kit),
                         ("Save starting parts list (CSV)…", self.save_kit_bom)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        right.addLayout(row)
        self.proj_lib_box = QWidget()
        outer = QVBoxLayout(self.proj_lib_box)
        outer.setContentsMargins(0, 0, 0, 0)
        pl = QHBoxLayout()
        info = QHBoxLayout()
        outer.addLayout(pl)
        outer.addLayout(info)
        self.own_lib = QCheckBox("Give this project its own library")
        self.own_lib.setToolTip("Off: the project uses your main library (simplest).\n"
                                "On: PartKit writes this project's parts into its own .SchLib/.PcbLib too.")
        self.own_lib.toggled.connect(self.toggle_own_library)
        self.proj_folder = QLabel("")
        folder_btn = QPushButton("Choose Altium project…")
        folder_btn.setToolTip("Pick your board's .PrjPcb: PartKit uses the .SchLib/.PcbLib already in it.\n"
                              "You can also pick a .SchLib or .PcbLib file.")
        folder_btn.clicked.connect(self.change_project_folder)
        self.proj_status = QLabel("")
        resend = QPushButton("Re-send all parts")
        resend.setToolTip("Copies every part again, e.g. after you fixed a part in your main library.")
        resend.clicked.connect(self.resend_project_library)
        self.proj_lib_widgets = (self.proj_folder, folder_btn, self.proj_status, resend)
        pl.addWidget(self.own_lib)
        pl.addWidget(folder_btn)
        pl.addWidget(resend)
        pl.addStretch()
        info.addWidget(self.proj_folder)
        info.addWidget(self.proj_status, 1)
        right.addWidget(self.proj_lib_box)
        lay.addLayout(right, 3)
        self.kit_lines = []
        self.view = ("none", [])
        return w

    def refresh_kits(self):
        if not hasattr(self, "kit_list"):
            return
        from . import kits, projects

        for widget, names in ((self.project_list, [p.name for p in projects.projects(self.lib)]),
                              (self.kit_list, [k.name for k in kits.kits(self.lib)])):
            chosen = {i.text() for i in widget.selectedItems()}
            widget.blockSignals(True)
            widget.clear()
            for n in names:
                widget.addItem(n)
                if n in chosen:
                    widget.item(widget.count() - 1).setSelected(True)
            widget.blockSignals(False)
        self.show_kit()

    def _project_picked(self):
        if self.project_list.selectedItems():
            self.kit_list.blockSignals(True)
            self.kit_list.clearSelection()
            self.kit_list.blockSignals(False)
        self.show_kit()

    def _template_picked(self):
        if self.kit_list.selectedItems():
            self.project_list.blockSignals(True)
            self.project_list.clearSelection()
            self.project_list.blockSignals(False)
        self.show_kit()

    def _chosen_kits(self) -> list[str]:
        return [i.text() for i in self.kit_list.selectedItems()]

    def _chosen_project(self):
        from . import projects

        items = self.project_list.selectedItems() if hasattr(self, "project_list") else []
        return projects.get(self.lib, items[0].text()) if items else None

    def show_kit(self):
        from . import kits, projects

        proj = self._chosen_project()
        names = self._chosen_kits()
        if proj:
            self.view = ("project", [proj.name])
            self.kit_lines = projects.parts_list(self.lib, proj)
        elif names:
            self.view = ("templates", names)
            self.kit_lines = kits.project_bom(self.lib, names)
        else:
            self.view = ("none", [])
            self.kit_lines = []
        rows = []
        for line in self.kit_lines:
            p = line.part
            in_lib = ("yes" if proj and line.mpn in proj.in_library else "not yet") if proj and proj.own_library else ""
            rows.append([line.mpn, str(line.qty), p.params.get("Value", "") if p else "",
                         p.params.get("Description", "") if p else "",
                         p.params.get("Supplier Part Number 1", "") if p else "", in_lib, line.warning])
        _set_rows(self.kit_table, rows, keep_order=True)
        self.proj_lib_box.setVisible(proj is not None)
        if proj:
            self.own_lib.blockSignals(True)
            self.own_lib.setChecked(proj.own_library)
            self.own_lib.blockSignals(False)
            for wdg in self.proj_lib_widgets:
                wdg.setVisible(proj.own_library)
            ready, waiting = projects.missing_from_library(self.lib, proj)
            changed = projects.changed_since_written(self.lib, proj)
            bits = []
            if ready:
                bits.append(f"{len(ready)} new part{'s go' if len(ready) != 1 else ' goes'} in on the next Send")
            if waiting:
                bits.append(f"{len(waiting)} wait{'s' if len(waiting) == 1 else ''} for Mark Ready")
            if changed:
                bits.append(f"{len(changed)} changed since: Re-send all parts to update")
            self.proj_status.setText(". ".join(bits) if bits else "Up to date")
            self.proj_status.setToolTip("\n".join(waiting + [f"{m}: changed in PartKit since" for m in changed]))
            sch, pcb = Path(proj.schlib), Path(proj.pcblib)
            new = [p.name for p in (sch, pcb) if not p.exists()]
            self.proj_folder.setText(f"Library: {sch.name} + {pcb.name}" + (" (new)" if new else "") + ".")
            self.proj_folder.setToolTip(f"{sch}\n{pcb}" + (f"\nPartKit makes {', '.join(new)} on the first Send."
                                                            if new else ""))
            self.kit_title.setText(f"Project '{proj.name}': {len(rows)} parts. Add more from My parts with "
                                   "'Add to project…'.")
        elif len(names) > 1:
            self.kit_title.setText(f"Templates {', '.join(names)} combined: {len(rows)} parts, quantities added up.")
        elif names:
            self.kit_title.setText(f"Template '{names[0]}': {len(rows)} parts.")
        else:
            self.kit_title.setText("Make a project for each board. Start it empty or from templates, then add "
                                   "parts from My parts with 'Add to project…'.")

    def new_project(self):
        from . import kits, projects

        d = NewProjectDialog(self, [k.name for k in kits.kits(self.lib)],
                             [p.name for p in projects.projects(self.lib)])
        if d.exec() != QDialog.Accepted:
            return
        folder = d.lib_folder.text().strip()
        files = self._choose_files(folder) if folder else ("", "")
        if files is None:
            return
        try:
            proj = projects.create(self.lib, d.name.text(), templates=d.templates(), copy_of=d.copy_of(),
                                   folder=folder, schlib=files[0], pcblib=files[1])
        except (ValueError, KeyError) as e:
            QMessageBox.information(self, "PartKit", str(e.args[0]))
            return
        self.refresh_kits()
        items = self.project_list.findItems(proj.name, Qt.MatchExactly)
        if items:
            items[0].setSelected(True)
        self.log(f"Project '{proj.name}' made with {len(proj.items)} parts.")

    def delete_project(self):
        from . import projects

        proj = self._chosen_project()
        if proj and QMessageBox.question(self, "PartKit", f"Delete project '{proj.name}'? Its parts stay in your "
                                         "library, and its library files are not deleted.") == QMessageBox.Yes:
            projects.delete(self.lib, proj.name)
            self.refresh_kits()

    def new_kit(self):
        from PySide6.QtWidgets import QInputDialog

        from . import kits

        name, ok = QInputDialog.getText(self, "New template", "Template name, e.g. USB-C power input:")
        if ok and name.strip():
            if kits.get(self.lib, name) is None:
                kits.save(self.lib, kits.Kit(name.strip()))
            self.refresh_kits()

    def delete_kit(self):
        from . import kits

        for name in self._chosen_kits():
            if QMessageBox.question(self, "PartKit", f"Delete template '{name}'? The parts stay in your library.") \
                    == QMessageBox.Yes:
                kits.delete(self.lib, name)
        self.refresh_kits()

    def _kit_rows(self) -> list[str]:
        rows = sorted({i.row() for i in self.kit_table.selectedIndexes()})
        return [self.kit_table.item(r, 0).text() for r in rows]

    def _change_list(self, change):
        """Apply change(obj) to the selected project, or to the one selected template."""
        from . import kits, projects

        proj = self._chosen_project()
        if proj:
            change(proj)
            projects.save(self.lib, proj)
        else:
            names = self._chosen_kits()
            if len(names) != 1:
                QMessageBox.information(self, "PartKit", "Select one project or one template to change it.")
                return
            kit = kits.get(self.lib, names[0])
            change(kit)
            kits.save(self.lib, kit)
        self.show_kit()

    def set_kit_qty(self):
        mpns, qty = self._kit_rows(), self.kit_qty.value()
        self._change_list(lambda obj: [obj.add(m, qty) for m in mpns])

    def remove_from_kit(self):
        mpns = self._kit_rows()
        self._change_list(lambda obj: [obj.remove(m) for m in mpns])

    def save_kit_bom(self, path: str | None = None):
        from . import kits

        kind, names = self.view
        if kind == "none":
            QMessageBox.information(self, "PartKit", "Select a project or templates first.")
            return
        if not path:
            default = str(Path.home() / "Documents" / (" + ".join(names) + " starting parts list.csv"))
            path, _ = QFileDialog.getSaveFileName(self, "Save starting parts list", default, "CSV (*.csv)")
        if path:
            kits.write_csv(self.kit_lines, Path(path))
            self.log(f"Starting parts list saved to {path}. It opens in Excel. (Your real BOM comes from Altium "
                     "once the schematic is done.)")

    def toggle_own_library(self, on: bool):
        from . import projects

        proj = self._chosen_project()
        if proj:
            proj.own_library = on
            projects.save(self.lib, proj)
            self.show_kit()

    def _pick_altium_project(self, start: str = "") -> str:
        f, _ = QFileDialog.getOpenFileName(self, "Your board's Altium project (or its library)", start,
                                           "Altium project or library (*.PrjPcb *.SchLib *.PcbLib)")
        return f

    def _choose_files(self, path: str):
        """(schlib, pcblib) to use for what was picked, asking only when there are several; None if cancelled."""
        from PySide6.QtWidgets import QInputDialog

        from . import projects

        p = Path(path)
        if p.suffix.lower() == ".prjpcb":
            schs, pcbs = projects.libraries_in_prjpcb(p)
        else:
            schs, pcbs = projects.libraries_in(p.parent if p.is_file() else p)
            if p.suffix.lower() == ".schlib":
                schs = [p.name]
            if p.suffix.lower() == ".pcblib":
                pcbs = [p.name]
        out = []
        for kind, found in (("SchLib", schs), ("PcbLib", pcbs)):
            if len(found) <= 1:
                out.append(found[0] if found else "")
                continue
            names = [Path(f).name for f in found]
            name, ok = QInputDialog.getItem(self, "PartKit", f"There are several .{kind} files. "
                                            "Which one is this board's?", names, 0, False)
            if not ok:
                return None
            out.append(found[names.index(name)])
        return tuple(out)

    def change_project_folder(self):
        from . import projects

        proj = self._chosen_project()
        if not proj:
            return
        f = self._pick_altium_project(proj.prjpcb or proj.folder)
        if not f:
            return
        files = self._choose_files(f)
        if files is None:
            return
        try:
            projects.use_file(proj, f, *files)
        except ValueError as e:
            QMessageBox.information(self, "PartKit", str(e))
            return
        projects.save(self.lib, proj)
        self.refresh_library()
        self.show_kit()
        self.log(f"Project '{proj.name}' now uses {proj.schlib} and {proj.pcblib}.")

    def update_project_library(self, everything: bool = False):
        """Write the project's parts into its library now (Send does the new ones anyway)."""
        from . import projects

        proj = self._chosen_project()
        if not proj:
            return
        self.check_sync_result()
        proj = projects.get(self.lib, proj.name)
        job, waiting = projects.write_update_job(self.lib, proj, everything=everything)
        for w in waiting:
            self.log(w)
        if not job:
            QMessageBox.information(self, "PartKit", f"The library for '{proj.name}' already has every Ready part."
                                    + (f"\n\nNot sent yet:\n" + "\n".join(waiting) if waiting else ""))
            return
        started, msg = start_sync(copy_scripts())
        if started:
            self.log(msg)
        else:
            QMessageBox.information(self, "PartKit", msg)
        self.show_kit()

    def resend_project_library(self):
        self.update_project_library(everything=True)

    def add_to_project(self):
        from . import kits, projects

        mpns = self._need_selection()
        if not mpns:
            return
        names = [p.name for p in projects.projects(self.lib)]
        if not names:
            QMessageBox.information(self, "PartKit", "Make a project first, on the Projects tab.")
            return
        d = AddToProjectDialog(self, names, [k.name for k in kits.kits(self.lib)])
        if d.exec() != QDialog.Accepted:
            return
        also = d.template.currentText()
        proj = projects.add_parts(self.lib, d.project.currentText(), mpns,
                                  also_template="" if also.startswith("No") else also)
        self.refresh_kits()
        self.log(f"Added {len(mpns)} part(s) to project '{proj.name}'."
                 + (" Send to Altium writes them into its library." if proj.own_library else ""))

    # ----- Import
    def import_path(self, path: Path):
        try:
            if path.suffix.lower() in STEP_EXT:
                mpns = self.selected_mpns()
                if len(mpns) != 1:
                    self.log(f"{path.name}: select the part in the Library first, then drop the 3D model.")
                    return
                res = attach_step(self.lib, mpns[0], path)
            else:
                res = import_zip(self.lib, path)
            for m in res.messages:
                self.log(m)
        except ImportProblem as e:
            self.log(f"{path.name}: {e}")

    def choose_zip(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Choose CAD downloads", str(Path.home() / "Downloads"),
                                                "CAD downloads (*.zip *.IntLib *.step *.stp)")
        for f in files:
            self.import_path(Path(f))

    def reimport(self):
        f, _ = QFileDialog.getOpenFileName(self, "Re-import from Archive", str(self.lib.root / "Archive"),
                                           "CAD downloads (*.zip *.IntLib *.step *.stp)")
        if f:
            self.import_path(Path(f))

    def toggle_watch(self, on: bool):
        if on:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
            from .watcher import handle_file, wait_until_complete

            win = self

            class H(FileSystemEventHandler):
                def _go(self, p):
                    path = Path(p)
                    if path.suffix.lower() in DOWNLOAD_EXT and wait_until_complete(path):
                        handle_file(win.lib, path, win.bridge.message.emit)

                def on_created(self, e):
                    if not e.is_directory:
                        self._go(e.src_path)

                def on_moved(self, e):
                    if not e.is_directory:
                        self._go(e.dest_path)

            folder = Path(self.lib.settings.watch_folder)
            if not folder.is_dir():
                self.log(f"Downloads folder not found: {folder}. Set it in Settings.")
                self.watch_box.setChecked(False)
                return
            self.observer = Observer()
            self.observer.schedule(H(), str(folder), recursive=False)
            self.observer.start()
            self.log(f"Watching {folder} for CAD downloads.")
        elif self.observer:
            self.observer.stop()
            self.observer.join(2)
            self.observer = None
            self.log("Stopped watching Downloads.")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            self.import_path(Path(url.toLocalFile()))

    # ----- Problems (health check), opened from My parts
    def _health_window(self):
        self.health_dialog = QDialog(self)
        self.health_dialog.setWindowTitle("Problems in your library")
        lay = QVBoxLayout(self.health_dialog)
        self.health_summary = QLabel("Finds missing BOM fields, missing files and 3D models that need replacing.")
        lay.addWidget(self.health_summary)
        self.health_table = _table(["MPN", "Problem", "Fix"])
        lay.addWidget(self.health_table)
        row = QHBoxLayout()
        again = QPushButton("Check again")
        again.clicked.connect(self.run_check)
        self.remove_starter_btn = QPushButton("Remove old starter parts")
        self.remove_starter_btn.setToolTip("Older PartKit versions added 381 passives with footprints nobody "
                                           "checked. This takes them out (copies are kept).")
        self.remove_starter_btn.clicked.connect(self.remove_starter)
        row.addWidget(again)
        row.addWidget(self.remove_starter_btn)
        row.addStretch()
        lay.addLayout(row)
        self.health_dialog.resize(800, 450)

    def show_problems(self):
        self.run_check()
        self.health_dialog.show()

    def remove_starter(self):
        n = self.lib.remove_starter_parts()
        self.log(f"Removed {n} old starter parts (copies kept in partkit-data/history).")
        self.run_check()

    def run_check(self):
        issues = self.lib.health_check()
        _set_rows(self.health_table, [[i.mpn, i.problem, i.fix] for i in issues])
        self.health_summary.setText("No problems found." if not issues else f"{len(issues)} problems found.")

    # ----- Settings tab
    def _settings_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.test_box = QCheckBox("Test mode: use a separate throwaway library, never my real parts")
        self.test_box.toggled.connect(self.set_test_mode)
        form.addRow(self.test_box)
        self.watch_folder = QLineEdit()
        form.addRow("Downloads folder", self.watch_folder)
        self.hunting = QComboBox()
        self.hunting.addItems(list(HUNTING_MODES))
        form.addRow("Hunt beyond preferred providers", self.hunting)
        self.skip_review = QCheckBox("Skip 'To check' (parts are Ready straight away)")
        form.addRow(self.skip_review)
        from .config import ALL_SUPPLIERS

        self.buy_from = QComboBox()
        self.buy_from.addItems(ALL_SUPPLIERS)
        self.also_check = QComboBox()
        self.also_check.addItems(["None"] + ALL_SUPPLIERS)
        self.buy_from.currentTextChanged.connect(self._suppliers_changed)
        self.also_check.currentTextChanged.connect(self._suppliers_changed)
        form.addRow("I buy from", self.buy_from)
        form.addRow("Also compare with (optional)", self.also_check)
        self.providers = QListWidget()
        self.providers.setMaximumHeight(90)
        prov = QHBoxLayout()
        prov.addWidget(self.providers)
        updown = QVBoxLayout()
        up, down = QPushButton("Move up"), QPushButton("Move down")
        up.clicked.connect(self.provider_up)
        down.clicked.connect(self.provider_down)
        updown.addWidget(up)
        updown.addWidget(down)
        prov.addLayout(updown)
        form.addRow("CAD provider order (first is tried first)", prov)
        from . import credentials

        self.key_fields = {}
        self.key_rows = {}
        self.settings_form = form
        note = QLabel("JLCPCB and LCSC need no key. DigiKey, Mouser and Farnell need a free key, asked "
                      "for only when you choose them above, and optional even then.")
        note.setWordWrap(True)
        form.addRow("Supplier keys", note)
        for sup, needed in credentials.NEEDED.items():
            row = QHBoxLayout()
            self.key_rows[sup] = row
            for field in needed:
                le = QLineEdit()
                le.setEchoMode(QLineEdit.Password)
                le.setPlaceholderText(field.replace("_", " "))
                row.addWidget(le)
                self.key_fields[(sup, field)] = le
            link = QLabel(f'<a href="{credentials.SIGNUP[sup]}">Get a free key</a>')
            link.setOpenExternalLinks(True)
            row.addWidget(link)
            form.addRow(f"{sup} API key", row)
        keys_btn = QPushButton("Save API keys (stored in Windows Credential Manager)")
        keys_btn.clicked.connect(self.save_keys)
        form.addRow(keys_btn)
        self.dk_site = QLineEdit()
        self.dk_currency = QLineEdit()
        self.farnell_store = QLineEdit()
        region = QHBoxLayout()
        for lbl, le in (("DigiKey site", self.dk_site), ("currency", self.dk_currency),
                        ("Farnell store", self.farnell_store)):
            region.addWidget(QLabel(lbl))
            region.addWidget(le)
        form.addRow("Region", region)
        self.targets = QTableWidget(len(F.CATEGORIES), 3)
        self.targets.setHorizontalHeaderLabels(["Category", "Symbol library (.SchLib)", "Footprint library (.PcbLib)"])
        self.targets.verticalHeader().setVisible(False)
        self.targets.horizontalHeader().setStretchLastSection(True)
        form.addRow("Where each category goes", self.targets)
        save = QPushButton("Save settings")
        save.clicked.connect(self.save_settings)
        form.addRow(save)
        return w

    def load_settings(self):
        if not hasattr(self, "targets"):
            return
        s = self.lib.settings
        self.watch_folder.setText(s.watch_folder)
        self.hunting.setCurrentText(s.hunting)
        self.skip_review.setChecked(s.skip_review)
        self.buy_from.blockSignals(True)
        self.also_check.blockSignals(True)
        self.buy_from.setCurrentText(s.suppliers[0] if s.suppliers else "JLCPCB")
        self.also_check.setCurrentText(s.suppliers[1] if len(s.suppliers) > 1 else "None")
        self.buy_from.blockSignals(False)
        self.also_check.blockSignals(False)
        self.providers.clear()
        self.providers.addItems(s.providers)
        self.dk_site.setText(s.digikey_site)
        self.dk_currency.setText(s.digikey_currency)
        self.farnell_store.setText(s.farnell_store)
        from . import credentials

        self._show_key_rows(s.suppliers)
        for (sup, field), le in self.key_fields.items():
            le.clear()
            le.setPlaceholderText(("saved" if credentials.get(sup, field) else "not set") + f": {field.replace('_', ' ')}")
        for r, cat in enumerate(F.CATEGORIES):
            sch, pcb = s.target_libs(cat)
            item = QTableWidgetItem(cat)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.targets.setItem(r, 0, item)
            self.targets.setItem(r, 1, QTableWidgetItem(sch))
            self.targets.setItem(r, 2, QTableWidgetItem(pcb))
        self.targets.resizeColumnsToContents()

    def _move_provider(self, step: int):
        i = self.providers.currentRow()
        j = i + step
        if i < 0 or not 0 <= j < self.providers.count():
            return
        item = self.providers.takeItem(i)
        self.providers.insertItem(j, item)
        self.providers.setCurrentRow(j)

    def provider_up(self):
        self._move_provider(-1)

    def provider_down(self):
        self._move_provider(1)

    def _chosen_suppliers(self) -> list[str]:
        out = [self.buy_from.currentText()]
        second = self.also_check.currentText()
        if second != "None" and second not in out:
            out.append(second)
        return out

    def _show_key_rows(self, suppliers: list[str]):
        for sup, row in self.key_rows.items():
            self.settings_form.setRowVisible(row, sup in suppliers)

    def _suppliers_changed(self, *_):
        self._show_key_rows(self._chosen_suppliers())

    def save_settings(self):
        s = self.lib.settings
        s.watch_folder = self.watch_folder.text().strip()
        s.hunting = self.hunting.currentText()
        s.skip_review = self.skip_review.isChecked()
        s.suppliers = self._chosen_suppliers()
        s.providers = [self.providers.item(i).text() for i in range(self.providers.count())]
        s.digikey_site = self.dk_site.text().strip() or "US"
        s.digikey_currency = self.dk_currency.text().strip() or "USD"
        s.farnell_store = self.farnell_store.text().strip() or "uk.farnell.com"
        targets = {}
        for r, cat in enumerate(F.CATEGORIES):
            sch, pcb = self.targets.item(r, 1).text().strip(), self.targets.item(r, 2).text().strip()
            if (sch, pcb) != (f"Libraries/{cat}.SchLib", f"Libraries/{cat}.PcbLib"):
                targets[cat] = {"schlib": sch, "pcblib": pcb}
        s.targets = targets
        self.lib.save_settings()
        self.statusBar().showMessage("Settings saved.", 5000)

    def save_keys(self):
        from . import credentials

        saved = []
        try:
            for (sup, field), le in self.key_fields.items():
                if le.text().strip():
                    credentials.set(sup, field, le.text().strip())
                    saved.append(sup)
        except RuntimeError as e:
            QMessageBox.warning(self, "PartKit", str(e))
            return
        ready = [n for n in credentials.NEEDED if credentials.is_set_up(n)]
        self.load_settings()
        QMessageBox.information(self, "PartKit", "Ready to search: " + (", ".join(ready) or "none yet") + ".")

    # ----- Sync
    def sync(self):
        self.check_sync_result()
        job = self.lib.write_sync_job()
        if not job:
            QMessageBox.information(self, "PartKit", "Your Altium libraries are already up to date.")
            return
        started, msg = start_sync(copy_scripts())
        if started:
            self.log(msg)
        else:
            QMessageBox.information(self, "PartKit", msg)

    def check_sync_result(self):
        """Record PartKit Sync's result as soon as Altium writes it, so there's no second click."""
        if not self.lib.sync_result_waiting():
            return
        messages = self.lib.read_sync_result()
        for m in messages:
            self.log_box.append(m)
        failed = sum("failed" in m for m in messages)
        self.log(f"Altium finished: {len(messages) - failed} done" + (f", {failed} failed (see above)." if failed
                                                                       else "."))
        self.refresh_all()

    def closeEvent(self, e):
        if self.observer:
            self.observer.stop()
        super().closeEvent(e)


def library_root_from_env() -> Path:
    env = os.environ.get("PARTKIT_LIBRARY")
    return Path(env) if env else default_library_path()


def main(argv: list[str] | None = None) -> int:
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("PartKit")
    root = library_root_from_env()
    if not (root / "partkit-settings.toml").exists():
        dlg = SetupDialog(folder=root)
        if dlg.exec() != QDialog.Accepted:
            return 0
        lib = dlg.run_setup()
        root = lib.root
        QMessageBox.information(None, "PartKit", FIRST_STEPS)
    win = MainWindow(root)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
