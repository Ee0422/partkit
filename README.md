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
- **Uses stages.** Parts go Review → Released → Obsolete. Nothing reaches your
  libraries until you approve it.
- **Writes into your own libraries.** You choose the .SchLib and .PcbLib for each
  category.
- **Tells variants apart.** Two 0603 100 nF capacitors at 16 V X5R and 50 V X7R
  are separate parts. Each category has the columns that tell its variants
  apart: voltage, dielectric, tolerance, height and so on.
- **Finds JLCPCB parts by value.** Type `1k 0603 1%` or `100nF 0603 50V X7R` and
  PartKit lists the matching JLCPCB parts, Basic first, one row per part with
  value, size, tolerance, rating, dielectric, stock and price. Show Basic only
  or Extended only, in stock only, one supplier, or narrow by typing. No API key is needed.
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
2. **Import.** Drop CAD zips or .IntLib files on the window, or tick *Watch my Downloads folder*.
3. **Review.** On the Library tab, check the part, set its category and click
   **Approve**.
4. **Send to Altium.** Click **Send to Altium**. If Altium is closed, PartKit
   opens it and runs PartKit Sync, which writes the parts into your libraries.
   If Altium is already open, PartKit doesn't start a second copy: run it there
   with File > Run Script > PartKitSync.PrjScr (it stays in that list after the
   first time).
5. **Check.** The Health check tab lists BOM gaps and missing or simple 3D models.

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
| `import <file>` | Import a CAD zip or .IntLib into Review |
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
| `remove-starter` | Take out the unchecked starter passives older versions added |
| `test-reset` | Reset the test library (with `--test`) |

## Roadmap

1. Library core and import
2. Desktop window, installer, automatic start of PartKit Sync (code signing to follow)
3. Supplier search (JLCPCB and LCSC with no key, DigiKey, Mouser, Farnell), value search, hunting (this release)
4. Reuse checked parts: "New value from this part" and "New part from this footprint"
5. Favourites and kits, with a starting parts list per project
6. Import your existing Altium libraries
7. Version 1.0

## Licence

MIT. Models you download from SnapMagic, SamacSys or Ultra Librarian stay on
your PC under those sites' terms.
