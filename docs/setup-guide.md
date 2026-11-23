# PartKit setup and test guide (milestone 1)

This guide is for the developer preview. A one-click installer replaces steps 1
and 2 in a later milestone.

## 1. Install

1. Install Python 3.10 or newer from python.org and tick "Add python.exe to PATH".
2. Open PowerShell and run:

   ```powershell
   pip install git+https://github.com/Ee0422/partkit
   ```

## 2. Create a test library

```powershell
partkit --test init
```

This creates `Documents\PartKit Library (Test)` with the starter pack: 366
resistors and 15 capacitors in 0402, 0603 and 0805. Your real library is never
touched while you use `--test`.

## 3. Import a part

1. On SnapMagic, SamacSys or a manufacturer site, download any part in
   **Altium** format.
2. Run:

   ```powershell
   partkit --test import "$HOME\Downloads\<file>.zip" --category ICs
   partkit --test show <MPN>
   ```

   The messages say which of the three 3D cases the download was: model inside
   the footprint, separate .step file, or none (simple box).
3. Approve it:

   ```powershell
   partkit --test approve <MPN>
   partkit --test sync
   ```

## 4. Run PartKit Sync in Altium

1. In Altium: **File > Run Script > Browse**, choose
   `altium-scripts\PartKitSync.PrjScr` from the PartKit folder, pick `Run`.
2. If it asks for a job file, choose
   `Documents\PartKit Library (Test)\partkit-data\sync\pending-sync.txt`.
3. When it finishes, run `partkit --test sync` again to read the result.

**What to check in Altium:**

- [ ] `Libraries\Generic Passives.SchLib` has components like `C 100nF 50V X7R 10% 0603`.
- [ ] `Libraries\Generic Passives.PcbLib` has `RESC1608X55N`, `CAPC2012X140N` and the others, with pads and a 3D body.
- [ ] Your imported part is in `Libraries\<Category>.SchLib` and `.PcbLib`, and its 3D model shows in 3D view (press 3).
- [ ] Each symbol has the parameters Manufacturer, Manufacturer Part Number, Supplier 1 and so on.
- [ ] The libraries show in the Components panel.
- [ ] Place a few parts on a test schematic and make a BOM (Reports > Bill of Materials). The Manufacturer and MPN columns are filled, and the 16 V and 50 V 100 nF capacitors are separate lines.

If anything fails, copy the error message and the last lines of
`partkit-data\sync\sync-result.txt` into the project thread or a GitHub issue.

## 5. Test without downloading again

- `partkit --test reimport <zip name>` imports a zip from `Archive\` again.
- `partkit --test test-reset` gives you a clean test library.

## Notes

- Starter-pack MPNs follow YAGEO's and Samsung's published part-number schemes.
  They will be checked against DigiKey once supplier search arrives
  (milestone 3). Until then, `partkit check` lists them as missing a supplier
  part number.
- The generic land patterns use IPC-7351B nominal values. Check them against
  your board house's rules before a production run.
