"""Write the markdown view of each JSON file.

The markdown is for reading by people. No module reads it. It adds notes that
come from index.json (amendments and Annex A links):
  - the NOK text: the amendments of each article, and where each paragraph is in the Code
  - the Code text: what each article codifies (Annex A), the NOK provisions it holds, its amendments
"""
from common import frontmatter, num_key, read_json
from convert import markers
from datasets import CODE, NOK, Dataset, heading_level, md_link
import ids, index


def articles_of(idx: dict, ds: Dataset) -> dict:
    """Return {article: index entry} of a dataset."""
    out = {}
    for gid, entry in idx.get("articles", {}).items():
        key, local = ids.split(gid)
        if key == ds.key:
            out[local] = entry
    return out


def links_by_article(idx: dict, side: str, other: str) -> dict:
    """Return {article of `side`: {its paragraph or "*": [local ids of `other`]}} from the Annex A links."""
    out = {}
    for link in idx.get("links", []):
        article, _, para = ids.split(link[side])[1].partition(".")
        out.setdefault(article, {}).setdefault(para or "*", []).append(ids.split(link[other])[1])
    return out


def place(gid: str) -> str:
    """«FEK-A-245-2020:120» -> «FEK-A-245-2020 άρθ. 120»."""
    source, local = ids.split(gid)
    return f"{source} άρθ. {local}"


def paragraph_lines(lines, paras):
    for p in paras:
        chain = markers(p["text"])
        lines += [("- " + p["text"]) if chain and chain[0][0] == "α" else p["text"], ""]


def amendment_line(pointers) -> str:
    refs = []
    for r in pointers:
        paras = f" ({', '.join(ids.split(x)[1] for x in r['paragraphs'])})" if r.get("paragraphs") else ""
        if r["by"]:
            source, article = ids.split(r["by"])
            link = f"[{source}]({source}.md)"
        else:
            link, article = r["act"], r["article"]
        later = f", superseded by {place(r['superseded_by'])}" if r.get("superseded_by") else ""
        refs.append(f"{link} άρθ. {article}{paras}{later}")
    return "> Amended in: " + " · ".join(refs)


def nok_notes(idx: dict | None = None) -> dict[str, list[str]]:
    """Return the notes under each NOK article: amendments and Code places (Annex A), from the index."""
    idx = index.load() if idx is None else idx
    places = links_by_article(idx, "nok", "code")
    articles = articles_of(idx, NOK)
    notes = {}
    for num in set(articles) | set(places):
        entry, lines = articles.get(num, {}), []
        if entry.get("repealed_by"):
            lines.append(f"> Repealed in: {place(entry['repealed_by'])}")
        if entry.get("amended_by"):
            lines.append(amendment_line(entry["amended_by"]))
            restated = [r for r in entry["amended_by"] if r.get("restates") and r["by"]]
            if restated:
                source, article = ids.split(restated[-1]["by"])
                lines.append(f"> Full text as restated on {restated[-1]['published']}: [{source}]({source}.md) "
                             f"άρθ. {article}. Later amendments in the list above still apply.")
        if num in places:
            by_para = places[num]
            code_articles = sorted({c.split(".")[0] for v in by_para.values() for c in v}, key=num_key)
            links = ", ".join(f"[άρθ. {c}]({md_link(CODE, CODE.main, c)})" for c in code_articles)
            detail = " · ".join(f"{'all' if k == '*' else 'παρ. ' + k} → {', '.join(sorted(set(v), key=num_key))}"
                                for k, v in sorted(by_para.items(), key=lambda kv: num_key(kv[0])))
            lines.append(f"> Now in the Code «Νικόλαος Ταγαράς»: {links} ({detail})")
        if entry.get("not_codified"):
            paras = ", ".join(x.rsplit(".", 1)[1] for x in entry["not_codified"])
            lines.append(f"> Not in Annex A of the Code: παρ. {paras}. Code article 477 "
                         f"repeals only the provisions that Annex A lists. Check whether this text still applies.")
        if lines:
            notes[num] = lines
    return notes


def issue_md(doc: dict, notes: dict | None = None) -> str:
    """Return the markdown of an issue file (every file except the Code text)."""
    multi = len(doc["acts_in_issue"]) > 1
    body = []
    for act in doc["acts"]:
        if multi:
            body += [f"## {act['act']}" + (f" — {act['title']}" if act["title"] else ""), ""]
        for p in act.get("text", []):
            body += [p["text"], ""]
        for a in act["articles"]:
            for h in a["headings"]:
                body += [f"#### {h}", ""]
            heading = a["label"] if a["article"].startswith("Π-") else f"Άρθρο {a.get('label') or a['article']}"
            body += [f"##### {heading}", ""]
            if a["title"]:
                body += [f"**{a['title']}**", ""]
            for note in (notes or {}).get(a["article"], []):
                body += [note, ""]
            paragraph_lines(body, a["paragraphs"])
    fm = frontmatter(title=doc["title"], fek=doc["fek"], acts=doc["acts_in_issue"], published=doc["published"],
                     source=doc["source"], pages=doc["pages"], cites=doc.get("cites"), extract=doc.get("extract"),
                     review=doc.get("review"), json=f"../json/{doc['file']}.json")
    return fm + f"\n# {doc['title']}\n\n" + "\n".join(body).rstrip() + "\n"


def nok_link(ref: str) -> str:
    """Return a markdown link to a NOK provision. Only articles of the 2012 text have a heading to link to."""
    article = ref.split(".")[0]
    anchor = article if article.isdigit() and int(article) <= NOK.last_article else None
    return f"[ΝΟΚ {ref}]({md_link(NOK, NOK.main, anchor)})"


def code_md(doc: dict, idx: dict) -> str:
    """Return the markdown of the Code text."""
    from_nok = links_by_article(idx, "code", "nok")
    amended = articles_of(idx, CODE)
    body, path = [], []
    for a in doc["articles"]:
        same = 0
        while same < min(len(path), len(a["path"])) and path[same] == a["path"][same]:
            same += 1
        for h in a["path"][same:]:
            body += [f"{'#' * heading_level(h)} {h}", ""]
        path = a["path"]
        body += [f"##### Άρθρο {a['article']}", ""]
        if a["title"]:
            body += [f"**{a['title']}**", ""]
        images = a.get("image_pages", [])
        if a.get("missing_text"):
            body += ["> The Gazette prints this article as an image. The PDF has no text for it. "
                     f"See the source PDF, pages {images[0]}-{images[-1]}.", ""]
        elif a.get("not_parsed"):
            body += [f"> The parser did not find this article. See the source PDF near page {a['page']}.", ""]
        elif images:
            body += [f"> Part of this article is an image in the Gazette (PDF pages {', '.join(map(str, images))}). "
                     "The text below is incomplete.", ""]
        if a.get("sources"):
            body.append("> Codifies (Annex A):")
            body += [f"> - {s['code_label'] or 'article'}: {s['source']}" for s in a["sources"]]
            body.append("")
        if a["article"] in from_nok:
            by_para = from_nok[a["article"]]
            detail = " · ".join(f"{'article' if k == '*' else 'παρ. ' + k} ← {', '.join(nok_link(n) for n in v)}"
                                for k, v in sorted(by_para.items(), key=lambda kv: num_key(kv[0])))
            body += [f"> From the NOK: {detail}", ""]
        if amended.get(a["article"], {}).get("amended_by"):
            body += [amendment_line(amended[a["article"]]["amended_by"]), ""]
        paragraph_lines(body, a["paragraphs"])
    fm = frontmatter(title=doc["title"], fek=doc["fek"], acts=[doc["act"]], published=doc["published"],
                     source=doc["source"], pages=doc["pages"], ratified_by=doc["ratified_by"],
                     repeals=doc["repeals"], articles=len(doc["articles"]), json=f"../json/{doc['file']}.json")
    return fm + f"\n# {doc['title']}\n\n" + "\n".join(body).rstrip() + "\n"


def markdown(ds: Dataset, doc: dict, notes: dict | None, idx: dict) -> str:
    """Return the markdown of one JSON document. `notes` are the NOK notes (see nok_notes)."""
    if ds is CODE and doc["file"] == CODE.main:
        return code_md(doc, idx)
    return issue_md(doc, notes if doc["file"] == ds.main else None)


def run(ds: Dataset, only: set[str] = frozenset()) -> int:
    """Write md/<id>.md for each JSON file of a dataset. Return the number of files."""
    idx = index.load()
    notes = nok_notes(idx) if ds is NOK else None
    count = 0
    for path in ds.json_paths():
        if only and path.stem not in only:
            continue
        md = markdown(ds, read_json(path), notes, idx)
        ds.md_dir.mkdir(parents=True, exist_ok=True)
        ds.md_path(path.stem).write_text(md, encoding="utf-8")
        count += 1
    print(f"-> {count} files in {ds.root.name}/md/")
    return count
