"""Unit tests of the Gazette harness (tools/gazette/lib), with small fixtures, and checks of the built data."""
import json, re
from types import SimpleNamespace

import pytest

import annex_a, common, convert, extract, fire, ids, ledger, lookups


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


def test_text_after_a_closed_clause_belongs_to_the_paragraph():
    # π.δ. 41/2018 Β7.3: «β) Να αποτελεί ξεχωριστό πυροδιαμέρισμα.» then the aisle widths of the paragraph.
    assert ids_of("7", "3. θα πρέπει:", "α) Να διαθέτει οδεύσεις.", "β) Να αποτελεί πυροδιαμέρισμα.",
                  "Οι διάδρομοι κυκλοφορίας ...", "Επιπλέον ...") == ["7.3", "7.3.α", "7.3.β", "7.3#1", "7.3#2"]
    # A clause that introduces text, or a heading clause without a full stop, keeps it.
    assert ids_of("9", "1. Κείμενο:", "α) με τη διαδικασία:", "Αρχικά υποβάλλεται ...") == ["9.1", "9.1.α", "9.1.α#1"]
    assert ids_of("7", "2. Κείμενο:", "γ) Πυροσβεστήρες οροφής", "Επιβάλλεται ...") == ["7.2", "7.2.γ", "7.2.γ#1"]


def test_last_clause_of_a_list_without_a_full_stop(monkeypatch):
    # π.δ. 41/2018 Α5.7.1: «γ) ... 900 τ.μ.,» then the end of the sentence that introduces the list.
    texts = ("5. Κείμενο:", "α) κτίρια,", "β) υπόγεια,", "αλλά και όπου αλλού απαιτείται.", "Το ελάχιστο πλάτος ...")
    monkeypatch.setattr(convert, "LAST_CLAUSE", True)
    assert ids_of("5", *texts)[3:] == ["5.5#1", "5.5#2"]
    # A heading clause keeps its text, and a list that goes on keeps the text between its clauses.
    assert ids_of("7", "2. Κείμενο:", "γ) Πυροσβεστήρες οροφής", "Επιβάλλεται ...") == ["7.2", "7.2.γ", "7.2.γ#1"]
    assert ids_of("7", "2. Κείμενο:", "α) πρώτο,", "και εξήγηση", "β) δεύτερο.") == ["7.2", "7.2.α", "7.2.α#1", "7.2.β"]
    monkeypatch.setattr(convert, "LAST_CLAUSE", False)
    assert ids_of("5", *texts)[3:] == ["5.5.β#1", "5.5.β#2"]


def test_a_second_list_is_not_nested_in_the_first():
    assert ids_of("1", "Σκοπός:", "α) πρώτο.", "β) δεύτερο.", "Οι παράμετροι είναι:", "α) χρήστες.", "β) χώροι.") == \
        ["1#1", "1.α", "1.β", "1#2", "1.α@2", "1.β@2"]


def test_a_list_goes_on_after_text_between_its_clauses():
    assert ids_of("5", "2. Κείμενο:", "α) πρώτο.", "Εξήγηση.", "β) δεύτερο.") == ["5.2", "5.2.α", "5.2#1", "5.2.β"]
    assert ids_of("5", "2. Κείμενο:", "β) δεύτερο.", "Εξήγηση.", "βα) υπο.", "ββ) υπο.") == \
        ["5.2", "5.2.β", "5.2#1", "5.2.β.α", "5.2.β.β"]
    assert ids_of("5", "2. Κείμενο:", "β) δεύτερο:", "α) υπο.", "Εξήγηση.", "β) υπο.") == \
        ["5.2", "5.2.β", "5.2.β.α", "5.2.β#1", "5.2.β.β"]


def test_quoted_decimal_article_and_its_misprint():
    # ν. 4710/2020 art. 26 par. 2 restates article 6 of the fire code, with «6.1.» printed for 6.6.
    art = SimpleNamespace(num="26", paras=[SimpleNamespace(text=t, quoted=q, page=1) for t, q in (
        ("2. Το άρθρο 6 διαμορφώνεται ως εξής:", False), ("6.1. Γενικά", True), ("Οι διατάξεις ...", True),
        ("6.5. Πυροδιαμερισματοποίηση", True), ("6.1. Μετάδοση φωτιάς εντός του κτιρίου", True),
        ("6.6.1. Κάθετη", True), ("6.7. Επικίνδυνοι χώροι", True))])
    out = convert.paragraphs_json(art)
    assert [p["id"] for p in out] == ["26.2", "26.2~6.1", "26.2~6.1#1", "26.2~6.5", "26.2~6.6", "26.2~6.6.1", "26.2~6.7"]
    assert [p.get("printed") for p in out] == [None, None, None, None, "6.1", None, None]


def test_same_law_references():
    refs = lambda text: convert.internal_refs(SimpleNamespace(title="", paras=[SimpleNamespace(text=text, quoted=False)]))
    assert refs("κατά το άρθρο 13 του παρόντος και τα άρθρα 14 έως 16") == {"13", "14", "15", "16"}
    assert refs("τους φορείς του άρθρου 13α του ν. 4310/2014") == set()
    assert refs("καταργούνται τα άρθρα 3, 30 έως και 33 του Κώδικα περί μεταλλείων") == set()
    assert refs("με τα άρθρα 13 περίπτωση α΄ και 263Α του Ποινικού Κώδικα") == set()
    assert refs("στα άρθρα 4 έως 7 του από 5/17.9.1935 π.δ.") == set()
    assert refs("καταργούνται τα άρθρα 1 έως και 4 και το άρθρο 16 του ν. 719/1977") == set()
    assert refs("Τα άρθρα 1 έως και 3 εφαρμόζονται") == {"1", "2", "3"}


def test_justified_words_keep_their_space():
    # ΦΕΚ Α΄ 80/2018 page 22: 0.44 pt between words. pdftotext splits a word with no gap.
    ws = [(68.0, 0, 87.15, 9, "Στην"), (87.59, 0, 132.39, 9, "περίπτωση"), (132.39, 0, 140.0, 9, "ς")]
    assert extract._line_text(ws) == "Στην περίπτωσης"
    # A superscript ordinal stays with its number (ΦΕΚ Α΄ 142/2025): raised, smaller, 0.29 pt away.
    ws = [(422.26, 273.48, 427.86, 285.29, "6"), (428.15, 271.51, 435.89, 279.43, "ον"), (440.4, 273.48, 470.3, 285.29, "αἰῶνα")]
    assert extract._line_text(ws) == "6ον αἰῶνα"


def test_issue_dates():
    hit = {"search_PublicationDate": "05/08/2018 00:00:00", "search_IssueDate": "05/07/2018 00:00:00"}
    assert common.dates(hit) == {"published": "2018-05-08", "issued": "2018-05-07"}
    assert common.issued({"published": "2018-05-08", "issued": "2018-05-07"}) == {"issued": "2018-05-07"}
    assert common.issued({"published": "2020-07-23", "issued": "2020-07-23"}) == {}


def test_table_paragraphs_and_row_order():
    Para = extract.Para
    regions = {54: [(300, 151, 527, 282)]}
    paras = [Para("Επιπλέον ... στον παρακάτω πίνακα:", 54, at=(300, 140)), Para("Αριθμός ... Πληθυσμός", 54, at=(300, 152)),
             Para("51 - 150 άτομα 2 0,90 μ.", 54, at=(300, 190)), Para("* Κατ’ εξαίρεση ...", 54, at=(300, 290))]
    # The sentence that introduces the table and the footnote under it are not table text.
    assert fire.in_tables(paras, regions) == [False, True, True, False]
    layout = [""] * 53 + ["κείμενο στήλης         51 - 150 άτομα            2              0,90 μ."]
    assert fire.rows_in_order(paras[1:3], layout)
    assert not fire.rows_in_order([paras[1], Para("Έως 50 2 0,90 μ. 51 1*", 54)], layout)


def test_annex_glyph_codes():
    assert fire.decode_cids("\u0245\u0230\u0246\u0230\u0246\u0248\u0238\u0240\u0230\x03\u0230") == "ΠΑΡΑΡΤΗΜΑ Α"
    assert fire.decode_cids("\u0448\u03f3\u03ec\x03\u028f\u0358\u0285\u0358") == "≥70 τ.μ."
    assert fire.UNKNOWN_CID in fire.decode_cids("\u0500")


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


# The fire code ------------------------------------------------------------------------------------

def test_decimal_paragraph_ids():
    art = SimpleNamespace(num="Α5", paras=[SimpleNamespace(text=t, quoted=False) for t in (
        "5.3. Σχεδιασμός", "Κείμενο", "5.3.7.1. Γενικά", "α) Πρώτο", "5.4. Επόμενο", "17.2.1989 ημερομηνία")])
    assert convert.paragraph_ids(art, decimal="5") == \
        ["Α5.3", "Α5.3#1", "Α5.3.7.1", "Α5.3.7.1.α", "Α5.4", "Α5.4#1"]
    # Without `decimal`, the NOK and Code numbering stays as it was: «5.3.» is not a marker.
    assert convert.markers("5.3. Σχεδιασμός") == []


def test_fire_paragraph_starts():
    assert fire.starts_paragraph("5.3.2. Παροχή όδευσης διαφυγής", "5")
    assert not fire.starts_paragraph("5.3.7.3. του άρθρου 5 του κεφαλαίου Α΄", "5")     # A wrapped citation.
    assert not fire.starts_paragraph("6.2. Απαιτήσεις", "5")                             # Another article.


def test_inline_clause_splits_only_at_the_next_clause():
    paras = [extract.Para("β) Στην περίπτωση προσθηκών. γ) Στις περιπτώσεις κτιρίων.", 2)]
    assert [p.text for p in fire.split_clauses(paras)] == ["β) Στην περίπτωση προσθηκών.", "γ) Στις περιπτώσεις κτιρίων."]
    paras = [extract.Para("β) Κείμενο. ε) Όχι η επόμενη.", 2)]
    assert len(fire.split_clauses(paras)) == 1


def test_numbering_errata_fix_the_id_and_keep_the_text():
    paras = [extract.Para(t, 27) for t in ("6.5. Πυροδιαμερισματοποίηση", "6.1. Μετάδοση φωτιάς εντός του κτιρίου",
                                           "6.6.1. Γενικές απαιτήσεις")]
    out = fire.paragraphs("Α6", "6", paras)
    assert [p["id"] for p in out] == ["Α6.5", "Α6.6", "Α6.6.1"]
    assert out[1]["text"].startswith("6.1. Μετάδοση") and out[1]["printed"] == "6.1"


def test_fire_ids_and_citations():
    assert ids.normalize("fire:A5.3.7.1") == "fire:Α5.3.7.1"
    assert ids.normalize("FIRE:b3.2.a") == "fire:Β3.2.α"
    assert ids.normalize("fire:π-γ") == "fire:Π-Γ"
    assert ids.cite("Α5.3.7.1.α", "Π.Δ. 41/2018", "Α΄ 80/2018") == \
        "άρθ. 5 Κεφ. Α΄ παρ. 5.3.7.1 περ. α΄ π.δ. 41/2018 (ΦΕΚ Α΄ 80/2018)"
    assert ids.cite("Β3", "Π.Δ. 41/2018", "Α΄ 80/2018") == "άρθ. 3 Κεφ. Β΄ π.δ. 41/2018 (ΦΕΚ Α΄ 80/2018)"


def test_fire_chapter_from_the_cited_paragraph():
    known = {"Α6": {"Α6", "Α6.7"}, "Β6": {"Β6", "Β6.2"}}
    assert ledger.fire_chapter("6", ["7"], known) == ("Α", True)
    assert ledger.fire_chapter("6", ["2"], known) == ("Β", True)
    assert ledger.fire_chapter("6", [], known) == ("Α", True)                 # Both fit: the general provisions.


def test_fire_cross_references():
    articles = [art("Α2", ("Α2.5", "2.5. Κείμενο")), art("Α4", ("Α4.2.2", "4.2.2. Κείμενο")),
                art("Β1", ("Β1.1#3", "Δεν εφαρμόζονται οι διατάξεις της παρ. 4.2.2 του άρθρου 4 του Κεφαλαίου Α΄."),
                    ("Β1.2", "1.2. Όπως στο άρθρο 2 του παρόντος Κεφαλαίου και στο Παράρτημα Γ.")),
                art("Β2", ("Β2.1", "2.1. Κείμενο")), art("Π-Γ"),
                art("Γ1", ("Γ1.1", "1.1. Καταργούνται τα Κεφάλαια Α και Γ, και του κεφ. Α΄ του π.δ. 71/1988."))]
    x = lookups.fire_xrefs(articles)
    assert x["fire:Β1.1#3"] == ["fire:Α4.2.2", "fire:Α4"]
    assert x["fire:Β1.2"] == ["fire:Β2", "fire:Π-Γ"]
    assert "fire:Γ1.1" not in x                    # Another decree.


def test_fire_definitions():
    base = {"fire": [art("Α3", ("Α3#7", "Αντίδραση στη φωτιά (πυραντίδραση): Συμπεριφορά δοκιμίου"))]}
    assert lookups.glossary(base) == [{"term": "Αντίδραση στη φωτιά", "id": "fire:Α3#7", "also": "πυραντίδραση"}]


def test_right_column_edge_ignores_a_cell_across_the_gap(tmp_path, monkeypatch):
    # ΦΕΚ Α΄ 80/2018, page 45: a table cell starts at 293.7, left of where the left column ends (294.8).
    def page(lines):
        rows = "".join(f'<line xMin="{x0}" yMin="{y}" xMax="{x1}" yMax="{y + 9}"><word xMin="{x0}" yMin="{y}" '
                       f'xMax="{x1}" yMax="{y + 9}">{t}</word></line>' for x0, y, x1, t in lines)
        return f'<page width="595.22" height="842.0">{rows}</page>'
    lines = [(68.0, 100, 294.8, "αριστερή α"), (68.0, 112, 294.8, "αριστερή β"),
             (309.0, 100, 535.8, "δεξιά α"), (309.0, 112, 535.8, "δεξιά β"), (293.7, 300, 421.2, "κελί πίνακα")]
    monkeypatch.setattr(extract, "pdftotext", lambda pdf, *args: page(lines))
    cols = {l.text: l.col for l in extract.lines(tmp_path / "x.pdf")}
    assert cols["αριστερή α"] == "L" and cols["δεξιά α"] == "R"


def test_line_across_the_column_gap_splits():
    # ΦΕΚ Α΄ 130/2020, page 166: «... του άρθρου» (left column) and «για κάθε» (right column) in one line.
    ws = [(240.0, 0, 286.3, 9, "άρθρου"), (300.5, 0, 315.0, 9, "για"), (318.0, 0, 340.0, 9, "κάθε")]
    assert [[w[4] for w in part] for part in extract._split_at_middle(ws, 595.22)] == [["άρθρου"], ["για", "κάθε"]]
    # A word space at the middle of a full-width line is not a column gap, even in spaced-out text
    # (ΦΕΚ Α΄ 142/2025, page 119: word spaces of 10-11 points).
    ws = [(280.0, 0, 296.0, 9, "λέξη"), (299.0, 0, 320.0, 9, "λέξη")]
    assert len(extract._split_at_middle(ws, 595.22)) == 1
    ws = [(188.0, 0, 239.0, 9, "ἑξηκοστοῦ"), (250.0, 0, 290.0, 9, "πέμπτου"), (301.0, 0, 320.0, 9, "65ου"),
          (333.0, 0, 346.0, 9, "(β)")]
    assert len(extract._split_at_middle(ws, 595.22)) == 1


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
    # «1. Η ισχύς ...» with more numbered paragraphs: they set other dates (ν. 4710/2020, article 65).
    many = doc("1. Η ισχύς του παρόντος νόμου αρχίζει από τη δημοσίευσή του στην Εφημερίδα της Κυβερνήσεως.")
    many["acts"][0]["articles"][0]["paragraphs"].append({"text": "2. Ειδικά η απαλλαγή αρχίζει από την 1η.1.2021."})
    assert lookups.commencement([many])[0]["rule"] == "publication-unless"
    # The masthead is dated a day before the release: the start counted from it too.
    late = doc("Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του.", published="2018-05-08")
    late["issued"] = "2018-05-07"
    assert lookups.commencement([late])[0]["from_issued"] == "2018-05-07"


# The built data -----------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def index():
    import index as index_module
    return index_module.load()


def test_index_checks(index):
    import validate
    from datasets import CODE, FIRE, NOK
    for ds in (CODE, NOK, FIRE):
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


def test_fire_text_is_complete(index):
    assert [g for g in index["articles"] if g.startswith("fire:")] == \
        [f"fire:{a}" for a in fire.expected_articles()] + [f"fire:Π-{x}" for x in "ΑΒΓΔ"]
    pointers = index["articles"]["fire:Α6"]["amended_by"]
    assert [(p["by"], p.get("restates"), p.get("status")) for p in pointers] == [("FEK-A-142-2020:26", True, "chapter")]


def test_fire_annexes_a_and_b_have_text(index):
    from datasets import FIRE
    arts = {a["article"]: a for a in FIRE.load(FIRE.main)["articles"]}
    a, b = arts["Π-Α"], arts["Π-Β"]
    assert a["title"].startswith("ΤΑΞΙΝΟΜΗΣΗ ΚΤΙΡΙΩΝ") and a.get("decoded") and not a.get("missing_text")
    assert "Γ | ΣΥΝΑΘΡΟΙΣΗ ΚΟΙΝΟΥ | Συνάθροιση min 50 ατόμων" in " ".join(p["text"] for p in a["paragraphs"])
    assert b.get("transcribed") and b["paragraphs"][0]["text"].startswith("ΚΤΙΡΙΟ → Μία χρήση")
    assert arts["Π-Γ"].get("missing_text") and arts["Π-Δ"].get("missing_text")


def test_shared_issue_is_listed_once(index):
    meta = index["files"]["FEK-A-142-2020"]
    assert meta["dataset"] == "nok" and meta["also"] == ["fire"]


def test_shipped_ids_module_is_the_one_the_harness_uses():
    from conftest import SKILL
    assert ids.__file__ == str(SKILL / "scripts" / "ids.py")
