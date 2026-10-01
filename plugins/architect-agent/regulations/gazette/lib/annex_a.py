"""Read Annex A of the Code «Νικόλαος Ταγαράς» (law 5306/2026, ΦΕΚ Α΄ 88/2026).

Annex A is a table. Each row gives a Code article, a Code paragraph, and the
provision that the paragraph codifies, with its amendments:
  «Παρ. 4 | Παρ. 5 του άρθρου 27 του ν. 4067/2012, όπως αυτή προστέθηκε με ...»

Article 477 of the Code repeals the provisions that Annex A lists, and only those.

This module gives:
  rows()           each entry of the table: Code article, Code paragraph, source text
  parse()          for each NOK article: the Code articles and the (law, article) amendments
  paragraph_map()  for each NOK paragraph: the Code places that hold it

The table text comes from `pdftotext -layout`. Cells wrap over lines, and page
headers interrupt rows. The far-right column cites the old basic planning code.
The module removes that column.
"""
import re
from collections import defaultdict

from common import PDF, pdftotext

CODE_PDF = PDF / "FEK-A-88-2026.pdf"
NOISE = re.compile(r"ΕΦΗΜΕΡΙΔΑ ΤΗΣ ΚΥΒΕΡΝΗΣΕΩΣ|Τεύχος A’|^\s*E\s*$|^\s*\d{4}\s*$|ΚΩΔΙΚΟΠΟΙ|^\s*ΔΙΑΤΑΞΗ\s*$")
NOK_REF = re.compile(r"(?:άρθρου|[Άά]ρθρο)\s+(\d+[Α-Ω]?)\s+του\s+ν\.\s*4067/2012")
# «Παρ. 5 του άρθρου 27 του ν. 4067/2012», «περ. β) της παρ. 3 του άρθρου 6 του ν. 4067/2012»,
# «Παρ. 1 και 2 του άρθρου 13 του ν. 4067/2012».
NOK_PARA_REF = re.compile(r"[Ππ]αρ\.\s*(\d+[α-ω]?(?:\s*(?:,|και|έως)\s*\d+[α-ω]?)*)\s+(?:του|της)\s+"
                          r"άρθρου\s+(\d+[Α-Ω]?)\s+του\s+ν\.\s*4067/2012")
# The layout can put a paragraph number of the next row inside a reference: «άρθρου 7 1 του ν. 4315/2014».
AMEND_REF = re.compile(r"(?:άρθρου|άρθρο)\s+(\d+[Α-Ω]?)(?:\s+\d{1,2})?\s+του\s+ν\.\s*(\d{4}/(\d{4}))")
FIRST_YEAR = 2012                         # A law older than the NOK cannot amend it.
SENTENCE = re.compile(r"(?<=[.])\s+(?=(?:Παρ|Περ|Άρθρο|Τρίτο|Πρώτο|Δεύτερο|Το|Η|Οι|Τα|Εδάφ|Υποπερ)\b)")
# A sentence that starts with the Code paragraph, then the source: «Παρ. 4 Παρ. 5 του άρθρου 27 ...»,
# «Περ. 40 Παρ. 40 ...», «Περ. α) έως ιδ) Άρθρο 1 ...». «Παρ. 8 του άρθρου 27» has no Code paragraph.
# The source can start with an ordinal («Πρώτο εδάφιο») or a clause («περ. α)»).
CODE_PARA = re.compile(r"^(Παρ|Περ)\.\s*(\S+?(?:\s+έως\s+\S+)?)\s+"
                       r"(?=(?:Παρ|Περ|Άρθρο|Υποπερ|Εδάφ|Τα|Το|Η|Οι|Πρώτο|Δεύτερο|Τρίτο|Τέταρτο|Τελευταίο|Εισαγωγικό)\b"
                       r"|περ\.)")
# The layout can split «Περ. 40Α» around the source: «Περ. Παρ. 22 του άρθρου 2 του ν. 1577/1985. 40Α».
SPLIT_PARA = re.compile(r"^(Παρ|Περ)\.\s+(?=Παρ|Περ|Άρθρο)(.*?)\s+(\d+[Α-Ω]?)$")

# Errors in the printed table, and one row that the text layout breaks. Each correction was checked
# against the Code text, the NOK text and the page image.
ERRATA = [
    # Code art. 1: the label «Περ. α) έως ιδ)» wraps, and «έως ιδ)» lands after the first source.
    ("Περ. α) Άρθρο 1 του ν. 4447/2016", "Περ. α) έως ιδ) Άρθρο 1 του ν. 4447/2016"),
    ("(Α΄ 245). έως ιδ) Περ. ιε)", "(Α΄ 245). Περ. ιε)"),
    # Code art. 197 περ. 34 «Κάλυψη του οικοπέδου» is NOK art. 2 §34. The table prints §33.
    ("Περ. 34 Παρ. 33 του άρθρου 2 του ν. 4067/2012", "Περ. 34 Παρ. 34 του άρθρου 2 του ν. 4067/2012"),
    # Code art. 197 περ. 59 «Πεζόδρομοι» is NOK art. 2 §59. The table prints §37.
    ("Περ. 59 Παρ. 37 του άρθρου 2 του ν. 4067/2012", "Περ. 59 Παρ. 59 του άρθρου 2 του ν. 4067/2012"),
    # Code art. 197 περ. 40 «Κοινωφελείς χώροι» is NOK art. 2 §40. The table prints «ν. 4064/2012».
    ("Παρ. 40 του άρθρου 2 του ν. 4064/2012", "Παρ. 40 του άρθρου 2 του ν. 4067/2012"),
    # Code art. 207: the label «Παρ. 1» wraps, and «1» lands inside the first source («άρθρου 7 1 του ν. 4315/2014»).
    ("Παρ. Περ. α) Περ. α) της παρ. 1 του άρθρου 12 του ν. 4067/2012, όπως τροποποιήθηκε με την παρ. 10 "
     "του άρθρου 7 1 του ν. 4315/2014",
     "Παρ. 1 περ. α) Περ. α) της παρ. 1 του άρθρου 12 του ν. 4067/2012, όπως τροποποιήθηκε με την παρ. 10 "
     "του άρθρου 7 του ν. 4315/2014"),
]


def _pages():
    pages = pdftotext(CODE_PDF, "-layout").split("\f")
    start = next(i for i, p in enumerate(pages) if "ΠΙΝΑΚΑΣ ΚΩΔΙΚΟΠΟΙΗΤΙΚΩΝ - ΚΩΔΙΚΟΠΟΙΟΥΜΕΝΩΝ ΔΙΑΤΑΞΕΩΝ" in p)
    end = next(i for i, p in enumerate(pages) if i > start and "ΠΑΡΑΡΤΗΜΑ Β" in p)
    return pages[start:end]


def _articles():
    """Yield (code_article, text) for each Code article in the table. The text has the errata applied."""
    code, buf, pending = None, [], False

    def text():
        # Control characters are page numbers in a broken font («\x17\x13\x14»). They block the sentence split.
        return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f]+", " ", " ".join(buf))).strip()
    for page in _pages():
        for line in page.split("\n"):
            gap = re.search(r"\s{4,}\S", line[100:])      # The far-right column starts after a wide gap.
            line = (line[:100 + gap.start()] if gap else line).rstrip()
            if not line.strip() or NOISE.search(line):
                continue
            m = re.match(r"^Άρθρο\s*(\d+)?(?=\s|$)", line)
            if m:
                if code:
                    yield code, text()
                code, buf, pending = m.group(1), [line[m.end():]], m.group(1) is None
                continue
            if pending and (m := re.match(r"^(\d+)\b", line)):   # The number is on the next line.
                code, pending = m.group(1), False
                line = line[m.end():]
            buf.append(line)
    if code:
        yield code, text()


def _with_errata(articles):
    articles = list(articles)
    for wrong, right in ERRATA:
        hits = [i for i, (_, t) in enumerate(articles) if wrong in t]
        if len(hits) != 1:
            raise RuntimeError(f"Annex A erratum not found exactly once: «{wrong}». Check the table layout.")
        code, t = articles[hits[0]]
        articles[hits[0]] = (code, t.replace(wrong, right))
    return articles


def rows() -> list[dict]:
    """Return each entry of the table as {code_article, code_paragraph, code_label, source}.

    code_paragraph is "4" or "α)"; code_label keeps the word: "Παρ. 4", "Περ. α)".
    Both are None when the source fills the whole Code article. A second source that
    continues the previous paragraph («... Παρ. 8 του άρθρου 27 ...») gets the paragraph
    of the entry before it.
    """
    out = []
    for code, text in _with_errata(_articles()):
        para = label = None
        for sentence in SENTENCE.split(text):
            if (m := SPLIT_PARA.match(sentence)):
                para, source = m.group(3), m.group(2)
                label = f"{m.group(1)}. {para}"
            elif (m := CODE_PARA.match(sentence)):
                para, source = m.group(2), sentence[m.end():]
                label = f"{m.group(1)}. {para}"
            else:
                source = sentence
            out.append({"code_article": code, "code_paragraph": para, "code_label": label, "source": source.strip()})
    return out


def nok_refs(source: str) -> list[tuple[str, str | None]]:
    """Return the NOK provisions that a source text names, as (article, paragraph or None).

    Only the first provision of the sentence counts. The references after it
    («όπως τροποποιήθηκε με το άρθρο 30 του ν. 4933/2022») are amendments.
    """
    head = source[:source.find("4067/2012") + len("4067/2012")] if "4067/2012" in source else ""
    if not head:
        return []
    if (m := NOK_PARA_REF.search(head)):
        return [(m.group(2), n) for n in _expand(m.group(1))]
    if (m := NOK_REF.search(head)):
        return [(m.group(1), None)]
    return []


def _expand(nums: str) -> list[str]:
    """Expand «1 και 2» and «3 έως 5». A letter suffix is a clause: «3α» is paragraph 3."""
    parts = [re.match(r"\d+", p).group() for p in re.findall(r"\d+[α-ω]?", nums)]
    if "έως" in nums and len(parts) == 2:
        return [str(n) for n in range(int(parts[0]), int(parts[1]) + 1)]
    return parts


def parse() -> tuple[dict[str, set[str]], dict[str, set[tuple[str, str]]]]:
    """Return (code_of, amended_by).

    code_of:    NOK article -> {Code article}
    amended_by: NOK article -> {(law, article)}, for example ("4933/2022", "30")
    """
    code_of, amended_by = defaultdict(set), defaultdict(set)
    for code, text in _with_errata(_articles()):
        for sentence in SENTENCE.split(text):
            refs = NOK_REF.findall(sentence)
            if not refs:
                continue
            nok = refs[0]
            code_of[nok].add(code)
            tail = sentence[sentence.find("4067/2012") + len("4067/2012"):]
            for article, law, year in AMEND_REF.findall(tail):
                if law != "4067/2012" and int(year) >= FIRST_YEAR:
                    amended_by[nok].add((law, article))
    return code_of, amended_by


def paragraph_map() -> dict[str, dict[str, set[str]]]:
    """Return NOK article -> {NOK paragraph: {Code place}}.

    The paragraph key is "*" when the table names the whole NOK article.
    A Code place is "224.4" (article 224, paragraph 4) or "198" (the whole article).
    """
    out = defaultdict(lambda: defaultdict(set))
    for r in rows():
        place = r["code_article"] + (f".{r['code_paragraph'].rstrip(')')}" if r["code_paragraph"] else "")
        for article, para in nok_refs(r["source"]):
            out[article][para or "*"].add(place)
    return out
