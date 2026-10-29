"""Build regulations/index.json: what links the Gazette files, by global id (ids.py).

The index holds no legal text. The text is in the JSON files of the datasets. The index holds:
  updated     how far discovery checked the Gazette (from discovered.json)
  datasets    the three base texts: folder, file, act, ΦΕΚ, publication date, and for the fire code the
              series Β issues that the official graph links to it (series_b: none changes its text)
  files       each Gazette issue of the datasets: dataset, ΦΕΚ, publication date. An issue that two datasets
              hold has a file in each, listed once: under its first dataset, with the others in `also`
  articles    each article of the three base texts, by global id ("code:273", "nok:27", "fire:Α6"):
                title, at (position in the base file; none for a NOK article that an amendment added),
                amended_by, and for the NOK not_codified and repealed_by
  paragraphs  each paragraph of the three base texts: global id -> [article position, paragraph position]
  links       the NOK -> Code links of Annex A: {"nok": "nok:27.5", "code": "code:224.4"}
  errata      the corrections to the printed Annex A
  xrefs, glossary, synonyms, commencement
              lookups for the query script (lookups.py)
  build       the pdftotext version and a hash of the dataset files, to explain a rebuild elsewhere

A pointer of amended_by (ledger.py builds them):
  by             the amending article, "FEK-A-108-2026:133". null if only Annex A names it (then act and article)
  act, published the amending act and its publication date
  paragraphs     the paragraphs of the amending article that name the target
  targets        the provisions that the sentence names, "code:273.1". Best effort.
  kind           amend or repeal
  restates       the amending article gives the full new text of the article
  status         NOK: confirmed, superseded, matcher, annex_a, unchecked, repeal, title. Fire code: chapter
                 (the amending text names no chapter). See ledger.py
  superseded_by  NOK only: the later confirmed pointer, "FEK-A-245-2020:120"

A position is the index in the file: articles of the Code or fire code file, or of the first act of the NOK file.
A NOK paragraph number in a link or a target is the number in the text in force when it was cited.
The 2012 text can lack it: an amendment added or renumbered it (see amended_by of its article).
"""
import hashlib, json, subprocess

from common import num_key, read_json
from datasets import CODE, DATASETS, FIRE, FIRE_SERIES_B, INDEX, NOK
import annex_a, discover, ids, kodikas, ledger, lookups

ABOUT = ("Links between the Gazette files of regulations/, by global id: code:224.3.β (the Code), nok:27.5 "
         "(the NOK), fire:Α5.3.7.1 (the fire code), FEK-A-108-2026:133.1 (another issue). No legal text: "
         "query it with scripts/regs.py.")
IN_FORCE = {
    "code": "from 2026-06-08",
    "nok": "until 2026-06-07, except the provisions that Annex A does not list (not_codified)",
    "fire": None,                    # From the decree file: fire.in_force.
}


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
    for key in ("code", "nok", "fire"):
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
    files, docs, digest, in_force = {}, [], hashlib.sha256(), dict(IN_FORCE)
    for ds in (CODE, NOK, FIRE):
        for path in ds.json_paths():
            doc = read_json(path)
            digest.update(path.read_bytes())
            if path.stem in files:
                files[path.stem].setdefault("also", []).append(ds.key)
            else:
                files[path.stem] = {"dataset": ds.key, "fek": doc["fek"], "published": doc["published"],
                                    **({"issued": doc["issued"]} if doc.get("issued") else {})}
            if path.stem == ds.main and doc.get("in_force"):
                in_force[ds.key] = doc["in_force"]
            if path.stem != ds.main:
                docs.append(doc)
    base = {key: base_articles(key) for key in ("code", "nok", "fire")}
    return {
        "about": ABOUT,
        "updated": updated(),
        "datasets": {
            ds.key: {"dir": ds.key, "file": ds.main, "act": ds.act, "fek": f"Α΄ {ds.number}/{ds.year}",
                     "title": ds.title, "published": files[ds.main]["published"], "in_force": in_force[ds.key],
                     **({"series_b": [{"fek": k, "what": v} for k, v in FIRE_SERIES_B.items()]} if ds is FIRE else {})}
            for ds in (CODE, NOK, FIRE)},
        "errata": [{"printed": w, "corrected": c} for w, c in annex_a.ERRATA],
        "links": kodikas.crosswalk(),
        "files": dict(sorted(files.items(), key=lambda kv: (kv[1]["published"], kv[0]))),
        "articles": articles,
        "paragraphs": paragraphs,
        **lookups.build(base, docs),
        "build": {"pdftotext": pdftotext_version(), "data_sha256": digest.hexdigest()},
    }


def pdftotext_version() -> str:
    """Return the poppler version: the extraction depends on it."""
    out = subprocess.run(["pdftotext", "-v"], capture_output=True, text=True).stderr
    return out.split("\n")[0].split()[-1] if out else "unknown"


def dump(index: dict) -> str:
    """Return the index as JSON with one record per line, so that a change gives a small diff."""
    def j(v):
        return json.dumps(v, ensure_ascii=False)
    parts = []
    for k, v in index.items():
        if isinstance(v, dict) and k in ("files", "articles", "paragraphs", "datasets", "xrefs"):
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
          f"{len(index['paragraphs'])} paragraphs, {len(index['links'])} links, {len(index['files'])} files, "
          f"{sum(map(len, index['xrefs'].values()))} cross-references, {len(index['glossary'])} terms; "
          f"Gazette checked through {index['updated']['through']} (scanned {index['updated']['scanned_at']})")
    return 0
