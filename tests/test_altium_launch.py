from pathlib import Path

from partkit import altium_launch as A


def test_copy_scripts_and_current(tmp_path):
    prjscr = A.copy_scripts(tmp_path / "scripts")
    assert prjscr.name == "PartKitSync.PrjScr" and prjscr.exists()
    assert "procedure Run" in (prjscr.parent / "PartKitSync.pas").read_text()
    assert A.scripts_are_current(tmp_path / "scripts")
    (prjscr.parent / "PartKitSync.pas").write_text("old")
    assert not A.scripts_are_current(tmp_path / "scripts")


def test_find_altium_picks_newest(tmp_path):
    for v in ("AD24", "AD26", "AD25"):
        d = tmp_path / "Altium" / v
        d.mkdir(parents=True)
        (d / "X2.exe").write_bytes(b"")
    assert A.find_altium([tmp_path / "Altium"]).parent.name == "AD26"
    assert A.find_altium([tmp_path / "nothing"]) is None


def test_sync_command_format(tmp_path):
    cmd = A.sync_command(Path("C:/Altium/AD26/X2.exe"), Path("C:/PartKit Scripts/PartKitSync.PrjScr"))
    assert cmd[1].startswith("-RScriptingSystem:RunScript(ProjectName=")
    assert 'ProcName="PartKitSync.pas>Run"' in cmd[1]


def test_start_sync_without_altium_explains(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "find_altium", lambda: None)
    started, msg = A.start_sync(prjscr=tmp_path / "PartKitSync.PrjScr")
    assert not started and "File > Run Script" in msg
