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
