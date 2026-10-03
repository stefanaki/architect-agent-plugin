"""Tests of scripts/regulations.py, the id grammar and index.json, against the bundled data.

    python3 -m unittest discover -s plugins/architect-agent/tests
"""
import json, subprocess, sys, unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_ROOT / "scripts" / "regulations.py"
sys.path.insert(0, str(PLUGIN_ROOT / "regulations" / "gazette" / "lib"))
import ids  # noqa: E402


def query(*args):
    r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, encoding="utf-8")
    return r.returncode, json.loads(r.stdout)


class Ids(unittest.TestCase):
    def test_normalize(self):
        for typed in ("code:224.3.b", "CODE:224.3.beta", "code:224.3.β΄", "code:224.3.β", " code:224.3.Β "):
            self.assertEqual(ids.normalize(typed), "code:224.3.β", typed)
        self.assertEqual(ids.normalize("nok:11.6.id"), "nok:11.6.ιδ")
        self.assertEqual(ids.normalize("nok:10a"), "nok:10Α")
        self.assertEqual(ids.normalize("fek-a-108-2026:133.1"), "FEK-A-108-2026:133.1")
        self.assertEqual(ids.normalize("FEK-A-245-2020:120#1~4"), "FEK-A-245-2020:120#1~4")
        for bad in ("foo:1", "code:", "code:abc", "nok:27.zz9", "code:224.", "code:224..3"):
            with self.assertRaises(ValueError, msg=bad):
                ids.normalize(bad)

    def test_cite(self):
        self.assertEqual(ids.cite("224.3.β", "Ν. 5306/2026", "Α΄ 88/2026"),
                         "άρθ. 224 παρ. 3 περ. β΄ ν. 5306/2026 (ΦΕΚ Α΄ 88/2026)")
        self.assertEqual(ids.cite("120#1~4", "Ν. 4759/2020", "Α΄ 245/2020"), "άρθ. 120 ν. 4759/2020 (ΦΕΚ Α΄ 245/2020)")
        self.assertEqual(ids.cite("23.α", "Ν. 4067/2012", "Α΄ 79/2012"), "άρθ. 23 περ. α΄ ν. 4067/2012 (ΦΕΚ Α΄ 79/2012)")

    def test_within(self):
        self.assertTrue(ids.within("code:224.3.β", "code:224.3"))
        self.assertTrue(ids.within("code:224.3#1", "code:224.3"))
        self.assertFalse(ids.within("code:224.30", "code:224.3"))
        self.assertTrue(ids.related("nok:27", "nok:27.5"))


class Index(unittest.TestCase):
    def test_index_checks(self):
        import index, validate
        from datasets import CODE, NOK
        idx = index.load()
        for ds in (CODE, NOK):
            errors, _ = validate.check_index(ds, idx)
            self.assertEqual(errors, [], ds.key)


class Script(unittest.TestCase):
    def test_every_response_states_the_update(self):
        for args in (("info",), ("get", "code:1"), ("get", "code:9999")):
            _, out = query(*args)
            self.assertIn("checked through", out["updated"])

    def test_get_ascii_id(self):
        code, out = query("get", "code:224.3.b")
        self.assertEqual(code, 0)
        self.assertEqual(out["id"], "code:224.3.β")
        self.assertEqual(out["paragraphs"][0]["cite"], "άρθ. 224 παρ. 3 περ. β΄ ν. 5306/2026 (ΦΕΚ Α΄ 88/2026)")

    def test_history_brings_amending_text_and_commencement(self):
        _, out = query("history", "code:273.1")
        by = [a["by"] for a in out["amendments"]]
        self.assertIn("FEK-A-108-2026:133", by)
        self.assertTrue(out["amendments"][0]["text"])
        self.assertIn("FEK-A-108-2026:143", [c["id"] for c in out["context"]])     # «Το άρθρο 133 ισχύει από ...»

    def test_history_superseded(self):
        _, out = query("history", "nok:27")
        self.assertNotIn("FEK-A-174-2013:48", [a["by"] for a in out["amendments"]])
        self.assertEqual(out["hidden"]["superseded"], 1)
        # In 2015 the later restatement did not exist yet, so the superseded pointer applies.
        _, out = query("history", "nok:27", "--as-of", "2015-01-01")
        self.assertEqual([a["by"] for a in out["amendments"]], ["FEK-A-174-2013:48", "FEK-A-269-2014:7"])

    def test_nok_paragraph_added_by_amendment(self):
        _, out = query("get", "nok:27.5")
        self.assertEqual(out["paragraphs"], [])
        self.assertTrue(out["notes"])
        _, out = query("history", "nok:27.5")
        self.assertIn("FEK-A-269-2014:7", [a["by"] for a in out["amendments"]])

    def test_trace(self):
        _, out = query("trace", "nok:27.5")
        self.assertEqual([x["code"] for x in out["links"]], ["code:224.4"])
        self.assertTrue(out["annex_a"])
        _, out = query("trace", "nok:27")
        self.assertEqual(out["not_codified"], ["nok:27.4"])

    def test_search_ranks_building_rules_first(self):
        _, out = query("search", "εξωστ", "--limit", "3")
        self.assertTrue(out["paragraphs"])
        self.assertTrue(all(p["id"].startswith("code:") for p in out["paragraphs"]))
        _, nok = query("search", "ΕΞΏΣΤΕΣ", "--dataset", "nok")
        self.assertTrue(all(not p["id"].startswith("code:") for p in nok["paragraphs"]))

    def test_toc(self):
        _, out = query("toc", "code", "--section", "οικοδομικος κανονισμος")
        self.assertEqual(out["sections"][0]["articles"][0][0], "code:195")
        _, out = query("toc", "FEK-A-108-2026")
        self.assertIn("FEK-A-108-2026:133", [a["id"] for act in out["acts"] for a in act["articles"]])

    def test_code_file_by_issue_id(self):
        code, out = query("get", "FEK-A-88-2026:224.4")
        self.assertEqual(code, 0)
        self.assertTrue(out["paragraphs"])
        code, out = query("toc", "FEK-A-88-2026")
        self.assertEqual(code, 0)

    def test_errors(self):
        for args in (("get", "code:9999"), ("get", "foo:1"), ("get", "code:224."),
                     ("history", "FEK-A-108-2026:133")):
            code, out = query(*args)
            self.assertEqual(code, 2, args)
            self.assertIn("error", out)

    def test_missing_index_is_a_json_error(self):
        import contextlib, importlib.util, io, tempfile
        spec = importlib.util.spec_from_file_location("regulations_script", SCRIPT)
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        with tempfile.TemporaryDirectory() as empty:
            script.REGULATIONS = Path(empty)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = script.main(["info"])
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(out.getvalue()))


if __name__ == "__main__":
    unittest.main()
