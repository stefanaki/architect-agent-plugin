"""Tests of skills/regulations/scripts/regs.py and the id grammar, against the bundled data."""
import subprocess, sys

import pytest

from conftest import SKILL

import ids

SCRIPT = SKILL / "scripts" / "regs.py"


def regs(*args) -> tuple[int, str]:
    r = subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, encoding="utf-8")
    return r.returncode, r.stdout


def test_normalize():
    for typed in ("code:224.3.b", "CODE:224.3.beta", "code:224.3.β΄", "code:224.3.β", " code:224.3.Β "):
        assert ids.normalize(typed) == "code:224.3.β", typed
    assert ids.normalize("nok:11.6.id") == "nok:11.6.ιδ"
    assert ids.normalize("nok:10a") == "nok:10Α"
    assert ids.normalize("fek-a-108-2026:133.1") == "FEK-A-108-2026:133.1"
    assert ids.normalize("FEK-A-245-2020:120#1~4") == "FEK-A-245-2020:120#1~4"
    for bad in ("foo:1", "code:", "code:abc", "nok:27.zz9", "code:224.", "code:224..3"):
        with pytest.raises(ValueError):
            ids.normalize(bad)


def test_cite():
    assert ids.cite("224.3.β", "Ν. 5306/2026", "Α΄ 88/2026") == "άρθ. 224 παρ. 3 περ. β΄ ν. 5306/2026 (ΦΕΚ Α΄ 88/2026)"
    assert ids.cite("120#1~4", "Ν. 4759/2020", "Α΄ 245/2020") == "άρθ. 120 ν. 4759/2020 (ΦΕΚ Α΄ 245/2020)"
    assert ids.cite("206.6.ιστ.α", "Ν. 5306/2026", "Α΄ 88/2026") == \
        "άρθ. 206 παρ. 6 περ. ιστ΄ υποπερ. α΄ ν. 5306/2026 (ΦΕΚ Α΄ 88/2026)"


def test_within():
    assert ids.within("code:224.3.β", "code:224.3")
    assert ids.within("code:224.3#1", "code:224.3")
    assert not ids.within("code:224.30", "code:224.3")
    assert ids.related("nok:27", "nok:27.5")


def test_every_response_states_the_update():
    for args in (("info",), ("read", "code:1"), ("read", "code:9999")):
        _, out = regs(*args)
        assert out.startswith("Gazette checked through ΦΕΚ Α΄"), args


def test_read_ascii_id_gives_cite_and_status():
    code, out = regs("read", "code:224.3.b")
    assert code == 0
    assert "[code:224.3.β] άρθ. 224 παρ. 3 περ. β΄ ν. 5306/2026 (ΦΕΚ Α΄ 88/2026)" in out
    assert "Status:" in out


def test_read_shows_nok_origin_and_cross_references():
    _, out = regs("read", "code:211.3")
    assert "From the NOK (Annex A): nok:16.3" in out
    assert "refers to: code:210.5" in out


def test_subclause_ids():
    code, out = regs("read", "code:206.6.ιστ")
    assert code == 0
    for sub in "αβγδ":
        assert f"[code:206.6.ιστ.{sub}]" in out


def test_history_brings_amending_text_and_start():
    _, out = regs("history", "code:273.1")
    assert "FEK-A-108-2026:133" in out
    assert "== Amendment 1 of" in out
    assert "starts:" in out
    assert "FEK-A-108-2026:143" in out          # «Το άρθρο 133 ισχύει από ...», a related article.


def test_history_dates_is_one_line_per_amendment():
    _, out = regs("history", "nok:11", "--dates")
    assert "== Amendment" not in out
    assert out.count("  amend") >= 5
    assert len(out) < 6000


def test_history_superseded():
    _, out = regs("history", "nok:27", "--dates")
    assert "FEK-A-174-2013:48" not in out
    assert "1 superseded amendment(s) left out" in out
    # In 2015 the later restatement did not exist yet, so the superseded pointer applies.
    _, out = regs("history", "nok:27", "--dates", "--as-of", "2015-01-01")
    assert "FEK-A-174-2013:48" in out and "FEK-A-269-2014:7" in out


def test_nok_paragraph_added_by_amendment():
    _, out = regs("read", "nok:27.5")
    assert "an amendment added or renumbered it" in out
    _, out = regs("history", "nok:27.5", "--dates")
    assert "FEK-A-269-2014:7" in out


def test_trace_after_annex_a_fix():
    _, out = regs("trace", "nok:17.1")
    assert "→ code:212.1" in out and "code:211.1" not in out
    _, out = regs("trace", "nok:27.5")
    assert "→ code:224.4" in out
    _, out = regs("trace", "nok:27")
    assert "Not codified: nok:27.4" in out


def test_search_ranks_building_rules_first_and_uses_synonyms():
    _, out = regs("search", "μπαλκον", "--limit", "2")
    assert "also matches: ανοικτ + εξωστ" in out
    first = next(line for line in out.splitlines() if line.startswith(("code:", "nok:", "FEK-")))
    assert first.startswith("code:2")
    _, out = regs("search", "ΕΞΏΣΤΕΣ", "--in", "nok")
    heads = [line for line in out.splitlines() if line.startswith(("code:", "nok:", "FEK-"))]
    assert heads and all(h.startswith("nok:") for h in heads)


def test_search_without_hits_suggests_stems():
    code, out = regs("search", "ξξξξ")
    assert code == 0
    assert "Try fewer or shorter stems" in out


def test_changes_since_the_code():
    _, out = regs("changes")
    assert "amendments of the Code published from 2026-06-08" in out
    assert "code:273" in out


def test_toc():
    _, out = regs("toc", "code", "--section", "οικοδομικος κανονισμος")
    assert out.splitlines()[1].startswith("ΜΕΡΟΣ Δ")
    assert "  code:195  " in out
    _, out = regs("toc", "FEK-A-108-2026")
    assert "FEK-A-108-2026:133" in out


def test_pages():
    _, first = regs("history", "nok:11")
    assert "Page 1 of" in first and len(first) < 13_000
    _, second = regs("history", "nok:11", "--page", "2")
    assert "Page 2 of" in second and second.startswith("Gazette checked through")
    _, full = regs("history", "nok:11", "--full")
    assert "Page " not in full and len(full) > len(first)


def test_errors():
    for args in (("read", "code:9999"), ("read", "foo:1"), ("read", "code:224."),
                 ("history", "FEK-A-108-2026:133")):
        code, out = regs(*args)
        assert code == 2, args
        assert "Error:" in out


def test_missing_data_is_an_error(tmp_path, monkeypatch, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("regs_script", SCRIPT)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script, "DATA", tmp_path)
    assert script.main(["info"]) == 2
    assert "Error: cannot read the datasets" in capsys.readouterr().out
