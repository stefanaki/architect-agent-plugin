"""The fire code «Κανονισμός Πυροπροστασίας Κτιρίων» (π.δ. 41/2018, ΦΕΚ Α΄ 80/2018): its text.

The decree issues the regulation as the quoted text of its «Άρθρο Πρώτο». The regulation has three
chapters, and their article numbers start again at 1:
  Α  general provisions (Γενικές διατάξεις), articles 1-8
  Β  provisions for each use (Ειδικές διατάξεις), articles 1-11
  Γ  repeals, transitional provisions, sanctions, annexes, articles 1-4
and annexes Α to Δ. An article id is the chapter letter and the number: "Α5", "Β3" (ids.py).
Paragraphs are numbered decimally from the article number: "Α5.3.7.1" is the paragraph that the
Gazette prints as «5.3.7.1.» in article 5 of Chapter Α.

Each chapter opens with a list of its articles («Άρθρο 1: Κατοικία»). It is the contents of the
chapter: the parser takes the titles from it and does not keep it as text. The text between the
list and the first article (the opening of Chapter Β) is the chapter's `text`.

The tables in the body and the four annexes are set in fonts without a text map: pdftotext gives
glyph codes, which extract.py removes. The figures are images. The pages of an article that hold
either are its `image_pages`, so the query script says that its text is incomplete.
"""
import datetime, html, re, subprocess, tempfile
from pathlib import Path
from types import SimpleNamespace

from common import PDF, degreekify, fek_url, issue_record, issued, pdftotext, write_json
from convert import DECIMAL, GREEK, greek_numeral, paragraphs_json
from datasets import FIRE, FIRE_CHAPTERS
import extract

FIRE_PDF = PDF / f"{FIRE.main}.pdf"
CHAPTER = re.compile(r"^ΚΕΦΑΛΑΙΟ\s+([ΑΒΓ])[’'΄]?\s*:\s*(.*)$")
HEADING = re.compile(r"^Άρθρο\s+(\d+)\s*:$")             # «Άρθρο 2:» alone on its line.
ENTRY = re.compile(r"^Άρθρο\s+(\d+)\s*:\s*(\S.*)$")       # «Άρθρο 1: Κατοικία» in a chapter's contents.
# The broken font prints «ΠΑΡΑΡΤΗΜΑ» as these glyph codes, then a space glyph and the letter.
# Checked by hand in the PDF: Ȱ, Ȳ, ȳ, ȴ are Α, Β, Γ, Δ.
ANNEX_GLYPHS = re.compile(r"ɅȰɆȰɆɈȸɀȰ\x03([ȰȲȳȴ])")
ANNEX_LETTER = {"Ȱ": "Α", "Ȳ": "Β", "ȳ": "Γ", "ȴ": "Δ"}
# The annexes are set in fonts without a text map (CID fonts without ToUnicode). pdftotext gives each
# glyph's CID as its code point, and the CIDs follow the glyph order of the font: Α-Ω from 0x230,
# α-ω from 0x272, the digits from 0x3EC. Each entry was checked against a render of page 63.
ANNEX_CIDS = {
    **dict(zip(range(0x3EC, 0x3F6), "0123456789")),
    0x230: "Α", 0x232: "Β", 0x233: "Γ", 0x234: "Δ", 0x235: "Ε", 0x236: "Έ", 0x237: "Ζ", 0x238: "Η", 0x23A: "Θ",
    0x23B: "Ι", 0x23E: "Κ", 0x23F: "Λ", 0x240: "Μ", 0x241: "Ν", 0x242: "Ξ", 0x243: "Ο", 0x245: "Π", 0x246: "Ρ",
    0x247: "Σ", 0x248: "Τ", 0x249: "Υ", 0x24A: "Ύ", 0x24C: "Φ", 0x24D: "Χ", 0x24E: "Ψ", 0x24F: "Ω",
    0x272: "α", 0x273: "ά", 0x274: "β", 0x276: "γ", 0x277: "δ", 0x278: "ε", 0x279: "έ", 0x27A: "ζ", 0x27B: "η",
    0x27C: "ή", 0x27D: "θ", 0x27F: "ι", 0x280: "ί", 0x283: "κ", 0x284: "λ", 0x285: "μ", 0x286: "ν", 0x287: "ξ",
    0x289: "ο", 0x28A: "ό", 0x28B: "π", 0x28C: "ρ", 0x28D: "σ", 0x28E: "ς", 0x28F: "τ", 0x290: "υ", 0x291: "ύ",
    0x294: "φ", 0x296: "χ", 0x297: "ψ", 0x298: "ω", 0x299: "ώ",
    0x15D: "i", 0x175: "m", 0x176: "n",                                  # «Συνάθροιση min 50 ατόμων».
    0x3: " ", 0x355: ",", 0x358: ".", 0x36C: "/", 0x372: "-", 0x398: "&", 0x38E: "*",
    0x444: "<", 0x445: ">", 0x448: "≥",
}
UNKNOWN_CID = "\ufffd"
DECODED = ("The font of the annex on PDF page {page} has no text map. Its text is decoded from the glyph codes "
           "(fire.ANNEX_CIDS), checked against the page image.")
RUNNING_HEAD = 80                    # Points from the top. The running head of the page is above this.
ANNEX_A_PAGE = 63
ANNEX_A_LABEL_X = 115                # Points. The category letters end left of this, the names start right of it.
ANNEX_A_TEXT_X = 255                 # Points. The descriptions start right of this.
GLYPH = extract.GLYPH
ROWS_IN_ORDER = 0.8                  # This share of a table's rows must be lines of the layout text.
TABLE_GLYPHS = 20                   # A page with more glyph codes holds a table without a text map.
CAPTION = re.compile(r"Πίνακας\s+(\d+)\s*[:.]\s*[Α-ΩΆ-Ώ]")      # «Πίνακας 4: Ελάχιστα ...», «Πίνακας 2. Απαιτήσεις ...»
DECIMAL_HEADING = re.compile(r"^\d+(?:\.\d+)+\.?\s+[Α-ΩΆ-Ώ]")      # «6.7. Απαιτήσεις Αντίδρασης στη φωτιά».
# A sentence end, then a clause marker and a capital: «... κτίρια. γ) Στις».
INLINE_CLAUSE = re.compile(r"(?<=[.:;·])\s+(?=([α-ω]{1,2})\)\s+[Α-ΩΆ-Ώ])")
# Misprinted paragraph numbers: (article, start of the paragraph as printed, its number in sequence).
# The text stays as printed. The id and the paragraph's `printed` field come from this table.
NUMBERING_ERRATA = [
    # Between 6.5 and 6.6.1. ν. 4710/2020 (ΦΕΚ Α΄ 142/2020, άρθ. 26) restates article 6 with the same misprint.
    ("Α6", "6.1. Μετάδοση φωτιάς εντός του κτιρίου", "6.6"),
    # A second «6.7» between 6.7 and 6.9. ν. 4710/2020 restates it as «6.8».
    ("Α6", "6.7. Απαιτήσεις Αντίδρασης στη φωτιά", "6.8"),
]


def chapter_contents(ls, i) -> tuple[dict, int]:
    """Return ({(number, False): [title]}, index of the first line after the list) for the list at line i."""
    toc, x0 = {}, ls[i].x0
    while i < len(ls):
        l = ls[i]
        if (m := ENTRY.match(l.text)):
            num = m.group(1)
            toc[(num, False)] = [m.group(2)]
        elif toc and l.x0 < x0 - extract.PARA_INDENT[0] and l.text[:1].islower():
            # Each entry starts at the paragraph indent. A wrapped title line («τους») starts at the margin.
            title = toc[(num, False)]
            title[0] = extract.join(title[0], l.text)
        else:
            break
        i += 1
    return toc, i


def starts_paragraph(text: str, article: str) -> bool:
    """Return True for a line that starts with a decimal number of its article: «5.3.2. Παροχή όδευσης».

    extract.parse_lines then starts a paragraph there. After a table or at a change from two columns to
    one, the first line of a paragraph has no indent. A citation that wraps to the start of a line
    («5.3.7.3. του άρθρου») has a lower-case word after it.
    """
    m = DECIMAL.match(text)
    return bool(m) and m.group(1).split(".", 1)[0] == article and text[m.end():m.end() + 1].isupper()


def split_clauses(paras: list) -> list:
    """Split a paragraph where the Gazette prints the next clause on the same line: «... κτίρια. γ) Στις».

    Only the clause after the paragraph's own clause splits it. Return the new list of paragraphs.
    """
    out = []
    for p in paras:
        text, start = p.text, 0
        clause = (m := GREEK.match(text)) and greek_numeral(m.group(1))
        for m in INLINE_CLAUSE.finditer(text):
            if clause and greek_numeral(m.group(1)) == clause + 1:
                out.append(extract.Para(text[start:m.start()], p.page, p.quoted, p.at))
                start, clause = m.end(), clause + 1
        out.append(extract.Para(text[start:], p.page, p.quoted, p.at) if start else p)
    return out


def paragraphs(article: str, number: str, paras: list) -> list[dict]:
    """Return the paragraph records of an article. The ids follow the numbering errata."""
    errata = [(printed, correct) for a, printed, correct in NUMBERING_ERRATA if a == article]
    shadow, printed_as = [], []
    for p in paras:
        hit = next(((printed, correct) for printed, correct in errata if p.text.startswith(printed)), None)
        printed = hit[0].split(" ", 1)[0] if hit else None                 # «6.1.»
        shadow.append(extract.Para(f"{hit[1]}.{p.text[len(printed):]}" if hit else p.text, p.page, p.quoted, p.at))
        printed_as.append(printed.rstrip(".") if hit else None)
    out = paragraphs_json(SimpleNamespace(num=article, paras=shadow), decimal=number)
    for record, p, printed in zip(out, paras, printed_as):
        record["text"] = p.text
        if printed:
            record["printed"] = printed
    return out


def tables(records: list[dict]) -> list[dict]:
    """Return the tables that an article prints in a readable font: [{"table": "4", "pages": [12, 13]}].

    The parser reads their cells in reading order, as paragraphs without numbers, so the rows of a table
    are out of order in the text. A table runs from its caption («Πίνακας 4:») to the next numbered
    paragraph: its pages are a safe upper bound.
    """
    out = []
    for k, p in enumerate(records):
        for m in CAPTION.finditer(p["text"]):
            end = next((q["page"] for q in records[k + 1:] if "#" not in q["id"]), records[-1]["page"])
            out.append({"table": m.group(1), "pages": list(range(p["page"], max(end, p["page"]) + 1))})
    return out


RULE_COLOUR = "rgb(10.101318%, 27.397156%, 55.511475%)"   # The rule under the running head and between columns.
STROKE = re.compile(r'<path fill="none"[^>]*stroke="([^"]+)"[^>]*d="([^"]+)"')
FILLED_RECTS = re.compile(r'<path fill-rule="nonzero" fill="[^"]+"[^>]*d="([^"]+)"')
SEGMENT = re.compile(r"M ([-\d.]+) ([-\d.]+) L ([-\d.]+) ([-\d.]+)")


PATH = re.compile(r"<path [^>]*>")
TRANSFORM = re.compile(r'transform="matrix\(([^)]*)\)"')
POINT = re.compile(r"[ML] ([-\d.]+) ([-\d.]+)")
REGION_GAP = 20                      # Points. Drawings of one column closer than this are one table.


def table_regions(pdf: Path = None) -> dict[int, list[tuple[float, float, float, float]]]:
    """Return the tables that each page draws: {page: [(left, top, right, bottom)]}, in points from the top.

    A table is three or more horizontal rules, or a grid of four or more filled cells, in the drawing of
    the page (`pdftocairo -svg`). Some tables have no caption («Αριθμός και πλάτος εξόδων κινδύνου ανά
    όροφο», page 54), so only the drawing shows them.
    """
    pdf = pdf or FIRE_PDF
    pages = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", str(pdf)], capture_output=True,
                                                             text=True, check=True).stdout).group(1))
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        for page in range(1, pages + 1):
            svg = Path(tmp) / f"{page}.svg"
            subprocess.run(["pdftocairo", "-svg", "-f", str(page), "-l", str(page), str(pdf), str(svg)], check=True)
            text = svg.read_text(encoding="utf-8")
            middle = float(re.search(r'width="([\d.]+)pt"', text).group(1)) / 2
            drawn = []                                  # [left, top, right, bottom, rules, cells]
            for tag in PATH.findall(text.split("</defs>", 1)[-1]):          # Glyph outlines are in <defs>.
                stroke = re.search(r'stroke="([^"]+)"', tag)
                if (stroke and stroke.group(1) == RULE_COLOUR) or not (stroke or 'fill-rule="nonzero"' in tag):
                    continue
                a, b, c, d, e, f = (map(float, m.group(1).replace(",", " ").split()) if (m := TRANSFORM.search(tag))
                                    else (1, 0, 0, 1, 0, 0))
                points = [(a * x + c * y + e, b * x + d * y + f)
                          for x, y in ((float(x), float(y)) for x, y in POINT.findall(re.search(r' d="([^"]+)"', tag).group(1)))]
                if not points:
                    continue
                xs, ys = [x for x, _ in points], [y for _, y in points]
                rules = sum(1 for (x0, y0), (x1, y1) in zip(points[::2], points[1::2])
                            if abs(y0 - y1) < 0.5 and abs(x1 - x0) > 20) if stroke else 0
                cells = 0 if stroke else re.search(r' d="([^"]+)"', tag).group(1).count("Z")
                drawn.append([min(xs), min(ys), max(xs), max(ys), rules, cells])
            regions = []
            for box in sorted(drawn, key=lambda b: b[1]):
                side = "L" if box[2] < middle + 5 else "R" if box[0] > middle - 5 else "S"
                near = next((r for r in regions if r[6] == side and box[1] <= r[3] + REGION_GAP), None)
                if near:
                    near[:6] = [min(near[0], box[0]), min(near[1], box[1]), max(near[2], box[2]), max(near[3], box[3]),
                                near[4] + box[4], near[5] + box[5]]
                else:
                    regions.append(box + [side])
            found = [tuple(r[:4]) for r in regions if r[4] >= 3 or r[5] >= 4]
            if found:
                out[page] = found
    return out


def in_tables(paras: list, regions: dict) -> list[bool]:
    """Return for each paragraph (extract.Para) whether it is text of a table that its page draws. A paragraph
    runs from its first line to the next paragraph's first line on the same page (or the foot of the page)."""
    out = []
    for k, p in enumerate(paras):
        nxt = paras[k + 1] if k + 1 < len(paras) else None
        if nxt is None:                                   # The end of the article: where it ends is unknown.
            end = p.at[1] if p.at else 0
        else:
            end = nxt.at[1] if nxt.page == p.page and nxt.at else float("inf")
        # It starts in the table, or starts above it and runs past its foot (the rows merged into it). A
        # paragraph that starts above and ends inside is the sentence that introduces the table.
        out.append(bool(p.at) and any(left - 3 <= p.at[0] <= right and (top - 2 <= p.at[1] <= bottom + 2
                                                                       or p.at[1] < top and end > bottom)
                                      for left, top, right, bottom in regions.get(p.page, [])))
    return out


def rows_in_order(paras: list, layout: list[str]) -> bool:
    """Return True if the rows of a table read in order: each paragraph after its header is one line of
    `pdftotext -layout` (the Chapter Β tables). Otherwise the cells are mixed (Πίνακας 4)."""
    rows = paras[1:]
    norm = lambda t: re.sub(r"\s+", " ", t).strip()
    lines = {pg: [norm(degreekify(line)) for line in layout[pg - 1].splitlines()] for pg in {p.page for p in rows}}
    hits = sum(1 for p in rows if any(norm(p.text) in line for line in lines[p.page]))
    return bool(rows) and hits >= ROWS_IN_ORDER * len(rows)


def table_records(article: dict, paras: list, regions: dict, images: set[int], layout: list[str]) -> list[dict]:
    """Return the tables of an article: [{"table": "4" or None, "pages", "paragraphs", "order"}].

    The paragraphs of a table are those that start inside a table that the page draws. A captioned table
    («Πίνακας 4:») takes them on its pages; the rest form tables without a caption, one per page. `order`
    is "rows" if the rows read in order and only the header is mixed, else "cells".
    """
    records = article["paragraphs"]
    in_table = {r["id"]: p for r, p, hit in zip(records, paras, in_tables(paras, regions)) if hit}
    out, taken = [], set()
    for t in tables(records):
        pages = [pg for pg in t["pages"] if pg in regions or pg in images] or t["pages"]
        ids = [i for i, p in in_table.items() if p.page in pages and i not in taken]
        taken |= set(ids)
        out.append({"table": t["table"], "pages": pages, "paragraphs": ids,
                    "order": "rows" if ids and rows_in_order([in_table[i] for i in ids], layout) else "cells"})
    for pg in sorted({p.page for i, p in in_table.items() if i not in taken and p.page not in images}):
        ids = [i for i, p in in_table.items() if p.page == pg and i not in taken]
        out.append({"table": None, "pages": [pg], "paragraphs": ids,
                    "order": "rows" if rows_in_order([in_table[i] for i in ids], layout) else "cells"})
    return out


# Annex Β is a diagram printed as an image (page 64), so it has no text to read. This is its text,
# transcribed by hand from the image: a decision tree, as (depth, box) from the root.
ANNEX_B_PAGE = 64
ANNEX_B_TREE = [
    (0, "ΚΤΙΡΙΟ"),
    (1, "Μία χρήση"),
    (2, "Κύρια με συμπληρωματικές"),
    (3, "Η συμπληρωματική χρήση διαθέτει πληρότητα"),
    (4, "Εξετάζεται κάθε χρήση με το ειδικό άρθρο της"),
    (5, "Εάν η συμπληρωματική χρήση δεν διαθέτει ανεξάρτητες οδεύσεις"),
    (6, "Ο θεωρητικός πληθυσμός (Θ.Π.) της συμπληρωματικής προσμετράται στο Θ.Π. της κυριαρχούσας"),
    (3, "Η συμπληρωματική χρήση δε διαθέτει πληρότητα"),
    (4, "Εξετάζεται συνολικά με την κυριαρχούσα χρήση"),
    (2, "Κύρια και μοναδική"),
    (3, "Διαθέτει πληρότητα"),
    (4, "Εξετάζεται με το ειδικό άρθρο της χρήσης"),
    (3, "Δε διαθέτει πληρότητα"),
    (4, "Εξετάζεται με τη συγγενέστερη χρήση"),
    (1, "Πολλαπλών χρήσεων"),
    (2, "Εμπλεκόμενες"),
    (3, "Χρήσεις που διαθέτουν πληρότητα"),
    (4, "Επιλέγονται οι κατά περίπτωση αυστηρότερες απαιτήσεις της κάθε χρήσης για το σύνολο του κτιρίου"),
    (5, "Εάν υπάρχει πυράντοχος διαχωρισμός και οι χρήσεις είναι τμήματα διαφορετικών ορόφων με κοινές "
        "πυροπροστατευμένες κατακόρυφες οδεύσεις"),
    (6, "Εξετάζεται κάθε χρήση ξεχωριστά, μόνο για την επιβολή των μέσων ενεργητικής πυροπροστασίας"),
    (3, "Χρήση που δεν διαθέτει πληρότητα"),
    (4, "Εξετάζεται με την κυριαρχούσα χρήση, ως δευτερεύουσα"),
    (2, "Διαχωρισμένες (Πυράντοχος διαχωρισμός και ανεξάρτητες οδεύσεις διαφυγής)"),
    (3, "Εξετάζεται κάθε χρήση με το ειδικό άρθρο της για το σύνολο του κτιρίου"),
]
TRANSCRIBED = ("The annex is a diagram, an image on PDF page {page}. Its text is transcribed by hand from the "
               "image: each paragraph is one path through the diagram, from the top box down, joined with «→».")


def annex_b() -> tuple[str, list[dict]]:
    """Return the title and the paragraphs of Annex Β: one paragraph for each path of ANNEX_B_TREE.

    The title is in the annex font above the image, so it is decoded like Annex Α.
    """
    page = pdftotext(FIRE_PDF, "-bbox-layout", "-f", str(ANNEX_B_PAGE), "-l", str(ANNEX_B_PAGE))
    lines = [decode_cids(html.unescape(w)) for _, y0, _, _, w in extract._WORD.findall(page) if float(y0) > RUNNING_HEAD]
    title = next(t for t in lines if t.startswith("Τρόπος"))
    paths, stack = [], []
    for k, (depth, box) in enumerate(ANNEX_B_TREE):
        del stack[depth:]
        stack.append(box)
        if k + 1 == len(ANNEX_B_TREE) or ANNEX_B_TREE[k + 1][0] <= depth:      # A leaf.
            paths.append(" → ".join(stack))
    return title, [{"id": f"Π-Β#{k}", "page": ANNEX_B_PAGE, "text": t} for k, t in enumerate(paths, 1)]


def decode_cids(text: str) -> str:
    """Return the text of an annex line: each CID through ANNEX_CIDS, an unknown one as U+FFFD."""
    return "".join(ANNEX_CIDS.get(ord(c), UNKNOWN_CID) for c in text).strip()


def annex_a() -> tuple[str, list[dict]]:
    """Return the title and the paragraphs of Annex Α, the uses of buildings (page 63).

    The annex is a table: category letter, use, description. Each letter is printed on the last line of
    its row, so a line belongs to the first row whose letter is not above it. A paragraph is one row,
    «Γ | ΣΥΝΑΘΡΟΙΣΗ ΚΟΙΝΟΥ | Συνάθροιση min 50 ατόμων, ...», after the header row and before the footnotes.
    """
    page = pdftotext(FIRE_PDF, "-bbox-layout", "-f", str(ANNEX_A_PAGE), "-l", str(ANNEX_A_PAGE))
    words = [(float(x0), float(y0), html.unescape(w)) for x0, y0, _, _, w in extract._WORD.findall(page)]
    body = [(x0, y0, t) for x0, y0, w in words if y0 > RUNNING_HEAD and (t := decode_cids(w))]
    body.sort(key=lambda w: (round(w[1]), w[0]))
    header = next(y0 for _, y0, t in body if t == "ΠΕΡΙΓΡΑΦΗ")
    labels = [(y0, t) for x0, y0, t in body if x0 < ANNEX_A_LABEL_X and y0 > header and len(t) == 1]
    title = " ".join(t for _, y0, t in body if y0 < header and not t.startswith("ΠΑΡΑΡΤΗΜΑ"))
    rows = {y0: [t, [], []] for y0, t in labels}
    notes = []
    for x0, y0, t in body:
        if y0 <= header or (x0 < ANNEX_A_LABEL_X and len(t) == 1):
            continue
        row = next((r for r, _ in labels if r >= y0 - 3), None)
        if row is None:                                  # The footnotes under the table.
            if t.startswith("*") or not notes:
                notes.append(t)
            else:
                notes[-1] += " " + t
            continue
        rows[row][1 if x0 < ANNEX_A_TEXT_X else 2].append(t)
    paragraphs = [{"id": "Π-Α#1", "page": ANNEX_A_PAGE, "text": "ΚΑΤΗΓΟΡΙΕΣ ΧΡΗΣΕΩΝ | ΠΕΡΙΓΡΑΦΗ"}]
    for letter, use, description in rows.values():
        paragraphs.append({"id": f"Π-Α#{len(paragraphs) + 1}", "page": ANNEX_A_PAGE,
                           "text": f"{letter} | {' '.join(use)} | {' '.join(description)}"})
    for note in notes:
        paragraphs.append({"id": f"Π-Α#{len(paragraphs) + 1}", "page": ANNEX_A_PAGE, "text": note})
    return title, paragraphs


def table_pages(pages: list[str]) -> set[int]:
    """Return the pages with a table in a font without a text map."""
    return {i + 1 for i, t in enumerate(pages) if len(GLYPH.findall(t)) > TABLE_GLYPHS}


def parse_fire():
    """Return (chapters, annexes, number of pages).

    Each chapter is {"letter", "title", "page", "contents" {number: title}, "text" [Para], "articles" [Article]}.
    Each annex is (letter, first page, last page).
    """
    ls = extract.lines(FIRE_PDF)
    start = next(i for i, l in enumerate(ls) if l.text == "Άρθρο Πρώτο")
    end = next(i for i, l in enumerate(ls) if i > start and l.text == "Άρθρο Δεύτερο")
    annexes_at = next(i for i in range(start, end) if ls[i].text == "ΠΑΡΑΡΤΗΜΑΤΑ")
    margins = extract._margins(ls[start:end])
    heads = [i for i in range(start, annexes_at) if CHAPTER.match(ls[i].text)]
    chapters = []
    for k, i in enumerate(heads):
        letter, title = CHAPTER.match(ls[i].text).groups()
        toc, body = chapter_contents(ls, i + 1)
        stop = heads[k + 1] if k + 1 < len(heads) else annexes_at
        lines = []
        for l in ls[body:stop]:
            if (m := HEADING.match(l.text)):
                l = extract.Line(l.page, l.x0, l.y0, l.x1, l.y1, f"Άρθρο {m.group(1)}", l.col)
            lines.append(l)
        for j in range(1, len(lines)):
            # A table cell of the other column that is printed above a heading goes before it, not into it
            # («Γενικές απαιτήσεις» of Πίνακας 12 and the heading «6.7. Απαιτήσεις Αντίδρασης», page 35).
            head, cell = lines[j - 1], lines[j]
            if DECIMAL_HEADING.match(head.text) and cell.page == head.page and cell.col != head.col \
                    and cell.y1 <= head.y0:
                lines[j - 1], lines[j] = cell, head
        act = extract.Act("κεφ.", None)
        extract.parse_lines(lines, act=act, toc=toc, margins=margins, starts=starts_paragraph)
        for a in act.articles:
            titles = toc.get((a.num, False), [])
            if titles and titles[0].endswith(a.title) and titles[0] != a.title:
                a.title = titles[0]            # The text layer lost the first title line.
        chapters.append({"letter": letter, "title": title, "page": ls[i].page,
                         "contents": {num: t[0] for (num, _), t in toc.items()},
                         "text": act.preamble, "articles": act.articles})

    pages = pdftotext(FIRE_PDF, "-layout").split("\f")
    starts = [(ANNEX_LETTER[m.group(1)], i + 1) for i, t in enumerate(pages) for m in ANNEX_GLYPHS.finditer(t)]
    last = ls[end].page - 1                    # The annexes end before the page of «Άρθρο Δεύτερο».
    annexes = [(letter, page, (starts[k + 1][1] - 1) if k + 1 < len(starts) else last)
               for k, (letter, page) in enumerate(starts)]
    # «Άρθρο Δεύτερο»: the commencement, up to the order to publish the decree («Στον Υπουργό ...»).
    text = ""
    for l in ls[end + 1:]:
        if l.text.startswith("Στον Υπουργό"):
            break
        text = extract.join(text, l.text)
    commencement = {"article": "Άρθρο Δεύτερο", "page": ls[end].page, "text": text}
    return chapters, annexes, len(pages) - (pages[-1] == ""), commencement


def write_text():
    """Write data/fire/FEK-A-80-2018.json."""
    chapters, annexes, npages, commencement = parse_fire()
    pages = pdftotext(FIRE_PDF, "-layout").split("\f")
    unreadable = table_pages(pages) | extract.image_pages(FIRE_PDF)
    regions = table_regions()
    issue = issue_record(FIRE.number, FIRE.year)        # The decree does not cite itself, so discovery lacks it.
    records = []
    for ch in chapters:
        letter, articles = ch["letter"], ch["articles"]
        path = [f"ΚΕΦΑΛΑΙΟ {letter}΄" + (f": {ch['title']}" if ch["title"] else "")]
        for k, a in enumerate(articles):
            next_page = articles[k + 1].page if k + 1 < len(articles) else max([p.page for p in a.paras] + [a.page])
            images = sorted(p for p in unreadable if a.page <= p <= next_page)
            number = a.num
            a.paras = split_clauses(a.paras)
            paras = paragraphs(f"{letter}{number}", number, a.paras)
            record = {"article": f"{letter}{number}", "label": f"{number} Κεφ. {letter}΄", "title": a.title,
                      "page": a.page, "path": path, **({"image_pages": images} if images else {}), "paragraphs": paras}
            if (found := table_records(record, a.paras, regions, set(images), pages)):
                record = {**{k: v for k, v in record.items() if k != "paragraphs"}, "tables": found, "paragraphs": paras}
            records.append(record)
    readers = {"Α": annex_a, "Β": annex_b}
    for letter, page, last in annexes:
        record = {"article": f"Π-{letter}", "label": f"Παράρτημα {letter}΄", "title": "", "page": page,
                  "path": ["ΠΑΡΑΡΤΗΜΑΤΑ"]}
        if letter in readers:
            record["title"], record["paragraphs"] = readers[letter]()
            if letter == "Β":
                record["transcribed"] = TRANSCRIBED.format(page=ANNEX_B_PAGE)
                record["image_pages"] = [ANNEX_B_PAGE]
            else:
                record["decoded"] = DECODED.format(page=page)
        else:
            record.update({"missing_text": True, "image_pages": list(range(page, last + 1)), "paragraphs": []})
        records.append(record)
    write_json(FIRE.json_path(FIRE.main), {
        "title": FIRE.title, "fek": f"Α΄ {FIRE.number}/{FIRE.year}", "file": FIRE.main, "act": FIRE.act,
        "published": issue["published"], **issued(issue), "source": fek_url(FIRE.number, FIRE.year), "search_id": issue["search_id"],
        "pages": npages, "issued_by": "Άρθρο πρώτο του π.δ. 41/2018",
        "in_force": in_force(issue), "commencement": commencement,
        "chapters": [{"chapter": ch["letter"], "title": ch["title"], "page": ch["page"], "contents": ch["contents"],
                      **({"text": [{"page": p.page, "text": p.text} for p in ch["text"]]} if ch["text"] else {})}
                     for ch in chapters],
        "articles": records})
    n = {ch["letter"]: len(ch["articles"]) for ch in chapters}
    print(f"   {FIRE.main}: articles per chapter {n}, {len(annexes)} annexes without text, "
          f"{sum(1 for r in records if r.get('image_pages'))} articles with tables or figures without text")


def in_force(issue: dict) -> str:
    """Return when the decree came into force: three months after publication («Άρθρο Δεύτερο»).

    The masthead is dated 7 May 2018 and the issue was released on 8 May 2018 (search.et.gr), so the
    start is 7 or 8 August 2018 depending on which counts as the publication.
    """
    def plus3(day: str) -> str:
        d = datetime.date.fromisoformat(day)
        return d.replace(month=d.month + 3).isoformat()
    issued = issue.get("issued", issue["published"])
    if issued == issue["published"]:
        return f"{plus3(issued)}: three months after publication (Άρθρο Δεύτερο)"
    return (f"{plus3(issued)} counted from the masthead date ({issued}), or {plus3(issue['published'])} from the "
            f"release of the issue ({issue['published']}): three months after publication (Άρθρο Δεύτερο)")


def expected_articles() -> list[str]:
    """Return the article ids of the fire code in order: "Α1" ... "Γ4"."""
    return [f"{letter}{n}" for letter, count in FIRE_CHAPTERS.items() for n in range(1, count + 1)]
