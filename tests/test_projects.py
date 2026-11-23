import pytest

from partkit import kits, projects
from partkit.library import Library, Part


def ready(lib, mpn, **kw):
    p = Part(mpn=mpn, category=kw.pop("category", "Resistors"), stage="Ready", source="SnapMagic", symbol=mpn,
             schlib=f"Review/{mpn}/{mpn}.SchLib", pcblib=f"Review/{mpn}/{mpn}.PcbLib", footprint="RESC1608X55N",
             **kw)
    lib.save(p)
    return p


def test_old_stage_names_still_load(lib):
    lib.save(Part(mpn="A", stage="Released"))
    lib.save(Part(mpn="B", stage="Review"))
    assert (lib.get("A").stage, lib.get("B").stage) == ("Ready", "To check")


def test_project_from_templates_then_add_only_the_330r(lib):
    for m in ("10K", "100NF", "330R"):
        ready(lib, m)
    kits.add_parts(lib, "Power input", ["10K", "100NF"])
    kits.add_parts(lib, "MCU basics", ["100NF"], qty=3)
    proj = projects.create(lib, "Motor driver", templates=["Power input", "MCU basics"], own_library=True)
    assert {it.mpn: it.qty for it in proj.items} == {"10K": 1, "100NF": 4}
    job, waiting = projects.write_update_job(lib, proj)
    text = job.read_text(encoding="utf-8-sig")
    assert text.count("[PART]") == 2 and f"DST_SCHLIB={proj.schlib}" in text and not waiting
    # PartKit Sync reports success
    (job.parent / "sync-result.txt").write_text("OK=10K\r\nOK=100NF\r\n", encoding="utf-8")
    lib.read_sync_result()
    proj = projects.get(lib, "Motor driver")
    assert sorted(proj.in_library) == ["100NF", "10K"]
    # later: only the 330R goes in, and the template is not changed
    projects.add_parts(lib, "Motor driver", ["330R"])
    job, _ = projects.write_update_job(lib, projects.get(lib, "Motor driver"))
    text = job.read_text(encoding="utf-8-sig")
    assert text.count("[PART]") == 1 and "MPN=330R" in text
    assert [it.mpn for it in kits.get(lib, "Power input").items] == ["10K", "100NF"]


def test_project_job_does_not_touch_main_library_state(lib):
    p = ready(lib, "10K")
    p.needs_sync = True
    lib.save(p)
    proj = projects.create(lib, "P", own_library=True)
    projects.add_parts(lib, "P", ["10K"], also_template="Basics")
    job, _ = projects.write_update_job(lib, projects.get(lib, "P"))
    (job.parent / "sync-result.txt").write_text("OK=10K\r\n", encoding="utf-8")
    lib.read_sync_result()
    assert lib.get("10K").needs_sync  # main library still waits for its own Send to Altium
    assert kits.get(lib, "Basics").items[0].mpn == "10K"
    assert lib.write_sync_job() is not None and "pending-kind" not in str(proj)


def test_parts_not_ready_wait_and_main_library_projects_need_no_update(lib):
    lib.save(Part(mpn="NEW", stage="To check"))
    proj = projects.create(lib, "Q", own_library=True)
    projects.add_parts(lib, "Q", ["NEW"])
    job, waiting = projects.write_update_job(lib, projects.get(lib, "Q"))
    assert job is None and "To check" in waiting[0]
    projects.create(lib, "Plain")
    with pytest.raises(ValueError, match="main library"):
        projects.write_update_job(lib, projects.get(lib, "Plain"))
    with pytest.raises(ValueError, match="already"):
        projects.create(lib, "plain")


def test_copy_of_project(lib):
    ready(lib, "10K")
    projects.create(lib, "A")
    projects.add_parts(lib, "A", ["10K"])
    b = projects.create(lib, "B", copy_of="A")
    assert [it.mpn for it in b.items] == ["10K"] and Library(lib.root).get("10K")


def test_project_uses_the_libraries_already_in_its_folder(lib, tmp_path):
    ready(lib, "10K")
    stm = tmp_path / "STM32 board"
    stm.mkdir()
    (stm / "STM32.SchLib").write_bytes(b"x")
    (stm / "STM32.PcbLib").write_bytes(b"x")
    proj = projects.create(lib, "STM32 board v2", folder=str(stm))
    assert proj.own_library and proj.schlib == str(stm / "STM32.SchLib") and proj.pcblib == str(stm / "STM32.PcbLib")
    projects.add_parts(lib, proj.name, ["10K"])
    job, _ = projects.write_update_job(lib, projects.get(lib, proj.name))
    text = job.read_text(encoding="utf-8-sig")
    assert f"DST_SCHLIB={stm / 'STM32.SchLib'}" in text and f"DST_PCBLIB={stm / 'STM32.PcbLib'}" in text


def test_empty_folder_gets_libraries_named_after_the_project(lib, tmp_path):
    proj = projects.create(lib, "Motor", folder=str(tmp_path))
    assert proj.schlib == str(tmp_path / "Motor.SchLib") and proj.pcblib == str(tmp_path / "Motor.PcbLib")


def test_folder_with_several_libraries_needs_a_choice(lib, tmp_path):
    for n in ("A.SchLib", "B.SchLib", "A.PcbLib"):
        (tmp_path / n).write_bytes(b"x")
    with pytest.raises(ValueError, match="2 .SchLib"):
        projects.create(lib, "X", folder=str(tmp_path))
    assert projects.get(lib, "X") is None
    proj = projects.create(lib, "X", folder=str(tmp_path), schlib="B.SchLib")
    assert proj.schlib.endswith("B.SchLib") and proj.pcblib.endswith("A.PcbLib")


def test_moving_a_project_library_sends_everything_again(lib, tmp_path):
    proj = projects.create(lib, "M", own_library=True)
    proj.in_library = ["10K"]
    projects.use_folder(proj, tmp_path)
    assert proj.in_library == [] and proj.schlib_file == ""


PRJPCB = """[Design]
Version=1.0

[Document1]
DocumentPath=Main.SchDoc

[Document2]
DocumentPath=Libs\\STM32.SchLib

[Document3]
DocumentPath=STM32.PcbLib
"""


def test_altium_project_file_gives_its_libraries(lib, tmp_path):
    prj = tmp_path / "Testing_Script.PrjPcb"
    prj.write_text(PRJPCB, encoding="utf-8")
    proj = projects.create(lib, "Board", folder=str(prj))
    assert proj.prjpcb == str(prj) and proj.own_library
    assert proj.schlib == str(tmp_path / "Libs" / "STM32.SchLib") and proj.pcblib == str(tmp_path / "STM32.PcbLib")


def test_altium_project_without_libraries_gets_new_ones_named_after_it(lib, tmp_path):
    prj = tmp_path / "Motor.PrjPcb"
    prj.write_text("[Document1]\nDocumentPath=Main.SchDoc\n", encoding="utf-8")
    proj = projects.create(lib, "M", folder=str(prj))
    assert proj.schlib == str(tmp_path / "Motor.SchLib") and proj.pcblib == str(tmp_path / "Motor.PcbLib")


def test_one_send_covers_main_library_and_project_libraries(lib, tmp_path):
    p = ready(lib, "10K")
    p.needs_sync = True
    lib.save(p)
    ready(lib, "330R")
    projects.create(lib, "Board", folder=str(tmp_path))
    projects.add_parts(lib, "Board", ["330R"])
    assert lib.send_count() == 2
    job = lib.write_sync_job()
    text = job.read_text(encoding="utf-8-sig")
    assert text.count("[PART]") == 2 and "FOR=main" in text and "FOR=project:Board" in text
    assert f"DST_SCHLIB={tmp_path / 'Board.SchLib'}" in text and "INSTALL=0" in text
    (job.parent / "sync-result.txt").write_text("FOR=main\r\nOK=10K\r\nFOR=project:Board\r\nOK=330R\r\n",
                                                 encoding="utf-8")
    msgs = lib.read_sync_result()
    assert not lib.get("10K").needs_sync and projects.get(lib, "Board").in_library == ["330R"]
    assert any("written into project Board" in m for m in msgs) and lib.send_count() == 0
    # a part changed after it was written: the project says so
    proj = projects.get(lib, "Board")
    assert projects.changed_since_written(lib, proj) == []
    proj.written_at["330R"] -= 10
    assert projects.changed_since_written(lib, proj) == ["330R"]


def test_delete_takes_part_out_everywhere_and_undo_brings_it_back(lib):
    ready(lib, "10K", params={"Value": "10k"})
    kits.add_parts(lib, "Basics", ["10K"])
    projects.create(lib, "P")
    projects.add_parts(lib, "P", ["10K"])
    lib.delete_part("10K", from_altium=True)
    assert lib.get("10K") is None and not kits.get(lib, "Basics").items and not projects.get(lib, "P").items
    job = lib.write_sync_job()
    text = job.read_text(encoding="utf-8-sig")
    assert "ACTION=REMOVE" in text and "FOR=remove" in text and "DST_SCHLIB=Libraries/Resistors.SchLib" in text
    (job.parent / "sync-result.txt").write_text("FOR=remove\r\nOK=10K\r\n", encoding="utf-8")
    lib.read_sync_result()
    assert lib.pending_removals() == []
    assert lib.undo("10K").mpn == "10K"


def test_undo_delete_cancels_the_removal(lib):
    ready(lib, "10K")
    lib.delete_part("10K", from_altium=True)
    assert len(lib.pending_removals()) == 1
    lib.undo("10K")
    assert lib.pending_removals() == [] and lib.get("10K") is not None
