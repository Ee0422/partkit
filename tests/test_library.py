import pytest

from partkit.config import Settings, load_settings, save_settings
from partkit.library import Part


def test_settings_roundtrip(tmp_path):
    s = Settings(hunting="ask", skip_review=True, targets={"ICs": {"schlib": "My ICs.SchLib", "pcblib": "My ICs.PcbLib"}})
    save_settings(tmp_path, s)
    back = load_settings(tmp_path)
    assert back.hunting == "ask" and back.skip_review
    assert back.target_libs("ICs") == ("My ICs.SchLib", "My ICs.PcbLib")
    assert back.target_libs("Diodes") == ("Libraries/Diodes.SchLib", "Libraries/Diodes.PcbLib")


def test_stages_sync_job_and_result(lib):
    lib.save(Part(mpn="LM358DR", category="ICs", symbol="LM358", footprint="SOIC8",
                  params={"Manufacturer": "TI", "Value": "LM358"}))
    assert lib.write_sync_job() is None  # Review parts are not synced
    lib.approve("LM358DR")
    job = lib.write_sync_job().read_text(encoding="utf-8-sig")
    assert "MPN=LM358DR" in job and "STAGE=Released" in job
    assert "PARAM=Manufacturer|TI" in job and "PARAM=Manufacturer Part Number|LM358DR" in job
    assert "PARAM=PartKit Status|Released" in job
    assert "DESIGNATOR=U?" in job  # vendor designators like "RC0603FR-071KL" are replaced
    (lib.root / "partkit-data/sync/sync-result.txt").write_text("OK=LM358DR\r\n", encoding="utf-8")
    assert lib.read_sync_result() == ["LM358DR: synced"]
    assert lib.write_sync_job() is None


def test_bom_fields_always_present_and_health_check(lib):
    p = Part(mpn="X1", symbol="X", footprint="Y")
    bp = p.bom_params()
    for f in ("Manufacturer", "Manufacturer Part Number", "Supplier 1", "Supplier Part Number 1"):
        assert f in bp
    assert bp["Manufacturer Part Number"] == "X1"
    lib.save(p)
    problems = [i.problem for i in lib.health_check()]
    assert any(pr.startswith("Missing BOM fields") for pr in problems)


def test_undo_restores_previous_version(lib):
    lib.save(Part(mpn="U1", params={"Value": "old"}))
    p = lib.get("U1"); p.params["Value"] = "new"; lib.save(p)
    assert lib.undo("U1").params["Value"] == "old"


def test_safe_names_for_odd_mpns(lib):
    lib.save(Part(mpn="LM317/T"))
    assert lib.get("LM317/T").mpn == "LM317/T"


def test_no_partkit_drawn_footprints_and_old_starter_parts_can_go(lib):
    old = Part(mpn="RC0603FR-0710KL", category="Resistors", source="PartKit", stage="Released", needs_sync=True)
    lib.save(old)
    lib.save(Part(mpn="LM358DR", category="ICs", source="SnapMagic", symbol="LM358", footprint="SOIC8",
                  stage="Released", needs_sync=True))
    job = lib.write_sync_job().read_text(encoding="utf-8-sig")
    assert "[FOOTPRINT]" not in job and "GENERIC=1" not in job
    assert any("starter" in i.problem for i in lib.health_check())
    with pytest.raises(KeyError, match="never checked"):
        lib.approve(old.mpn)
    assert lib.remove_starter_parts() == 1
    assert lib.get(old.mpn) is None and lib.get("LM358DR")


def test_imported_passive_without_specs_is_named_by_mpn():
    from partkit import fields as F

    assert F.display_name({"Manufacturer Part Number": "RC0603FR-071KL"}, "Resistors") == ""
    assert F.display_name({"Resistance": "1k", "Size": "0603"}, "Resistors") == "R 1k 0603"
