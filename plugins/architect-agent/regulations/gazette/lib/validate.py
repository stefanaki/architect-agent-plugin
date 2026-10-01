"""Check a dataset. Each error fails the command. Warnings do not.

Checks for each JSON file:
  noise      Gazette page headers, page numbers inside words, the masthead date at the end
             of a paragraph, quoted text as a heading, the president line in an act title,
             control characters. Latin letters inside Greek words give a warning only.
  invented   Parsed words that the plain text of the PDF does not have. The parser makes
             them when it glues two columns or splits a word. More than 5 is an error.
  ids        Paragraph ids are unique within an article.
  md         md/<id>.md is the current rendering of the JSON file.
  page tops  The first body line of each page that a kept article spans is in the text.
  coverage   The words that pdftotext finds on the pages of a kept article are in the
             parsed text of those pages. More than 1% missing is an error.
  sequence   Article numbers of each act run without gaps. A gap is an error only if the
             file keeps the article before it: a missed heading merges its text into that article.
  NOK        48 articles. Each article has a title, except where the Gazette has none.
The Code text: articles 1 to 477, titles equal to the contents entries, coverage per article (a
warning only on pages with a broken text layer), and each Code paragraph that Annex A names is in
the text.
Ledgers: each pointer resolves. Crosswalk: each id is well formed and names an existing article.
A paragraph that the text does not have gives a warning.
"""
import re
from collections import Counter

from common import PDF, degreekify, pdftotext, read_json
from datasets import CODE, CROSSWALK, NOK, Dataset, split_ref
import extract, render

NOISE = [
    (re.compile(r"ΕΦΗΜΕΡΙ[ΣΔ∆]"), "Gazette header"),
    (re.compile(r"Τεύχος\s+[AΑ][’']\s*\d+/\d"), "«Τεύχος» header"),
    (re.compile(r"[α-ωά-ώ]{2,}\d{3,5}\s?[α-ωά-ώ]{2,}"), "page number inside a word"),
    # A date at the end of a paragraph that is not a signature line («Λευκάδα, 30 Ιουλίου 2014»).
    (re.compile(rf"^(?![Α-ΩΆ-Ώ][α-ωά-ώ]+(?:\s+[Α-ΩΆ-Ώ][α-ωά-ώ]+)*,\s*\d).*\S\s+\d{{1,2}}\s+"
                rf"(?:{extract.MONTHS})\s+\d{{4}}$"), "masthead date at the end of a paragraph"),
    (re.compile(r"[α-ωά-ώΑ-ΩΆ-Ώ][A-Za-z]|[A-Za-z][α-ωά-ώΑ-ΩΆ-Ώ]"), "Latin letter in a Greek word"),
    (re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]"), "control character"),
]
# Words of the page header that the broken text layer can glue to other lines.
HEADER_WORDS = re.compile(r"ΕΦΗΜΕΡΙ[ΣΔ∆]Α?|ΚΥΒΕΡΝΗΣΕΩΣ|Τεύχος|ΤΕΥΧΟΣ\s+ΠΡΩΤΟ")
INVENTED_LIMIT = 5                  # Parsed words that the raw text does not have. More is an error.
# Articles of law 4067/2012 that have no title in the Gazette (checked in the PDF).
NOK_UNTITLED = {"29", "30", "37", "39", "40", "41", "42", "43", "44", "45", "46", "47"}
# Greek words of 2 or more letters. Garbled table text from bad fonts does not match.
GREEK_WORD = re.compile(r"[Ά-ώἀ-῾]{2,}")
# The header can wrap: «ΕΦΗΜΕΡΙΔΑ» and «ΤΗΣ ΚΥΒΕΡΝΗΣΕΩΣ» on two lines.
RAW_HEADER = re.compile(r"(?m)^.*(ΕΦΗΜΕΡΙ[ΣΔ∆]|Τεύχος\s+[AΑ][’']\s*\d+/|ΤΕΥΧΟΣ ΠΡΩΤΟ).*$|^\s*ΤΗΣ\s+ΚΥΒΕΡΝΗΣΕΩΣ\s*$")
# The masthead on page 1 ends at the header of the first act.
FIRST_ACT = re.compile(r"(?m)^\s*(?:NOMOΣ|ΝΟΜΟΣ|ΠΡΟΕΔΡΙΚΟ ΔΙΑΤΑΓΜΑ|ΠΡΑΞΗ|ΔΙΟΡΘΩΣΕΙΣ ΣΦΑΛΜΑΤΩΝ)")
COVERAGE_LIMIT = 0.01
ANNEX_UNRESOLVED_LIMIT = 0.02       # Annex A paragraphs that the Code text does not have. More is an error.


def words(text):
    text = re.sub("[-‐−­]\\s*\n\\s*", "", text)          # Join words split at a line end.
    return Counter(w.lower() for w in GREEK_WORD.findall(text))


def raw_words(pdf) -> set[str]:
    """Return the Greek words of the whole PDF, in plain text mode.

    A word split at a line end counts joined and unjoined, so both spellings are valid.
    """
    text = degreekify(pdftotext(pdf))
    joined = re.sub("[-‐−­]\\s*\n\\s*", "", text)
    return {w.lower() for w in GREEK_WORD.findall(text)} | {w.lower() for w in GREEK_WORD.findall(joined)}


def invented(texts, pdf, errors, warnings, broken: bool = False):
    """Report parsed words that the raw text of the PDF does not have.

    The parser makes such words when it glues two columns or splits a word.
    The coverage check does not see them: it counts only the raw words.
    A file with a broken text layer gets a warning only: that layer can hold a second
    copy of the text in another layout (ΦΕΚ Α΄ 67/2026, page 169).
    """
    have = raw_words(pdf)
    bad = Counter(w.lower() for t in texts for w in GREEK_WORD.findall(t) if w.lower() not in have)
    if not bad:
        return
    sample = ", ".join(w for w, _ in bad.most_common(8))
    msg = f"invented: {sum(bad.values())} parsed words are not in the PDF text ({sample})"
    (errors if sum(bad.values()) > INVENTED_LIMIT and not broken else warnings).append(msg)


def norm_title(t: str) -> str:
    """Return a title without hyphenation and with single spaces, for comparison."""
    return re.sub(r"\s+", " ", re.sub(r"(?<=[α-ωά-ώ])- (?=[α-ωά-ώ])", "", t)).strip()


def fragments_removed(missing: Counter, parsed: Counter) -> Counter:
    """Remove "missing" words that are two parsed pieces glued together.

    On some pages pdftotext mixes the two columns. It then glues the start of a
    word in one column to a word of the other column («υποχρε» + «κατά»).
    The parser has the real words, so these are not lost text.
    """
    whole = set(parsed)
    prefixes = {w[:i] for w in whole for i in range(2, len(w) + 1)}
    suffixes = {w[i:] for w in whole for i in range(0, len(w) - 1)}
    out = Counter()
    for w, n in missing.items():
        if not any(w[:i] in prefixes and w[i:] in suffixes for i in range(2, len(w) - 1)):
            out[w] = n
    return out


def parsed_words_by_page(acts):
    """Return a Counter of words for each page, from all parsed items of all acts."""
    pages = {}

    def add(page, text):
        pages.setdefault(page, Counter()).update(words(text))
    for act in acts:
        add(act.page, act.title)
        for p in act.preamble:
            add(p.page, p.text)
        for a in act.articles + act.annexes:
            add(a.page, " ".join(a.headings) + " " + a.title + " Άρθρο " + (a.label or a.num))
            for p in a.paras:
                add(p.page, p.text)
    return pages


def noise(texts, errors, warnings):
    for t in texts:
        for rx, what in NOISE:
            for m in rx.finditer(t):
                ctx = t[max(0, m.start() - 30):m.end() + 30]
                (warnings if "Latin" in what else errors).append(f"noise ({what}): ...{ctx}...")


def check_md(ds: Dataset, doc: dict, notes, errors):
    path = ds.md_path(doc["file"])
    if not path.exists() or path.read_text(encoding="utf-8") != render.markdown(ds, doc, notes):
        errors.append(f"md: {ds.root.name}/md/{doc['file']}.md is not the current rendering. Run: render {ds.key}")


def check_issue(ds: Dataset, doc: dict, notes) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    ident = doc["file"]
    kept = [a for act in doc["acts"] for a in act["articles"]]
    texts = [act["title"] for act in doc["acts"]] + [t["text"] for act in doc["acts"] for t in act.get("text", [])]
    for a in kept:
        texts += [a["title"], *a["headings"], *(p["text"] for p in a["paragraphs"])]
    noise(texts, errors, warnings)
    for act in doc["acts"]:
        if re.search(r"ΠΡΟΕΔΡΟΣ\s+ΤΗΣ", act["title"]):
            errors.append(f"noise (president line in act title): {act['act']}: ...{act['title'][-60:]}")
    for a in kept:
        if any(h.startswith("«") for h in a["headings"]):
            errors.append(f"noise (quoted text as a heading): article {a.get('label') or a['article']}")
        dup = [i for i, n in Counter(p["id"] for p in a["paragraphs"]).items() if n > 1]
        if dup:
            errors.append(f"ids: article {a.get('label') or a['article']}: repeated ids {dup[:5]}")
    check_md(ds, doc, notes, errors)

    pdf = PDF / f"{ident}.pdf"
    broken = extract.broken_pages(pdf)
    invented(texts, pdf, errors, warnings, broken=bool(broken))
    acts = extract.parse(pdf)
    firsts = extract.first_body_lines(pdf)
    by_page = parsed_words_by_page(acts)
    flat = re.sub(r"\s+", " ", " ".join(texts))
    norm = lambda s: re.sub(r"[-‐−]$", "", s).strip()[:24]
    for a in kept:
        name = f"article {a.get('label') or a['article']}"
        pages = sorted({p["page"] for p in a["paragraphs"]} | {a["page"]})
        for pg in range(pages[0] + 1, pages[-1] + 1):
            first = firsts.get(pg, "")
            # Skip lines without Greek words: garbled table fonts or empty lines.
            if GREEK_WORD.search(first) and norm(first) not in flat and not first.startswith("Άρθρο"):
                errors.append(f"page top: {name}, page {pg}: missing «{first[:50]}»")
        # A paragraph that starts on the last page can continue on the next page.
        lo, hi = pages[0], pages[-1] + 1
        raw = pdftotext(pdf, "-f", str(lo), "-l", str(hi))
        if lo == 1 and (m := FIRST_ACT.search(raw)):
            raw = raw[m.start():]
        raw = re.split(r"(?m)^\s*Αθήνα,\s*\d{1,2}\s+\S+\s+\d{4}.*$", RAW_HEADER.sub("", raw))[0]
        expected = words(degreekify(HEADER_WORDS.sub("", raw)))
        got = Counter()
        for pg in range(lo - 1, hi + 1):
            got.update(by_page.get(pg, Counter()))
        missing = fragments_removed(expected - got, got)
        total = sum(expected.values())
        if total and sum(missing.values()) > max(5, COVERAGE_LIMIT * total):
            sample = ", ".join(w for w, _ in missing.most_common(8))
            # On a page with a broken text layer, plain pdftotext is not a reliable reference: warn only.
            report = warnings if broken & set(range(lo, hi + 1)) else errors
            report.append(f"coverage: {name}, pages {lo}-{hi}: {sum(missing.values())} of {total} words "
                          f"not parsed ({sample})")

    kept_nums = {a["article"] for a in kept}
    for act in acts:
        nums = [int(re.match(r"\d+", x.num).group()) for x in act.articles]
        gaps = [(act.articles[i - 1].num, nums[i - 1], nums[i]) for i in range(1, len(nums))
                if nums[i] - nums[i - 1] not in (0, 1)]
        if nums and nums[0] != 1:
            errors.append(f"sequence: {act.kind} {act.number}: first article {nums[0]}")
        for before, lo, hi in gaps:
            report = errors if before in kept_nums else warnings
            report.append(f"sequence: {act.kind} {act.number}: gap {lo} -> {hi}"
                          + (f" (article {before} is kept)" if before in kept_nums else ""))

    if ds is NOK and ident == NOK.main:
        nums = [a["article"] for a in kept]
        if nums != [str(i) for i in range(1, NOK.last_article + 1)]:
            errors.append(f"NOK: articles {nums}")
        for a in kept:
            if not a["title"] and a["article"] not in NOK_UNTITLED:
                errors.append(f"NOK: article {a['article']} has no title")
    return errors, warnings


def check_code_text(doc: dict) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    arts = doc["articles"]
    noise([a["title"] for a in arts] + [h for a in arts for h in a["path"]]
          + [p["text"] for a in arts for p in a["paragraphs"]], errors, warnings)
    check_md(CODE, doc, None, errors)
    pdf = PDF / f"{CODE.main}.pdf"
    broken = extract.broken_pages(pdf)
    invented([a["title"] for a in arts] + [p["text"] for a in arts for p in a["paragraphs"]], pdf, errors, warnings,
             broken=bool(broken))
    if [a["article"] for a in arts] != [str(i) for i in range(1, CODE.last_article + 1)]:
        errors.append(f"sequence: the Code articles do not run 1 to {CODE.last_article}")
    toc = extract._toc(extract.lines(pdf))
    for a in arts:
        if not a["title"]:
            errors.append(f"article {a['article']}: no title")
        # The contents of the issue give each title. The parsed title must be one of them.
        titles = [norm_title(t) for t in toc.get((a["article"], False), [])]
        if titles and norm_title(a["title"]) not in titles:
            errors.append(f"title: article {a['article']}: «{a['title'][:60]}» is not the contents entry «{titles[0][:60]}»")
        dup = [i for i, n in Counter(p["id"] for p in a["paragraphs"]).items() if n > 1]
        if dup:
            errors.append(f"ids: article {a['article']}: repeated ids {dup[:5]}")
        if a.get("missing_text"):
            warnings.append(f"article {a['article']}: no text layer in the PDF (image)")
        if a.get("not_parsed"):
            errors.append(f"article {a['article']}: the parser did not find the article")

    # Coverage: the Greek words that pdftotext finds on the pages of each article are in the parsed text.
    pages = pdftotext(pdf).split("\f")
    raw = {i + 1: HEADER_WORDS.sub("", RAW_HEADER.sub("", t)) for i, t in enumerate(pages)}
    first, last = arts[0]["page"], max(p["page"] for p in arts[-1]["paragraphs"])
    raw[first] = raw[first][raw[first].find("ΜΕΡΟΣ Α"):]            # The ratifying text comes before it.
    raw[last] = raw[last].split("Άρθρο δεύτερο")[0]
    got_by_page = {}
    for a in arts:
        got_by_page.setdefault(a["page"], Counter()).update(
            words(" ".join(a["path"]) + " " + a["title"] + f" Άρθρο {a['article']}"))
        for p in a["paragraphs"]:
            got_by_page.setdefault(p["page"], Counter()).update(words(p["text"]))
    for a in arts:
        if a.get("missing_text") or a.get("image_pages"):
            continue
        lo = a["page"]
        hi = max([p["page"] for p in a["paragraphs"]] + [lo])
        # On a page with a broken text layer, plain pdftotext is not a reliable reference: warn only.
        report = warnings if broken & set(range(lo, hi + 1)) else errors
        expected = words(degreekify("\n".join(raw.get(pg, "") for pg in range(lo, hi + 1))))
        got = Counter()
        for pg in range(lo - 1, hi + 2):
            got.update(got_by_page.get(pg, Counter()))
        missing = fragments_removed(expected - got, got)
        total = sum(expected.values())
        if total and sum(missing.values()) > max(5, COVERAGE_LIMIT * total):
            report.append(f"coverage: article {a['article']}, pages {lo}-{hi}: {sum(missing.values())} of {total} "
                          f"words not parsed ({', '.join(w for w, _ in missing.most_common(8))})")

    # Annex A: each Code paragraph that the table names is in the Code text.
    unresolved, total = [], 0
    for a in arts:
        ids = {p["id"] for p in a["paragraphs"]}
        for s in a.get("sources", []):
            para = (s["code_paragraph"] or "").rstrip(")")
            if not re.fullmatch(r"\d+|[α-ω]{1,3}", para):
                continue
            total += 1
            prefix = f"{a['article']}.{para}"
            if not any(i == prefix or i.startswith(prefix + ".") or i.startswith(prefix + "#") for i in ids):
                unresolved.append(prefix)
    if total and len(unresolved) > ANNEX_UNRESOLVED_LIMIT * total:
        errors.append(f"annex A: {len(unresolved)} of {total} Code paragraphs not in the text ({unresolved[:10]})")
    elif unresolved:
        warnings.append(f"annex A: {len(unresolved)} of {total} Code paragraphs not in the text ({unresolved[:10]})")
    return errors, warnings


def pointer_article(ds: Dataset, p: dict, docs: dict, tag: str, errors: list) -> dict | None:
    """Return the amending article of a pointer, or None with an error."""
    if p["source"] not in docs:
        f = ds.json_path(p["source"])
        docs[p["source"]] = read_json(f) if f.exists() else None
    doc = docs[p["source"]]
    if doc is None:
        errors.append(f"{tag}: file does not exist")
        return None
    art = next((a for act in doc["acts"] for a in act["articles"] if a["article"] == p["article"]), None)
    if art is None:
        errors.append(f"{tag}: article is not in the file")
        return None
    have = {x["id"] for x in art["paragraphs"]}
    errors += [f"{tag}: paragraph {pid} does not exist" for pid in p.get("paragraphs", []) if pid not in have]
    return art


def check_ledger(ds: Dataset) -> list[str]:
    """Check that each pointer resolves, and that its targets are in the article of the entry.

    NOK: the article text must name the NOK article (except status annex_a). A superseded pointer
    names a later confirmed pointer of the same article.
    """
    if not ds.ledger.exists():
        return [f"ledger: {ds.root.name}/ledger.json does not exist"]
    errors, docs = [], {}
    for num, entry in read_json(ds.ledger)["articles"].items():
        name = re.compile(rf"(?:άρθρ(?:ο|ου|α|ων)|προστίθεται\s+άρθρο)[^.]{{0,40}}?\b{re.escape(num)}(?![\dΑ-Ω])")
        confirmed = {f"{p['source']} άρθ. {p['article']}" for p in entry["amended_in"] if p.get("status") == "confirmed"}
        if not all(x.isdigit() for x in entry.get("not_codified", [])):
            errors.append(f"ledger: {num}: bad not_codified {entry['not_codified']}")
        for p in entry["amended_in"]:
            tag = f"ledger: {ds.key} {num} -> {p['source']} article {p['article']}"
            errors += [f"{tag}: target {t} is not in article {num}" for t in p.get("targets", []) if t.split(".")[0] != num]
            if p.get("status") == "superseded" and p.get("superseded_by") not in confirmed:
                errors.append(f"{tag}: superseded_by «{p.get('superseded_by')}» is not a confirmed pointer")
            if not p["source"]:
                if p.get("status") != "annex_a":
                    errors.append(f"{tag}: no source file")
                continue
            art = pointer_article(ds, p, docs, tag, errors)
            if art is not None and ds is NOK and p["status"] != "annex_a":
                text = re.sub(r"\s+", " ", art["title"] + " " + " ".join(x["text"] for x in art["paragraphs"]))
                if not name.search(text):
                    errors.append(f"{tag}: the article text does not name article {num}")
    return errors


def has_paragraph(ids: set[str], article: str, para: str) -> bool:
    prefix = f"{article}.{para}"
    return any(i == prefix or i.startswith(prefix + ".") or i.startswith(prefix + "#") for i in ids)


def check_crosswalk() -> tuple[list[str], list[str]]:
    """Check that each crosswalk id is well formed and names an existing article of its dataset.

    A paragraph that the text does not have gives a warning. NOK paragraph numbers come from
    the text in force at codification, so the 2012 text can lack them.
    """
    if not CROSSWALK.exists():
        return [f"crosswalk: {CROSSWALK.name} does not exist"], []
    for ds in (NOK, CODE):
        if not ds.json_path(ds.main).exists():
            return [f"crosswalk: {ds.root.name}/json/{ds.main}.json does not exist. Run: fetch {ds.key}"], []
    nok_articles = set(read_json(NOK.ledger)["articles"]) if NOK.ledger.exists() else set()
    nok_text = {a["article"]: {p["id"] for p in a["paragraphs"]} for a in NOK.load(NOK.main)["acts"][0]["articles"]}
    code_text = {a["article"]: {p["id"] for p in a["paragraphs"]} for a in CODE.load(CODE.main)["articles"]}
    nok_articles |= set(nok_text)
    errors, warnings, seen, missing = [], [], set(), {"nok": [], "code": []}
    for link in read_json(CROSSWALK)["links"]:
        pair = (link["nok"], link["code"])
        if pair in seen:
            errors.append(f"crosswalk: repeated link {pair}")
        seen.add(pair)
        for ref, key, known, text in ((link["nok"], "nok", nok_articles, nok_text),
                                      (link["code"], "code", set(code_text), code_text)):
            k, article, para = split_ref(ref)
            # A paragraph can have a letter: Code definitions «Περ. 7Α» give "code:197.7Α".
            if k != key or not re.fullmatch(rf"{key}:\d+[Α-Ω]?(?:\.(?:\d+[Α-Ω]?|[α-ω]+))?", ref):
                errors.append(f"crosswalk: bad id «{ref}»")
            elif article not in known:
                errors.append(f"crosswalk: «{ref}»: article {article} is not in the {key} dataset")
            elif para and article in text and not has_paragraph(text[article], article, para):
                missing[key].append(ref)
    if missing["nok"]:
        warnings.append(f"crosswalk: {len(missing['nok'])} NOK paragraphs are not in the 2012 text (numbering of the "
                        f"text in force at codification): {', '.join(missing['nok'][:8])} ...")
    if missing["code"]:
        warnings.append(f"crosswalk: {len(missing['code'])} Code paragraphs are not in the Code text: "
                        f"{', '.join(missing['code'][:8])}")
    return errors, warnings


def report(name: str, errors: list[str], warnings: list[str], limit: int = 5) -> bool:
    print(f"{'FAIL' if errors else 'ok  '} {name}" + (f"  ({len(warnings)} warnings)" if warnings else ""))
    for e in errors:
        print(f"    {e}")
    for w in warnings[:limit]:
        print(f"    ~ {w}")
    return bool(errors)


def run(ds: Dataset, only: set[str] = frozenset()) -> int:
    """Check the files of a dataset, its ledger and (for the Code) the crosswalk. Return the number of failures."""
    notes = render.nok_notes() if ds is NOK else None
    failed, files = 0, 0
    for path in ds.json_paths():
        if only and path.stem not in only:
            continue
        doc = read_json(path)
        files += 1
        if ds is CODE and path.stem == CODE.main:
            failed += report(path.stem, *check_code_text(doc), limit=10)
        else:
            failed += report(path.stem, *check_issue(ds, doc, notes))
    print(f"\n{files - failed}/{files} files without errors")
    if not only:
        failed += report("ledger.json", check_ledger(ds), [])
        if ds is CODE:
            failed += report(CROSSWALK.name, *check_crosswalk())
    return failed
