# PartKit

**Find, import and manage Altium Designer parts without the hunting, unzipping and retyping.**

PartKit is a free, open-source Windows tool. It takes the CAD zips you download from
SnapMagic, SamacSys, Ultra Librarian or a manufacturer and files them into the
Altium libraries you choose, together with their 3D models. It also gives you a
ready-made library of common resistors and capacitors, and makes sure every
part carries the same BOM fields.

> **Status: early development (milestone 1 of 6).** The engine and command line
> work today. The desktop window, the installer and supplier search are coming
> in later milestones. The Altium script (PartKit Sync) has not yet been tested
> inside Altium. Please try it in Test mode and report what happens.

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

## Quick start (developer preview)

Requires Python 3.10+ on Windows. The installer comes in a later milestone and
won't need Python.

```powershell
pip install git+https://github.com/Ee0422/partkit
partkit --test init                    # test library with the starter pack
partkit --test import "$HOME\Downloads\LIB_TPS62130RGTR.zip" --category Power
partkit --test list --stage Review
partkit --test approve TPS62130RGTR
partkit --test sync                    # writes the job for Altium
```

Then, in Altium: **File > Run Script**, open `altium-scripts/PartKitSync.PrjScr`
and run `Run`. Back in PartKit, run `partkit --test sync` again to read the
result.

`partkit --test watch` imports every CAD zip as it lands in Downloads.

See [docs/setup-guide.md](docs/setup-guide.md) for the full guide.

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
| `sync` | Write the job for PartKit Sync in Altium and read its result |
| `set-target <category> <schlib> <pcblib>` | Choose the libraries a category goes into |
| `set-hunting off/ask/always` | Hunt beyond your preferred providers only when they can't find a part |
| `test-reset` | Reset the test library (with `--test`) |

## Roadmap

1. Library core and import (this release)
2. Desktop window, signed installer, automatic start of PartKit Sync
3. Supplier search (DigiKey, Mouser, Farnell), provider preferences, hunting
4. Passive picker and more starter packs
5. Library screen and full health check
6. Version 1.0

## Licence

MIT. The starter-pack symbols and footprints are PartKit's own and are free to
share. Models you download from SnapMagic, SamacSys or Ultra Librarian stay on
your PC under those sites' terms.
