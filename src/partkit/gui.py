"""PartKit desktop window (PySide6).

Five screens over the same engine the command line uses:
Find parts, Library, Import, Health check and Settings, plus a one-screen
first-run setup.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from . import __version__
from . import fields as F
from .altium_launch import copy_scripts, start_sync
from .config import HUNTING_MODES, default_library_path, remember_library_path
from .importer import DOWNLOAD_EXT, STEP_EXT, ImportProblem, attach_step, import_zip
from .library import Library
from .passives import install_starter_pack


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


def _set_rows(t: QTableWidget, rows: list[list[str]]) -> None:
    t.setSortingEnabled(False)
    t.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            t.setItem(r, c, QTableWidgetItem(str(v)))
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
        self.starter = QCheckBox("Add the starter pack (366 resistors, 15 capacitors in 0402/0603/0805)")
        self.starter.setChecked(True)
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
        lay.addWidget(self.starter)
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
        if self.starter.isChecked():
            install_starter_pack(lib)
        copy_scripts()
        return lib


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
        self.tabs.addTab(self._library_tab(), "Library")
        self.tabs.addTab(self._import_tab(), "Import")
        self.tabs.addTab(self._health_tab(), "Health check")
        self.tabs.addTab(self._settings_tab(), "Settings")

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
        self.setCentralWidget(central)
        self.setAcceptDrops(True)
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
        self.load_settings()

    def log(self, msg: str):
        self.log_box.append(msg)
        self.statusBar().showMessage(msg, 8000)
        self.refresh_library()

    # ----- Find parts tab
    def _search_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Manufacturer part number, e.g. CL10B104KB8NNNC")
        self.search_box.returnPressed.connect(self.run_search)
        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.run_search)
        row.addWidget(self.search_box)
        row.addWidget(self.search_btn)
        lay.addLayout(row)
        self.search_msg = QLabel("Searches your preferred suppliers in your order (Settings).")
        self.search_msg.setWordWrap(True)
        lay.addWidget(self.search_msg)
        self.results = _table(["Supplier", "Supplier PN", "MPN", "Manufacturer", "Stock", "Price @1",
                               "Status", "Description"])
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
        return w

    def run_search(self):
        mpn = self.search_box.text().strip()
        if not mpn:
            return
        self.search_btn.setEnabled(False)
        self.search_msg.setText(f"Searching for {mpn}…")
        settings = self.lib.settings
        import threading

        from .search import find

        def work():
            try:
                res = find(mpn, settings)
            except Exception as e:  # noqa: BLE001 - never let a search crash the window
                from .search import SearchResult

                res = SearchResult(mpn=mpn, messages=[f"Search failed: {e}"])
            self.bridge.searched.emit(res)

        threading.Thread(target=work, daemon=True).start()

    def show_results(self, res):
        self.search_btn.setEnabled(True)
        self.last_search = res
        self.offers = res.exact or res.offers
        rows = []
        for o in self.offers:
            price = o.unit_price(1)
            rows.append([o.supplier, o.supplier_pn, o.mpn, o.manufacturer,
                         "" if o.stock is None else f"{o.stock:,}",
                         "" if price is None else f"{price:g} {o.currency}".strip(), o.status, o.description])
        _set_rows(self.results, rows)
        msgs = list(res.messages)
        if self.offers:
            msgs.insert(0, f"Found {len(self.offers)} offer(s) for {res.mpn}.")
        self.search_msg.setText("\n".join(msgs) or f"No results for {res.mpn}.")
        self.cad_list, self.cad_index = [], -1
        self.next_btn.setEnabled(False)

    def _search_mpn(self) -> str:
        rows = sorted({i.row() for i in self.results.selectedIndexes()})
        if rows:
            return self.results.item(rows[0], 2).text()
        if self.offers:
            return self.offers[0].mpn
        return self.search_box.text().strip()

    def add_result(self):
        from .search import add_from_search

        res = getattr(self, "last_search", None)
        mpn = self._search_mpn()
        if not mpn:
            QMessageBox.information(self, "PartKit", "Type a manufacturer part number first.")
            return
        # without supplier keys the part is added with just its MPN; the CAD file fills in the rest
        offers = [o for o in res.best() if o.mpn == mpn] or res.best() if res and res.offers else []
        cat = self.add_cat.currentText()
        part = add_from_search(self.lib, mpn, offers, category=None if cat.startswith("Let") else cat)
        self.log(f"{part.mpn} added to Review as {part.category}. Click 'Get CAD files' next.")

    # bound methods, not lambdas: a lambda holding the window keeps it alive past Qt's shutdown
    def get_cad_first(self):
        self.get_cad(next_=False)

    def get_cad_next(self):
        self.get_cad(next_=True)

    def get_cad(self, next_: bool):
        from .providers import cad_sources, open_source

        mpn = self._search_mpn()
        if not mpn:
            QMessageBox.information(self, "PartKit", "Search for a part first.")
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

        rows = sorted({i.row() for i in self.results.selectedIndexes()})
        if rows and rows[0] < len(self.offers) and self.offers[rows[0]].url:
            webbrowser.open(self.offers[rows[0]].url)
            return
        name = self.lib.settings.suppliers[0] if self.lib.settings.suppliers else "DigiKey"
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
        filters.addWidget(self.search, 3)
        filters.addWidget(self.stage_filter, 1)
        filters.addWidget(self.cat_filter, 1)
        lay.addLayout(filters)

        self.parts_table = _table(["MPN", "Category", "Stage", "Value", "3D", "Footprint", "Goes into"])
        self.parts_table.doubleClicked.connect(self.show_details)
        lay.addWidget(self.parts_table)

        actions = QHBoxLayout()
        self.cat_choice = QComboBox()
        self.cat_choice.addItems(list(F.CATEGORIES))
        for text, fn in (("Approve", self.approve), ("Set category", self.set_category),
                         ("Attach 3D model…", self.attach_3d), ("Mark obsolete", self.obsolete),
                         ("Undo last change", self.undo), ("Details", self.show_details)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            if text == "Set category":
                actions.addWidget(self.cat_choice)
            actions.addWidget(b)
        actions.addStretch()
        lay.addLayout(actions)
        return w

    def refresh_library(self):
        if not hasattr(self, "parts_table"):
            return
        text = self.search.text().strip().lower()
        stage = self.stage_filter.currentText()
        cat = self.cat_filter.currentText()
        rows = []
        for p in self.lib.parts():
            if stage in F.STAGES and p.stage != stage:
                continue
            if cat in F.CATEGORIES and p.category != cat:
                continue
            hay = f"{p.mpn} {p.params.get('Value', '')} {p.footprint}".lower()
            if text and text not in hay:
                continue
            rows.append([p.mpn, p.category, p.stage, p.params.get("Value", ""), p.model_3d,
                         p.footprint, Path(p.target_schlib).stem])
        _set_rows(self.parts_table, rows)

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
                if QMessageBox.question(self, "PartKit", f"{m} is still in category Misc. Approve anyway?") \
                        != QMessageBox.Yes:
                    continue
            try:
                self.lib.approve(m)
            except KeyError as e:
                QMessageBox.warning(self, "PartKit", str(e.args[0]))
        self.refresh_library()

    def set_category(self):
        cat = self.cat_choice.currentText()
        for m in self._need_selection():
            p = self.lib.get(m)
            p.category = cat
            p.target_schlib, p.target_pcblib = self.lib.settings.target_libs(cat)
            self.lib.save(p)
        self.refresh_library()

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

    # ----- Import tab
    def _import_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        drop = QLabel("Drop CAD downloads (SnapMagic, SamacSys, Ultra Librarian, manufacturer):\n"
                      ".zip, .IntLib or .step files, anywhere on this window")
        drop.setAlignment(Qt.AlignCenter)
        drop.setMinimumHeight(120)
        drop.setStyleSheet("border: 2px dashed #888; border-radius: 8px; font-size: 14px;")
        lay.addWidget(drop)
        row = QHBoxLayout()
        choose = QPushButton("Choose file…")
        choose.clicked.connect(self.choose_zip)
        archive = QPushButton("Re-import from Archive…")
        archive.clicked.connect(self.reimport)
        self.watch_box = QCheckBox("Watch my Downloads folder and import CAD downloads automatically")
        self.watch_box.toggled.connect(self.toggle_watch)
        row.addWidget(choose)
        row.addWidget(archive)
        row.addWidget(self.watch_box)
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(QLabel("Messages"))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        lay.addWidget(self.log_box)
        return w

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

    # ----- Health tab
    def _health_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        b = QPushButton("Run health check")
        b.clicked.connect(self.run_check)
        self.health_summary = QLabel("Finds missing BOM fields, missing files and 3D models that need replacing.")
        row = QHBoxLayout()
        row.addWidget(b)
        row.addWidget(self.health_summary)
        row.addStretch()
        lay.addLayout(row)
        self.health_table = _table(["MPN", "Problem", "Fix"])
        lay.addWidget(self.health_table)
        return w

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
        self.skip_review = QCheckBox("Skip the Review stage (release parts straight away)")
        form.addRow(self.skip_review)
        self.suppliers = QListWidget()
        self.suppliers.setDragDropMode(QAbstractItemView.InternalMove)
        self.suppliers.setMaximumHeight(90)
        form.addRow("Supplier order (drag to reorder)", self.suppliers)
        self.providers = QListWidget()
        self.providers.setDragDropMode(QAbstractItemView.InternalMove)
        self.providers.setMaximumHeight(90)
        form.addRow("Model provider order (drag to reorder)", self.providers)
        from . import credentials

        self.key_fields = {}
        for sup, needed in credentials.NEEDED.items():
            row = QHBoxLayout()
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
        self.suppliers.clear()
        self.suppliers.addItems(s.suppliers)
        self.providers.clear()
        self.providers.addItems(s.providers)
        self.dk_site.setText(s.digikey_site)
        self.dk_currency.setText(s.digikey_currency)
        self.farnell_store.setText(s.farnell_store)
        from . import credentials

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

    def save_settings(self):
        s = self.lib.settings
        s.watch_folder = self.watch_folder.text().strip()
        s.hunting = self.hunting.currentText()
        s.skip_review = self.skip_review.isChecked()
        s.suppliers = [self.suppliers.item(i).text() for i in range(self.suppliers.count())]
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
        for m in self.lib.read_sync_result():
            self.log(m)
        job = self.lib.write_sync_job()
        if not job:
            QMessageBox.information(self, "PartKit", "Your Altium libraries are already up to date.")
            return
        started, msg = start_sync(copy_scripts())
        QMessageBox.information(self, "PartKit", msg + "\n\nWhen Altium says it has finished, "
                                "press Send to Altium again to record the result.")

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
        QMessageBox.information(None, "PartKit", "Your library is ready. Press 'Send to Altium' to write the "
                                "starter pack into Altium.")
    win = MainWindow(root)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
