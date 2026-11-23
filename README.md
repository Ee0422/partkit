# PartKit

**Find, import and manage Altium Designer parts without the hunting, unzipping and retyping.**

PartKit is a free, open-source Windows tool. It takes the CAD zips you download from
SnapMagic, SamacSys, Ultra Librarian or a manufacturer and files them into the
Altium libraries you choose, together with their 3D models. It also gives you a
ready-made library of common resistors and capacitors, and makes sure every
part carries the same BOM fields.

> **Status: early development (milestone 2 of 6).** It has a desktop window, an
> installer build, and starts the Altium script for you. PartKit Sync has synced the
> 381-part starter pack in Altium Designer 26. Importing vendor zips into Altium is
> being tested now. Supplier search comes in milestone 3.

## What it does

- **Imports any CAD zip.** It finds the symbol, footprint and 3D model wherever
  they sit in the zip, including zips inside zips and mixed KiCad/Eagle/Altium
  bundles.
- **Gives every footprint a 3D model.** If the model is already inside the
  PcbLib, PartKit keeps it and saves a .step copy. If it comes as a separate
  .step file, PartKit Sync places it on the footprint. If there's no model at all,
  PartKit adds a simple 3D box so the 3D view and clearance checks still work.
- **Uses stages.** Parts go Review → Released → Obsolete. Nothing reaches your
  libraries until you approve it.
- **Writes into your own libraries.** You choose the .SchLib and .PcbLib for each
  category.
- **Tells variants apart.** Two 0603 100 nF capacitors at 16 V X5R and 50 V X7R
  are separate parts. Each category has the columns that tell its variants
  apart: voltage, dielectric, tolerance, height and so on.
- **Includes a starter pack.** It has 366 resistors (E24 1% plus 0 Ω jumpers) and
  15 common capacitors in 0402, 0603 and 0805. Shared footprints are named to
  IPC-7351B, with height classes. No API key is needed.
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

1. **Import.** Drop CAD zips on the window, or tick *Watch my Downloads folder*.
2. **Review.** On the Library tab, check the part, set its category and click
   **Approve**.
3. **Send to Altium.** Click **Send to Altium**. PartKit starts PartKit Sync in
   Altium, which writes the parts into your libraries. If Altium can't be
   started automatically, PartKit tells you the one menu click to make instead.
4. **Check.** The Health check tab lists BOM gaps and missing or simple 3D models.

Use **Settings > Test mode** (or `partkit --test`) to try things on a
throwaway library.

## Commands

| Command | What it does |
| --- | --- |
| `init` | Create the library folder (and the starter pack) |
| `import <zip>` | Import a CAD zip into Review |
| `reimport <name>` | Import a zip again from the Archive folder |
| `attach-3d <mpn> <step>` | Attach or replace a part's 3D model |
| `watch` | Auto-import CAD downloads from Downloads |
| `list`, `show <mpn>` | Browse parts and see the parameters Altium will get |
| `approve <mpn>` | Review → Released |
| `obsolete <mpn>` | Mark a part obsolete |
| `undo <mpn>` | Undo the last change to a part |
| `check` | Health check: BOM gaps, missing files, Simple or missing 3D models |
| `sync` | Send approved parts to Altium (starts PartKit Sync) and read the last result |
| `scripts` | Copy the latest Altium script to Documents\PartKit Scripts |
| `gui` | Open the window |
| `set-target <category> <schlib> <pcblib>` | Choose the libraries a category goes into |
| `set-hunting off/ask/always` | Hunt beyond your preferred providers only when they can't find a part |
| `test-reset` | Reset the test library (with `--test`) |

## Roadmap

1. Library core and import
2. Desktop window, installer, automatic start of PartKit Sync (this release; code signing to follow)
3. Supplier search (DigiKey, Mouser, Farnell), provider preferences, hunting
4. Passive picker and more starter packs
5. Library screen and full health check
6. Version 1.0

## Licence

MIT. The starter-pack symbols and footprints are PartKit's own and are free to
share. Models you download from SnapMagic, SamacSys or Ultra Librarian stay on
your PC under those sites' terms.
