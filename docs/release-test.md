# Release test (before each version)

Install with **PartKit-Setup-<version>.exe** from the release page, the way a new user would.
Use your Altium Designer, with a test project open. Tick each line or note what went wrong.

1. **Install.** Run the installer (More info → Run anyway). PartKit opens on setup; press Start.
2. **Test mode.** Settings → Test mode on.
3. **Search.** `100nF` shows capacitors with filters; set 0603 / 50 V / X7R, *Remember as my usual*.
   `capacitor 0805` lists parts. `LM358DR` finds the part.
4. **Get CAD files.** Pick a part, Get CAD files, download the Altium files. The part appears in
   My parts by itself, with supplier part number. (If the number differs, PartKit asks.)
5. **No CAD files.** Pick another 0603 capacitor → *No CAD files? Use one of my footprints…*
   (after step 6, using the first part).
6. **Check.** My parts → Mark Ready.
7. **Send with Altium open.** Send to Altium (N). Altium runs PartKit Sync by itself; PartKit
   shows the result without a second click. The libraries are not added to your Altium project.
8. **Project library.** Projects → New project → *Altium project…* → your test .PrjPcb. The
   dialog shows the .SchLib/.PcbLib. Add a part with *Add to project…*, Send: it's in that library.
9. **Delete.** My parts → More → Delete…, tick *also remove from Altium*, Send: the symbol is gone.
   Undo last change brings the part back in PartKit.
10. **Uninstall.** Windows Settings → Apps → PartKit → Uninstall. Your library folder stays.
