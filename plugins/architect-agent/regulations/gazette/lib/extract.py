"""Convert a Government Gazette PDF (ΦΕΚ) into structured text.

The parser uses the position of each line on the page, not plain text.
Position gives these signals:
  - The running header is in the top 9.5% of the page. The parser removes that zone.
  - A two-column page is read left column first, then right column.
  - A paragraph starts with a first-line indent.
  - An article heading («Άρθρο N») is alone on its line.
    It is centred (2012 layout) or indented (2020 layout).
  - The title lines of an article follow the heading with the same alignment.
  - A section heading (ΜΕΡΟΣ, ΚΕΦΑΛΑΙΟ, ...) is upper case and centred or indented.
  - An annex starts with a centred «ΠΑΡΑΡΤΗΜΑ» line.

Article numbers run in sequence within one act. A heading out of sequence is
quoted text from another law, so the parser keeps it as text. When the issue
has a table of contents, the title of a heading must also match the contents entry.

A ratifying law quotes a whole act: a code after «Άρθρο πρώτο», or a ΠΝΠ after «Άρθρο 1».
The parser reads the quoted act as its own act of kind «κώδ.» with the number of the
ratifying law. The quoted act starts at its first heading, which has the other numbering
style, and ends at the next heading of the ratifying law.
"""
import html, os, re, unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from common import degreekify, pdftotext


@dataclass
class Line:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    col: str = ""              # L, R, or S (spans both columns, or single-column page)


@dataclass
class Para:
    text: str
    page: int
    quoted: bool = False       # The paragraph starts inside quoted text «...».


@dataclass
class Article:
    num: str                   # Always a number ("1"), also for «Άρθρο πρώτο». Annexes use "Π-Ι".
    page: int
    title: str = ""
    paras: list = field(default_factory=list)
    headings: list = field(default_factory=list)   # Section headings before the article.
    label: str = ""            # Original label: "πρώτο" for worded numbers, "ΠΑΡΑΡΤΗΜΑ Ι" for annexes.


@dataclass
class Act:
    kind: str                  # ν. | π.δ. | ΠΝΠ | διορθ.
    number: str | None         # "4067". The caller knows the year.
    title: str = ""
    page: int = 1
    articles: list = field(default_factory=list)
    annexes: list = field(default_factory=list)
    preamble: list = field(default_factory=list)    # Text before the first article (e.g. corrigenda).
    signed: str | None = None                      # Last signature line, e.g. «Αθήνα, 9 Απριλίου 2012».


TRACE = re.compile(os.environ["NOK_TRACE"]) if os.environ.get("NOK_TRACE") else None
HEADER_ZONE = 0.095            # Fraction of page height. Body text starts at about 0.10.
PARA_INDENT = (3, 16)          # First-line indent of a paragraph, in points.
STANDOUT_INDENT = 18           # Headings are indented more than paragraphs.
SOFT_HYPHEN = "­"

_LINE = re.compile(r'<line xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</line>', re.S)
_WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>')
_PAGE = re.compile(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', re.S)

HYPH = re.compile(r"([^\W\d_])[-‐−­]$")
_UNITS_W = {"πρώτο": 1, "δεύτερο": 2, "τρίτο": 3, "τέταρτο": 4, "πέμπτο": 5, "έκτο": 6, "έβδομο": 7,
            "όγδοο": 8, "ένατο": 9}
_TENS_W = {"δέκατο": 10, "εικοστό": 20, "τριακοστό": 30, "τεσσαρακοστό": 40, "πεντηκοστό": 50, "εξηκοστό": 60,
           "εβδομηκοστό": 70, "ογδοηκοστό": 80, "ενενηκοστό": 90, "εκατοστό": 100}
_ORD = "(?:(?:{t})(?:\\s+(?:{u}))?|ενδέκατο|δωδέκατο|{u})".format(t="|".join(_TENS_W), u="|".join(_UNITS_W))
ARTICLE = re.compile(rf"^Άρθρο\s+(\d+[Α-Ω]?|{_ORD})$")
# Some issues put the title on the heading line. Accept this only with a large indent, outside the contents.
ARTICLE_INLINE = re.compile(rf"^Άρθρο\s+(\d+[Α-Ω]?|{_ORD})\s+([^\d«(].*)$")
# «ΠΑΡΑΡΤΗΜΑ», «ΠΑΡΑΡΤΗΜΑ ΙΙ», «ΠΑΡΑΡΤΗΜΑ Α΄», «ΠΑΡΑΡΤΗΜΑ ΑΡΘΡΟΥ 76»: at most 3 tokens without lower case.
ANNEX = re.compile(r"^ΠΑΡΑΡΤΗΜΑ((?:\s+[^\sa-zα-ωά-ώ]+){0,3})$")
ACT = re.compile(r"^(ΝΟΜΟΣ|ΠΡΟΕΔΡΙΚΟ\s+ΔΙΑΤΑΓΜΑ|ΠΡΑΞΗ\s+ΝΟΜΟΘΕΤΙΚΟΥ\s+ΠΕΡΙΕΧΟΜΕΝΟΥ|ΔΙΟΡΘΩΣΕΙΣ\s+ΣΦΑΛΜΑΤΩΝ)"
                 r"(?:\s+ΥΠ[’'΄]?\s*ΑΡΙΘ\S*\s*(\d+))?")
KIND = {"ΝΟΜΟΣ": "ν.", "ΠΡΟΕΔΡΙΚΟ": "π.δ.", "ΠΡΑΞΗ": "ΠΝΠ", "ΔΙΟΡΘΩΣΕΙΣ": "διορθ."}
SIGNED = re.compile(r"^Αθήνα,\s*\d{1,2}\s+\S+\s+\d{4}")
# Some issues print the article with a Latin letter («H ΠΡΟΕΔΡΟΣ»). degreekify does not change a one-letter word.
PRESIDENT = re.compile(r"^[ΟΗOH]\s+ΠΡΟΕΔΡΟΣ")
LEVEL = re.compile(r"^(ΜΕΡΟΣ|ΚΕΦΑΛΑΙΟ|ΥΠΟΚΕΦΑΛΑΙΟ|ΤΜΗΜΑ|ΕΝΟΤΗΤΑ|ΤΙΤΛΟΣ)\b")
NOISE = re.compile(r"^(Αρ\. Φύλλου \d+|\d{1,2}\s+\S+\s+\d{4})$")
MONTHS = "Ιανουαρίου|Φεβρουαρίου|Μαρτίου|Απριλίου|Μα[ΐί]ου|Ιουνίου|Ιουλίου|Αυγούστου|Σεπτεμβρίου|Οκτωβρίου|Νοεμβρίου|Δεκεμβρίου"
# The issue date in the masthead of page 1 («9 Απριλίου 2012»). It is alone on its line, in the right column.
MASTHEAD_DATE = re.compile(rf"^\d{{1,2}}\s+(?:{MONTHS})\s+\d{{4}}$")
# A line that starts body text, not a title line: a numbering marker, a quote or a sub-heading.
NOT_TITLE = re.compile(r"^(?:\d+[Α-Ω]?[.)]|[α-ω]{1,4}[΄'’]?[.)]|«|Άρθρο\s|Παράγραφος\s|ΠΑΡΑΓΡΑΦΟΣ\s)")
# A numbering marker and a space. A title line does not start with this. A paragraph does.
# «ν. 4067/2012» is a law citation, not a marker.
TITLE_STOP = re.compile(r"^(?:\d+[Α-Ω]?[.)]|[α-ω]{1,4}[΄'’]?[.)])\s(?!\s*\d{3,}/)")
# An abbreviation at the end of a line: «Α.Ε.», «κ.λπ.». The full stop does not end a sentence.
ABBREV_END = re.compile(r"(?:^|\s)(?:[Α-Ωα-ω]{1,2}\.){2,}$")
# A word from an invisible text layer with a broken font map, e.g. «dZF]dbXge» (the Code, ΦΕΚ Α΄ 88/2026).
BROKEN = re.compile(r"[\x00-\x1f\^\\\[\]_`<>{}|#$&@~]")
CONTROL = re.compile(r"[\x00-\x1f]")
GREEK_CHAR = re.compile(r"[Ͱ-Ͽἀ-῿]")
BROKEN_MIN = 20                # Fewer broken words than this on a page: keep all words.
TOUCH = 0.5                    # Points. Two words closer than this are one word that pdftotext split.
MIN_COLUMN_LINE = 0.2          # Fraction of the page width. Shorter lines do not set the right column edge.


def article_number(label: str) -> tuple[str, bool]:
    """Return (number, worded). Example: "12Α" -> ("12Α", False), "δέκατο τρίτο" -> ("13", True)."""
    if label[0].isdigit():
        return label, False
    special = {"ενδέκατο": 11, "δωδέκατο": 12}
    n = special.get(label) or sum(_TENS_W.get(w, 0) + _UNITS_W.get(w, 0) for w in label.split())
    return str(n), True


def _broken_heights(words) -> set[float]:
    """Return the word heights of an invisible text layer with a broken font map.

    On some pages a second text layer lies on top of the real text. Its words
    have no Greek letters, contain characters such as «^» or «]», and have their
    own font size. The function returns the heights of that layer, or an empty set.
    """
    broken = Counter(round(w[3] - w[1], 1) for w in words if BROKEN.search(w[4]) and not GREEK_CHAR.search(w[4]))
    if sum(broken.values()) < BROKEN_MIN:
        return set()
    greek = Counter(round(w[3] - w[1], 1) for w in words if GREEK_CHAR.search(w[4]))
    body = greek.most_common(1)[0][0] if greek else None
    return {h for h, n in broken.items() if n >= 5 and h != body}


FRAGMENT_GAP = 10              # Points. Fragments of one line are closer. Two text columns are further apart.


def _merge_fragments(groups):
    """Join line fragments that pdftotext split around the words of a broken text layer.

    The fragments of one line have the same top edge and almost touch. The function
    sorts the words of each joined line from left to right.
    """
    groups = sorted((ws for ws in groups if ws), key=lambda ws: min(w[1] for w in ws))
    rows, out = [], []
    for ws in groups:
        y = min(w[1] for w in ws)
        if rows and abs(y - rows[-1][0]) <= 1.5:
            rows[-1][1].append(ws)
        else:
            rows.append((y, [ws]))
    for _, row in rows:
        row.sort(key=lambda ws: min(w[0] for w in ws))
        cur = list(row[0])
        for ws in row[1:]:
            if min(w[0] for w in ws) - max(w[2] for w in cur) <= FRAGMENT_GAP:
                cur += ws
            else:
                out.append(sorted(cur, key=lambda w: w[0]))
                cur = list(ws)
        out.append(sorted(cur, key=lambda w: w[0]))
    return out


def _line_text(ws) -> str:
    """Join the words of one line. Two words that touch are one word. pdftotext splits some words."""
    out = ws[0][4]
    for a, b in zip(ws, ws[1:]):
        out += ("" if abs(b[0] - a[2]) < TOUCH else " ") + b[4]
    return out


def lines(pdf: Path) -> list[Line]:
    """Return the body lines in reading order. The page header is removed."""
    out = []
    for p, m in enumerate(_PAGE.finditer(pdftotext(pdf, "-bbox-layout")), 1):
        W, H = float(m.group(1)), float(m.group(2))
        raw = [[(*map(float, w[:4]), html.unescape(w[4])) for w in _WORD.findall(l.group(5))]
               for l in _LINE.finditer(m.group(3))]
        # Find the heights of the broken layer first: its words with control characters count.
        bad = _broken_heights([w for ws in raw for w in ws])
        # A word with a control character and no Greek letter is not text. Remove it.
        raw = [[w for w in ws if not CONTROL.search(w[4]) or GREEK_CHAR.search(w[4])] for ws in raw]
        if bad:
            raw = _merge_fragments([[w for w in ws if round(w[3] - w[1], 1) not in bad or GREEK_CHAR.search(w[4])]
                                    for ws in raw])
        ls = []
        for ws in raw:
            if not ws:
                continue
            x0, y0 = min(w[0] for w in ws), min(w[1] for w in ws)
            x1, y1 = max(w[2] for w in ws), max(w[3] for w in ws)
            if x0 < -2 or x1 > W + 2:
                continue                            # Text outside the page is an embedded layer, not body text.
            t = CONTROL.sub("", degreekify(_line_text(ws))).strip()
            if t.endswith(SOFT_HYPHEN):
                t = t[:-1] + "-"                    # A soft hyphen at line end is a word break.
            t = t.replace(SOFT_HYPHEN, "")
            t = re.sub(r"^(?:[΄'’`]\s?Αρθρο|ΑΡΘΡΟ)(?=\s+\d)", "Άρθρο", t)
            if t and y1 >= H * HEADER_ZONE:
                ls.append(Line(p, x0, y0, x1, y1, t))
        # The right column starts at the left edge of the lines in the right half of the page.
        # A short line (a table cell, a centred heading) does not set the edge.
        right = [l.x0 for l in ls if l.x0 > W / 2 - 5 and l.x1 - l.x0 > W * MIN_COLUMN_LINE]
        right = right or [l.x0 for l in ls if l.x0 > W / 2 - 5]
        rstart = min(right) if right else W
        for l in ls:
            l.col = "L" if l.x1 < rstart - 2 else "R" if l.x0 >= rstart - 2 else "S"
        # Most lines cross the middle: this is a single-column page.
        if sum(l.col == "S" for l in ls) > len(ls) / 2:
            for l in ls:
                l.col = "S"
        # Full-width lines split the page into bands. In each band, read left, then right.
        ls.sort(key=lambda l: (l.y0, l.x0))
        band = []

        def flush():
            out.extend(sorted((l for l in band if l.col == "L"), key=lambda l: l.y0))
            out.extend(sorted((l for l in band if l.col == "R"), key=lambda l: l.y0))
            band.clear()
        for l in ls:
            if l.col == "S":
                flush()
                out.append(l)
            else:
                band.append(l)
        flush()
    return out


def _margins(ls):
    """Return the left and right text edge for each (page, column).

    The edges come from full-width lines. A column with few lines has no
    reliable edge. It gets the most common edge of pages with the same parity.
    """
    groups = defaultdict(list)
    for l in ls:
        groups[(l.page, l.col)].append(l)
    res, parity = {}, defaultdict(Counter)
    for k, v in groups.items():
        x1 = max(l.x1 for l in v)
        full = [l.x0 for l in v if l.x1 > x1 - 3]
        res[k] = (min(full) if full else min(l.x0 for l in v), x1)
        if len(v) >= 12:
            parity[(k[0] % 2, k[1])][(round(res[k][0], 1), round(x1, 1))] += 1
    for k, v in groups.items():
        common = parity.get((k[0] % 2, k[1]))
        if len(v) < 12 and common:
            res[k] = common.most_common(1)[0][0]
    return res


def join(a: str, b: str) -> str:
    """Join two lines. Remove the hyphen only when the next line continues the word."""
    if not a:
        return b
    if HYPH.search(a) and b[:1].isalpha() and a[-2].islower() == b[0].islower():
        return a[:-1] + b
    if a.endswith("/") and b[:1].isdigit():         # «ν. 4014/» + «2011»
        return a + b
    return a + " " + b


def _upper(t):
    letters = [c for c in t if c.isalpha()]
    return len(letters) > 3 and all(c.isupper() for c in letters)


def _quote_state(inside: bool, text: str) -> bool:
    """Return the quote state after a paragraph.

    In Greek drafting, each quoted paragraph opens with «, but only the last
    one closes with ». So the parser does not count depth. The state stays
    open until a paragraph closes more quotes than it opens.
    """
    o, c = text.count("«"), text.count("»")
    return (c <= o) if inside else (o > c)


_COMMON = {"τροπο", "αρθρο", "προσθ", "αντικ", "καταρ", "ρυθμι", "διατα", "σχετι"}


def _stems(t: str) -> set[str]:
    """Return 5-letter stems of the words in a title, without accents."""
    t = "".join(c for c in unicodedata.normalize("NFD", t.lower()) if not unicodedata.combining(c))
    return {w[:5] for w in re.findall(r"[^\W\d_]{4,}", t)}


def _same_title(body: str, toc: str) -> bool:
    """Compare an article title with its contents entry.

    The two texts are not always equal, so a sufficient word overlap is enough.
    An article of another law with the same number usually has no overlap.
    Common words («Τροποποίηση», ...) count only if a title has no other words.
    """
    a, b = _stems(" ".join(body.split()[:10])), _stems(toc)
    shared = a & b
    if not shared:
        return False
    if shared - _COMMON:
        return len(shared) >= max(1, round(0.3 * len(a)))
    return not (a - _COMMON) or not (b - _COMMON)


def _toc(ls) -> dict[tuple[str, bool], list[str]]:
    """Return the table of contents as {(number, worded): [titles]}.

    One number can occur more than once (e.g. articles of an annexed protocol),
    so each key keeps all titles. The result is empty for issues without contents.
    """
    toc, cur, inside = {}, None, False
    for l in ls:
        if l.text.startswith("ΠΙΝΑΚΑΣ ΠΕΡΙΕΧΟΜΕΝΩΝ"):
            inside = True
            continue
        if not inside:
            continue
        if ARTICLE.match(l.text):            # The first standalone heading ends the contents.
            break
        m = ARTICLE_INLINE.match(l.text) or re.match(r"^Άρθρο\s+(\d+[Α-Ω]?)\s*[:.-]\s*(.*)$", l.text)
        if m:
            cur = article_number(m.group(1))
            toc.setdefault(cur, []).append(m.group(2).lstrip(":.- "))
        elif cur and not NOISE.match(l.text) and not _upper(l.text) and not l.text.startswith("Άρθρο "):
            toc[cur][-1] = join(toc[cur][-1], l.text)
        else:
            cur = None
    return toc


def _lookahead_title(ls, i, margins, inline):
    """Return the title that a heading on line i would get. Do not consume lines.

    If the next lines are not aligned like a title, return the next line.
    """
    if inline:
        return inline
    l = ls[i]
    title = ""
    for q in ls[i + 1:i + 6]:
        qx0, qx1 = margins.get((q.page, q.col), (q.x0, q.x1))
        ind, gap = q.x0 - qx0, qx1 - q.x1
        if abs(q.x0 - l.x0) < 2.5 or (ind > 2 and gap > 2 and abs(ind - gap) < 3.5):
            title = join(title, q.text)
        else:
            break
    return title or (ls[i + 1].text if i + 1 < len(ls) else "")


def _better_heading(ls, i, num, n_int, titles, margins) -> bool:
    """Return True if a later standalone «Άρθρο num» matches the contents title.

    The search stops at the heading of the next article number.
    """
    for k in range(i + 1, len(ls)):
        m = ARTICLE.match(ls[k].text)
        if not m:
            continue
        n, _ = article_number(m.group(1))
        if n == num and any(_same_title(_lookahead_title(ls, k, margins, ""), t) for t in titles):
            return True
        if re.match(r"\d+", n) and int(re.match(r"\d+", n).group()) == n_int + 1:
            return False
    return False


def _title_tail(title, text, gap_r, nxt, margins) -> bool:
    """Return True if a short line is the last line of a title with the wrong alignment.

    Some issues set the last title line at the paragraph indent, for example
    «Τροποποιήσεις των διατάξεων εκδόσεως» + «αδειών δόμησης». Such a line is short,
    has no numbering marker and no final stop, and a new paragraph starts after it.
    """
    if not title or title[-1] in ".:;·»)" or gap_r < 20 or NOT_TITLE.match(text) or _upper(text) or nxt is None:
        return False
    if text[-1] in ".:;·" and not ABBREV_END.search(text):     # «Α.Ε.» ends a title. A sentence does not.
        return False
    nx0, _ = margins.get((nxt.page, nxt.col), (nxt.x0, nxt.x1))
    return PARA_INDENT[0] < nxt.x0 - nx0 < PARA_INDENT[1] or bool(ARTICLE.match(nxt.text))


def _split_quoted_heads(heads: list[str]) -> tuple[list[str], list[str]]:
    """Return (headings that belong to quoted text, section headings of the next article).

    An upper-case line that opens or closes a quote («ΚΕΦΑΛΑΙΟ Γ΄ ...».) is text that an
    amendment inserts. It ends the previous article. It is not a heading of the next article.
    """
    k = max((i for i, h in enumerate(heads) if h.startswith("«") or h.count("»") > h.count("«")), default=-1)
    return heads[:k + 1], heads[k + 1:]


def parse(pdf: Path) -> list[Act]:
    return parse_lines(lines(pdf))


def parse_lines(ls: list[Line], act: Act | None = None, toc: dict | None = None,
                margins: dict | None = None) -> list[Act]:
    """Parse lines into acts, articles and paragraphs.

    Without `act`, the lines are a whole issue. With `act`, the lines are the body
    of that act, for example a code that a ratifying law quotes. `toc` and `margins`
    replace the contents and text edges that the function finds in the lines.
    Give them from all lines of the issue when `ls` is only a part of a page.
    """
    margins = _margins(ls) if margins is None else margins
    toc = _toc(ls) if toc is None else toc
    acts: list[Act] = [act] if act else []
    art = None
    buf, buf_page, inside = "", 0, False
    title_mode = None            # None | "center" | "upper" | x0 of the heading
    head_x = None                # x0 of the current multi-line section heading
    act_title_open = False
    in_toc = False               # From «ΠΙΝΑΚΑΣ ΠΕΡΙΕΧΟΜΕΝΩΝ» to the first standalone heading
    pending_heads = []
    style = None                 # False: «Άρθρο 1», True: «Άρθρο πρώτο». One style per act.
    closed = False               # True after a signature line, until the next article or annex
    outer = None                 # (act, style) of a ratifying law while the parser reads the code it ratifies
    skip = 0

    def flush():
        nonlocal buf, inside
        if not buf:
            return
        p = Para(buf, buf_page, quoted=inside)
        inside = _quote_state(inside, buf)
        # A paragraph without a letter or a digit is not text. A paragraph without a Greek letter
        # and with symbols of a broken font is not text. Do not keep them.
        is_text = re.search(r"[^\W_]", buf) and (GREEK_CHAR.search(buf) or len(BROKEN.findall(buf)) < 3)
        if act is not None and not closed and is_text:
            (art.paras if art is not None else act.preamble).append(p)
        buf = ""

    for li, l in enumerate(ls):
        if skip:
            skip -= 1
            continue
        x0, x1 = margins.get((l.page, l.col), (l.x0, l.x1))
        indent, gap_r = l.x0 - x0, x1 - l.x1
        loose_center = indent > 2 and gap_r > 2 and abs(indent - gap_r) < 3.5
        strict_center = indent > 12 and gap_r > 12 and abs(indent - gap_r) < 6
        standout = strict_center or indent > STANDOUT_INDENT
        text = l.text
        if text == "ΠΡΑΞΗ" and li + 1 < len(ls) and ls[li + 1].text.startswith("ΝΟΜΟΘΕΤΙΚΟΥ"):
            text, skip = text + " " + ls[li + 1].text, 1      # Header split on two lines.
        if l.page == 1 and MASTHEAD_DATE.match(text):
            continue

        m = ACT.match(text)
        # An act header fills the whole line. A mention inside a sentence is not a header.
        if m and m.end() >= len(text.rstrip(".")) and not inside and not buf:
            flush()
            act = Act(KIND[m.group(1).split()[0]], m.group(2), page=l.page)
            acts.append(act)
            art, title_mode, inside, pending_heads, style, closed = None, None, False, [], None, False
            act_title_open = act.kind != "διορθ."
            continue
        if act is None:
            continue
        if act_title_open:
            if PRESIDENT.match(text) or ARTICLE.match(text) or text.startswith(("ΠΙΝΑΚΑΣ ΠΕΡΙΕΧΟΜΕΝΩΝ", "Εκδίδομε")):
                act_title_open = False
            else:
                if not NOISE.match(text):        # «Αρ. Φύλλου 67» from the right column
                    act.title = join(act.title, text)
                continue
        quoted_now = _quote_state(inside, buf) if buf else inside
        if SIGNED.match(text) and not quoted_now and not closed:
            flush()
            act.signed, art, closed = text, None, True
            continue

        # Annex: a centred «ΠΑΡΑΡΤΗΜΑ» line, before or after the signature.
        am = ANNEX.match(text)
        if am and (strict_center or indent > STANDOUT_INDENT) and not quoted_now:
            flush()
            quoted_heads, pending_heads = _split_quoted_heads(pending_heads)
            if art is not None:
                art.paras.extend(Para(h, l.page, quoted=True) for h in quoted_heads)
            closed, inside = False, False
            art = Article("Π-" + am.group(1).strip().replace(" ", "-"), l.page, headings=pending_heads, label=text)
            pending_heads = []
            act.annexes.append(art)
            title_mode = "upper"
            continue

        if text.startswith("ΠΙΝΑΚΑΣ ΠΕΡΙΕΧΟΜΕΝΩΝ"):
            in_toc = True
        m = ARTICLE.match(text)
        exact = bool(m)
        if m:
            in_toc = False
        elif not in_toc and (indent > STANDOUT_INDENT or strict_center):
            m = ARTICLE_INLINE.match(text)
        if m:
            num, worded = article_number(m.group(1))
            n_int = int(re.match(r"\d+", num).group())
            if outer is not None and worded == outer[1] and (standout or not buf or buf.rstrip()[-1:] in ".»:;·)"):
                # A heading in the style of the ratifying law, with its next number, ends the ratified
                # act («Άρθρο δεύτερο» after a code, «Άρθρο 2» after a ΠΝΠ). Return to the ratifying law.
                o_last = outer[0].articles[-1].num
                if n_int == int(re.match(r"\d+", o_last).group()) + 1:
                    flush()
                    act, style = outer
                    outer, art, inside = None, None, False
            # A ratifying law quotes a whole act: a code after «Άρθρο πρώτο», a ΠΝΠ after «Άρθρο 1».
            # The first heading of the quoted act has the other style and the number 1.
            # The parser reads the quoted act as its own act, so its articles get their own numbers.
            ratified = outer is None and style is not None and style != worded and n_int == 1 and exact \
                and len(act.articles) == 1 and art is not None \
                and ("Κύρωση" in act.title + art.title or any("Κυρώνεται" in p.text for p in art.paras))
            last = "0" if ratified else act.articles[-1].num if act.articles else "0"
            expected = int(re.match(r"\d+", last).group()) + 1
            same_style = ratified or style is None or style == worded
            # Numbers run in sequence within one act. Allow one missed article (N+2) and "19Α".
            in_sequence = n_int in (expected, expected + 1) or (n_int == expected - 1 and num[-1].isalpha())
            ended = not buf or buf.rstrip()[-1:] in ".»:;·)"
            accept = False
            if (standout or (exact and n_int == expected and ended)) and same_style:
                titles = toc.get((num, worded))
                if titles:
                    # With contents, the title decides, together with a plausible sequence.
                    inline = m.group(2) if m.re is ARTICLE_INLINE else ""
                    guess = _lookahead_title(ls, li, margins, inline)
                    accept = any(_same_title(guess, t) for t in titles) and \
                        (expected <= n_int <= expected + 3 or (n_int == expected - 1 and num[-1].isalpha()))
                    if not accept and exact and standout and n_int == expected and not quoted_now:
                        # The text layer can scramble the title lines. Accept the heading if no later
                        # heading with this number matches the contents title before the next article.
                        accept = not _better_heading(ls, li, num, n_int, titles, margins)
                else:
                    accept = in_sequence and (not quoted_now or n_int == expected) and (standout or not quoted_now)
            if TRACE and TRACE.search(text):
                print(f"TRACE p{l.page}{l.col} {text[:40]!r} indent={indent:.1f} expected={expected} "
                      f"standout={standout} quoted_now={quoted_now} "
                      f"toc={str(toc.get((num, worded), '-'))[:60]!r} accept={accept}")
            if accept:
                flush()
                quoted_heads, pending_heads = _split_quoted_heads(pending_heads)
                if quoted_heads:
                    (art.paras if art is not None else act.preamble).extend(
                        Para(h, l.page, quoted=True) for h in quoted_heads)
                if ratified:
                    outer = (act, style)
                    act = Act("κώδ.", act.number, title=art.title if art is not None else "", page=l.page)
                    acts.append(act)
                inside, closed, style = False, False, worded
                art = Article(num, l.page, headings=pending_heads, label=m.group(1) if worded else "",
                              title=m.group(2) if m.re is ARTICLE_INLINE else "")
                pending_heads = []
                act.articles.append(art)
                title_mode = "center" if strict_center else l.x0
                continue
        if closed:                           # Signatures after «Αθήνα, ...»
            continue
        if art is not None and title_mode is not None and not buf:
            if re.fullmatch(r"\d{1,4}", text) and not art.title:
                continue                     # A page number or figure label between a heading and its title.
            if title_mode == "center":
                # A title line can fill almost the whole column («Αρχής Προσφυγών και Υπηρεσίας ...»).
                # A body line fills it exactly, so both edge gaps are near 0.
                cont = loose_center or (bool(art.title) and indent > 1 and gap_r > 1 and abs(indent - gap_r) < 1)
            elif title_mode == "upper":
                cont = _upper(text) and (loose_center or standout)
            else:
                cont = abs(l.x0 - title_mode) < 2.5
            if TITLE_STOP.match(text):           # «1. Όταν ...» is the first paragraph, not the title.
                cont = False
            if not cont and title_mode != "upper":
                cont = _title_tail(art.title, text, gap_r, ls[li + 1] if li + 1 < len(ls) else None, margins)
            if cont:
                art.title = join(art.title, text)
                continue
            title_mode = None

        # Section heading. A continuation line can have few letters («ΚΑΙ 4067/2012»).
        continues_head = head_x is not None and bool(pending_heads) and abs(l.x0 - head_x) < 2.5 \
            and not any(c.islower() for c in text)
        if (_upper(text) or continues_head) and standout and not quoted_now \
                and not PRESIDENT.match(text) and text != "ΤΗΣ ΕΛΛΗΝΙΚΗΣ ΔΗΜΟΚΡΑΤΙΑΣ":
            flush()
            if continues_head and not LEVEL.match(text):
                pending_heads[-1] = join(pending_heads[-1], text)
            else:
                pending_heads.append(text)
            head_x = l.x0
            continue
        head_x = None

        if pending_heads and art is not None:
            # Upper-case lines that no article follows are body text (e.g. «Ε) ΣΙΝΑΪΤΙΚΗ ΑΔΕΛΦΟΤΗΣ»).
            art.paras.extend(Para(h, l.page, quoted=inside) for h in pending_heads)
            pending_heads = []
        if PARA_INDENT[0] < indent < PARA_INDENT[1] or not buf:
            flush()
            buf_page = l.page
        buf = join(buf, text)
    flush()
    return acts


def broken_pages(pdf: Path) -> set[int]:
    """Return the pages that have an invisible text layer with a broken font map.

    On these pages plain `pdftotext` mixes real and broken words, so it is not a reliable reference.
    """
    out = set()
    for p, m in enumerate(_PAGE.finditer(pdftotext(pdf, "-bbox-layout")), 1):
        words = [(*map(float, w[:4]), html.unescape(w[4])) for w in _WORD.findall(m.group(3))]
        if _broken_heights(words):
            out.add(p)
    return out


def first_body_lines(pdf: Path) -> dict[int, str]:
    """Return the first body line of each page. The validator uses it to find lost page tops."""
    res = {}
    for l in lines(pdf):
        res.setdefault(l.page, l.text)
    return res
