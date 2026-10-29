"""Lookups for the query script, computed once at build time and stored in index.json.

  xrefs         internal references of the two base texts: «της παρ. 5 του άρθρου 210» in code:211.3
                gives {"code:211.3": ["code:210.5"]}. References to other laws are left out.
  glossary      the defined terms of the Code (code:197) and the NOK (nok:2): term, synonym, global id
  synonyms      groups of search stems that mean the same: the glossary synonyms («μπαλκόνι») and
                SYNONYMS below. Each alternative is one or more stems, all of which must match.
  commencement  for each amending act: its commencement article and, where the text is regular,
                the date its provisions start (best effort; "rule" says how sure).
"""
import datetime, re

from common import num_key
from convert import EXTERNAL, greek_numeral
import ids

# Everyday words that the Gazette does not use, or spells two ways. Folded stems (ids.fold).
# Review with practising architects before adding more.
SYNONYMS = [
    ["πυλωτ", "πιλοτη", "πιλοτων"],          # Not «πιλοτ»: it matches «πιλοτικό» (pilot programme).
    ["μαντρ", "περιφραγμ", "περιφραξ"],
    ["πισιν", "κολυμβητικ δεξαμεν"],
    ["ρετιρε", "εσοχ"],
]

# «της περ. β) της παρ. 3 του άρθρου 224», «της παρ. 5 του άρθρου 210», «του άρθρου 210».
REF = re.compile(
    r"(?:(?:περ\.|περίπτωση[ς]?)\s*([α-ω]{1,4})[΄'’]?\)?\s+(?:της|του)\s+)?"
    r"(?:(?:παρ\.|παράγραφο[υς]?)\s*(\d+[Α-Ω]?)\s+(?:του|της)\s+)?"
    r"(?:άρθρου|άρθρο)\s+(\d+[Α-Ω]?)(?![\dΑ-Ω])")
# «των άρθρων 211 και 212», «των άρθρων 183 έως 185».
REFS = re.compile(r"(?:άρθρων|άρθρα)\s+(\d+[Α-Ω]?(?:\s*(?:,|και|έως)\s*\d+[Α-Ω]?)+)")
# «της παρ. 3 του παρόντος», «της παρ. 3 του παρόντος άρθρου»: the same article.
SAME = re.compile(r"(?:παρ\.|παράγραφο[υς]?)\s*(\d+[Α-Ω]?)\s+(?:του\s+παρόντος(?!\s+(?:Τμήματος|Μέρους|Κεφαλαίου|Κώδικα))"
                  r"|ανωτέρω|του\s+ίδιου\s+άρθρου)")
# «του παρόντος Κώδικα» after a reference names the Code itself, so it is internal.
THIS_CODE = re.compile(r"\s*(?:του\s+παρόντος(?:\s+Κώδικα)?|του\s+Κώδικα\s+αυτού)")

# «Ανοικτός εξώστης (μπαλκόνι)»: the word in brackets is the everyday name. «(Σ.Δ.)» is an abbreviation.
DEFINITION = re.compile(r"^(\d+[Α-Ω]?)\.\s*«([^»(]{2,120}?)\s*(?:\(([^)]{2,60})\))?\s*»\s*:")
DEFINITION_ANY = re.compile(r"^(\d+[Α-Ω]?)\.\s*«([^»]{2,160})»\s*:")
# The NOK has no quotes: «5. Ανοικτός Εξώστης (μπαλκόνι) είναι ...».
DEFINITION_NOK = re.compile(r"^(\d+[Α-Ω]?)\.\s*([^.:«»()]{2,100}?)\s*(?:\(([^)]{2,60})\))?\s+(?:είναι|νοείται|νοούνται)\b")


def _range(nums: str) -> list[str]:
    parts = re.findall(r"\d+[Α-Ω]?", nums)
    if "έως" in nums and len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        lo, hi = int(parts[0]), int(parts[1])
        if 0 < hi - lo <= 30:
            return [str(n) for n in range(lo, hi + 1)]
    return parts


def _resolve(key: str, known: dict, article: str, para: str | None = None, clause: str | None = None) -> str | None:
    """Return the deepest existing global id for a reference, or None if the article does not exist."""
    if article not in known:
        return None
    gid = ids.make(key, article)
    for part in (para, clause):
        if not part:
            break
        deeper = f"{gid}.{part}"
        if deeper not in known[article]:
            break
        gid = deeper
    return gid


# «του ίδιου νόμου», «της ίδιας απόφασης», «του ως άνω διατάγματος»: an act named earlier in the sentence.
SAME_ACT = re.compile(r"\s*(?:του|της)\s+(?:ίδιου|ίδιας|ως\s+άνω|εν\s+λόγω|αυτού|αυτής)\b")


def _external(text: str, end: int) -> bool:
    tail = text[end:end + 60]
    return (bool(EXTERNAL.match(tail)) or bool(SAME_ACT.match(tail))) and not THIS_CODE.match(tail)


def xrefs(base: dict[str, list[dict]]) -> dict[str, list[str]]:
    """Return {paragraph gid: [referenced gids]} for the base texts. `base` is {dataset key: articles}."""
    out = {}
    for key, articles in base.items():
        known = {a["article"]: {ids.make(key, p["id"]) for p in a["paragraphs"]} for a in articles}
        for a in articles:
            for p in a["paragraphs"]:
                text, refs = p["text"], []
                for m in REF.finditer(text):
                    if _external(text, m.end()):
                        continue
                    clause = ids.fold(m.group(1)) if m.group(1) and greek_numeral(m.group(1)) else None
                    refs.append(_resolve(key, known, m.group(3), m.group(2), clause))
                for m in REFS.finditer(text):
                    if not _external(text, m.end()):
                        refs += [_resolve(key, known, n) for n in _range(m.group(1))]
                for m in SAME.finditer(text):
                    refs.append(_resolve(key, known, a["article"], m.group(1)))
                me = ids.make(key, p["id"])
                refs = [r for r in dict.fromkeys(refs) if r and not ids.related(r, me)]
                if refs:
                    out[me] = refs
    return dict(sorted(out.items(), key=lambda kv: num_key(kv[0].replace(":", "."))))


def glossary(base: dict[str, list[dict]]) -> list[dict]:
    """Return the defined terms: code:197 (Code Part Δ definitions) and nok:2 (NOK definitions)."""
    out = []
    for key, article in (("code", "197"), ("nok", "2")):
        a = next((x for x in base[key] if x["article"] == article), None)
        for p in (a or {}).get("paragraphs", []):
            text = p["text"]
            if (m := DEFINITION.match(text) or DEFINITION_ANY.match(text) or DEFINITION_NOK.match(text)):
                entry = {"term": m.group(2).strip(), "id": ids.make(key, p["id"])}
                if m.re is not DEFINITION_ANY and m.group(3):
                    entry["also"] = m.group(3).strip()
                out.append(entry)
    return out


STOP = {"η", "ο", "το", "τα", "οι", "του", "της", "των", "και", "ή"}


def stem(phrase: str) -> str:
    """Return search stems of a phrase: «Ανοικτός εξώστης» -> "ανοικτ εξωστ". Crude, for matching only."""
    words = [w for w in re.findall(r"[α-ω]+", ids.fold(phrase)) if w not in STOP]
    return " ".join(re.sub(r"(?:ου|ων|ος|ης|ας|ες|οι|εσ|οσ|ησ|ασ|α|η|ο|ι|ε|υ|σ)$", "", w) if len(w) > 4 else w
                    for w in words)


def synonyms(terms: list[dict]) -> list[list[str]]:
    """Return the synonym groups: SYNONYMS and the «term (synonym)» pairs of the glossary."""
    groups = [list(g) for g in SYNONYMS]
    for t in terms:
        if t.get("also") and not re.search(r"[\d.]", t["also"]):
            group = [stem(t["also"]), stem(t["term"])]
            if group not in groups:
                groups.append(group)
    return groups


PUBLICATION = re.compile(r"(?:ισχύ|ισχύει|σε\s+ισχύ)[^.]{0,80}?(?:από|μετά(?:\s+από)?)\s+(?:τη[ν]?\s+)?δημοσίευσ")
DAYS_AFTER = re.compile(r"(?:(\d+)|[α-ωά-ώ]+\s+\((\d+)\))\s+ημέρ\w*\s+μετά")
UNLESS = re.compile(r"εκτός|έκτος|επιφύλαξη|άλλως|ειδικότερα|διαφορετικά")


def commencement(docs: list[dict]) -> list[dict]:
    """Return the commencement rule of each amending act: {article, act, rule, from}.

    rule: "publication" (all of the act starts on `from`), "publication-unless" (the act starts on
    `from` unless a provision says otherwise: check the amending article), or "text" (read the
    article; `from` is absent).
    """
    out = []
    for doc in docs:
        for act in doc.get("acts", []):
            for a in act["articles"]:
                if a.get("match") != "commencement":
                    continue
                first = re.split(r"(?<=[.])\s+(?=[Α-ΩΆ-Ώ0-9])", " ".join(p["text"] for p in a["paragraphs"][:2]))[0]
                first = re.sub(r"^\d+\.\s*", "", first)
                entry = {"article": ids.make(doc["file"], a["article"]), "act": act["act"], "rule": "text"}
                if PUBLICATION.search(first):
                    start = datetime.date.fromisoformat(doc["published"])
                    if (m := DAYS_AFTER.search(first)):
                        start += datetime.timedelta(days=int(m.group(1) or m.group(2)))
                    entry["rule"] = "publication-unless" if UNLESS.search(first) else "publication"
                    entry["from"] = start.isoformat()
                out.append(entry)
    return out


def build(base: dict[str, list[dict]], docs: list[dict]) -> dict:
    terms = glossary(base)
    return {"xrefs": xrefs(base), "glossary": terms, "synonyms": synonyms(terms), "commencement": commencement(docs)}

