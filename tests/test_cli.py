from typer.testing import CliRunner

from partkit import search
from partkit.cli import app
from partkit.search import SearchResult
from test_reuse_kits import J47, checked_10k

runner = CliRunner()


def run(lib, *args):
    r = runner.invoke(app, ["--library", str(lib.root), *args])
    assert r.exit_code == 0, r.output
    return r.output


def test_new_value_favourite_and_kits_from_the_command_line(lib, monkeypatch, tmp_path):
    checked_10k(lib)
    monkeypatch.setattr(search, "find_any", lambda q, s, http=None: SearchResult(mpn=q, offers=[J47]))
    assert "added to To check" in run(lib, "new-value", "RC0603FR-0710KL", "--value", "4.7k").replace("\n", " ")
    assert lib.get("0603WAF4701T5E").footprint == "RESC1608X55N"
    run(lib, "favourite", "0603WAF4701T5E")
    assert lib.get("0603WAF4701T5E").favourite
    run(lib, "kit", "add", "Basics", "0603WAF4701T5E", "RC0603FR-0710KL", "--qty", "2")
    out = tmp_path / "bom.csv"
    text = run(lib, "kit", "bom", "Basics", "--out", str(out))
    assert "0603WAF4701T5E" in text and out.exists()
    assert "Basics" in run(lib, "kit", "list")
