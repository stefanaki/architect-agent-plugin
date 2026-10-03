"""Build regulations/index.json: what links the Gazette files, by global id (ids.py).

The index holds no legal text. The text is in the JSON files of the datasets. The index holds:
  updated     how far discovery checked the Gazette (from discovered.json)
  datasets    the two base texts: folder, file, act, ΦΕΚ, publication date
  files       each JSON file of both datasets: dataset, ΦΕΚ, publication date
  articles    each article of the two base texts, by global id ("code:273", "nok:27"):
                title, at (position in the base file; none for a NOK article that an amendment added),
                amended_by, and for the NOK not_codified and repealed_by
  paragraphs  each paragraph of the two base texts: global id -> [article position, paragraph position]
  links       the NOK -> Code links of Annex A: {"nok": "nok:27.5", "code": "code:224.4"}
  errata      the corrections to the printed Annex A

A pointer of amended_by (ledger.py builds them):
  by             the amending article, "FEK-A-108-2026:133". null if only Annex A names it (then act and article)
  act, published the amending act and its publication date
  paragraphs     the paragraphs of the amending article that name the target
  targets        the provisions that the sentence names, "code:273.1". Best effort.
  kind           amend or repeal
  restates       the amending article gives the full new text of the article
  status         NOK only: confirmed, superseded, matcher, annex_a, unchecked, repeal, title (ledger.py)
  superseded_by  NOK only: the later confirmed pointer, "FEK-A-245-2020:120"

A position is the index in the file: articles of the Code file, or of the first act of the NOK file.
A NOK paragraph number in a link or a target is the number in the text in force when it was cited.
The 2012 text can lack it: an amendment added or renumbered it (see amended_by of its article).
"""
import json

from common import num_key, read_json
from datasets import CODE, DATASETS, INDEX, NOK
import annex_a, discover, ids, kodikas, ledger

ABOUT = ("Links between the Gazette files of regulations/, by global id: code:224.3.β (the Code), nok:27.5 "
         "(the NOK), FEK-A-108-2026:133.1 (another issue). No legal text: query it with scripts/regulations.py.")


def updated() -> dict:
    """Return how far discovery checked the Gazette: the last year scanned, its last issue and the scan date."""
    scanned = discover.load()["scanned"]
    year = max(scanned, key=int)
    s = scanned[year]
    return {"through": f"ΦΕΚ Α΄ {s['max_number']}/{year}", "scanned_at": s["scanned_at"]}


def base_articles(key: str) -> list[dict]:
    ds = DATASETS[key]
    return ids.acts(ds.load(ds.main))[0]["articles"]


def pointer(p: dict, key: str) -> dict:
    """Return a ledger pointer with global ids."""
    src = p.get("source")
    out = {"by": ids.make(src, p["article"]) if src else None}
    if not src:
        out["article"] = p["article"]
    out["act"] = p["act"]
    if p.get("published"):
        out["published"] = p["published"]
    if p.get("paragraphs"):
        out["paragraphs"] = [ids.make(src, x) for x in p["paragraphs"]]
    if p.get("targets"):
        out["targets"] = [ids.make(key, t) for t in p["targets"]]
    out["kind"] = p["kind"]
    for k in ("restates", "status", "superseded_by"):
        if p.get(k):
            out[k] = p[k]
    return out


def build() -> dict:
    pointers = ledger.build()
    articles, paragraphs = {}, {}
    for key in ("code", "nok"):
        entries, base = pointers[key], base_articles(key)
        positions = {}
        for k, a in enumerate(base):
            positions[a["article"]] = k
            for j, p in enumerate(a["paragraphs"]):
                gid = ids.make(key, p["id"])
                if gid in paragraphs:
                    raise RuntimeError(f"index: repeated paragraph id {gid}")
                paragraphs[gid] = [k, j]
        titles = {a["article"]: a["title"] for a in base}
        for num in sorted(set(positions) | set(entries), key=num_key):
            e = entries.get(num, {})
            entry = {"title": e.get("title") or titles.get(num, "")}
            if num in positions:
                entry["at"] = positions[num]
            if e.get("repealed_in"):
                entry["repealed_by"] = e["repealed_in"]
            if e.get("not_codified"):
                entry["not_codified"] = [ids.make(key, f"{num}.{p}") for p in e["not_codified"]]
            if e.get("amended_in"):
                entry["amended_by"] = [pointer(p, key) for p in e["amended_in"]]
            articles[ids.make(key, num)] = entry
    files = {}
    for ds in (CODE, NOK):
        for path in ds.json_paths():
            doc = read_json(path)
            files[path.stem] = {"dataset": ds.key, "fek": doc["fek"], "published": doc["published"]}
    return {
        "about": ABOUT,
        "updated": updated(),
        "datasets": {
            ds.key: {"dir": ds.root.name, "file": ds.main, "act": f"Ν. {ds.law}", "fek": f"Α΄ {ds.number}/{ds.year}",
                     "title": ds.title, "published": files[ds.main]["published"],
                     "in_force": "from 2026-06-08" if ds is CODE else
                     "until 2026-06-07, except the provisions that Annex A does not list (not_codified)"}
            for ds in (CODE, NOK)},
        "errata": [{"printed": w, "corrected": c} for w, c in annex_a.ERRATA],
        "links": kodikas.crosswalk(),
        "files": dict(sorted(files.items(), key=lambda kv: (kv[1]["published"], kv[0]))),
        "articles": articles,
        "paragraphs": paragraphs,
    }


def dump(index: dict) -> str:
    """Return the index as JSON with one record per line, so that a change gives a small diff."""
    def j(v):
        return json.dumps(v, ensure_ascii=False)
    parts = []
    for k, v in index.items():
        if isinstance(v, dict) and k in ("files", "articles", "paragraphs", "datasets"):
            body = ",\n".join(f"  {j(kk)}: {j(vv)}" for kk, vv in v.items())
            parts.append(f" {j(k)}: {{\n{body}\n }}")
        elif isinstance(v, list):
            body = ",\n".join(f"  {j(x)}" for x in v)
            parts.append(f" {j(k)}: [\n{body}\n ]")
        else:
            parts.append(f" {j(k)}: {j(v)}")
    return "{\n" + ",\n".join(parts) + "\n}\n"


def load() -> dict:
    return read_json(INDEX) if INDEX.exists() else {}


def run() -> int:
    index = build()
    INDEX.write_text(dump(index), encoding="utf-8")
    amended = sum(1 for a in index["articles"].values() if a.get("amended_by"))
    print(f"-> {INDEX.name}: {len(index['articles'])} articles ({amended} amended), "
          f"{len(index['paragraphs'])} paragraphs, {len(index['links'])} links, {len(index['files'])} files; "
          f"Gazette checked through {index['updated']['through']} (scanned {index['updated']['scanned_at']})")
    return 0
