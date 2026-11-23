"""`partkit` command line. The desktop window (next milestone) uses the same engine."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import fields as F
from .config import HUNTING_MODES, default_library_path, remember_library_path
from .importer import ImportProblem, attach_step, import_zip
from .library import Library
from .passives import install_starter_pack

app = typer.Typer(add_completion=False, help="PartKit: find, import and manage Altium parts.")
console = Console()

_state = {"library": None, "test": False}


def library_root() -> Path:
    if _state["library"]:
        return Path(_state["library"])
    env = os.environ.get("PARTKIT_LIBRARY")
    root = Path(env) if env else default_library_path()
    if _state["test"]:
        root = root.with_name(root.name + " (Test)")
    return root


def open_lib() -> Library:
    root = library_root()
    if not (root / "partkit-settings.toml").exists():
        console.print(f"[red]No PartKit library at {root}.[/] Run [bold]partkit init[/] first.")
        raise typer.Exit(1)
    return Library(root)


@app.callback()
def main(
    library: Optional[Path] = typer.Option(None, "--library", "-l", help="Library folder (default: Documents/PartKit Library)."),
    test: bool = typer.Option(False, "--test", help="Use the separate test library, never your real parts."),
):
    _state["library"] = library
    _state["test"] = test


@app.command()
def init(starter: bool = typer.Option(True, help="Add the starter-pack passives.")):
    """Create the library folder with good defaults."""
    root = library_root()
    lib = Library.init(root)
    if not _state["test"]:
        remember_library_path(root)
    console.print(f"Library ready at [bold]{root}[/]")
    if starter:
        added, skipped = install_starter_pack(lib)
        console.print(f"Starter pack: {added} passives added, {skipped} already there.")
    from .altium_launch import copy_scripts

    console.print(f"Altium script copied to {copy_scripts().parent}")
    console.print("Next: run [bold]partkit sync[/] to write the libraries into Altium.")


@app.command("import")
def import_cmd(
    zip_path: Path = typer.Argument(..., exists=True, dir_okay=False),
    mpn: Optional[str] = typer.Option(None, help="Manufacturer part number, if the file name doesn't show it."),
    category: Optional[str] = typer.Option(None, help="One of: " + ", ".join(F.CATEGORIES)),
):
    """Import a CAD download (.zip or .IntLib from SnapMagic, SamacSys, Ultra Librarian, manufacturer) into Review."""
    lib = open_lib()
    _check_category(category)
    try:
        res = import_zip(lib, zip_path, mpn=mpn, category=category)
    except ImportProblem as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(1)
    for m in res.messages:
        console.print(m)


@app.command()
def reimport(name: str = typer.Argument(..., help="Zip file name in the Archive folder")):
    """Import a zip again from the Archive folder, without downloading it again."""
    lib = open_lib()
    path = lib.root / "Archive" / name
    if not path.exists():
        console.print(f"[red]{name} is not in {lib.root / 'Archive'}[/]")
        raise typer.Exit(1)
    for m in import_zip(lib, path).messages:
        console.print(m)


@app.command("attach-3d")
def attach_3d(mpn: str, step: Path = typer.Argument(..., exists=True, dir_okay=False)):
    """Attach or replace a part's 3D model with a .step file."""
    for m in attach_step(open_lib(), mpn, step).messages:
        console.print(m)


@app.command()
def watch(folder: Optional[Path] = typer.Option(None, help="Folder to watch (default: your Downloads).")):
    """Import CAD downloads automatically as they arrive."""
    from .watcher import watch as run_watch

    lib = open_lib()
    run_watch(lib, folder or Path(lib.settings.watch_folder), report=console.print)


@app.command("list")
def list_cmd(stage: Optional[str] = typer.Option(None, help="Review, Released or Obsolete"),
             category: Optional[str] = None):
    """List parts in the library."""
    t = Table("MPN", "Category", "Stage", "Value", "3D", "Footprint")
    for p in open_lib().parts():
        if (stage and p.stage != stage) or (category and p.category != category):
            continue
        t.add_row(p.mpn, p.category, p.stage, p.params.get("Value", ""), p.model_3d, p.footprint)
    console.print(t)


@app.command()
def show(mpn: str):
    """Show every parameter of a part, as it will appear in Altium."""
    p = open_lib().get(mpn)
    if not p:
        console.print(f"[red]No part {mpn}[/]")
        raise typer.Exit(1)
    t = Table("Parameter", "Value")
    for k, v in p.bom_params().items():
        t.add_row(k, v)
    console.print(t)
    console.print(f"Symbol: {p.symbol} ({p.schlib}) -> {p.target_schlib}")
    console.print(f"Footprint: {p.footprint} ({p.pcblib}) -> {p.target_pcblib}")
    for n in p.notes:
        console.print(f"Note: {n}")


@app.command()
def approve(mpn: str, category: Optional[str] = typer.Option(None)):
    """Move a part from Review to Released, ready for PartKit Sync."""
    lib = open_lib()
    _check_category(category)
    if category:
        p = lib.get(mpn)
        if p:
            p.category = category
            p.target_schlib, p.target_pcblib = lib.settings.target_libs(category)
            lib.save(p)
    try:
        p = lib.approve(mpn)
    except KeyError as e:
        console.print(f"[red]{e.args[0]}[/]")
        raise typer.Exit(1)
    console.print(f"{p.mpn} released to {p.target_schlib} and {p.target_pcblib}. Run PartKit Sync in Altium.")


@app.command()
def obsolete(mpn: str, reason: str = ""):
    """Mark a part obsolete (kept for old designs, flagged in new ones)."""
    console.print(f"{open_lib().mark_obsolete(mpn, reason).mpn} marked Obsolete.")


@app.command()
def undo(mpn: str):
    """Undo the last change to a part."""
    p = open_lib().undo(mpn)
    console.print(f"{mpn} restored." if p else f"[yellow]Nothing to undo for {mpn}.[/]")


@app.command()
def check():
    """Health check: missing BOM fields, missing files, 3D models that need replacing."""
    issues = open_lib().health_check()
    if not issues:
        console.print("[green]No problems found.[/]")
        return
    t = Table("MPN", "Problem", "Fix")
    for i in issues:
        t.add_row(i.mpn, i.problem, i.fix)
    console.print(t)


@app.command()
def sync(start: bool = typer.Option(True, help="Ask Altium to run PartKit Sync automatically.")):
    """Send approved parts to Altium (runs PartKit Sync), and read back the last result."""
    from .altium_launch import copy_scripts, start_sync

    lib = open_lib()
    for m in lib.read_sync_result():
        console.print(m)
    path = lib.write_sync_job()
    if not path:
        console.print("[green]Altium libraries are up to date.[/]")
        return
    console.print(f"Sync job written: {path}")
    prjscr = copy_scripts()
    if start:
        started, msg = start_sync(prjscr)
        console.print(msg)
    else:
        console.print(f"In Altium: File > Run Script > Browse, choose {prjscr}, then pick Run.")
    console.print("When Altium has finished, run [bold]partkit sync[/] again to record the result.")


@app.command()
def scripts():
    """Copy the latest Altium script to Documents/PartKit Scripts and show where it is."""
    from .altium_launch import copy_scripts

    console.print(f"PartKit Sync script: {copy_scripts()}")


@app.command()
def gui():
    """Open the PartKit window."""
    try:
        from .gui import main as gui_main
    except ImportError:
        console.print("[red]The window needs PySide6:[/] pip install \"partkit[gui] @ git+https://github.com/Ee0422/partkit\"")
        raise typer.Exit(1)
    if library_root() != default_library_path() or _state["test"]:
        os.environ["PARTKIT_LIBRARY"] = str(library_root())
    raise typer.Exit(gui_main([]))


# ---------------------------------------------------------------- finding parts

@app.command()
def keys(supplier: str = typer.Argument(..., help="DigiKey, Mouser or Farnell")):
    """Save a supplier's free API key in Windows Credential Manager."""
    from . import credentials

    name = next((n for n in credentials.NEEDED if n.lower() == supplier.lower()), None)
    if not name:
        console.print(f"[red]Use one of: {', '.join(credentials.NEEDED)}[/]")
        raise typer.Exit(1)
    console.print(f"Get a free key at {credentials.SIGNUP[name]}")
    for field in credentials.NEEDED[name]:
        value = typer.prompt(f"{name} {field.replace('_', ' ')}", hide_input=True, default="", show_default=False)
        credentials.set(name, field, value.strip())
    console.print(f"{name} is {'set up' if credentials.is_set_up(name) else 'not set up'}.")


def _offers_table(offers) -> Table:
    t = Table("Supplier", "Supplier PN", "MPN", "Manufacturer", "Stock", "Price @1", "Description")
    for o in offers:
        price = o.unit_price(1)
        t.add_row(o.supplier, o.supplier_pn, o.mpn, o.manufacturer,
                  "" if o.stock is None else f"{o.stock:,}",
                  "" if price is None else f"{price:g} {o.currency}".strip(), o.description)
    return t


@app.command("search")
def search_cmd(mpn: str):
    """Look a part up at your preferred suppliers."""
    from .search import find

    res = find(mpn, open_lib().settings)
    for m in res.messages:
        console.print(f"[yellow]{m}[/]")
    if res.offers:
        console.print(_offers_table(res.exact or res.offers))


@app.command()
def add(mpn: str, category: Optional[str] = typer.Option(None, help="Leave out to let PartKit guess.")):
    """Add a part from supplier search: fills Manufacturer, Description, Datasheet, supplier numbers and specs."""
    from .search import add_from_search, find

    lib = open_lib()
    _check_category(category)
    res = find(mpn, lib.settings)
    for m in res.messages:
        console.print(f"[yellow]{m}[/]")
    if not res.offers:
        console.print(f"[red]{mpn} wasn't found, so nothing was added.[/]")
        raise typer.Exit(1)
    part = add_from_search(lib, mpn, res.best(), category=category)
    console.print(f"{part.mpn} added to Review as {part.category}. Next: [bold]partkit cad {part.mpn}[/]")


@app.command()
def cad(mpn: str, next_: bool = typer.Option(False, "--next", help="Try the next provider in your order.")):
    """Open your preferred CAD provider for a part; the Downloads watcher imports what you download."""
    from .providers import cad_sources, open_source

    lib = open_lib()
    part = lib.get(mpn)
    srcs = cad_sources(mpn, lib.settings)
    if not srcs:
        console.print("[red]No CAD providers in your settings.[/]")
        raise typer.Exit(1)
    state = lib.root / "partkit-data" / "cad-next.txt"
    idx = 0
    if next_ and state.exists():
        name, _, n = state.read_text(encoding="utf-8").partition("|")
        idx = int(n) + 1 if name == mpn and n.isdigit() else 0
    if idx >= len(srcs):
        console.print("No more providers to try. Turn hunting on (partkit set-hunting ask) to search wider.")
        raise typer.Exit(1)
    state.write_text(f"{mpn}|{idx}", encoding="utf-8")
    src = srcs[idx]
    open_source(src)
    console.print(f"Opened {src.name}{' (hunting)' if src.hunting else ''}: {src.url}")
    console.print("Download the Altium files there. With [bold]partkit watch[/] running, they import by themselves.")
    if part is None:
        console.print(f"Tip: run [bold]partkit add {mpn}[/] first so supplier details are filled in too.")


@app.command("set-target")
def set_target(category: str, schlib: str, pcblib: str):
    """Choose which .SchLib and .PcbLib a category goes into."""
    _check_category(category)
    lib = open_lib()
    lib.settings.targets[category] = {"schlib": schlib, "pcblib": pcblib}
    lib.save_settings()
    console.print(f"{category} parts will go into {schlib} and {pcblib}.")


@app.command("set-hunting")
def set_hunting(mode: str = typer.Argument(..., help="off, ask or always")):
    """Hunt beyond your preferred providers only when they can't find a part."""
    if mode not in HUNTING_MODES:
        console.print(f"[red]Use one of: {', '.join(HUNTING_MODES)}[/]")
        raise typer.Exit(1)
    lib = open_lib()
    lib.settings.hunting = mode
    lib.save_settings()
    console.print(f"Hunting set to {mode}.")


@app.command("test-reset")
def test_reset():
    """Delete and recreate the test library (only works with --test)."""
    if not _state["test"]:
        console.print("[red]test-reset only works together with --test.[/]")
        raise typer.Exit(1)
    root = library_root()
    if root.exists():
        shutil.rmtree(root)
    Library.init(root)
    console.print(f"Test library reset at {root}")


def _check_category(category: Optional[str]) -> None:
    if category and category not in F.CATEGORIES:
        console.print(f"[red]Unknown category {category!r}. Use one of: {', '.join(F.CATEGORIES)}[/]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
