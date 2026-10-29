"""Unit tests of the Gazette harness (tools/gazette/lib), with small fixtures, and checks of the built data."""
import json, re
from types import SimpleNamespace

import pytest

import annex_a, common, convert, extract, ids, ledger, lookups


# Annex A ------------------------------------------------------------------------------------------

def row(article, para, source="…"):
    return {"code_article": article, "code_paragraph": para, "code_label": f"Παρ. {para}" if para else None,
            "source": source}


def test_annex_a_first_row_printed_before_its_article_moves_to_the_next():
    # pdftotext -layout puts «Παρ. 1» of article 212 at the end of article 211 (ΦΕΚ Α΄ 88/2026).
    rows = [row("211", "10"), row("211", "11"), row("211", "1", "Παρ. 1 του άρθρου 17 του ν. 4067/2012."),
            row("212", "2"), row("212", "3")]
    fixed = annex_a._fix_boundaries(rows)
    assert [(r["code_article"], r["code_paragraph"]) for r in fixed] == \
        [("211", "10"), ("211", "11"), ("212", "1"), ("212", "2"), ("212", "3")]


def test_annex_a_rows_in_order_stay():
    rows = [row("196", "1"), row("196", "2"), row("197", "1"), row("197", "2")]
    assert annex_a._fix_boundaries(rows) == rows
    # A second source of paragraph 1 that continues it (no new label) is not a boundary.
    rows = [row("10", "1"), row("10", "1"), row("11", "1")]
    assert annex_a._fix_boundaries(rows) == rows


def test_annex_a_nok_refs():
    assert annex_a.nok_refs("Παρ. 5 του άρθρου 27 του ν. 4067/2012, όπως προστέθηκε με το άρθρο 7 του ν. 4315/2014") \
        == [("27", "5")]
    assert annex_a.nok_refs("Παρ. 1 και 2 του άρθρου 13 του ν. 4067/2012") == [("13", "1"), ("13", "2")]
    assert annex_a.nok_refs("Άρθρο 3 του ν. 4067/2012") == [("3", None)]
    assert annex_a.nok_refs("Παρ. 22 του άρθρου 2 του ν. 1577/1985") == []


# Paragraph ids ------------------------------------------------------------------------------------

def ids_of(num, *texts):
    art = SimpleNamespace(num=num, paras=[SimpleNamespace(text=t, quoted=False) for t in texts])
    return convert.paragraph_ids(art)


def test_subclauses_get_their_own_level():
    assert ids_of("206", "6. Δεν προσμετρώνται:", "ιε) οι κατασκευές", "ιστ) ο ελεύθερος χώρος, εφόσον έχει:",
                  "ιστα) επιφάνεια", "ιστβ) στάθμη", "ιζ) η επιφάνεια") == \
        ["206.6", "206.6.ιε", "206.6.ιστ", "206.6.ιστ.α", "206.6.ιστ.β", "206.6.ιζ"]


def test_subclause_in_the_same_paragraph_as_its_clause():
    assert ids_of("206", "6. Κείμενο", "ιβ) ιβα) Για ειδικά κτίρια", "ιββ) Ειδικά για κτίρια") == \
        ["206.6", "206.6.ιβ.α", "206.6.ιβ.β"]


def test_subclause_with_a_two_letter_numeral():
    assert ids_of("22", "5. Κείμενο", "α) πρώτο", "αε) πέμπτο", "αστ) έκτο") == ["22.5", "22.5.α", "22.5.α.ε", "22.5.α.στ"]


def test_subclause_after_deeper_numbering_attaches_to_its_clause():
    # ΦΕΚ Α΄ 88/2026 article 238: «2. ... β) ... βα) ... ββ)» inside a numbered zone list.
    assert ids_of("238", "2. Σ.Δ.:", "β) για κτίρια", "βα) πρώτα", "ββ) επόμενα", "γ) για κατοικία") == \
        ["238.2", "238.2.β", "238.2.β.α", "238.2.β.β", "238.2.γ"]


def test_words_that_look_like_markers_stay_text():
    assert ids_of("5", "1. Κείμενο", "και) δεν είναι αρίθμηση") == ["5.1", "5.1#1"]


def test_numerals():
    assert convert.greek_numeral("ιστ") == 16
    assert convert.greek_numeral("κε") == 25
    assert convert.greek_numeral("ιστα") is None


# Extraction clean-up ------------------------------------------------------------------------------

def test_broken_font_glyph_words_are_removed():
    assert extract.clean_word("ɅȰɆȰɆɈȸɀȰ") == ""
    assert extract.clean_word("ϭ͗ɷɿɳ") == ""
    assert extract.clean_word("στρατηγική́") == "στρατηγική"
    assert extract.clean_word("οικόπεδο") == "οικόπεδο"
    assert extract.clean_word("MWh") == "MWh"


def test_mixed_roman_numerals_become_latin():
    assert common.degreekify("ΤΜΗΜΑ VΙΙ") == "ΤΜΗΜΑ VII"
    assert common.degreekify("ΧIV.") == "XIV."
    assert common.degreekify("ΚΕΦΑΛΑΙΟ Ι") == "ΚΕΦΑΛΑΙΟ Ι"         # Not mixed: unchanged.
    assert common.degreekify("NOMOΣ") == "ΝΟΜΟΣ"


def test_commencement_article_ends_at_an_absorbed_table():
    art = SimpleNamespace(paras=[SimpleNamespace(text="Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του."),
                                 SimpleNamespace(text="212 0 95 375 709"), SimpleNamespace(text="ΙΙ. Οι προβλέψεις")])
    assert convert.commencement_end(art) == 1
    art.paras = art.paras[:1]
    assert convert.commencement_end(art) is None


# Amendment matcher --------------------------------------------------------------------------------

TARGET = re.compile(rf"άρθρ(?:ο|ου|α|ων)\s+{ledger.NUMS}\s+{ledger.BETWEEN}{ledger.NOK_NAME}")


def match(text):
    m = TARGET.search(text)
    assert m, text
    return m


@pytest.mark.parametrize("text, kind", [
    ("Η περ. ιδ΄ της παρ. 6 του άρθρου 11 του ν. 4067/2012 (Α΄ 79) αντικαθίσταται ως εξής:", "amend"),
    ("Στο άρθρο 27 του ν. 4067/2012 προστίθεται παρ. 5 ως εξής:", "amend"),
    ("Καταργείται η παρ. 4 του άρθρου 20 του ν. 4067/2012.", "repeal"),
    ("Οι άδειες εκδίδονται σύμφωνα με την παρ. 2 του άρθρου 6 του ν. 4067/2012.", None),
])
def test_amending(text, kind):
    m = match(text)
    assert ledger.amending(text, m.start(), m.end(), False) == kind


@pytest.mark.parametrize("text, article, targets, restated", [
    ("Η περ. ιδ΄ της παρ. 6 του άρθρου 11 του ν. 4067/2012 αντικαθίσταται ως εξής:", "11", {"11.6.ιδ"}, False),
    ("Στο άρθρο 28 του ν. 4067/2012 προστίθεται παρ. 11 ως εξής:", "28", {"28.11"}, False),
    ("Το άρθρο 4 του ν. 4067/2012 αντικαθίσταται ως εξής:", "4", {"4"}, True),
    ("Οι παρ. 2 και 4 του άρθρου 27 του ν. 4067/2012 τροποποιούνται ως εξής:", "27", {"27.2", "27.4"}, False),
])
def test_targets(text, article, targets, restated):
    assert ledger.targets(text, match(text), article) == (targets, restated)


def test_labels():
    assert ledger.labels("2 και 4") == ["2", "4"]
    assert ledger.labels("ιδ΄") == ["ιδ"]
    assert ledger.labels("3α") == ["3.α"]
    assert ledger.labels("το") == []


# Lookups ------------------------------------------------------------------------------------------

def art(num, *paras):
    return {"article": num, "paragraphs": [{"id": pid, "text": text} for pid, text in paras]}


def test_cross_references():
    base = {"code": [
        art("210", ("210.5", "5. Κείμενο"), ("210.5.α", "α) Κείμενο")),
        art("211", ("211.3", "3. Όπως ορίζεται στις περ. α) και β) της παρ. 5 του άρθρου 210."),
            ("211.4", "4. Σύμφωνα με το άρθρο 7 του ν. 4315/2014 και το άρθρο 13 του ίδιου νόμου."),
            ("211.5", "5. Κατά την παρ. 3 του παρόντος και τα άρθρα 210 έως 212 του παρόντος Κώδικα.")),
        art("212", ("212.1", "1. Κείμενο"))], "nok": []}
    x = lookups.xrefs(base)
    assert x["code:211.3"] == ["code:210.5"]
    assert "code:211.4" not in x                   # Other laws.
    # «τα άρθρα 210 έως 212»: 211 holds the paragraph itself, so it is left out. «την παρ. 3 του παρόντος» is 211.3.
    assert x["code:211.5"] == ["code:210", "code:212", "code:211.3"]


def test_glossary_and_synonyms():
    base = {"code": [art("197", ("197.5", "5. «Ανοικτός εξώστης (μπαλκόνι)»: είναι η προεξοχή"),
                         ("197.82", "82. «Συντελεστής Δόμησης (Σ.Δ.)»: είναι ο αριθμός"))],
            "nok": [art("2", ("2.58", "58. Προκήπιο (ή πρασιά) είναι ο χώρος"))]}
    terms = lookups.glossary(base)
    assert {"term": "Ανοικτός εξώστης", "id": "code:197.5", "also": "μπαλκόνι"} in terms
    assert {"term": "Προκήπιο", "id": "nok:2.58", "also": "ή πρασιά"} in terms
    groups = lookups.synonyms(terms)
    assert ["μπαλκον", "ανοικτ εξωστ"] in groups and ["πρασι", "προκηπι"] in groups
    assert not any("σ.δ" in s for g in groups for s in g)       # Abbreviations are not synonyms.


def test_commencement_rules():
    def doc(text, published="2020-12-10"):
        return {"file": "FEK-A-245-2020", "published": published, "acts": [{"act": "Ν. 4759/2020", "articles": [
            {"article": "172", "match": "commencement", "paragraphs": [{"text": text}]}]}]}
    rule = lambda text: lookups.commencement([doc(text)])[0]                      # noqa: E731
    assert rule("Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της Κυβερνήσεως.") == \
        {"article": "FEK-A-245-2020:172", "act": "Ν. 4759/2020", "rule": "publication", "from": "2020-12-10"}
    assert rule("Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του, εκτός αν ορίζεται διαφορετικά.")["rule"] == \
        "publication-unless"
    assert rule("Η ισχύς του παρόντος νόμου αρχίζει δέκα (10) ημέρες μετά τη δημοσίευσή του.")["from"] == "2020-12-20"
    assert rule("Στο άρθρο 26 του ν. 5240/2025 προστίθεται παράγραφος.")["rule"] == "text"


# The built data -----------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def index():
    import index as index_module
    return index_module.load()


def test_index_checks(index):
    import validate
    from datasets import CODE, NOK
    for ds in (CODE, NOK):
        errors, _ = validate.check_index(ds, index)
        assert errors == [], ds.key


def test_annex_a_rows_run_in_order():
    import validate
    from datasets import CODE
    assert validate.annex_order(CODE.load(CODE.main)["articles"]) == []


def test_known_links(index):
    links = {(x["nok"], x["code"]) for x in index["links"]}
    assert ("nok:17.1", "code:212.1") in links and ("nok:17.1", "code:211.1") not in links
    assert ("nok:1.1", "code:196.1") in links
    assert ("nok:27.5", "code:224.4") in links


def test_no_glyph_noise_in_the_data():
    from datasets import DATASETS
    rx = re.compile(r"[ɐ-ʯ̀-ͯϘ-ϯЀ-ӿ]")
    for ds in DATASETS.values():
        for path in ds.json_paths():
            doc = json.loads(path.read_text(encoding="utf-8"))
            for act in ids.acts(doc):
                for a in act["articles"]:
                    assert not any(rx.search(p["text"]) for p in a["paragraphs"]), (path.stem, a["article"])


def test_shipped_ids_module_is_the_one_the_harness_uses():
    from conftest import SKILL
    assert ids.__file__ == str(SKILL / "scripts" / "ids.py")
