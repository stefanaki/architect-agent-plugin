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

from common import PDF, download, fek_id, fek_url, write_json
from datasets import Dataset
import extract

# Numbering marker at the start of a paragraph: «2.», «ιβ.», «α)», or a chain «1.α.».
# «ν. 4067/2012» is a law citation, not the marker «ν.».
ARABIC = re.compile(r"(\d{1,3}[Α-Ω]?)[.)](?!\d)\s*")
GREEK = re.compile(r"([α-ω]{1,4})[΄'’]?[.)]\s*(?!\d{3,}/)")
_UNITS = {"α": 1, "β": 2, "γ": 3, "δ": 4, "ε": 5, "στ": 6, "ζ": 7, "η": 8, "θ": 9}
_TENS = {"ι": 10, "κ": 20, "λ": 30, "μ": 40, "ν": 50, "ξ": 60, "ο": 70, "π": 80}

COMMENCEMENT = re.compile(r"Έναρξη\s+ισχύος")
# «άρθρων 66 έως 71», «του άρθρου 67 και 68»: article numbers of the same law.
INTERNAL = re.compile(r"άρθρ(?:ο|ου|α|ων)\s+((?:\d+[Α-Ω]?\s*(?:,|και|έως|ως|-)\s*)*\d+[Α-Ω]?)")
EXTERNAL = re.compile(r"\s*(?:του|της|των)\s+(?:ν\.|νόμου|π\.δ\.|Κώδικα|Ν\.Ο\.Κ\.|Νέου|κ\.υ\.α\.|ΚΥΑ|υπ’|Συντάγματος)"
                      r"|\s*(?:ν\.|\()")


def greek_numeral(s):
    """Return the value of a Greek numeral ("ιστ" -> 16). Return None if s is not a numeral (e.g. "και")."""
    tens = _TENS.get(s[:1], 0)
    rest = s[1:] if tens else s
    if not rest:
        return tens or None
    return tens + _UNITS[rest] if rest in _UNITS else None


def markers(text):
    """Return the numbering markers at the start of the text: «5. α) ...» -> [("1", 5, "5"), ("α", 1, "α")]."""
    t, out = text, []
    while True:
        if (m := ARABIC.match(t)):
            out.append(("1", int(re.match(r"\d+", m.group(1)).group()), m.group(1)))
        elif (m := GREEK.match(t)) and (v := greek_numeral(m.group(1))):
            out.append(("α", v, m.group(1)))
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

    def enter(self, chain) -> str:
        """Add the markers of one paragraph. Return the path of labels, for example "6.ιδ"."""
        for kind, value, lab in chain:
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
        return ".".join(s[2] for s in self.stack)


def paragraph_ids(art):
    """Return an id for each paragraph: "article.paragraph.clause...".

    Text without a marker gets the previous id + "#k".
    Quoted text «...» is the text of another provision, for example the new text of a NOK
    article. It gets the id of the paragraph before the quote, then "~", then its own
    numbering. "120#1~4" is paragraph 4 of the text that paragraph "120#1" introduces.
    "120#1~4.γ#1" is text without a marker after its clause γ. Quoted text before the
    first quoted marker is "~#k". An id that occurs again in the article gets "@2", "@3", ...
    """
    own, quote = Levels(), None
    last, extra, anchor, qlast, qextra = art.num, 0, art.num, "", 0
    out, seen = [], Counter()
    for p in art.paras:
        if not (p.quoted or p.text.startswith("«")):      # «στ. ...» is text of another law.
            quote = None
            if (chain := markers(p.text)):
                last, extra = f"{art.num}.{own.enter(chain)}", 0
                pid = last
            else:
                extra += 1
                pid = f"{last}#{extra}"
        else:
            if quote is None:
                quote, anchor, qlast, qextra = Levels(), (out[-1] if out else art.num), "", 0
            if (chain := markers(p.text.lstrip("«").lstrip())):
                qlast, qextra = quote.enter(chain), 0
                pid = f"{anchor}~{qlast}"
            else:
                qextra += 1
                pid = f"{anchor}~{qlast}#{qextra}"
        seen[pid] += 1
        out.append(pid if seen[pid] == 1 else f"{pid}@{seen[pid]}")
    return out


def paragraphs_json(art) -> list[dict]:
    return [{"id": i, "page": p.page, **({"quoted": True} if p.quoted else {}), "text": p.text}
            for i, p in zip(paragraph_ids(art), art.paras)]


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
    for m in INTERNAL.finditer(text):
        if EXTERNAL.match(text, m.end()):
            continue
        nums = re.findall(r"\d+", m.group(1))
        if "έως" in m.group(1) or "ως" in m.group(1).split() or "-" in m.group(1):
            lo, hi = int(nums[0]), int(nums[-1])
            out |= {str(n) for n in range(lo, hi + 1)} if hi - lo < 50 else set()
        out |= set(nums)
    return out


def annex_referenced(annex, chosen):
    """Return True if a chosen article refers to this annex («Παράρτημα Ι»)."""
    numeral = annex.num.split("-", 1)[1]
    pattern = r"Παράρτημ\w*" + (r"\s+" + re.escape(numeral) + r"(?![\wΑ-Ω])" if numeral else "")
    return any(re.search(pattern, text_of(a), re.I) for a, _ in chosen)


def article_json(art, how, is_main, ds: Dataset):
    scope = None
    if is_main and ds.building_rules and not art.num.startswith("Π-"):
        scope = "building_rules" if int(re.match(r"\d+", art.num).group()) in ds.building_rules else "other"
    return {
        "article": art.num, **({"label": art.label} if art.label else {}),
        "title": art.title, "page": art.page, "headings": art.headings,
        **({"scope": scope} if scope else {}), **({"match": how} if not is_main else {}),
        "paragraphs": paragraphs_json(art)}


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
            jact["articles"].append(article_json(art, how, is_main, ds))
            kept += 1
            review |= how == "name"
        jacts.append(jact)

    if not jacts:
        print(f"   {ident}: no article cites law {ds.law} (only preamble or contents?)")
        return None
    in_issue = [a for a in acts if a.articles or a.preamble]
    main_act = in_issue[0]
    doc = {
        "title": label(main_act, y) + (f" — {main_act.title}" if main_act.title else ""),
        "fek": f"Α΄ {n}/{y}", "file": ident, "acts_in_issue": [label(a, y) for a in in_issue],
        "published": issue["published"], "source": fek_url(n, y), "search_id": issue["search_id"],
        "pages": issue["pages"],
        **({} if is_main else {"cites": ds.law,
                               "extract": f"Only the articles relevant to law {ds.law}. The full text is at the source URL."}),
        **({"review": True} if review else {}),
        "acts": jacts}
    write_json(ds.json_path(ident), doc)
    print(f"   {ident}: {label(main_act, y)}, {kept} articles" + (" [review]" if review else ""))
    return ident
