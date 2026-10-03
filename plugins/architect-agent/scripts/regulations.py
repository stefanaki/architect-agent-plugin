#!/usr/bin/env python3
"""Query the bundled Greek building regulations. Read-only, offline, standard library only.

    regulations.py info
    regulations.py search <term> [<term> ...] [--dataset code|nok] [--limit N]
    regulations.py get <id>
    regulations.py history <id> [--as-of YYYY-MM-DD]
    regulations.py trace <id>
    regulations.py toc <code|nok|FEK-A-<n>-<year>> [--section TEXT]

Ids: code:224.3.β (the Code «Νικόλαος Ταγαράς», law 5306/2026), nok:27.5 (the NOK, law 4067/2012),
FEK-A-108-2026:133.1 (another Gazette issue). ASCII works for clause letters: code:224.3.b.
Output is one JSON object. Each response has `updated`: how far the Gazette was checked.
"""
import argparse, json, re, sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REGULATIONS = PLUGIN_ROOT / "regulations"
sys.path.insert(0, str(REGULATIONS / "gazette" / "lib"))
import ids  # noqa: E402

SNIPPET = 300                       # Characters of a search hit. Shorter paragraphs are given whole.
BUILDING_RULES = "ΜΕΡΟΣ Δ"          # Code Part Δ «Κανόνες δόμησης και χρήσης» (from article 195).
AS_OF_NOTE = ("Amendments published after this date are left out. Publication is not commencement: "
              "check the commencement articles in `context`.")


class QueryError(Exception):
    pass


class Store:
    """The index and the JSON files, each read once."""

    def __init__(self):
        self.index = json.loads((REGULATIONS / "index.json").read_text(encoding="utf-8"))
        self.docs = {}

    @property
    def updated(self) -> str:
        u = self.index["updated"]
        return f"Gazette checked through {u['through']} (scanned {u['scanned_at']})"

    def doc(self, file: str) -> dict:
        if file not in self.docs:
            meta = self.index["files"].get(file)
            if not meta:
                raise QueryError(f"{file} is not in the datasets")
            folder = self.index["datasets"][meta["dataset"]]["dir"]
            self.docs[file] = json.loads((REGULATIONS / folder / "json" / f"{file}.json").read_text(encoding="utf-8"))
        return self.docs[file]

    def base(self, key: str) -> list[dict]:
        return ids.acts(self.doc(self.index["datasets"][key]["file"]))[0]["articles"]

    def locate(self, gid: str) -> dict:
        """Return where an id is: its scope, local id, act, ΦΕΚ, article record and index entry."""
        scope, local = ids.split(gid)
        if scope in ids.SCOPES:
            ds = self.index["datasets"][scope]
            entry = self.index["articles"].get(ids.make(scope, ids.article(local)))
            if entry is None:
                raise QueryError(f"{ids.make(scope, ids.article(local))} is not an article of the {scope} dataset")
            record = self.base(scope)[entry["at"]] if "at" in entry else None
            return {"scope": scope, "local": local, "file": ds["file"], "act": ds["act"], "fek": ds["fek"],
                    "record": record, "entry": entry}
        doc = self.doc(scope)
        if not local:
            raise QueryError(f"{gid} names a whole issue: use toc {gid}")
        for act in ids.acts(doc):
            for a in act["articles"]:
                if a["article"] == ids.article(local):
                    return {"scope": scope, "local": local, "file": scope, "act": act["act"], "fek": doc["fek"],
                            "record": a, "entry": None}
        raise QueryError(f"{scope} has no article {ids.article(local)}: use toc {scope}")

    def cite(self, where: dict, local: str) -> str:
        a = where["record"]
        label = None
        if a and a.get("label"):
            label = a["label"] if a["article"].startswith("Π-") else f"άρθ. {a['label']}"
        return ids.cite(local, where["act"], where["fek"], label)

    def paragraphs(self, where: dict, locals_: list[str] | None = None) -> list[dict]:
        """Return the paragraphs of an article inside any of `locals_` (default: the id of `where`)."""
        a = where["record"]
        if a is None:
            return []
        within = locals_ or [where["local"]]
        return [{"id": ids.make(where["scope"], p["id"]), "cite": self.cite(where, p["id"]), "text": p["text"]}
                for p in a["paragraphs"] if any(ids.within(p["id"], w) for w in within)]

    def article_info(self, where: dict) -> dict:
        a, scope = where["record"], where["scope"]
        local = ids.article(where["local"])
        out = {"id": ids.make(scope, local), "cite": self.cite(where, local)}
        if a is None:
            out["title"] = where["entry"]["title"]
            out["in_text"] = False
            return out
        out["title"] = a["title"]
        for k in ("path", "scope", "match", "missing_text", "not_parsed", "image_pages"):
            if a.get(k):
                out[k] = a[k]
        return out


def amendments_of(where: dict, gid: str, as_of: str | None = None) -> tuple[list[dict], int]:
    """Return (the pointers that can change gid, the number of superseded pointers left out).

    A pointer without targets concerns the whole article. `as_of` keeps the pointers published by
    that date. A superseded pointer is left out only if the pointer that rewrote its text is kept.
    """
    article_level = where["local"] == ids.article(where["local"])
    pointers = [p for p in where["entry"].get("amended_by", [])
                if (article_level or not p.get("targets") or any(ids.related(t, gid) for t in p["targets"]))
                and (not as_of or not p.get("published") or p["published"] <= as_of)]
    kept = {p["by"] for p in pointers}
    shown = [p for p in pointers if not (p.get("status") == "superseded" and p.get("superseded_by") in kept)]
    return shown, len(pointers) - len(shown)


def uncodified(where: dict, gid: str) -> list[str]:
    return [x for x in (where["entry"] or {}).get("not_codified", []) if ids.related(x, gid)]


def notes_for(where: dict, gid: str, paras: list[dict]) -> list[str]:
    a, notes = where["record"], []
    if a is None:
        notes.append(f"{ids.make(where['scope'], ids.article(where['local']))} is not in the text of "
                     f"{where['file']}: an amendment added it. Run: history {gid}")
    elif a.get("missing_text"):
        notes.append(f"The Gazette prints this article as an image (PDF pages {a.get('image_pages')}). "
                     "The datasets have no text for it.")
    elif a.get("not_parsed"):
        notes.append(f"The parser did not find this article. See the Gazette PDF near page {a.get('page')}.")
    elif a.get("image_pages"):
        notes.append(f"Part of this article is an image in the Gazette (PDF pages {a['image_pages']}). "
                     "The text is incomplete.")
    if a is not None and not paras and not a.get("missing_text") and not a.get("not_parsed"):
        if not a["paragraphs"]:
            notes.append(f"The datasets have no text for this article (a table or an image in the Gazette). "
                         f"See the Gazette PDF of {where['file']} near page {a.get('page')}.")
        elif where["scope"] == "nok":
            notes.append(f"{gid} is not in the 2012 text: an amendment added or renumbered it. Run: history {gid}")
        else:
            notes.append(f"{gid} is not a paragraph id of the text. Run: get "
                         f"{ids.make(where['scope'], ids.article(where['local']))}")
    return notes


def cmd_info(store: Store, args) -> dict:
    counts = {}
    for meta in store.index["files"].values():
        counts[meta["dataset"]] = counts.get(meta["dataset"], 0) + 1
    return {"about": store.index["about"], "datasets": store.index["datasets"], "files": counts,
            "ids": ids.GRAMMAR, "usage": [line.strip() for line in __doc__.split("\n\n")[1].splitlines()]}


def cmd_get(store: Store, args) -> dict:
    gid = ids.normalize(args.id)
    where = store.locate(gid)
    paras = store.paragraphs(where)
    out = {"id": gid, "cite": store.cite(where, where["local"]), "article": store.article_info(where),
           "paragraphs": paras}
    if where["entry"] is not None:
        out["amendments"] = len(amendments_of(where, gid)[0])
        out["links"] = sum(ids.related(link[where["scope"]], gid) for link in store.index["links"])
        if (rest := uncodified(where, gid)):
            out["not_codified"] = rest
    if (notes := notes_for(where, gid, paras)):
        out["notes"] = notes
    return out


def context_of(store: Store, file: str, act_label: str, article: str) -> list[dict]:
    """Return the commencement articles of an act, and its related articles that name the amending article."""
    doc = store.doc(file)
    names = re.compile(rf"άρθρ\w*\s+(?:\d+[Α-Ω]?\s*(?:,|και|έως|-)\s*)*{re.escape(article)}(?![\dΑ-Ω])")
    out = []
    for act in ids.acts(doc):
        if act["act"] != act_label:
            continue
        for a in act["articles"]:
            if a["article"] == article or a.get("match") not in ("commencement", "related"):
                continue
            if a.get("match") == "related" and not names.search(" ".join(p["text"] for p in a["paragraphs"])):
                continue
            where = {"scope": file, "local": a["article"], "act": act["act"], "fek": doc["fek"], "record": a}
            out.append({"id": ids.make(file, a["article"]), "cite": store.cite(where, a["article"]),
                        "match": a["match"], "title": a["title"], "paragraphs": store.paragraphs(where)})
    return out


def cmd_history(store: Store, args) -> dict:
    gid = ids.normalize(args.id)
    where = store.locate(gid)
    if where["entry"] is None:
        raise QueryError("history works on code: and nok: ids. Use get for an issue of the Gazette.")
    pointers, hidden = amendments_of(where, gid, args.as_of)
    amendments, context = [], {}
    for p in pointers:
        item = {k: p[k] for k in ("by", "article", "act", "published", "kind", "restates", "status", "targets")
                if p.get(k) is not None}
        if not p["by"]:
            item["note"] = "Only Annex A of the Code names this amendment. Its Gazette text is not in the datasets."
            amendments.append(item)
            continue
        source, article = ids.split(p["by"])
        by = store.locate(p["by"])
        item["cite"] = store.cite(by, article)
        locals_ = [ids.split(x)[1] for x in p.get("paragraphs", [])] or [article]
        item["text"] = store.paragraphs(by, locals_)
        if not p.get("published"):
            item["note"] = "Publication date unknown."
        amendments.append(item)
        key = f"{source} {by['act']}"
        if key not in context:
            context[key] = context_of(store, source, by["act"], article)
    out = {"id": gid, "cite": store.cite(where, where["local"]), "article": store.article_info(where),
           "base": store.paragraphs(where), "amendments": amendments,
           "context": [c for items in context.values() for c in items]}
    if args.as_of:
        out["as_of"] = {"date": args.as_of, "note": AS_OF_NOTE}
    if hidden:
        out["hidden"] = {"superseded": hidden, "note": "Rewritten later by a confirmed amendment in the list."}
    if (rest := uncodified(where, gid)):
        out["not_codified"] = rest
    if not amendments:
        out["notes"] = ["No amendment of this provision in the datasets."]
    return out


def cmd_trace(store: Store, args) -> dict:
    gid = ids.normalize(args.id)
    where = store.locate(gid)
    scope = where["scope"]
    if scope not in ids.SCOPES:
        raise QueryError("trace works on code: and nok: ids.")
    code_where = lambda c: store.locate(ids.make("code", ids.article(ids.split(c)[1])))  # noqa: E731
    nok_ds = store.index["datasets"]["nok"]
    links = []
    for link in store.index["links"]:
        if not ids.related(link[scope], gid):
            continue
        nok_local, code_local = ids.split(link["nok"])[1], ids.split(link["code"])[1]
        links.append({"nok": link["nok"], "nok_cite": ids.cite(nok_local, nok_ds["act"], nok_ds["fek"]),
                      "code": link["code"], "code_cite": store.cite(code_where(link["code"]), code_local)})
    places = [gid] if scope == "code" else [x["code"] for x in links]
    rows = []
    for article in dict.fromkeys(ids.article(ids.split(c)[1]) for c in places):
        record = code_where(f"code:{article}")["record"] or {}
        for s in record.get("sources", []):
            para = (s["code_paragraph"] or "").rstrip(")")
            row_id = ids.make("code", f"{article}.{para}" if para else article)
            if any(ids.related(row_id, c) for c in places):
                rows.append({"code": row_id, "label": s["code_label"], "source": s["source"]})
    out = {"id": gid, "cite": store.cite(where, where["local"]), "links": links, "annex_a": rows}
    if (rest := uncodified(where, gid)):
        out["not_codified"] = rest
        out["notes"] = ["Annex A does not list these provisions, so Code article 477 did not repeal them, and the "
                        "Code has no such text. Whether they still apply needs legal advice."]
    elif not links:
        out["notes"] = [f"Annex A links no NOK provision to {gid}." if scope == "code" else
                        f"Annex A links no Code provision to {gid}."]
    return out


def tier(key: str, base: bool, article: dict) -> int:
    """Search order: Code Part Δ (building rules), other Code articles, later issues, the NOK, NOK amendments."""
    if key == "code":
        if not base:
            return 2
        return 0 if (article.get("path") or [""])[0].startswith(BUILDING_RULES) else 1
    return 3 if base else 4


def snippet(text: str, terms: list[str]) -> str:
    if len(text) <= SNIPPET:
        return text
    folded = ids.fold(text)
    at = min((folded.find(t) for t in terms if t in folded), default=0)
    lo = max(0, at - SNIPPET // 3)
    hi = min(len(text), lo + SNIPPET)
    return ("…" if lo else "") + text[lo:hi] + ("…" if hi < len(text) else "")


def cmd_search(store: Store, args) -> dict:
    terms = [ids.fold(t) for t in args.terms if t.strip()]
    if not terms:
        raise QueryError("give at least one search term")
    hits, titles, order = [], [], 0
    for file, meta in store.index["files"].items():
        key = meta["dataset"]
        if args.dataset and key != args.dataset:
            continue
        doc = store.doc(file)
        base = file == store.index["datasets"][key]["file"]
        for act in ids.acts(doc):
            for a in act["articles"]:
                scope = key if base else file
                where = {"scope": scope, "local": a["article"], "act": act["act"], "fek": doc["fek"], "record": a}
                t = tier(key, base, a)
                ftitle = ids.fold(a["title"] or "")
                if all(term in ftitle for term in terms):
                    titles.append((t, order, {"id": ids.make(scope, a["article"]),
                                              "cite": store.cite(where, a["article"]), "title": a["title"]}))
                for p in a["paragraphs"]:
                    order += 1
                    hay = ids.fold(p["text"])
                    if not all(term in hay for term in terms):
                        continue
                    score = sum(hay.count(term) for term in terms) + sum(2 for term in terms if term in ftitle)
                    hits.append((t, -score, order, {
                        "id": ids.make(scope, p["id"]), "cite": store.cite(where, p["id"]), "title": a["title"],
                        "snippet": snippet(p["text"], terms), "score": score}))
    hits.sort(key=lambda h: h[:3])
    titles.sort(key=lambda h: h[:2])
    return {"terms": terms, "total": len(hits), "articles": [h[-1] for h in titles[:args.limit]],
            "paragraphs": [h[-1] for h in hits[:args.limit]]}


def cmd_toc(store: Store, args) -> dict:
    target = args.target.strip()
    scope = target.lower() if target.lower() in ids.SCOPES else ids.normalize(target)
    section = ids.fold(args.section) if args.section else None
    if scope == "code":
        groups = []
        for a in store.base("code"):
            if section and not any(section in ids.fold(h) for h in a["path"]):
                continue
            if not groups or groups[-1]["path"] != a["path"]:
                groups.append({"path": a["path"], "articles": []})
            groups[-1]["articles"].append([f"code:{a['article']}", a["title"]])
        return {"dataset": "code", "sections": groups}
    if scope == "nok":
        scopes = {a["article"]: a.get("scope") for a in store.base("nok")}
        rows = []
        for gid, entry in store.index["articles"].items():
            if not gid.startswith("nok:"):
                continue
            num = ids.split(gid)[1]
            if section and section not in ids.fold(entry["title"]):
                continue
            row = {"id": gid, "title": entry["title"]}
            if "at" not in entry:
                row["in_text"] = False
            elif scopes.get(num):
                row["scope"] = scopes[num]
            rows.append(row)
        return {"dataset": "nok", "articles": rows}
    if ":" in scope:
        raise QueryError("toc takes code, nok or a file id such as FEK-A-108-2026")
    doc = store.doc(scope)
    acts = []
    for act in ids.acts(doc):
        acts.append({"act": act["act"], "title": act.get("title", ""), "articles": [
            {"id": ids.make(scope, a["article"]), "title": a["title"], "match": a.get("match")}
            for a in act["articles"] if not section or section in ids.fold(a["title"])]})
    return {"file": scope, "fek": doc["fek"], "published": doc["published"], "acts": acts}


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info", help="datasets, update time, id grammar")
    p = sub.add_parser("search", help="find paragraphs by words or word stems")
    p.add_argument("terms", nargs="+")
    p.add_argument("--dataset", choices=ids.SCOPES)
    p.add_argument("--limit", type=int, default=20)
    for name, help_text in (("get", "the text of an article or paragraph"),
                            ("history", "the base text and the amendments that concern it"),
                            ("trace", "NOK <-> Code links (Annex A)")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("id")
        if name == "history":
            p.add_argument("--as-of", help="YYYY-MM-DD: only amendments published by this date")
    p = sub.add_parser("toc", help="the articles of code, nok or an issue")
    p.add_argument("target")
    p.add_argument("--section", help="only sections (code) or titles (nok, issues) that contain this text")
    args = parser.parse_args(argv)
    if getattr(args, "as_of", None) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.as_of):
        parser.error("--as-of takes a date YYYY-MM-DD")

    commands = {"info": cmd_info, "search": cmd_search, "get": cmd_get, "history": cmd_history,
                "trace": cmd_trace, "toc": cmd_toc}
    store = None
    try:
        store = Store()
        result, code = {"updated": store.updated, **commands[args.command](store, args)}, 0
    except (QueryError, ValueError, OSError) as e:      # ValueError includes a broken JSON file.
        result, code = {"error": str(e)}, 2
        if store:
            result = {"updated": store.updated, **result}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return code


if __name__ == "__main__":
    sys.exit(main())
