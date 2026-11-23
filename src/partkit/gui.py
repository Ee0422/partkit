"""PartKit desktop window (PySide6).

Four screens over the same engine the command line uses:
Library, Import, Health check and Settings, plus a one-screen first-run setup.
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
from .importer import STEP_EXT, ImportProblem, attach_step, import_zip
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
    """Carries messages from the Downloads watcher thread to the window."""
    message = Signal(str)


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
        self.observer = None

        self.setWindowTitle(f"PartKit {__version__}")
        self.resize(1100, 700)
        self.tabs = QTabWidget()
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
            self.lib.approve(m)
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
        drop = QLabel("Drop CAD zips (SnapMagic, SamacSys, Ultra Librarian, manufacturer)\n"
                      "or .step files anywhere on this window")
        drop.setAlignment(Qt.AlignCenter)
        drop.setMinimumHeight(120)
        drop.setStyleSheet("border: 2px dashed #888; border-radius: 8px; font-size: 14px;")
        lay.addWidget(drop)
        row = QHBoxLayout()
        choose = QPushButton("Choose zip…")
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
                                                "CAD downloads (*.zip)")
        for f in files:
            self.import_path(Path(f))

    def reimport(self):
        f, _ = QFileDialog.getOpenFileName(self, "Re-import from Archive", str(self.lib.root / "Archive"),
                                           "CAD downloads (*.zip)")
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
                    if path.suffix.lower() in {".zip"} | STEP_EXT and wait_until_complete(path):
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
        targets = {}
        for r, cat in enumerate(F.CATEGORIES):
            sch, pcb = self.targets.item(r, 1).text().strip(), self.targets.item(r, 2).text().strip()
            if (sch, pcb) != (f"Libraries/{cat}.SchLib", f"Libraries/{cat}.PcbLib"):
                targets[cat] = {"schlib": sch, "pcblib": pcb}
        s.targets = targets
        self.lib.save_settings()
        self.statusBar().showMessage("Settings saved.", 5000)

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
