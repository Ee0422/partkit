"""Watch the Downloads folder and import CAD downloads as they arrive."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .importer import ImportProblem, attach_step, guess_mpn_from_name, import_zip, looks_like_cad_download, DOWNLOAD_EXT, STEP_EXT
from .library import Library

PARTIAL_SUFFIXES = (".crdownload", ".part", ".tmp", ".download")


def wait_until_complete(path: Path, settle_s: float = 1.5, timeout_s: float = 120) -> bool:
    """Browsers write downloads in pieces; wait until the size stops changing."""
    deadline = time.monotonic() + timeout_s
    last = -1
    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False
        if size == last and size > 0:
            return True
        last = size
        time.sleep(settle_s)
    return False


def handle_file(lib: Library, path: Path, report: Callable[[str], None]) -> None:
    path = Path(path)
    if path.name.lower().endswith(PARTIAL_SUFFIXES) or not looks_like_cad_download(path):
        return
    try:
        if path.suffix.lower() in STEP_EXT:
            mpn = guess_mpn_from_name(path.name)
            if lib.get(mpn):
                for m in attach_step(lib, mpn, path).messages:
                    report(m)
            else:
                report(f"{path.name}: a 3D model with no matching part; drop it on a part to attach it.")
            return
        for m in import_zip(lib, path).messages:
            report(m)
    except ImportProblem as e:
        report(f"{path.name}: {e}")


def watch(lib: Library, folder: Path, report: Callable[[str], None] = print) -> None:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    seen: set[str] = set()

    class Handler(FileSystemEventHandler):
        def _consider(self, p: str) -> None:
            if p in seen:
                return
            path = Path(p)
            if path.suffix.lower() not in DOWNLOAD_EXT:
                return
            seen.add(p)
            if wait_until_complete(path):
                handle_file(lib, path, report)

        def on_created(self, event):
            if not event.is_directory:
                self._consider(event.src_path)

        def on_moved(self, event):  # browsers rename .crdownload -> .zip when done
            if not event.is_directory:
                self._consider(event.dest_path)

    obs = Observer()
    obs.schedule(Handler(), str(folder), recursive=False)
    obs.start()
    report(f"Watching {folder} for CAD downloads. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        obs.stop()
        obs.join()
