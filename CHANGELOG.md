# What's in PartKit

## 1.0.0

The first full release. Everything here works without any API key.

**Find parts**
- One search box: a part number, or a value such as `1k 0603 1%` or `100nF 0603 50V X7R`.
- `capacitor 0805` or `resistor 0603 1%` (no value) lists JLCPCB parts of that kind.
- JLCPCB parts with Basic first (no extra assembly fee), one row per part, with value, size,
  tolerance, rating, dielectric, stock and price.
- Filters that fit the part (size, voltage, dielectric, tolerance, power), and
  *Remember as my usual*.
- *Get CAD files* opens SnapMagic, SamacSys or Ultra Librarian. The download is imported
  by itself and joined with the supplier part you picked. If its number differs, PartKit asks.
- *No CAD files? Use one of my footprints…* makes the part on a footprint you've checked.

**My parts**
- Imports .zip and .IntLib downloads, with their 3D models (or a simple 3D box).
- Stages: To check, Ready, Obsolete. Nothing reaches Altium until you mark it Ready.
- Clean BOM fields on every part (Manufacturer, MPN, Description, Value, Supplier 1,
  Supplier Part Number 1) and a list of problems to fix.
- *New value from this part* and *New part from this footprint* reuse a checked symbol,
  footprint and 3D model. No download needed.
- Favourites, Delete (with undo), Undo last change.

**Projects**
- A parts list per board, started empty, from templates, or as a copy.
- An optional own library: pick the board's Altium project (.PrjPcb) or folder, and PartKit
  shows exactly which .SchLib/.PcbLib the parts go into.
- Tells you when a part changed after it was written into the project's library.

**Send to Altium**
- One button sends everything: new and changed parts, deletions, and new project-library parts.
- Runs PartKit Sync in your open Altium (or opens Altium first). The result shows in PartKit
  by itself.
- Libraries PartKit creates are kept out of your Altium project.

**Known limits**
- The installer isn't code-signed yet (Windows shows a warning on first start).
- PartKit Sync has been tested with Altium Designer 26.
- Importing your existing Altium libraries comes later.
