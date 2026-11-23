# PartKit

**Find, import and manage Altium Designer parts without the hunting, unzipping and retyping.**

PartKit is a free, open-source Windows tool. It takes the CAD zips you download from
SnapMagic, SamacSys, Ultra Librarian or a manufacturer and files them into the
Altium libraries you choose, together with their 3D models, and makes sure every
part carries the same BOM fields. You build one checked library that every
project uses.

> **Status: early development.** It has a desktop window, an installer build, and
> starts the Altium script for you. Importing SnapMagic downloads into Altium
> Designer 26 works. Supplier search (JLCPCB with no key) is being tested now.

## What it does

- **Imports any CAD download.** Zips and single-file .IntLib downloads (SnapMagic)
  both work. It finds the symbol, footprint and 3D model wherever
  they sit in the zip, including zips inside zips and mixed KiCad/Eagle/Altium
  bundles.
- **Gives every footprint a 3D model.** If the model is already inside the
  PcbLib, PartKit keeps it and saves a .step copy. If it comes as a separate
  .step file, PartKit Sync places it on the footprint. If there's no model at all,
  PartKit adds a simple 3D box so the 3D view and clearance checks still work.
- **Uses stages.** Parts go *To check* → *Ready* → *Obsolete*. Nothing reaches
  your libraries until you mark it Ready.
- **Writes into your own libraries.** You choose the .SchLib and .PcbLib for each
  category.
- **Tells variants apart.** Two 0603 100 nF capacitors at 16 V X5R and 50 V X7R
  are separate parts. Each category has the columns that tell its variants
  apart: voltage, dielectric, tolerance, height and so on.
- **Finds JLCPCB parts by value.** Type `1k 0603 1%` or `100nF 0603 50V X7R` and
  PartKit lists the matching JLCPCB parts, Basic first, one row per part with
  value, size, tolerance, rating, dielectric, stock and price. Show Basic only
  or Extended only, in stock only, one supplier, or narrow by typing. No API key is needed.
- **Reuses parts you've checked.** Check one 0603 resistor in Altium, then
  **New value from this part** makes 4.7k, 22k and so on with the same symbol,
  footprint and 3D model: type the value, pick a JLCPCB part, no download.
  **New part from this footprint** does the same for a part nobody has CAD
  files for, with the symbol copied from any part you choose.
- **Projects.** Each board gets a project with its own parts list, started empty,
  from templates (groups such as "USB-C power input") or as a copy of another
  project. Add more parts any time with *Add to project*. Choose a *project library
  folder* and the project gets its own library there: if the folder already has
  a .SchLib and .PcbLib (your board's existing library), PartKit adds to those,
  whatever they're called; if not, it makes new ones named after the project.
  *Update project library* writes only the parts the project's library doesn't
  have yet. The starting parts list saves as a CSV for Excel; the real BOM comes
  from Altium once the schematic is done.
- **Favourites.** Star the parts you use all the time; they're listed first.
- **Keeps the BOM clean.** Every part gets Manufacturer, Manufacturer Part
  Number, Description, Value, Supplier 1 and Supplier Part Number 1. Comment
  shows the value. A health check flags gaps before they reach a BOM.
- **Is safe to test.** `--test` uses a separate throwaway library. Every zip is
  kept in `Archive/`, so `partkit reimport` replays it without downloading
  again. `partkit undo` reverts a change.

## Install

**Installer (recommended):** download `PartKit-Setup-<version>.exe` from
[Releases](https://github.com/Ee0422/partkit/releases), run it, and click Next
and Finish. No admin rights or Python are needed. PartKit opens on a one-screen
setup: press **Start**.

**From source (Python 3.10+):**

```powershell
pip install "partkit[gui] @ git+https://github.com/Ee0422/partkit"
partkit gui          # the window
partkit --help       # the command line
```

## Using it

1. **Find.** On *Find parts*, type a manufacturer part number, or a resistor or
   capacitor value such as `1k 0603 1%`, and press Search. PartKit asks the
   supplier you buy from (*Settings > I buy from*, JLCPCB by default) and an
   optional second one. JLCPCB and LCSC need no key: they give the LCSC part number
   (C-number), stock and whether the part is Basic (no extra assembly fee) or
   Extended (about US$3 extra per part type). If a part number isn't in JLCPCB's
   list, PartKit says so: JLCPCB only lists parts it stocks. **Add to library** fills Manufacturer, Description,
   Datasheet, both supplier part numbers and the specs that tell same-size
   parts apart. **Get CAD files** opens your first preferred provider
   (SnapMagic, SamacSys, Ultra Librarian); download the Altium files there and
   PartKit imports them. If that provider doesn't have the part, click
   **Try next provider**. With hunting on, wider searches follow your list.
   **No API keys are needed.** Without them, Get CAD files still opens the
   part, and the CAD file fills in Manufacturer, MPN and Description. A
   supplier key is optional and adds supplier numbers, stock, price and
   specs. Mouser's is the quickest to get (one form, key by email); add it in
   *Settings*. Keys stay in Windows Credential Manager.
2. **Import.** Downloads import by themselves (*My parts > Import CAD downloads
   from my Downloads folder automatically*), or drop files anywhere on the window.
3. **Check.** On *My parts*, check the symbol and footprint, set the category and
   click **Mark Ready**.
4. **Send to Altium.** The button shows how many changes are waiting. If Altium is closed, PartKit
   opens it and runs PartKit Sync, which writes the parts into your libraries.
   If Altium is already open, PartKit doesn't start a second copy: run it there
   with File > Run Script > PartKitSync.PrjScr (it stays in that list after the
   first time).
5. **Problems.** *My parts* shows how many problems PartKit found (BOM gaps,
   missing files, simple 3D models); *Show problems* lists them.
6. **Reuse.** On *My parts*, select a Ready part and click **New value from this
   part** or **New part from this footprint**. Pick the supplier part yourself;
   PartKit warns if its package doesn't match the footprint.
7. **Projects.** On *Projects*, make a project, add parts from *My parts* with
   **Add to project**, and (optionally) choose its library folder, such as the
   folder of your Altium project that already has its .SchLib and .PcbLib.

Use **Settings > Test mode** (or `partkit --test`) to try things on a
throwaway library.

## Commands

| Command | What it does |
| --- | --- |
| `init` | Create the library folder |
| `keys <supplier>` | Save a DigiKey, Mouser or Farnell API key |
| `search <mpn or value> [--basic]` | Look a part up, or find JLCPCB parts by value (`"1k 0603 1%"`) |
| `add <mpn>` | Add a part from search, with supplier numbers and specs |
| `cad <mpn> [--next]` | Open your preferred CAD provider (or the next one) for a part |
| `import <file>` | Import a CAD zip or .IntLib (To check) |
| `reimport <name>` | Import a zip again from the Archive folder |
| `attach-3d <mpn> <step>` | Attach or replace a part's 3D model |
| `watch` | Auto-import CAD downloads from Downloads |
| `list`, `show <mpn>` | Browse parts and see the parameters Altium will get |
| `approve <mpn>` (or `ready`) | To check → Ready |
| `obsolete <mpn>` | Mark a part obsolete |
| `undo <mpn>` | Undo the last change to a part |
| `check` | Health check: BOM gaps, missing files, Simple or missing 3D models |
| `sync` | Send Ready parts to Altium (starts PartKit Sync) and read the last result |
| `scripts` | Copy the latest Altium script to Documents\PartKit Scripts |
| `gui` | Open the window |
| `set-target <category> <schlib> <pcblib>` | Choose the libraries a category goes into |
| `set-hunting off/ask/always` | Hunt beyond your preferred providers only when they can't find a part |
| `new-value <part> --value 4.7k` | New value with the same checked symbol, footprint and 3D (or `--mpn` for other parts) |
| `new-from-footprint <part> <mpn> [--symbol-from <part>]` | New part on a checked footprint |
| `favourite <mpn> [--off]` | Star a part |
| `project new <name> [--template T] [--folder F]` | Make a project; with `--folder`, it uses the libraries already in F (`--schlib`/`--pcblib` if several) |
| `project add <name> <mpn>...` | Add parts to one project |
| `project show <name> [--out file.csv]` | A project's parts and starting parts list |
| `project update <name> [--all]` | Write only the new parts into the project's own library |
| `template add/remove/list/delete/bom` | Manage templates (`kit` also works) |
| `remove-starter` | Take out the unchecked starter passives older versions added |
| `test-reset` | Reset the test library (with `--test`) |

## Roadmap

1. Library core and import
2. Desktop window, installer, automatic start of PartKit Sync (code signing to follow)
3. Supplier search (JLCPCB and LCSC with no key, DigiKey, Mouser, Farnell), value search, hunting
4. Reuse checked parts, favourites, templates
5. Simpler layout, projects with their own libraries (this release)
6. Import your existing Altium libraries
7. Version 1.0

## Licence

MIT. Models you download from SnapMagic, SamacSys or Ultra Librarian stay on
your PC under those sites' terms.
