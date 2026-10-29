#!/usr/bin/env python3
"""Query the bundled Greek building regulations. Read-only, offline, standard library only.

    regs.py info
    regs.py search <stem> [<stem> ...] [--in code|nok|fire|issues|all] [--limit N]
    regs.py read <id>
    regs.py history <id> [--dates] [--as-of YYYY-MM-DD]
    regs.py changes [--since YYYY-MM-DD] [--in code|nok|fire]
    regs.py trace <id>
    regs.py toc <code|nok|fire|FEK-A-<n>-<year>> [--section TEXT]

Every command also takes --page N (long output comes in pages of about 12,000 characters)
and --full (no pages).

Ids: code:224.3.β (the Code «Νικόλαος Ταγαράς», law 5306/2026), nok:27.5 (the NOK, law 4067/2012),
fire:Α5.3.7.1 (the fire code, π.δ. 41/2018: Chapter Α, article 5, paragraph 5.3.7.1),
FEK-A-108-2026:133.1 (another Gazette issue). ASCII works for Greek letters: code:224.3.b, fire:A5.3.
Output is plain text. Its first line says how far the Gazette was checked.
"""
import argparse, datetime, json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
sys.dont_write_bytecode = True      # Never write __pycache__ into the installed plugin.
sys.path.insert(0, str(HERE))
import ids  # noqa: E402

PAGE = 12_000                       # Characters per page of output.
SNIPPET = 260                       # Characters of a search hit. Shorter paragraphs are given whole.
PER_ARTICLE = 3                     # Search hits shown per article.
BUILDING_RULES = "ΜΕΡΟΣ Δ"          # Code Part Δ «Κανόνες δόμησης και χρήσης» (from article 195).
# Part Δ Section Ι (articles 195-225) is the general building code («Οικοδομικός Κανονισμός»).
GENERAL_RULES = re.compile(r"^ΤΜΗΜΑ [IΙ] ")
TITLE_WEIGHT = 10                   # Search score of each search term in an article title.
CODE_START = "2026-06-08"           # The Code is in force from this date. The NOK applies before it.
FIRE_PUBLISHED = "2018-05-08"       # ΦΕΚ Α΄ 80/2018, the fire code.
WEAK = {"matcher", "annex_a", "unchecked", "title", "chapter"}
STATUS = {
    "confirmed": "the amending text names the article and Annex A of the Code lists it",
    "superseded": "a later confirmed amendment rewrote this text",
    "unchecked": "one source only: the article is not in Annex A",
    "matcher": "one source only: found by the text matcher. Check the amending text",
    "annex_a": "one source only: Annex A lists it, and its Gazette text is not in the datasets",
    "title": "one source only: the title of the amending article names the article",
    "repeal": "a repeal",
    "chapter": "the amending text names the article without its chapter: the chapter comes from the paragraph "
               "numbers it cites. Check it",
}
NAMES = {"code": "Code", "nok": "NOK", "fire": "fire code"}
# The fire code applies with acts of series Β of the Gazette, which the datasets do not hold.
SERIES_B = ("Series Β of the Gazette is not in the datasets: the Fire Service provisions (Πυροσβεστικές Διατάξεις) "
            "and the ministerial decisions that apply with the fire code are not here. Say so if the answer can "
            "depend on them.")


class QueryError(Exception):
    pass


class Store:
    """The index and the JSON files, each read once."""

    def __init__(self):
        self.index = json.loads((DATA / "index.json").read_text(encoding="utf-8"))
        self.docs = {}

    @property
    def updated(self) -> str:
        u = self.index["updated"]
        return f"Gazette checked through {u['through']} (scanned {u['scanned_at']})"

    def doc(self, file: str) -> dict:
        """Return a Gazette file. An issue that two datasets hold has a file in each: they are read as one."""
        if file not in self.docs:
            meta = self.index["files"].get(file)
            if not meta:
                raise QueryError(f"{file} is not in the datasets. List the files with: regs.py info")
            copies = [json.loads((DATA / self.index["datasets"][key]["dir"] / f"{file}.json").read_text(encoding="utf-8"))
                      for key in [meta["dataset"], *meta.get("also", [])]]
            self.docs[file] = merged(copies)
        return self.docs[file]

    def base(self, key: str) -> list[dict]:
        return ids.acts(self.doc(self.index["datasets"][key]["file"]))[0]["articles"]

    def locate(self, gid: str) -> dict:
        """Return where an id is: scope, local id, act, ΦΕΚ, file, article record and index entry."""
        scope, local = ids.split(gid)
        if scope in ids.SCOPES:
            ds = self.index["datasets"][scope]
            entry = self.index["articles"].get(ids.make(scope, ids.article(local)))
            if entry is None:
                hint = ""
                if scope == "fire" and ids.article(local).isdigit():     # The fire code numbers each chapter from 1.
                    rest = local[len(ids.article(local)):]
                    found = [ids.make(scope, c + local) for c in "ΑΒΓ"
                             if ids.make(scope, c + ids.article(local)) in self.index["articles"]]
                    hint = (f" Its articles start with the chapter letter: {' or '.join(found)}" if found and not rest
                            else f" Its articles start with the chapter letter, e.g. fire:Α{local}") + "."
                raise QueryError(f"{ids.make(scope, ids.article(local))} is not an article of the {scope} dataset.{hint} "
                                 f"Browse the articles with: regs.py toc {scope}")
            record = self.base(scope)[entry["at"]] if "at" in entry else None
            return {"scope": scope, "local": local, "file": ds["file"], "act": ds["act"], "fek": ds["fek"],
                    "record": record, "entry": entry}
        doc = self.doc(scope)
        if not local:
            raise QueryError(f"{gid} names a whole issue. List its articles with: regs.py toc {gid}")
        for act in ids.acts(doc):
            for a in act["articles"]:
                if a["article"] == ids.article(local):
                    return {"scope": scope, "local": local, "file": scope, "act": act["act"], "fek": doc["fek"],
                            "record": a, "entry": None}
        raise QueryError(f"{scope} has no article {ids.article(local)} in the datasets. "
                         f"List its articles with: regs.py toc {scope}")

    def cite(self, where: dict, local: str) -> str:
        a = where["record"]
        label = None
        if a and a.get("label"):
            label = a["label"] if a["article"].startswith("Π-") else f"άρθ. {a['label']}"
        return ids.cite(local, where["act"], where["fek"], label)

    def paragraphs(self, where: dict, within: list[str] | None = None) -> list[dict]:
        """Return the paragraphs of an article inside any local id of `within` (default: the id of `where`)."""
        a = where["record"]
        if a is None:
            return []
        within = within or [where["local"]]
        return [p for p in a["paragraphs"] if any(ids.within(p["id"], w) for w in within)]


def merged(copies: list[dict]) -> dict:
    """Return one file from the copies of an issue: the articles of each act that any copy keeps, in order."""
    doc = copies[0]
    reasons = [m.group(1) for c in copies if (m := re.search(r"relevant to (.+?)\. The full text", c.get("extract", "")))]
    if len(reasons) > 1:
        doc["extract"] = f"Only the articles relevant to {' or '.join(dict.fromkeys(reasons))}. The full text is at the source URL."
    for other in copies[1:]:
        for act in other["acts"]:
            same = next((a for a in doc["acts"] if a["act"] == act["act"]), None)
            if same is None:
                doc["acts"].append(act)
                continue
            have = {a["article"] for a in same["articles"]}
            same["articles"] += [a for a in act["articles"] if a["article"] not in have]
            same["articles"].sort(key=lambda a: (a["article"].startswith("Π-"), int(re.match(r"\d*", a["article"]).group() or 0)))
    return doc


class Out:
    """Plain-text output, in pages of about PAGE characters."""

    def __init__(self, updated: str):
        self.head, self.lines = updated, []

    def __call__(self, line: str = ""):
        self.lines.append(line)

    def render(self, page: int, full: bool) -> str:
        body = "\n".join(self.lines).strip("\n")
        if full or len(body) <= PAGE:
            if page > 1:
                return f"{self.head}\nThere is only one page."
            return f"{self.head}\n{body}"
        pages, cur, size = [], [], 0
        for line in body.split("\n"):
            while len(line) > PAGE:                  # A very long paragraph is split inside the line.
                cut = line.rfind(" ", 0, PAGE)
                cut = cut if cut > 0 else PAGE
                if cur:
                    pages.append(cur)
                pages.append([line[:cut] + " …"])
                cur, size, line = [], 0, "… " + line[cut:].lstrip()
            if size + len(line) > PAGE and cur:
                pages.append(cur)
                cur, size = [], 0
            cur.append(line)
            size += len(line) + 1
        pages.append(cur)
        if page > len(pages):
            return f"{self.head}\nThere are only {len(pages)} pages."
        more = (f"Page {page} of {len(pages)}. Next: run the same command with --page {page + 1}."
                if page < len(pages) else f"Page {page} of {len(pages)} (last).")
        return f"{self.head}\n" + "\n".join(pages[page - 1]) + f"\n\n{more}"


def paragraph_block(out: Out, store: Store, where: dict, p: dict, xrefs: dict | None = None):
    out(f"[{ids.make(where['scope'], p['id'])}] {store.cite(where, p['id'])}")
    if p.get("printed"):
        out(f"  The Gazette misprints its number as «{p['printed']}». The id follows the sequence of the numbers.")
    out(p["text"])
    refs = (xrefs or {}).get(ids.make(where["scope"], p["id"]))
    if refs:
        out(f"  refers to: {', '.join(refs)}")


def article_header(out: Out, store: Store, where: dict):
    a = where["record"]
    article = ids.article(where["local"])
    title = a["title"] if a else where["entry"]["title"]
    out(f"{store.cite(where, article)} — {title or '(no title)'}")
    if a and a.get("path"):
        out("Section: " + " › ".join(a["path"]))
    if a and a.get("match"):
        out(f"Kept because: {MATCH.get(a['match'], a['match'])}")


MATCH = {
    "number": "it cites the law of the dataset by number",
    "name": "it names the NOK without its number (check it)",
    "related": "an article of the same act that refers to an amending article",
    "commencement": "the commencement article of the act",
    "title": "the whole act is about the NOK",
    "annex": "an annex that a kept article refers to",
}


def gaps(where: dict, gid: str, shown: list[dict]) -> list[str]:
    """Return the notes about text the datasets lack."""
    a, notes = where["record"], []
    if a is None:
        return [f"{ids.make(where['scope'], ids.article(where['local']))} is not in the text of {where['file']}: an "
                f"amendment added it. Read its text with: regs.py history {gid}"]
    whole = where["local"] == ids.article(where["local"])
    # A paragraph id shows the images and tables on the pages of its paragraphs, and the tables they name.
    pages = None if whole or not shown else set(range(min(p["page"] for p in shown), max(p["page"] for p in shown) + 1))
    named = {n for p in shown for n in re.findall(r"Πίνακ\w*\s+(\d+)", p["text"])}
    if a.get("transcribed"):
        notes.append(a["transcribed"] + " Check the diagram in the Gazette before relying on it.")
    elif a.get("missing_text"):
        notes.append(f"The Gazette prints this article as an image (PDF pages {a.get('image_pages')}). The datasets "
                     "have no text for it: do not state its rule.")
    elif a.get("not_parsed"):
        notes.append(f"The parser did not find this article. See the Gazette PDF near page {a.get('page')}.")
    elif a.get("image_pages") and (pages is None or pages & set(a["image_pages"])):
        images = a["image_pages"] if pages is None else sorted(pages & set(a["image_pages"]))
        notes.append(f"Part of this article is an image, or a table without a text layer, in the Gazette (PDF pages "
                     f"{images}). The text below is incomplete.")
    if a.get("decoded"):
        notes.append(a["decoded"])
    ids_shown = {p["id"] for p in shown}
    for t in a.get("tables", []):
        # A table is shown with the paragraphs that hold it, or that name it. A table whose text the build
        # did not place (a font without a text map) goes by its pages.
        here = ids_shown & set(t["paragraphs"]) if t.get("paragraphs") else pages is None or pages & set(t["pages"])
        if pages is not None and not here and t["table"] not in named:
            continue
        first, last = t["pages"][0], t["pages"][-1]
        at = f"PDF page {first}" if first == last else f"PDF pages {first}-{last}"
        name = f"Πίνακας {t['table']}" if t["table"] else "A table without a caption"
        if t.get("order") == "rows":
            notes.append(f"{name} ({at}): its rows are in the text below in order, but its column headings are "
                         "not. Check the headings on the page before you state a value, and cite the table and its page.")
        else:
            notes.append(f"{name} ({at}): its cells are in the text below out of order. Do not state "
                         "a value from the table: cite it and its page.")
    if a.get("cut"):
        notes.append(a["cut"])
    if not shown and not a.get("missing_text") and not a.get("not_parsed"):
        if not a["paragraphs"]:
            notes.append(f"The datasets have no text for this article (a table or an image in the Gazette). "
                         f"See the Gazette PDF of {where['file']} near page {a.get('page')}.")
        elif where["scope"] == "nok":
            notes.append(f"{gid} is not in the 2012 text: an amendment added or renumbered it. "
                         f"Run: regs.py history {gid}")
        else:
            notes.append(f"{gid} is not a paragraph id of the text. Read the article: regs.py read "
                         f"{ids.make(where['scope'], ids.article(where['local']))}")
    return notes


def pointers_of(where: dict, gid: str, as_of: str | None = None) -> tuple[list[dict], int]:
    """Return (the amendments that can change gid, in date order; the number of superseded ones left out).

    A pointer without targets concerns the whole article. `as_of` keeps the pointers published by that
    date. A superseded pointer is left out only if the pointer that rewrote its text is kept.
    """
    whole = where["local"] == ids.article(where["local"])
    pointers = [p for p in where["entry"].get("amended_by", [])
                if (whole or not p.get("targets") or any(ids.related(t, gid) for t in p["targets"]))
                and (not as_of or not p.get("published") or p["published"] <= as_of)]
    kept = {p["by"] for p in pointers}
    shown = [p for p in pointers if not (p.get("status") == "superseded" and p.get("superseded_by") in kept)]
    shown.sort(key=lambda p: p.get("published") or "")
    return shown, len(pointers) - len(shown)


def uncodified(where: dict, gid: str) -> list[str]:
    return [x for x in (where["entry"] or {}).get("not_codified", []) if ids.related(x, gid)]


def links_of(store: Store, gid: str) -> list[dict]:
    scope = ids.split(gid)[0]
    return [link for link in store.index["links"] if ids.related(link[scope], gid)]


def status_lines(store: Store, where: dict, gid: str) -> list[str]:
    out = []
    pointers, _ = pointers_of(where, gid)
    if pointers:
        last = max((p.get("published") or "" for p in pointers), default="")
        out.append(f"Status: amended {len(pointers)} time(s) in the datasets, latest {last or 'date unknown'}. "
                   f"The text below is as first published. Run: regs.py history {gid}")
    elif where["scope"] == "code":
        out.append(f"Status: no amendment in the datasets since {CODE_START}.")
    else:
        out.append("Status: no amendment in the datasets.")
    if where["entry"].get("repealed_by"):
        out.append(f"Repealed by {where['entry']['repealed_by']}.")
    if where["scope"] == "fire":                 # Annex A of the Code does not cover the fire code.
        out.append(SERIES_B)
        return out
    links = links_of(store, gid)
    if links:
        other = "nok" if where["scope"] == "code" else "code"
        names = list(dict.fromkeys(link[other] for link in links))
        verb = "From the NOK (Annex A)" if other == "nok" else "Now in the Code (Annex A)"
        out.append(f"{verb}: {', '.join(names[:8])}{' …' if len(names) > 8 else ''}. Run: regs.py trace {gid}")
    if (rest := uncodified(where, gid)):
        out.append(f"Not codified: {', '.join(rest)}. Annex A does not list them, so Code article 477 did not repeal "
                   "them, and the Code has no such text. Whether they still apply needs legal advice.")
    return out


def cmd_info(store: Store, args, out: Out):
    idx = store.index
    counts = {}
    for meta in idx["files"].values():
        for key in [meta["dataset"], *meta.get("also", [])]:
            counts[key] = counts.get(key, 0) + 1
    out("Datasets:")
    for key, ds in idx["datasets"].items():
        out(f"  {key:5} {ds['title']}, {ds['act'].lower()} (ΦΕΚ {ds['fek']}). In force {ds['in_force']}. "
            f"{counts.get(key, 1) - 1} other Gazette issues that amend or cite it.")
    out("The texts are Gazette texts, not consolidations: apply each amendment to the text yourself.")
    out("")
    out("Ids:")
    for k, v in ids.GRAMMAR.items():
        out(f"  {k:38} {v}")
    out("")
    out("Commands:")
    for line in __doc__.split("\n\n")[1].splitlines():
        out("  " + line.strip())


def alternatives(term: str, groups: list[list[str]]) -> list[list[str]]:
    """Return the ways a search stem can match: itself, and each synonym of its group (one or more stems)."""
    alts = [[term]]
    for group in groups:
        singles = [s for s in group if " " not in s]
        if any(term.startswith(s) or (len(term) >= 4 and s.startswith(term)) for s in singles):
            alts += [s.split() for s in group if s.split() not in alts]
    return alts


def tier(key: str, base: bool, article: dict) -> int:
    """Search order: the general building code (Code Part Δ Section Ι), the rest of Part Δ and the fire code, other
    Code articles, later issues, the NOK, NOK amendments."""
    if key == "fire":
        return 1 if base else 3
    if key == "code":
        if not base:
            return 3
        path = (article.get("path") or []) + ["", ""]
        if path[0].startswith(BUILDING_RULES):
            return 0 if GENERAL_RULES.match(path[1]) else 1
        return 2
    return 4 if base else 5


LOOKALIKE = str.maketrans("abehikmnoptxyz", "αβεηικμνορτχυζ")


def searchable(text: str) -> str:
    """Return text for matching: folded (ids.fold), with Latin letters that look Greek as Greek. The Gazette
    mixes them («Α2-s1» with a Greek Α, «Cα»), and an engineer types either. The length does not change."""
    return ids.fold(text).translate(LOOKALIKE)


def snippet(text: str, stems: list[str]) -> str:
    if len(text) <= SNIPPET:
        return text
    folded = searchable(text)
    at = min((folded.find(s) for s in stems if s in folded), default=0)
    lo = max(0, at - SNIPPET // 3)
    if lo:                                          # Start and end on a word boundary.
        lo = text.find(" ", lo) + 1 or lo
    hi = min(len(text), lo + SNIPPET)
    if hi < len(text):
        hi = text.rfind(" ", lo, hi) if text.rfind(" ", lo, hi) > lo else hi
    return ("…" if lo else "") + text[lo:hi] + ("…" if hi < len(text) else "")


def cmd_search(store: Store, args, out: Out):
    terms = [searchable(t) for t in args.terms if t.strip()]
    if not terms:
        raise QueryError("give at least one search stem")
    alts = [alternatives(t, store.index.get("synonyms", [])) for t in terms]
    for t, a in zip(terms, alts):
        if len(a) > 1:
            out(f"«{t}» also matches: {', '.join(' + '.join(x) for x in a[1:])}")
    hits = {}                          # (tier, order) -> [article line, [(score, order, paragraph line)]]
    order = 0
    for file, meta in store.index["files"].items():
        key = meta["dataset"]
        base = file == store.index["datasets"][key]["file"]
        part = key if base else "issues"
        if args.scope != "all" and args.scope != part:
            continue
        doc = store.doc(file)
        for act in ids.acts(doc):
            for a in act["articles"]:
                order += 1
                scope = key if base else file
                where = {"scope": scope, "local": a["article"], "act": act["act"], "fek": doc["fek"], "record": a}
                ftitle = searchable(a["title"] or "")
                found = []
                for p in a["paragraphs"]:
                    hay = searchable(p["text"])
                    matched = [next((alt for alt in alt_set if all(s in hay or s in ftitle for s in alt)), None)
                               for alt_set in alts]
                    if not all(matched):
                        continue
                    stems = [s for alt in matched for s in alt]
                    if not any(s in hay for s in stems):     # The title alone does not make a hit.
                        continue
                    score = sum(hay.count(s) for s in stems) + sum(2 for s in stems if s in ftitle)
                    found.append((-score, len(found),
                                  f"  {ids.make(scope, p['id'])}  {snippet(p['text'], stems)}"))
                if found:
                    head = f"{ids.make(scope, a['article'])}  {store.cite(where, a['article'])} — {a['title']}"
                    if not base:
                        head += f"  [{doc['published']}]"
                    in_title = sum(any(all(s in ftitle for s in alt) for alt in alt_set) for alt_set in alts)
                    found.sort()
                    hits[(tier(key, base, a), order)] = (head, found, TITLE_WEIGHT * in_title - found[0][0])
    if not hits:
        out(f"No paragraph matches all of: {', '.join(terms)}.")
        out("Try fewer or shorter stems (Greek inflects: «εξωστ», «υψ», «προκηπ»), or --in all.")
        return
    keys = sorted(hits, key=lambda k: (k[0], -hits[k][2], k[1]))
    total = sum(len(h[1]) for h in hits.values())
    out(f"{total} paragraphs in {len(hits)} articles match. The general building rules of the Code "
        "(Part Δ Section Ι, articles 195-225) come first, then the rest of Part Δ and the fire code.")
    for k in keys[:args.limit]:
        head, found, _ = hits[k]
        out("")
        out(head)
        for _, _, line in found[:PER_ARTICLE]:
            out(line)
        if len(found) > PER_ARTICLE:
            out(f"  … {len(found) - PER_ARTICLE} more paragraphs in this article: regs.py read {head.split()[0]}")
    if len(keys) > args.limit:
        rest = keys[args.limit:]
        out("")
        out(f"{len(rest)} more articles: " + ", ".join(hits[k][0].split()[0] for k in rest[:20])
            + (" …" if len(rest) > 20 else "") + f". Show more with --limit {min(len(keys), args.limit * 3)}.")


def cmd_read(store: Store, args, out: Out):
    gid = ids.normalize(args.id)
    where = store.locate(gid)
    shown = store.paragraphs(where)
    a = where["record"]
    if not shown and a and a["paragraphs"] and where["local"] != ids.article(where["local"]) and where["scope"] != "nok":
        raise QueryError(f"{gid} is not a paragraph id of the text. {nearest(where)}")
    article_header(out, store, where)
    if where["entry"] is not None:
        for line in status_lines(store, where, gid):
            out(line)
    for note in gaps(where, gid, shown):
        out(f"Note: {note}")
    xrefs = store.index.get("xrefs", {}) if where["scope"] in ids.SCOPES else {}
    for p in shown:
        out("")
        paragraph_block(out, store, where, p, xrefs)


def nearest(where: dict) -> str:
    """Return a hint for a paragraph id that the text does not have: the ids of its nearest existing part."""
    local, have = where["local"], [p["id"] for p in where["record"]["paragraphs"]]
    while local != ids.article(local):
        local = re.split(r"[.#~@][^.#~@]*$", local)[0]
        inner = [i for i in have if ids.within(i, local) and i != local]
        if local in have or inner:
            listed = ", ".join(ids.make(where["scope"], i) for i in ([local] if local in have else []) + inner[:12])
            return (f"The nearest part that exists is {ids.make(where['scope'], local)}: {listed}"
                    f"{' …' if len(inner) > 12 else ''}. Since version 2.1.0 the text after a clause that ends a "
                    "sentence has the id of its paragraph («7.3#2», formerly «7.3.β#1»).")
    return f"Read the article: regs.py read {ids.make(where['scope'], ids.article(where['local']))}"


def commencement_of(store: Store, by: str, act: str) -> list[dict]:
    file = ids.split(by)[0]
    return [c for c in store.index.get("commencement", []) if ids.split(c["article"])[0] == file and c["act"] == act]


def governing(rules: list[dict], by: str) -> dict:
    """Return the commencement article that governs the article `by`.

    An omnibus law closes each of its parts with a commencement article (ν. 4710/2020: article 11
    for its tax part, article 65 for the rest). The one that governs an article is the first at or
    after it, else the last.
    """
    def number(gid: str) -> int:
        m = re.match(r"\d+", ids.article(ids.split(gid)[1]))
        return int(m.group()) if m else 0
    rules = sorted(rules, key=lambda c: number(c["article"]))
    return next((c for c in rules if number(c["article"]) >= number(by)), rules[-1])


def start_line(store: Store, p: dict) -> str:
    if not p["by"]:
        return "starts: unknown (no Gazette text in the datasets)"
    rules = commencement_of(store, p["by"], p["act"])
    if not rules:
        return "starts: no commencement article in the datasets. Check the act"
    c = governing(rules, p["by"])
    also = (f", or {c['from_issued']} counted from the date on the masthead" if c.get("from_issued") else "")
    if c["rule"] == "publication":
        return f"starts: {c['from']}{also} (the whole act, {c['article']})"
    if c["rule"] == "publication-unless":
        return (f"starts: {c['from']}{also} unless the amending article sets another date "
                f"(commencement article {c['article']})")
    return f"starts: read the commencement article {c['article']}"


def amendment_line(store: Store, p: dict) -> str:
    by = p["by"] or f"{p['act']} άρθ. {p['article']} (no Gazette text)"
    targets = f" → {', '.join(p['targets'])}" if p.get("targets") else ""
    status = f" [{p['status']}]" if p.get("status") else ""
    restates = " (gives the full new text)" if p.get("restates") else ""
    return f"{p.get('published') or 'date unknown'}  {p['act']}  {by}  {p['kind']}{restates}{targets}{status}"


def restated_part(gid: str, texts: list[dict]) -> list[dict] | None:
    """Return the paragraphs of an amendment that restates a whole article, cut to the part `gid` asks for.

    The new text is quoted: "26.2~6.7#3" is text of paragraph 6.7 that ν. 4710/2020 art. 26 par. 2 gives
    article 6 of the fire code. A fire code paragraph keeps its decimal number in the quote («6.7»),
    others their number below the article. Return None for a whole article, or if no quoted text matches.
    """
    local = ids.split(gid)[1]
    article = ids.article(local)
    if local == article:
        return None
    m = ids.CHAPTERED.fullmatch(article)
    want = m.group(2) + local[len(article):] if m else local[len(article) + 1:]
    part = [q for q in texts if "~" not in q["id"]
            or ids.within(q["id"].split("~", 1)[1], want)]
    return part if any("~" in q["id"] for q in part) else None


def cmd_history(store: Store, args, out: Out):
    gid = ids.normalize(args.id)
    where = store.locate(gid)
    if where["entry"] is None:
        raise QueryError("history works on code:, nok: and fire: ids. Read a Gazette issue with: regs.py read <id>")
    pointers, hidden = pointers_of(where, gid, args.as_of)
    article_header(out, store, where)
    if args.as_of:
        out(f"As of {args.as_of}: amendments published after this date are left out. Publication is not "
            "commencement: see the start line of each amendment.")
    if where["scope"] == "nok" and args.as_of and args.as_of >= CODE_START:
        out(f"Note: from {CODE_START} the Code applies. Run: regs.py trace {gid}")
    if (rest := uncodified(where, gid)):
        out(f"Not codified: {', '.join(rest)} (see regs.py trace {gid}).")
    weak = sorted({p["status"] for p in pointers if p.get("status") in WEAK})
    if not pointers:
        out("No amendment of this provision in the datasets.")
    if args.dates:
        out("")
        for p in pointers:
            out(amendment_line(store, p))
            out(f"    {start_line(store, p)}")
        if pointers:
            out("")
            out(f"Read the texts with: regs.py history {gid}" + (f" --as-of {args.as_of}" if args.as_of else ""))
    else:
        out("")
        out("== Text as first published")
        base = store.paragraphs(where)
        for note in gaps(where, gid, base):
            out(f"Note: {note}")
        for p in base:
            out("")
            paragraph_block(out, store, where, p)
        for n, p in enumerate(pointers, 1):
            out("")
            out(f"== Amendment {n} of {len(pointers)}: {amendment_line(store, p)}")
            out(start_line(store, p))
            if not p["by"]:
                out("Only Annex A of the Code names this amendment. Its Gazette text is not in the datasets.")
                continue
            source, article = ids.split(p["by"])
            by = store.locate(p["by"])
            locals_ = [ids.split(x)[1] for x in p.get("paragraphs", [])] or [article]
            texts = full = store.paragraphs(by, locals_)
            if p.get("restates") and (part := restated_part(gid, texts)) is not None:
                out(f"Only the new text of {gid} and the amending words. All of it: regs.py history "
                    f"{ids.make(where['scope'], ids.article(where['local']))}")
                texts = part
            quoted = [q["page"] for q in texts if "~" in q["id"]] or [q["page"] for q in texts]
            after = full.index(texts[-1]) + 1 if texts else len(full)
            end = full[after]["page"] if after < len(full) else max(quoted, default=0)   # A table before the next part.
            images = sorted(pg for pg in (by["record"] or {}).get("image_pages", [])
                            if quoted and min(quoted) <= pg <= max(end, max(quoted)))
            if images:
                out(f"Note: Part of this amending text is an image in the Gazette (PDF pages {images}): its tables "
                    "and figures are not in the text below." + (" They replace those of the text as first published: "
                                                                "do not state the old values." if p.get("restates") else ""))
            for q in texts:
                out("")
                paragraph_block(out, store, by, q)
            related = related_of(store, source, by["act"], article)
            if related:
                out("")
                out("Related articles of the same act (read them if the answer depends on them):")
                for r in related:
                    out(f"  {r}")
    if hidden:
        out("")
        out(f"{hidden} superseded amendment(s) left out: a later confirmed amendment in the list rewrote them.")
    if weak:
        out("")
        for s in weak:
            out(f"[{s}]: {STATUS[s]}.")


def related_of(store: Store, file: str, act_label: str, article: str) -> list[str]:
    """Return the articles of the amending act that name the amending article (title and id only)."""
    names = re.compile(rf"άρθρ\w*\s+(?:\d+[Α-Ω]?\s*(?:,|και|έως|-)\s*)*{re.escape(article)}(?![\dΑ-Ω])")
    out = []
    for act in ids.acts(store.doc(file)):
        if act["act"] != act_label:
            continue
        for a in act["articles"]:
            if a["article"] != article and a.get("match") == "related" and \
                    names.search(" ".join(p["text"] for p in a["paragraphs"])):
                out.append(f"{ids.make(file, a['article'])} — {a['title']}")
    return out


def cmd_changes(store: Store, args, out: Out):
    since = args.since or {"code": CODE_START, "nok": "2012-04-09", "fire": FIRE_PUBLISHED}[args.scope]
    rows = []
    for gid, entry in store.index["articles"].items():
        if ids.split(gid)[0] != args.scope:
            continue
        for p in entry.get("amended_by", []):
            if (p.get("published") or "") >= since and p.get("status") != "superseded":
                rows.append((p.get("published") or "", gid, entry["title"], p))
    rows.sort(key=lambda r: (r[0], ids.article(ids.split(r[1])[1]).zfill(4)))
    name = NAMES[args.scope]
    if not rows:
        out(f"No amendment of the {name} published from {since} in the datasets.")
        return
    out(f"{len(rows)} amendments of the {name} published from {since}, oldest first:")
    for date, gid, title, p in rows:
        out("")
        out(f"{gid} — {title or '(article added by an amendment)'}")
        out(f"  {amendment_line(store, p)}")
        out(f"  {start_line(store, p)}")
    out("")
    out("Read the text of an amendment with: regs.py history <id>")


def cmd_trace(store: Store, args, out: Out):
    gid = ids.normalize(args.id)
    where = store.locate(gid)
    scope = where["scope"]
    if scope not in ("code", "nok"):
        raise QueryError("trace works on code: and nok: ids: it follows Annex A of the Code, which does not "
                         "cover the fire code.")
    out(f"{store.cite(where, where['local'])} — {(where['record'] or where['entry'])['title']}")
    nok = store.index["datasets"]["nok"]
    code_where = lambda c: store.locate(ids.make("code", ids.article(ids.split(c)[1])))  # noqa: E731
    links = links_of(store, gid)
    if links:
        out("")
        out("Annex A links (NOK → Code):")
        for link in links:
            nok_local, code_local = ids.split(link["nok"])[1], ids.split(link["code"])[1]
            out(f"  {link['nok']}  {ids.cite(nok_local, nok['act'], nok['fek'])}")
            out(f"    → {link['code']}  {store.cite(code_where(link['code']), code_local)}")
    places = [gid] if scope == "code" else [link["code"] for link in links]
    rows = []
    for article in dict.fromkeys(ids.article(ids.split(c)[1]) for c in places):
        record = code_where(f"code:{article}")["record"] or {}
        for s in record.get("sources", []):
            para = (s["code_paragraph"] or "").rstrip(")")
            row_id = ids.make("code", f"{article}.{para}" if para else article)
            if any(ids.related(row_id, c) for c in places):
                rows.append(f"  {row_id} ({s['code_label'] or 'whole article'}): {s['source']}")
    if rows:
        out("")
        out("Annex A rows (what each Code paragraph codifies, with the amendments it took in):")
        for r in rows:
            out(r)
    if (rest := uncodified(where, gid)):
        out("")
        out(f"Not codified: {', '.join(rest)}. Annex A does not list these provisions, so Code article 477 did not "
            "repeal them, and the Code has no such text. Whether they still apply needs legal advice.")
    elif not links:
        out("")
        out(f"Annex A links no NOK provision to {gid}." if scope == "code" else
            f"Annex A links no Code provision to {gid}.")


def cmd_toc(store: Store, args, out: Out):
    target = args.target.strip()
    scope = target.lower() if target.lower() in ids.SCOPES else ids.normalize(target)
    section = ids.fold(args.section) if args.section else None
    if scope == "code":
        path, n = None, 0
        for a in store.base("code"):
            if section and not any(section in ids.fold(h) for h in a["path"]) and section not in ids.fold(a["title"]):
                continue
            if a["path"] != path:
                path = a["path"]
                out("")
                out(" › ".join(path))
            out(f"  code:{a['article']}  {a['title']}")
            n += 1
        if not n:
            out(f"No section or title of the Code contains «{args.section}».")
        return
    if scope == "nok":
        scopes = {a["article"]: a.get("scope") for a in store.base("nok")}
        for gid, entry in store.index["articles"].items():
            if not gid.startswith("nok:"):
                continue
            num = ids.split(gid)[1]
            if section and section not in ids.fold(entry["title"]):
                continue
            note = " (added by an amendment)" if "at" not in entry else \
                (" (not a building rule)" if scopes.get(num) == "other" else "")
            out(f"  {gid}  {entry['title']}{note}")
        return
    if scope == "fire":
        doc = store.doc(store.index["datasets"]["fire"]["file"])
        out(f"In force: {doc['in_force']}.")
        if doc.get("commencement"):
            c = doc["commencement"]
            out(f"{c['article']} του π.δ. (PDF page {c['page']}): «{c['text']}»")
        path = None
        for a in doc["articles"]:
            if section and not any(section in ids.fold(h) for h in a["path"]) and section not in ids.fold(a["title"]):
                continue
            if a["path"] != path:
                path = a["path"]
                out("")
                out(path[0])
                for ch in doc["chapters"]:
                    if path[0].startswith(f"ΚΕΦΑΛΑΙΟ {ch['chapter']}΄"):
                        for p in ch.get("text", []):
                            out(f"  {p['text']}")
            note = (" (no text: a table in a font without a text map)" if a.get("missing_text") else
                    " (a diagram: its text is transcribed by hand)" if a.get("transcribed") else "")
            out(f"  fire:{a['article']}  {a['title'] or a['label']}{note}")
        return
    if ":" in scope:
        raise QueryError("toc takes code, nok, fire or a file id such as FEK-A-108-2026")
    doc = store.doc(scope)
    dated = f", dated {doc['issued']} on its masthead" if doc.get("issued") else ""
    out(f"{doc['title']} (ΦΕΚ {doc['fek']}, published {doc['published']}{dated})")
    if doc.get("extract"):
        out(doc["extract"])
    for act in ids.acts(doc):
        out("")
        out(act["act"] + (f" — {act['title']}" if act.get("title") else ""))
        starts = [a["article"] for a in act["articles"] if a.get("match") == "commencement"]
        for a in act["articles"]:
            if not section or section in ids.fold(a["title"]):
                why = MATCH.get(a.get("match"), a.get("match") or "")
                if a.get("match") == "commencement" and len(starts) > 1:
                    # An omnibus law has one per part: it governs the articles after the one before it.
                    k = starts.index(a["article"])
                    first = int(re.match(r"\d*", starts[k - 1]).group() or 0) + 1 if k else 1
                    why = f"a commencement article of the act, for articles {first}-{a['article']}"
                out(f"  {ids.make(scope, a['article'])}  {a['title']}  [{why}]")


def date(text: str) -> str:
    try:
        return datetime.date.fromisoformat(text).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError("use a date YYYY-MM-DD")


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--page", type=int, default=1, help="page of a long output")
    common.add_argument("--full", action="store_true", help="the whole output, without pages")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info", parents=[common], help="datasets, id grammar, commands")
    p = sub.add_parser("search", parents=[common], help="find paragraphs by word stems (all must match)")
    p.add_argument("terms", nargs="+")
    p.add_argument("--in", dest="scope", choices=["code", "nok", "fire", "issues", "all"], default="all")
    p.add_argument("--limit", type=int, default=8, help="articles to show")
    p = sub.add_parser("read", parents=[common], help="an article or paragraph, with its status")
    p.add_argument("id")
    p = sub.add_parser("history", parents=[common], help="the text as published and each amendment")
    p.add_argument("id")
    p.add_argument("--dates", action="store_true", help="one line per amendment, no texts")
    p.add_argument("--as-of", type=date, help="only amendments published by this date")
    p = sub.add_parser("changes", parents=[common], help="amendments published since a date")
    p.add_argument("--since", type=date)
    p.add_argument("--in", dest="scope", choices=["code", "nok", "fire"], default="code")
    p = sub.add_parser("trace", parents=[common], help="NOK <-> Code links (Annex A)")
    p.add_argument("id")
    p = sub.add_parser("toc", parents=[common], help="the articles of code, nok, fire or an issue")
    p.add_argument("target")
    p.add_argument("--section", help="only sections or titles that contain this text")
    args = parser.parse_args(argv)

    commands = {"info": cmd_info, "search": cmd_search, "read": cmd_read, "history": cmd_history,
                "changes": cmd_changes, "trace": cmd_trace, "toc": cmd_toc}
    try:
        store = Store()
    except (OSError, ValueError) as e:
        print(f"Error: cannot read the datasets in {DATA}: {e}")
        return 2
    out = Out(store.updated)
    try:
        commands[args.command](store, args, out)
    except (QueryError, ValueError) as e:
        print(f"{store.updated}\nError: {e}")
        return 2
    print(out.render(max(1, args.page), args.full))
    return 0


if __name__ == "__main__":
    sys.exit(main())
