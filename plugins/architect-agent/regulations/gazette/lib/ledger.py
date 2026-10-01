"""Build ledger.json of a dataset: for each article, the Gazette articles that amend it.

The ledger does not say what changed. It says where to look.

The matcher reads the JSON files of the dataset. It keeps a reference to an article of
the law («άρθρου 14 του ν. 4067/2012», «άρθρο 224 του Κώδικα Χωροταξίας - Πολεοδομίας»)
only if its sentence has an amending verb («τροποποιείται», «αντικαθίσταται», «προστίθεται»,
«καταργείται», ...) or the article title is an amendment title. A reference without this
is a mention. The ledger does not keep mentions.

NOK ledger. Annex A of the Code names the amendments of each codified NOK paragraph. It is a
second source. Each pointer gets a status:
  confirmed    both sources agree
  superseded   only the matcher found it, and a later confirmed pointer rewrote the same text
  matcher      only the matcher found it, for a NOK article that Annex A lists (review it)
  annex_a      only Annex A names it: the matcher missed the citation form (review it)
  unchecked    the NOK article is not in Annex A, so no second source exists
  repeal       a repeal. Annex A cannot list it, because repealed text is not in the Code
  title        the amending article's title names the NOK article, but Annex A does not list it
Each article can have:
  not_codified     paragraphs that Annex A does not list and no pointer repeals. Code article 477
                   repeals only what Annex A lists. Check these paragraphs by hand.
  repealed_in      the pointer that repeals the whole article
The NOK ledger stops at the Code (8 June 2026). The links to the Code are in crosswalk.json.

Code ledger. There is no second source. Each pointer has `kind`: amend or repeal.

Each pointer of both ledgers can have:
  targets      the provisions that the sentence names: "27" (whole article), "27.4", "11.6.ιδ". Best effort.
  restates     true if the amending article gives the full new text of the article
"""
import datetime, re

from common import num_key, read_json, write_json
from datasets import CODE, CODE_PUBLISHED, CROSSWALK, NOK, Dataset
import annex_a

NOK_NAME = (r"(?:(?:του\s+|στον?\s+)?(?:ν\.|Ν\.|νόμου)\s*4067\s*/\s*2012|(?:του\s+)?Ν\.\s?Ο\.\s?Κ\."
            r"|(?:του\s+)?Νέου\s+Οικοδομικού\s+Κανονισμού|(?:του\s+)?ΝΟΚ(?![^\W\d_]))")
# «άρθρου 224 του Κώδικα Χωροταξίας - Πολεοδομίας «Νικόλαος Ταγαράς»», «άρθρο 206 του ν. 5306/2026».
CODE_NAME = (r"(?:(?:του\s+|στον?\s+)?(?:ν\.\s*5306\s*/\s*2026|Κώδικα\s+Χωροταξίας\s*[-–]\s*Πολεοδομίας"
             r"(?:\s*«Νικόλαος\s+Ταγαράς»)?|Κώδικα\s+«?Νικόλαος\s+Ταγαράς»?))")
NUMS = r"((?:\d+[Α-Ω]?\s*(?:,|και|έως|-)\s*)*\d+[Α-Ω]?)"
# Optional text between the article number and the law:
# «άρθρο 23 παρ. δ΄ του ν. 4067/2012», «άρθρου 32Α με τίτλο «...» στο ν. 4067/2012».
BETWEEN = r"(?:(?:παρ|περ)\.\s*[^\s,]+\s+|με\s+τίτλο\s+«[^»]{0,200}»\s+)?"
VERB = re.compile(r"τροποποιε[ίι]ται|τροποποιούνται|αντικαθ[ίι]σταται|αντικαθίστανται|προστίθε(?:ται|νται)|"
                  r"καταργε[ίι]ται|καταργούνται|αναστέλλεται|αναστέλλονται|συμπληρώνεται|αναριθμε[ίι]ται|"
                  r"διαγράφ(?:εται|ονται)|απαλείφ(?:εται|ονται)|διαμορφώνεται|διαμορφώνονται|επέρχονται|"
                  r"παρατείνεται|παρατείνονται")
TITLE_VERB = re.compile(r"Τροποποίηση|Τροποποιήσεις|Προσθήκη|Κατάργηση|Αντικατάσταση|Συμπλήρωση|Αναστολή|Παράταση")
# A sentence ends at «.» or «;» after a word of 3+ characters or after «»» or «)», before a capital letter.
# This keeps abbreviations such as «ν. 4067/2012» and «παρ. 2» inside the sentence.
# «διορθ. σφαλμ. Α’ 99» is a citation of a corrigendum. It does not end the sentence.
SENTENCE_END = re.compile(r"(?:(?<=[^\s.]{3}[.;·])|(?<=[»)][.;·]))(?<!σφαλμ\.)(?<!διορθ\.)(?<!Διορθ\.)(?<!αριθμ\.)"
                          r"\s+(?=[Α-ΩΆ-Ώ])")
WINDOW = (150, 400)                     # Characters before and after the reference.
REPEAL = re.compile(r"καταργε[ίι]ται|καταργούνται", re.I)   # «Καταργείται» can start the sentence.
# A sentence that names its target first: «Στο άρθρο 11 ...», «Στην περ. γ΄ της παρ. 1 του άρθρου 10 ...».
TARGET_FIRST = re.compile(r"^\s*(?:\d+[.)]\s*)?(?:[α-ω]{1,3}[.)]\s*)?Στ(?:ο|ην|ον|α|ις|ους)\b")

# Parts of a target: «η περ. ιδ΄ της παρ. 6 του άρθρου 11», «οι παρ. 2 και 4 του άρθρου 27».
PARA_WORD = r"(?:παρ\.|παράγραφος|παραγράφου|παράγραφο|παράγραφοι|παραγράφων|παραγράφους)"
CLAUSE_WORD = r"(?:περ\.|περίπτωση|περίπτωσης|περιπτώσεως|περιπτώσεις|περιπτώσεων|υποπερ\.)"
LABEL = r"(?:\d+[α-ω]?|[α-ω]{1,4}[΄'’]?\)?)"
LIST = rf"{LABEL}(?:\s*(?:,|και|έως)\s*{LABEL})*"
CHAIN_BEFORE = re.compile(rf"(?:{CLAUSE_WORD}\s*({LIST})\s+(?:της|των)\s+)?{PARA_WORD}\s*({LIST})\s+(?:του|στο|στον)\s+$")
PARA_INSIDE = re.compile(rf"{PARA_WORD}\s*({LIST})")
ADDED = re.compile(rf"προστίθε(?:ται|νται)\s+(?:νέα\s+|νέες\s+|νέο\s+)?(?:({PARA_WORD})|({CLAUSE_WORD}))\s*({LIST})")
RESTATES = re.compile(r"άρθρο(?:\s+\d+[Α-Ω]?)?\s+διαμορφώνεται|αντικαθ[ίι]σταται\s+ως\s+εξής")
GREEK_NUMERAL = re.compile(r"(?=.)(?:[ικλμνξοπ])?(?:α|β|γ|δ|ε|στ|ζ|η|θ)?")


def sentence_around(text: str, start: int, end: int) -> tuple[str, str]:
    """Return the text before and after text[start:end] in the same sentence, without quoted text."""
    lo, hi = max(0, start - WINDOW[0]), min(len(text), end + WINDOW[1])
    before, after = text[lo:start], text[end:hi]
    cuts = list(SENTENCE_END.finditer(before))
    if cuts:
        before = before[cuts[-1].end():]
    cut = SENTENCE_END.search(after)
    if cut:
        after = after[:cut.start()]
    return re.sub(r"«[^«»]*»", " ", before), re.sub(r"«[^«»]*»?", " ", after)


def amending(text: str, start: int, end: int, is_title: bool) -> str | None:
    """Return "amend" or "repeal" if the reference at text[start:end] is part of an amending sentence.

    The function looks at the sentence around the reference, not further than WINDOW.
    Quoted text «...» is new text of the law, so its verbs do not count.
    A verb after the reference counts. A verb before the reference counts in a repeal list
    («καταργούνται: α) ... του άρθρου 11»), when the sentence starts with the verb, or when
    the sentence names its target first. This rejects mentions like
    «... τροποποιούνται ... σύμφωνα με την παρ. 2 του άρθρου 6 του ν. 4067/2012».
    """
    if is_title:
        return "amend" if TITLE_VERB.search(text) else None
    before, after = sentence_around(text, start, end)
    if REPEAL.search(after) or REPEAL.search(before):
        return "repeal"
    # «Αντικαθίσταται το πέμπτο εδάφιο της παρ. 2 του άρθρου 36 ...»: the sentence starts with the verb.
    verb_first = bool(re.match(rf"^\s*(?:\d+[.)]\s*)?(?:[α-ω]{{1,3}}[.)]\s*)?(?:{VERB.pattern})", before, re.I))
    if VERB.search(after) or verb_first or (VERB.search(before) and TARGET_FIRST.search(before)):
        return "amend"
    return None


def labels(s: str) -> list[str]:
    """Split «2 και 4», «ιδ΄», «3α» into id parts: ["2", "4"], ["ιδ"], ["3.α"].

    Only numbers and Greek numerals count. Words such as «και», «το», «ως» are not labels.
    """
    out = []
    for lab in re.split(r"\s*(?:,|\bκαι\b|\bέως\b)\s*", s):
        lab = re.sub(r"[΄'’)]", "", lab.strip())
        if re.fullmatch(r"\d+[α-ω]?", lab) or GREEK_NUMERAL.fullmatch(lab):
            out.append(re.sub(r"^(\d+)([α-ω])$", r"\1.\2", lab))
    return out


def targets(text: str, m: re.Match, article: str) -> tuple[set[str], bool]:
    """Return (the provisions that a reference names, whether the whole article is restated).

    «Η περ. ιδ΄ της παρ. 6 του άρθρου 11 ...»  -> {"11.6.ιδ"}
    «Στο άρθρο 27 παρ. 4 ... προστίθεται εδάφιο» -> {"27.4"}
    «Στο άρθρο 28 ... προστίθεται παρ. 11»       -> {"28.11"}
    «Το άρθρο 4 ... αντικαθίσταται ως εξής»      -> {"4"}, restated
    """
    before, after = sentence_around(text, m.start(), m.end())
    paras, clauses = [], []
    if (c := CHAIN_BEFORE.search(before)):
        paras, clauses = labels(c.group(2)), labels(c.group(1) or "")
    elif (c := PARA_INSIDE.search(m.group(0))):
        paras = labels(c.group(1))
    base = [f"{article}.{p}" for p in paras] or [article]
    out = {f"{b}.{c}" for b in base for c in clauses} or set(base)
    added = set()
    for a in ADDED.finditer(after):
        new = labels(a.group(3))
        if a.group(1):                                   # A new paragraph of the article.
            added |= {f"{article}.{n}" for n in new}
        else:                                            # A new clause of the named paragraph.
            added |= {f"{b}.{n}" for b in base for n in new}
    if added and out == {article}:
        out = set()                                      # «Στο άρθρο 27 προστίθεται παρ. 5»: the target is §5 only.
    out |= added
    restated = bool(re.search(r"άρθρο(?:\s+\d+[Α-Ω]?)?\s+διαμορφώνεται", after)) or \
        (not paras and bool(RESTATES.search(after)))
    return out, restated


def expand(nums: str) -> list[str]:
    """Expand «11, 12 και 13» and «29 έως 33» into article numbers."""
    parts = re.findall(r"\d+[Α-Ω]?", nums)
    if ("έως" in nums or "-" in nums) and len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        lo, hi = int(parts[0]), int(parts[1])
        return [str(n) for n in range(lo, hi + 1)] if hi - lo < 50 else parts
    return parts


def law_of(act_label: str) -> str | None:
    m = re.search(r"(\d+/\d{4})$", act_label)
    return m.group(1) if m else None


def matcher(ds: Dataset, name: str, kinds: set[str], keep) -> dict:
    """Return {article: {(source, article): entry}} from the JSON files of a dataset.

    `kinds` are the article matches to read. `keep(published)` selects the issues by date.
    An entry has "act", "law", "published", "paragraphs", "kinds", "targets" {(id, kind)} and "restates".
    """
    target = re.compile(rf"άρθρ(?:ο|ου|α|ων)\s+{NUMS}\s+{BETWEEN}{name}")
    # «Στον ν. 4067/2012 (Α΄ 79) προστίθεται άρθρο 20Α», «... προστίθεται το άρθρο 10Α»
    insert = re.compile(rf"{name}[^.«]{{0,60}}?προστίθε(?:ται|νται)\s+(?:τ[οα]\s+)?άρθρ(?:ο|α)\s+{NUMS}")
    found = {}
    for path in ds.json_paths():
        if path.stem == ds.main:
            continue
        doc = read_json(path)
        if not keep(doc["published"]):
            continue
        for act in doc["acts"]:
            for a in act["articles"]:
                if a.get("match") not in kinds:
                    continue
                # Quoted paragraphs count too: quote tracking can mark the law's own text as quoted,
                # and a ratified act is quoted text that amends the law. The verb rule rejects mentions.
                for pid, text in [("", a["title"])] + [(p["id"], p["text"]) for p in a["paragraphs"]]:
                    flat = re.sub(r"\s+", " ", text)
                    hits = [(n, kind, m) for m in target.finditer(flat)
                            if (kind := amending(flat, m.start(), m.end(), not pid)) for n in expand(m.group(1))]
                    hits += [(n, "insert", m) for m in insert.finditer(flat) for n in expand(m.group(1))]
                    for n, kind, m in hits:
                        if not 1 <= int(re.match(r"\d+", n).group()) <= ds.last_article:
                            continue
                        entry = found.setdefault(n, {}).setdefault((path.stem, a["article"]), {
                            "act": act["act"], "law": law_of(act["act"]), "published": doc["published"],
                            "paragraphs": set(), "kinds": set(), "targets": set(), "restates": False})
                        entry["kinds"].add("title" if not pid else "amend" if kind == "insert" else kind)
                        if not pid:
                            continue
                        entry["paragraphs"].add(pid)
                        if kind == "insert":
                            entry["targets"].add((n, "amend"))
                            continue
                        # A list «των άρθρων 11, 12 και 13» names articles, not paragraphs of one article.
                        single = len(expand(m.group(1))) == 1
                        ids, restated = targets(flat, m, n) if single else ({n}, False)
                        entry["targets"] |= {(t, kind) for t in ids}
                        entry["restates"] |= restated
    return found


def covers(later: set[str], earlier: set[str]) -> bool:
    """Return True if each earlier target is equal to, or inside, a later target."""
    return bool(earlier) and all(any(t == q or t.startswith(q + ".") for q in later) for t in earlier)


def added_titles(found) -> dict[str, str]:
    """Return titles for articles that amendments added (10Α, 27Α, ...), from the quoted new text."""
    out, docs = {}, {}
    for num, pointers in found.items():
        if not re.search(r"[Α-Ω]$", num):
            continue
        for (source, article), e in sorted(pointers.items(), key=lambda kv: kv[1]["published"]):
            doc = docs.setdefault(source, NOK.load(source))
            art = next(a for act in doc["acts"] for a in act["articles"] if a["article"] == article)
            for p in art["paragraphs"]:
                if (m := re.search(rf"«\s*Άρθρο\s+{num}\s+([^«»\d][^«»]*?)\s*(?:\d+\.\s|»|$)", p["text"])):
                    out[num] = m.group(1).strip().rstrip(".")
                    break
            if num in out:
                break
    return out


def top_paragraphs(article: dict) -> set[str]:
    """Return the top-level paragraph numbers of an article."""
    out = set()
    for p in article["paragraphs"]:
        parts = p["id"].split(".")
        if len(parts) > 1 and (m := re.match(r"\d+", parts[1])):
            out.add(m.group())
    return out


def build_nok():
    nok_articles = {a["article"]: a for a in NOK.load(NOK.main)["acts"][0]["articles"]}
    titles = {k: a["title"] for k, a in nok_articles.items()}
    code_of, amended_by = annex_a.parse()
    code_paras = annex_a.paragraph_map()
    found = matcher(NOK, NOK_NAME, {"number", "name"}, lambda published: published < CODE_PUBLISHED)
    titles.update({k: v for k, v in added_titles(found).items() if not titles.get(k)})

    # Map (law, article) to a source file, for pointers that only Annex A gives.
    by_law = {}
    for path in NOK.json_paths():
        for act in read_json(path)["acts"]:
            if (law := law_of(act["act"])):
                for a in act["articles"]:
                    by_law[(law, a["article"])] = (path.stem, act["act"])

    articles = {}
    for num in sorted(set(titles) | set(found) | set(code_of), key=num_key):
        pointers = {}
        for (source, article), e in found.get(num, {}).items():
            if e["law"] and (e["law"], article) in amended_by.get(num, set()):
                status = "confirmed"
            elif num not in code_of:
                status = "unchecked"
            elif "repeal" in e["kinds"]:
                status = "repeal"            # Repealed text is not in the Code, so Annex A cannot list it.
            elif "title" in e["kinds"]:
                status = "title"             # The article title names the NOK article as its target.
            else:
                status = "matcher"
            ids = sorted({t for t, _ in e["targets"]}, key=num_key)
            pointers[(source, article)] = {
                "source": source, "act": e["act"], "article": article, "published": e["published"],
                **({"paragraphs": sorted(e["paragraphs"])} if e["paragraphs"] else {}),
                **({"targets": ids} if ids else {}), **({"restates": True} if e["restates"] else {}),
                "status": status, "_repeals": {t for t, k in e["targets"] if k == "repeal"}}
        for law, article in sorted(amended_by.get(num, set())):
            if any(p["act"].endswith(law) and p["article"] == article for p in pointers.values()):
                continue
            source, act = by_law.get((law, article), (None, f"Ν. {law}"))
            pointers[(source or law, article)] = {"source": source, "act": act, "article": article,
                                                  "status": "annex_a", "_repeals": set()}

        # A matcher pointer is superseded when a later confirmed pointer rewrote the same text.
        for p in pointers.values():
            if p["status"] != "matcher":
                continue
            for q in sorted(pointers.values(), key=lambda q: q.get("published", "")):
                if q["status"] == "confirmed" and q.get("published", "") > p.get("published", "") and \
                        (q.get("restates") or covers(set(q.get("targets", [])), set(p.get("targets", [])))):
                    p["status"], p["superseded_by"] = "superseded", f"{q['source']} άρθ. {q['article']}"
                    break

        ordered = sorted(pointers.values(), key=lambda p: (p.get("published") or "9999", p["source"] or "",
                                                          num_key(p["article"])))
        whole = next((p for p in ordered if num in p["_repeals"]), None)
        repealed = set().union(*(p.pop("_repeals") for p in ordered)) if ordered else set()
        entry = {"title": titles.get(num, "")}
        if whole:
            entry["repealed_in"] = f"{whole['source']} άρθ. {whole['article']}"
        cp = code_paras.get(num)
        if cp and "*" not in cp and num in nok_articles:
            added = {t.split(".")[1] for p in ordered for t in p.get("targets", [])
                     if t.count(".") == 1 and t.split(".")[1].isdigit() and p["status"] != "repeal"}
            gone = {t.split(".")[1] for t in repealed if t.count(".") == 1}
            missing = (top_paragraphs(nok_articles[num]) | added) - set(cp) - gone
            if missing and num not in repealed:
                entry["not_codified"] = sorted(missing, key=int)
        entry["amended_in"] = ordered
        articles[num] = entry

    write_json(NOK.ledger, {
        "law": NOK.law, "title": NOK.title, "fek": "Α΄ 79/2012", "closed_at": CODE_PUBLISHED,
        # The act that codified the NOK. It repealed only the provisions of its Annex A (see not_codified).
        "codified_in": {"law": CODE.law, "title": CODE.title, "fek": "Α΄ 88/2026", "dataset": f"../{CODE.root.name}",
                        "crosswalk": f"../{CODE.root.name}/{CROSSWALK.name}"},
        "generated": datetime.date.today().isoformat(),
        "articles": articles})
    counts = {}
    for a in articles.values():
        for p in a["amended_in"]:
            counts[p["status"]] = counts.get(p["status"], 0) + 1
    review = sum(counts.get(s, 0) for s in ("matcher", "annex_a"))
    uncodified = {k: a["not_codified"] for k, a in articles.items() if a.get("not_codified")}
    print(f"-> {NOK.root.name}/ledger.json: {len(articles)} articles, pointers {counts}, {review} to review, "
          f"not codified {uncodified}")


def build_code():
    found = matcher(CODE, CODE_NAME, {"number"}, lambda published: published >= CODE_PUBLISHED)
    articles = {}
    for n in sorted(found, key=num_key):
        pointers = []
        for (source, article), e in sorted(found[n].items(), key=lambda kv: (kv[1]["published"], kv[0])):
            ids = sorted({t for t, _ in e["targets"]}, key=num_key)
            pointers.append({"source": source, "act": e["act"], "article": article, "published": e["published"],
                             **({"paragraphs": sorted(e["paragraphs"])} if e["paragraphs"] else {}),
                             **({"targets": ids} if ids else {}), **({"restates": True} if e["restates"] else {}),
                             "kind": "repeal" if "repeal" in e["kinds"] else "amend"})
        articles[n] = {"amended_in": pointers}
    write_json(CODE.ledger, {
        "law": CODE.law, "title": CODE.title, "fek": "Α΄ 88/2026", "from": CODE_PUBLISHED,
        "generated": datetime.date.today().isoformat(), "articles": articles})
    print(f"-> {CODE.root.name}/ledger.json: {len(articles)} articles amended, "
          f"{sum(len(a['amended_in']) for a in articles.values())} pointers")


def run(ds: Dataset):
    (build_nok if ds is NOK else build_code)()
