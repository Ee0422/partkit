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
def init():
    """Create the library folder with good defaults."""
    root = library_root()
    Library.init(root)
    if not _state["test"]:
        remember_library_path(root)
    console.print(f"Library ready at [bold]{root}[/]")
    from .altium_launch import copy_scripts

    console.print(f"Altium script copied to {copy_scripts().parent}")
    console.print("Next: search for a part with [bold]partkit search[/], or open the PartKit window.")


@app.command("import")
def import_cmd(
    zip_path: Path = typer.Argument(..., exists=True, dir_okay=False),
    mpn: Optional[str] = typer.Option(None, help="Manufacturer part number, if the file name doesn't show it."),
    category: Optional[str] = typer.Option(None, help="One of: " + ", ".join(F.CATEGORIES)),
):
    """Import a CAD download (.zip or .IntLib from SnapMagic, SamacSys, Ultra Librarian, manufacturer) into To check."""
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
def list_cmd(stage: Optional[str] = typer.Option(None, help="'To check', Ready or Obsolete"),
             category: Optional[str] = None):
    """List parts in the library."""
    t = Table("MPN", "Category", "Stage", "Value", "3D", "Footprint")
    stage = F.OLD_STAGE_NAMES.get(stage, stage) if stage else stage
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
    """Mark a checked part Ready, so Send to Altium writes it into your libraries."""
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
    console.print(f"{p.mpn} is Ready for {p.target_schlib} and {p.target_pcblib}. Next: [bold]partkit sync[/]")


app.command("ready", help="Same as approve: mark a checked part Ready.")(approve)


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


def _rows_table(rows) -> Table:
    t = Table("MPN", "Value", "Size", "Tol.", "Rating", "Dielectric", "JLCPCB", "Stock", "Price @1",
              "Sold by", "Supplier PN")
    for r in rows:
        o = r.offer
        price = o.unit_price(1)
        t.add_row(r.mpn, r.value(), r.specs.get("Size", ""), r.specs.get("Tolerance", ""), r.rating(),
                  r.specs.get("Dielectric", ""), o.status if "JLCPCB" in r.sold_by else "",
                  "" if o.stock is None else f"{o.stock:,}", "" if price is None else f"{price:g}",
                  ", ".join(r.sold_by), o.supplier_pn)
    return t


@app.command("search")
def search_cmd(text: str = typer.Argument(..., help="A part number, or a value such as '1k 0603 1%'"),
               basic: bool = typer.Option(False, "--basic", help="Only JLCPCB Basic parts.")):
    """Look a part up at your suppliers, or find JLCPCB resistors and capacitors by value."""
    from .search import find_any, merge_rows

    lib = open_lib()
    res = find_any(text, lib.settings)
    for m in res.messages:
        console.print(f"[yellow]{m}[/]")
    rows = merge_rows(res.exact or res.offers, lib.settings.suppliers)
    if basic:
        rows = [r for r in rows if r.offer.status == "Basic"]
    if rows:
        console.print(_rows_table(rows[:30]))


@app.command()
def add(mpn: str, category: Optional[str] = typer.Option(None, help="Leave out to let PartKit guess.")):
    """Add a part from supplier search: fills Manufacturer, Description, Datasheet, supplier numbers and specs."""
    from .search import add_from_search, find

    lib = open_lib()
    _check_category(category)
    res = find(mpn, lib.settings)
    for m in res.messages:
        console.print(f"[yellow]{m}[/]")
    if not res.offers and not res.not_set_up:
        console.print(f"[red]{mpn} wasn't found at your suppliers, so nothing was added.[/]")
        raise typer.Exit(1)
    part = add_from_search(lib, mpn, res.best(), category=category)
    console.print(f"{part.mpn} added to To check as {part.category}. Next: [bold]partkit cad {part.mpn}[/]")


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


@app.command("new-value")
def new_value_cmd(
    source: str = typer.Argument(..., help="A checked (Ready) part to copy, e.g. your 10k 0603"),
    value: Optional[str] = typer.Option(None, "--value", help="New value for a resistor or capacitor, e.g. 4.7k"),
    mpn: Optional[str] = typer.Option(None, "--mpn", help="Or the new part number, for any other part"),
    pick: int = typer.Option(1, "--pick", help="Which search result to use (1 = the first, Basic first)"),
):
    """New part with the same checked symbol, footprint and 3D model. No download."""
    from . import reuse
    from .search import find, find_any, merge_rows, offers_for

    lib = open_lib()
    src = lib.get(source)
    try:
        reuse._check_source(src, source)
    except reuse.ReuseProblem as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(1)
    if value and reuse.can_search_by_value(src):
        res = find_any(reuse.value_query_text(src, value), lib.settings)
    elif mpn:
        res = find(mpn, lib.settings)
    else:
        console.print("[red]Give --value (resistors and capacitors) or --mpn.[/]")
        raise typer.Exit(1)
    for m in res.messages:
        console.print(f"[yellow]{m}[/]")
    rows = merge_rows(res.exact or res.offers, lib.settings.suppliers)
    if rows:
        console.print(_rows_table(rows[:10]))
    if not rows and not mpn:
        raise typer.Exit(1)
    row = rows[min(pick, len(rows)) - 1] if rows else None
    try:
        part = reuse.new_value(lib, source, mpn or "", offers_for(row, lib.settings.suppliers) if row else [])
    except reuse.ReuseProblem as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(1)
    console.print(f"{part.mpn} added to To check, copied from {source}. Next: [bold]partkit approve {part.mpn}[/]")


@app.command("new-from-footprint")
def new_from_footprint_cmd(
    source: str = typer.Argument(..., help="A checked part whose footprint the new part shares"),
    mpn: str = typer.Argument(..., help="The new part's manufacturer part number"),
    symbol_from: Optional[str] = typer.Option(None, "--symbol-from", help="Copy the symbol from this part"),
    category: Optional[str] = typer.Option(None, help="Leave out to keep the source part's category"),
):
    """New part on a checked footprint, e.g. an LDO nobody has CAD files for."""
    from . import reuse
    from .search import find

    lib = open_lib()
    _check_category(category)
    res = find(mpn, lib.settings)
    try:
        part = reuse.new_from_footprint(lib, source, mpn, res.best() if res.exact else [],
                                        symbol_from=symbol_from or "", category=category or "")
    except reuse.ReuseProblem as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(1)
    console.print(f"{part.mpn} added to To check on the footprint of {source}. " + part.notes[0])


@app.command()
def favourite(mpn: str, off: bool = typer.Option(False, "--off", help="Take the star off")):
    """Star a part you use often; favourites are listed first."""
    open_lib().set_favourite(mpn, not off)
    console.print(f"{mpn} {'is no longer a favourite' if off else 'is a favourite'}.")


kit_app = typer.Typer(help="Templates (kits): groups of parts you start projects from, e.g. 'USB-C power input'.")
app.add_typer(kit_app, name="template")
app.add_typer(kit_app, name="kit", hidden=True)  # the older name still works


@kit_app.command("list")
def kit_list():
    """Show your kits."""
    from . import kits

    for k in kits.kits(open_lib()):
        console.print(f"[bold]{k.name}[/]: {len(k.items)} parts")


@kit_app.command("add")
def kit_add(name: str, mpns: list[str], qty: int = typer.Option(1, help="How many per board")):
    """Add parts to a kit (made if it doesn't exist)."""
    from . import kits

    try:
        kit = kits.add_parts(open_lib(), name, mpns, qty)
    except KeyError as e:
        console.print(f"[red]{e.args[0]}[/]")
        raise typer.Exit(1)
    console.print(f"Kit '{kit.name}' now has {len(kit.items)} parts.")


@kit_app.command("remove")
def kit_remove(name: str, mpns: list[str]):
    """Take parts out of a kit."""
    from . import kits

    lib = open_lib()
    kit = kits.get(lib, name)
    if kit is None:
        console.print(f"[red]No kit called {name!r}[/]")
        raise typer.Exit(1)
    for m in mpns:
        kit.remove(m)
    kits.save(lib, kit)


@kit_app.command("delete")
def kit_delete(name: str):
    """Delete a kit. Its parts stay in your library."""
    from . import kits

    console.print("Deleted." if kits.delete(open_lib(), name) else f"[red]No kit called {name!r}[/]")


@kit_app.command("bom")
def kit_bom(names: list[str], out: Optional[Path] = typer.Option(None, "--out", help="Save as CSV (opens in Excel)")):
    """Parts list for a new project from one or more kits."""
    from . import kits

    lib = open_lib()
    try:
        lines = kits.project_bom(lib, names)
    except KeyError as e:
        console.print(f"[red]{e.args[0]}[/]")
        raise typer.Exit(1)
    t = Table("Qty", "MPN", "Value", "Description", "Supplier PN", "Note")
    for line in lines:
        p = line.part
        t.add_row(str(line.qty), line.mpn, p.params.get("Value", "") if p else "",
                  p.params.get("Description", "") if p else "",
                  p.params.get("Supplier Part Number 1", "") if p else "", line.warning)
    console.print(t)
    if out:
        kits.write_csv(lines, out)
        console.print(f"Saved to {out}")


project_app = typer.Typer(help="Projects: the parts one board uses, optionally with its own library.")
app.add_typer(project_app, name="project")


@project_app.command("new")
def project_new(name: str, template: list[str] = typer.Option([], "--template", help="Start from this template (repeat)"),
                copy_of: str = typer.Option("", "--copy-of", help="Start as a copy of another project"),
                own_library: bool = typer.Option(False, "--own-library", help="Give it its own .SchLib/.PcbLib")):
    """Make a project: empty, from templates, or as a copy of another project."""
    from . import projects

    try:
        p = projects.create(open_lib(), name, templates=template, copy_of=copy_of, own_library=own_library)
    except (ValueError, KeyError) as e:
        console.print(f"[red]{e.args[0]}[/]")
        raise typer.Exit(1)
    console.print(f"Project '{p.name}' made with {len(p.items)} parts."
                  + (f" Its library goes in {p.folder}" if p.own_library else ""))


@project_app.command("list")
def project_list():
    """Show your projects."""
    from . import projects

    for p in projects.projects(open_lib()):
        console.print(f"[bold]{p.name}[/]: {len(p.items)} parts" + (", own library" if p.own_library else ""))


@project_app.command("add")
def project_add(name: str, mpns: list[str], also_template: str = typer.Option("", "--also-template")):
    """Add parts to one project (and, if you like, a template too)."""
    from . import projects

    try:
        p = projects.add_parts(open_lib(), name, mpns, also_template=also_template)
    except KeyError as e:
        console.print(f"[red]{e.args[0]}[/]")
        raise typer.Exit(1)
    console.print(f"Project '{p.name}' now has {len(p.items)} parts.")


@project_app.command("show")
def project_show(name: str, out: Optional[Path] = typer.Option(None, "--out", help="Save the starting parts list as CSV")):
    """A project's parts, and whether each is in its own library yet."""
    from . import kits, projects

    lib = open_lib()
    p = projects.get(lib, name)
    if p is None:
        console.print(f"[red]No project called {name!r}[/]")
        raise typer.Exit(1)
    lines = projects.parts_list(lib, p)
    t = Table("Qty", "MPN", "Value", "In project library", "Note")
    for line in lines:
        t.add_row(str(line.qty), line.mpn, line.part.params.get("Value", "") if line.part else "",
                  ("yes" if line.mpn in p.in_library else "not yet") if p.own_library else "", line.warning)
    console.print(t)
    if out:
        kits.write_csv(lines, out)
        console.print(f"Saved to {out}")


@project_app.command("update")
def project_update(name: str, everything: bool = typer.Option(False, "--all", help="Send every part again"),
                   start: bool = typer.Option(True, help="Ask Altium to run PartKit Sync automatically.")):
    """Write the project's new parts (only those it doesn't have yet) into its own library."""
    from . import projects
    from .altium_launch import copy_scripts, start_sync

    lib = open_lib()
    for m in lib.read_sync_result():
        console.print(m)
    p = projects.get(lib, name)
    if p is None:
        console.print(f"[red]No project called {name!r}[/]")
        raise typer.Exit(1)
    try:
        job, waiting = projects.write_update_job(lib, p, everything=everything)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(1)
    for w in waiting:
        console.print(f"[yellow]{w}[/]")
    if not job:
        console.print("[green]The project library already has every Ready part.[/]")
        return
    if start:
        console.print(start_sync(copy_scripts())[1])
    console.print(f"When Altium has finished, run [bold]partkit project update \"{p.name}\"[/] again to record it.")


@app.command("remove-starter")
def remove_starter():
    """Take out the unchecked starter passives that older PartKit versions added."""
    n = open_lib().remove_starter_parts()
    console.print(f"Removed {n} starter parts (copies kept in partkit-data/history).")
    if n:
        console.print("In Altium you can also delete Libraries/Generic Passives.SchLib and .PcbLib "
                      "if no project uses them.")


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
