"""Convert a Gazette issue into structured JSON: text, paragraph ids and metadata.

  - The main act of a dataset (the NOK, ΦΕΚ Α΄ 79/2012): all articles.
  - Each other issue: only the relevant articles. These are the articles that cite the
    law of the dataset, the articles of the same law that refer to them, the commencement
    article, and the annexes they refer to. An issue that names the law only without its
    number gets `review: true`.

The JSON file is the source of truth. render.py writes the markdown from it.
The Code itself (ΦΕΚ Α΄ 88/2026) has its own converter in kodikas.py.
"""
import re
from collections import Counter

from common import PDF, download, fek_id, fek_url, issued, write_json
from datasets import Dataset
import extract

# Numbering marker at the start of a paragraph: «2.», «ιβ.», «α)», or a chain «1.α.».
# «ν. 4067/2012» is a law citation, not the marker «ν.».
ARABIC = re.compile(r"(\d{1,3}[Α-Ω]?)[.)](?!\d)\s*")
GREEK = re.compile(r"([α-ω]{1,5})[΄'’]?[.)]\s*(?!\d{3,}/)")
# Decimal numbering, as the fire code prints it: «5.3.7.1.» is paragraph 5.3.7.1 of article 5.
DECIMAL = re.compile(r"(\d{1,2}(?:\.\d{1,2}){1,4})\.?\s+")
_UNITS = {"α": 1, "β": 2, "γ": 3, "δ": 4, "ε": 5, "στ": 6, "ζ": 7, "η": 8, "θ": 9}
_TENS = {"ι": 10, "κ": 20, "λ": 30, "μ": 40, "ν": 50, "ξ": 60, "ο": 70, "π": 80}

COMMENCEMENT = re.compile(r"Έναρξη\s+ισχύος")
# «άρθρων 66 έως 71», «του άρθρου 67 και 68»: article numbers of the same law.
# A number can carry a letter: «13Α», «13α», «14β».
INTERNAL = re.compile(r"άρθρ(?:ο|ου|α|ων)\s+((?:\d+(?:[Α-Ωα-ω](?![α-ωά-ώ]))?\s*(?:,|έως\s+και|και|έως|ως|-)\s*)*"
                      r"\d+(?:[Α-Ωα-ω](?![α-ωά-ώ]))?)")
EXTERNAL = re.compile(r"\s*(?:του|της|των)\s+(?:ν\.|νόμου|π\.δ\.|Κώδικα|Ν\.Ο\.Κ\.|Νέου|κ\.υ\.α\.|ΚΥΑ|υπ’|Συντάγματος)"
                      r"|\s*(?:ν\.|\()")
# A law named after the numbers and their subdivisions, before the next «άρθρ...»: «των άρθρων 13 περίπτωση α΄
# και 263Α του Ποινικού Κώδικα», «τα άρθρα 4 έως 7 του από 5/17.9.1935 π.δ.».
LAW_AFTER = re.compile(r"(?:του|της|των)\s+(?:ν\.|ν\.δ\.|β\.δ\.|α\.ν\.|νόμου|π\.δ\.|από\s+\d|[Α-Ω]\w+\s+Κώδικα|Κώδικα"
                       r"|Ν\.Ο\.Κ\.|ΝΟΚ|κ\.υ\.α\.|ΚΥΑ|υπ’|Συντάγματος)")
OWN_LAW = re.compile(r"\s*(?:του|της)\s+(?:παρόντος|παρούσας|ίδιου|ιδίου)")
JOINED = re.compile(r"\s*(?:,|και)\s*(?:το|του|τα|των|στο|στα)?\s*")     # Between two references of one list.
LAW_WINDOW = 80                      # Characters after the numbers in which LAW_AFTER is looked for.


def greek_numeral(s):
    """Return the value of a Greek numeral ("ιστ" -> 16). Return None if s is not a numeral (e.g. "και")."""
    tens = _TENS.get(s[:1], 0)
    rest = s[1:] if tens else s
    if not rest:
        return tens or None
    return tens + _UNITS[rest] if rest in _UNITS else None


def markers(text, decimal: str | None = None):
    """Return the numbering markers at the start of the text: «5. α) ...» -> [("1", 5, "5"), ("α", 1, "α")].

    Letters that are not a numeral can be a sub-clause, the label of its clause and a numeral:
    «ιστα)» is sub-clause α of clause ιστ, «αστ)» sub-clause στ of clause α. They come back as
    ("α?", None, "ιστα"). Levels.enter resolves them against the open clause, or drops them.
    With `decimal`, the number of an article that numbers its paragraphs decimally, «5.3.7.1.»
    comes back as ("d", None, "3.7.1"): the full path below the article. Another first number
    («17.2.1989») is not a marker.
    """
    t, out = text, []
    if decimal and (m := DECIMAL.match(t)) and m.group(1).split(".", 1)[0] == decimal:
        out.append(("d", None, m.group(1).split(".", 1)[1]))
        t = t[m.end():]
    while True:
        if (m := ARABIC.match(t)):
            out.append(("1", int(re.match(r"\d+", m.group(1)).group()), m.group(1)))
        elif (m := GREEK.match(t)) and (v := greek_numeral(m.group(1))):
            out.append(("α", v, m.group(1)))
        elif (m := GREEK.match(t)) and len(m.group(1)) >= 2:
            out.append(("α?", None, m.group(1)))
        else:
            return out
        t = t[m.end():]


def label(act, year):
    return f"{act.kind[0].upper()}{act.kind[1:]} {act.number}/{year}" if act.number else f"{act.kind} {year}"


class Levels:
    """A stack of numbering levels, for example «6.» -> «ιδ.» -> «α)».

    The hierarchy is not fixed. In the NOK, clause 11.6.ιβ has sub-paragraphs 1., 2.,
    and clause ιζ has sub-clauses α)-γ). A marker that continues an open level of the
    same type (value = last + 1) returns to it. A marker with value 1 opens a new level.
    """

    def __init__(self):
        self.stack = []              # [(type, value, label)]
        self.closed = None           # The clause close_clause took off, until the next marker.

    def subclause(self, lab):
        """Resolve «ιστα» against the open clauses: ("αα", 1, "α") under clause ιστ, or None."""
        for depth in range(len(self.stack) - 1, -1, -1):
            kind, _, parent = self.stack[depth]
            rest = lab[len(parent):]
            if kind == "α" and lab.startswith(parent) and rest and (v := greek_numeral(rest)):
                del self.stack[depth + 1:]
                return ("αα", v, rest)
        return None

    def enter(self, chain) -> str | None:
        """Add the markers of one paragraph. Return the path of labels, for example "6.ιδ".

        A sub-clause candidate that resolves against no open clause ends the chain. If no marker
        is left, return None and leave the levels unchanged: the paragraph is unnumbered text.
        """
        saved, entered = list(self.stack), 0
        if self.closed and chain and (chain[0][:2] == (self.closed[0], self.closed[1] + 1)
                                      or chain[0][0] == "α?" and chain[0][2].startswith(self.closed[2])):
            self.stack.append(self.closed)          # The closed list goes on: «γ)» or «βα)» after «β).».
        for kind, value, lab in chain:
            if kind == "d":                         # A decimal number gives the whole path.
                new, old = [int(x) for x in lab.split(".")], [v for k, v, _ in self.stack if k == "d"]
                if len(old) >= len(new) and old[:len(new) - 1] == new[:-1] and new[-1] <= old[len(new) - 1]:
                    new[-1] = old[len(new) - 1] + 1     # A number that goes back or repeats is a misprint.
                self.stack = [("d", x, str(x)) for x in new]
                entered += 1
                continue
            if kind == "α?":
                if (sub := self.subclause(lab)) is None:
                    break
                self.stack.append(sub)              # subclause() left its clause on top.
                entered += 1
                continue
            for depth in range(len(self.stack) - 1, -1, -1):
                if self.stack[depth][0] == kind and self.stack[depth][1] == value - 1:
                    del self.stack[depth:]
                    break
            else:
                if value != 1:       # No match: use the level of the nearest marker of the same type.
                    same = [d for d in range(len(self.stack)) if self.stack[d][0] == kind]
                    if same:
                        del self.stack[same[-1]:]
            self.stack.append((kind, value, lab))
            entered += 1
        if not entered:
            self.stack = saved
            return None
        self.closed = None
        return ".".join(s[2] for s in self.stack)


def paragraph_ids(art, decimal: str | None = None):
    """Return an id for each paragraph: "article.paragraph.clause...".

    Text without a marker gets the previous id + "#k".
    Quoted text «...» is the text of another provision, for example the new text of a NOK
    article. It gets the id of the paragraph before the quote, then "~", then its own
    numbering. "120#1~4" is paragraph 4 of the text that paragraph "120#1" introduces.
    "120#1~4.γ#1" is text without a marker after its clause γ. Quoted text before the
    first quoted marker is "~#k". An id that occurs again in the article gets "@2", "@3", ...
    `decimal` is the printed article number of an article with decimal paragraphs (see markers).
    """
    own, quote = Levels(), None
    base, extra, anchor = art.num, Counter(), art.num
    qbase, qextra = "", Counter()
    out, seen = [], Counter()
    prev = ""
    # The first marker of the next numbered paragraph of the article's own text, for each paragraph.
    following, nxt = [None] * len(art.paras), None
    for k in range(len(art.paras) - 1, -1, -1):
        following[k] = nxt
        q = art.paras[k]
        if not (q.quoted or q.text.startswith("«")) and (chain := markers(q.text, decimal)):
            nxt = chain[0]
    for k, p in enumerate(art.paras):
        if not (p.quoted or p.text.startswith("«")):      # «στ. ...» is text of another law.
            if quote is not None:
                quote, prev = None, ""
            if (path := own.enter(markers(p.text, decimal))) is not None:
                base = pid = f"{art.num}.{path}"
                extra[base] = 0
                numbered = True
            else:
                if close_clause(own, prev, p.text, following[k]):
                    base = ".".join([art.num, *(s[2] for s in own.stack)])
                extra[base] += 1
                pid = f"{base}#{extra[base]}"
                numbered = False
        else:
            text = p.text.lstrip("«").lstrip()
            if quote is None:
                quote, anchor, qbase, qextra = Levels(), (out[-1] if out else art.num), "", Counter()
                prev, qdecimal = "", None
            if qdecimal is None and not quote.stack and (m := DECIMAL.match(text)):
                qdecimal = m.group(1).split(".", 1)[0]      # The new text of a decimal article: «6.1. Γενικά».
            chain = [("d", v, f"{qdecimal}.{lab}") if kind == "d" else (kind, v, lab)
                     for kind, v, lab in markers(text, qdecimal)]
            if (path := quote.enter(chain)) is not None:
                qbase = path
                qextra[qbase] = 0
                pid = f"{anchor}~{qbase}"
                numbered = True
            else:
                if close_clause(quote, prev):
                    qbase = ".".join(s[2] for s in quote.stack)
                qextra[qbase] += 1
                pid = f"{anchor}~{qbase}#{qextra[qbase]}"
                numbered = False
        prev = p.text if numbered else ""                 # Only a numbered clause can be closed.
        seen[pid] += 1
        out.append(pid if seen[pid] == 1 else f"{pid}@{seen[pid]}")
    return out


LAST_CLAUSE = False                  # Also close the last clause of a list that ends with «,» or «;» (not yet applied).


def close_clause(levels: Levels, prev: str, text: str = "", following=None) -> bool:
    """Close the open clause when unnumbered text follows a clause that ends a sentence.

    «β) Να αποτελεί ξεχωριστό πυροδιαμέρισμα.» followed by «Οι διάδρομοι ...»: the text belongs
    to the paragraph, not to clause β, and a later list «α) ...» starts again at the paragraph.
    The last clause of a list that ends with «,» or «;» is closed too: the text after it ends the
    sentence that introduces the list («γ) ... 900 τ.μ.,» then «αλλά και όπου αλλού απαιτείται ...»).
    A clause that ends with «:» introduces its own text, and one without punctuation («γ)
    Πυροσβεστήρες οροφής») is a heading: the text after them stays in the clause.
    """
    if not (levels.stack and levels.stack[-1][0] in ("α", "αα") and prev):
        return False
    kind, value, label = levels.stack[-1]
    end = prev.rstrip()
    last = following is None or not (following[:2] == (kind, value + 1)
                                     or following[0] == "α?" and following[2].startswith(label))
    if end.endswith(".") or (LAST_CLAUSE and last and end.endswith((",", ";", "·"))
                             and not re.match(r"[α-ω]{1,3}[΄'’]?\)", text)):
        levels.closed = levels.stack.pop()
        return True
    return False


def paragraphs_json(art, decimal: str | None = None) -> list[dict]:
    return [{"id": i, "page": p.page, **({"quoted": True} if p.quoted else {}), **printed(i, p.text), "text": p.text}
            for i, p in zip(paragraph_ids(art, decimal), art.paras)]


def printed(pid: str, text: str) -> dict:
    """Return {"printed": number} when a decimal number in quoted text is a misprint the id corrects.

    ν. 4710/2020 restates article 6 of the fire code with «6.1. Μετάδοση φωτιάς» for 6.6: "26.2~6.6".
    """
    local = pid.split("~")[-1]
    if "~" in pid and "#" not in local and (m := DECIMAL.match(text.lstrip("«").lstrip())) \
            and "." in local and not local.split("@")[0].endswith(m.group(1)):
        return {"printed": m.group(1)}
    return {}


def text_of(art):
    return art.title + " " + " ".join(p.text for p in art.paras)


def matches(art, primary, names):
    """Return "number" if the article cites the law by number, "name" if it names it only, else None."""
    text = text_of(art)
    if primary.search(text):
        return "number"
    if any(rx.search(text) for rx in names):
        return "name"
    return None


def internal_refs(art):
    """Return the article numbers of the same law that the article refers to.

    Only the article's own text counts. Text inside «...» belongs to another law.
    """
    own = [p.text for p in art.paras if not p.quoted and not p.text.startswith("«")]
    text = re.sub(r"«[^«»]*»", " ", art.title + " " + " ".join(own))
    out = set()
    refs = list(INTERNAL.finditer(text))
    external = [bool(EXTERNAL.match(text, m.end()) or not OWN_LAW.match(text, m.end())
                     and LAW_AFTER.search(text[m.end():m.end() + LAW_WINDOW].split("άρθρ")[0])) for m in refs]
    for k in range(len(refs) - 2, -1, -1):
        # «τα άρθρα 1 έως και 4 και το άρθρο 16 του ν. 719/1977»: the law named last is the law of both.
        if external[k + 1] and JOINED.fullmatch(text, refs[k].end(), refs[k + 1].start()):
            external[k] = True
    for m, ext in zip(refs, external):
        if ext:
            continue
        nums = re.findall(r"\d+", m.group(1))
        if "έως" in m.group(1) or "ως" in m.group(1).split() or "-" in m.group(1):    # A range.
            lo, hi = int(nums[0]), int(nums[-1])
            out |= {str(n) for n in range(lo, hi + 1)} if hi - lo < 50 else set()
        out |= set(nums)
    return out


def annex_referenced(annex, chosen):
    """Return True if a chosen article refers to this annex («Παράρτημα Ι»)."""
    numeral = annex.num.split("-", 1)[1]
    pattern = r"Παράρτημ\w*" + (r"\s+" + re.escape(numeral) + r"(?![\wΑ-Ω])" if numeral else "")
    return any(re.search(pattern, text_of(a), re.I) for a, _ in chosen)


GREEK_WORD = re.compile(r"[Ά-ώ]{3,}")


def commencement_end(art) -> int | None:
    """Return where a commencement article ends early, or None.

    The last article of an act can absorb an annex whose heading the parser cannot read (a broken
    font: ν. 4549/2018, ΦΕΚ Α΄ 105/2018, pages 60-78). A commencement article has only sentences,
    so it ends at its first paragraph without a Greek word: a table row of that annex.
    """
    return next((i for i, p in enumerate(art.paras) if i and not GREEK_WORD.search(p.text)), None)


def article_json(art, how, is_main, ds: Dataset, images: set[int] = frozenset()):
    scope = None
    if is_main and ds.building_rules and not art.num.startswith("Π-"):
        scope = "building_rules" if int(re.match(r"\d+", art.num).group()) in ds.building_rules else "other"
    paragraphs = paragraphs_json(art)
    cut = commencement_end(art) if how == "commencement" else None
    last = max([p.page for p in art.paras[:cut]] + [art.page])
    shown = sorted(p for p in images if art.page <= p <= last)   # Figures and tables printed as images.
    return {
        "article": art.num, **({"label": art.label} if art.label else {}),
        "title": art.title, "page": art.page, "headings": art.headings,
        **({"scope": scope} if scope else {}), **({"match": how} if not is_main else {}),
        **({"cut": f"Text from page {art.paras[cut].page} on is left out: it is an annex in a font the parser "
                   f"cannot read, not part of this article. See the source PDF."} if cut is not None else {}),
        **({"image_pages": shown} if shown else {}),
        "paragraphs": paragraphs[:cut]}


def choose(act, is_main, primary, names):
    """Return [(article, reason)] for the articles and annexes to keep."""
    if is_main:
        return [(a, "all") for a in act.articles]
    how = {a.num: matches(a, primary, names) for a in act.articles}
    hits = {k for k, v in how.items() if v == "number"}
    if hits:
        # Keep articles of the same law that refer to an amending article (transitional
        # rules, exceptions), and the commencement article. They tell when a change applies.
        for a in act.articles:
            if not how[a.num] and internal_refs(a) & hits:
                how[a.num] = "related"
            elif not how[a.num] and COMMENCEMENT.search(a.title):
                how[a.num] = "commencement"
    chosen = [(a, how[a.num]) for a in act.articles if how[a.num]]
    if not chosen and any(rx.search(act.title) for rx in (primary, *names)):
        # An act about the law as a whole (e.g. a decree on the NOK incentives) that does not cite it.
        chosen = [(a, "title") for a in act.articles]
    for annex in act.annexes:
        how_annex = matches(annex, primary, names) or ("annex" if chosen and annex_referenced(annex, chosen) else None)
        if how_annex:
            chosen.append((annex, how_annex))
    return chosen


def convert(issue: dict, ds: Dataset) -> str | None:
    """Write <dataset>/json/<id>.json for one issue. Return the id, or None if nothing is relevant."""
    n, y = issue["number"], issue["year"]
    ident = fek_id(n, y)
    is_main = ident == ds.main
    pdf = download(fek_url(n, y), PDF / f"{ident}.pdf")
    acts = extract.parse(pdf)
    images = extract.image_pages(pdf)

    jacts, kept, review = [], 0, False
    for act in acts:
        chosen = choose(act, is_main, ds.primary, ds.names)
        loose = [] if is_main or act.articles else [p for p in act.preamble if ds.primary.search(p.text)]
        if not chosen and not loose:
            continue
        jact = {"act": label(act, y), "title": act.title, "signed": act.signed, "articles": []}
        if loose:                                   # For example, a corrigendum has no articles.
            jact["text"] = [{"page": p.page, "text": p.text} for p in loose]
        for art, how in chosen:
            jact["articles"].append(article_json(art, how, is_main, ds, images))
            kept += 1
            review |= how == "name"
        jacts.append(jact)

    if not jacts:
        print(f"   {ident}: no article cites {ds.cited} (only preamble or contents?)")
        return None
    in_issue = [a for a in acts if a.articles or a.preamble]
    main_act = in_issue[0]
    doc = {
        "title": label(main_act, y) + (f" — {main_act.title}" if main_act.title else ""),
        "fek": f"Α΄ {n}/{y}", "file": ident, "acts_in_issue": [label(a, y) for a in in_issue],
        "published": issue["published"], **issued(issue), "source": fek_url(n, y), "search_id": issue["search_id"],
        "pages": issue["pages"],
        **({} if is_main else {"cites": ds.law,
                               "extract": f"Only the articles relevant to {ds.cited}. The full text is at the source URL."}),
        **({"review": True} if review else {}),
        "acts": jacts}
    write_json(ds.json_path(ident), doc)
    print(f"   {ident}: {label(main_act, y)}, {kept} articles" + (" [review]" if review else ""))
    return ident
