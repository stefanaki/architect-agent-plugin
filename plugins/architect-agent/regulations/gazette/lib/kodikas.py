"""The Code «Νικόλαος Ταγαράς» (law 5306/2026, ΦΕΚ Α΄ 88/2026): its text and its crosswalk.

The Code is the quoted text of «Άρθρο πρώτο» of law 5306/2026. write_text() parses it into
kodikas-tagaras-5306-2026/json/FEK-A-88-2026.json. Each article gets its section path and
the Annex A rows that name its sources.

write_crosswalk() writes kodikas-tagaras-5306-2026/crosswalk.json: each link between a NOK
provision and a Code place that Annex A gives, for example {"nok": "nok:27.5", "code": "code:224.4"}.
The crosswalk is the only place that stores links between the two datasets.
"""
import datetime, re

from common import PDF, fek_url, pdftotext, write_json
from convert import paragraphs_json
from datasets import CODE, CROSSWALK, NOK, heading_level
import annex_a, discover, extract

CODE_PDF = PDF / f"{CODE.main}.pdf"
IMAGE_PAGE_WORDS = 50               # A page with fewer words holds its content as an image.


def parse_code():
    """Return (articles, image pages, number of pages) of the Code.

    The function parses the lines from the first section heading of «Άρθρο πρώτο» to
    «Άρθρο δεύτερο» as one act. The contents of the issue give the expected titles.
    An article that the parser does not find gets its title from the contents, no
    paragraphs, and the attribute `missing`.
    """
    ls = extract.lines(CODE_PDF)
    toc = extract._toc(ls)
    start = next(i for i, l in enumerate(ls) if l.text == "Άρθρο πρώτο")
    end = next(i for i, l in enumerate(ls) if i > start and l.text == "Άρθρο δεύτερο")
    first = next(i for i in range(start, end) if extract.LEVEL.match(ls[i].text))
    act = extract.Act("κώδ.", None)
    # The first page of the Code also holds the end of the contents and the ratifying paragraphs.
    # All its full-width lines start with a paragraph indent, so its text edges are wrong.
    # The page two pages later has the same layout (same parity). Use its edges.
    margins = extract._margins(ls[start:end])
    page = ls[first].page
    for col in ("L", "R", "S"):
        if (page + 2, col) in margins:
            margins[(page, col)] = margins[(page + 2, col)]
    extract.parse_lines(ls[first:end], act=act, toc=toc, margins=margins)
    for a in act.articles:
        # The text layer can lose the first title line, or a broken text layer can push the last
        # title line into the first paragraph. The contents entry has the full title.
        titles = toc.get((a.num, False), [])
        if not a.title or not titles or titles[0] == a.title:
            continue
        if titles[0].endswith(a.title):
            a.title = titles[0]
        elif a.paras and titles[0] == f"{a.title} {a.paras[0].text}":
            a.title = titles[0]
            del a.paras[0]
    pages = pdftotext(CODE_PDF).split("\f")
    image_pages = {i + 1 for i, t in enumerate(pages) if len(t.split()) < IMAGE_PAGE_WORDS}

    out, expected = [], 1
    for a in act.articles:
        n = int(re.match(r"\d+", a.num).group())
        while expected < n:
            titles = toc.get((str(expected), False)) or [""]
            out.append(extract.Article(str(expected), out[-1].page if out else a.page, title=titles[0]))
            out[-1].missing = True
            expected += 1
        out.append(a)
        expected = n + 1
    return out, image_pages, len(pages)


def write_text():
    """Write json/FEK-A-88-2026.json."""
    articles, image_pages, npages = parse_code()
    issue = next(i for i in discover.load()["issues"] if i["id"] == CODE.main)
    sources = {}
    for r in annex_a.rows():
        sources.setdefault(r["code_article"], []).append(
            {"code_paragraph": r["code_paragraph"], "code_label": r["code_label"], "source": r["source"]})
    records, path = [], []
    for k, a in enumerate(articles):
        for h in a.headings:
            path = [x for x in path if heading_level(x) < heading_level(h)] + [h]
        next_page = articles[k + 1].page if k + 1 < len(articles) else a.page
        images = sorted(p for p in image_pages if a.page <= p <= next_page)
        missing = getattr(a, "missing", False)
        records.append({
            "article": a.num, "title": a.title, "page": a.page, "path": list(path),
            **({"missing_text": True} if missing and images else {}),
            **({"not_parsed": True} if missing and not images else {}),
            **({"image_pages": images} if images else {}),
            **({"sources": sources[a.num]} if a.num in sources else {}),
            "paragraphs": paragraphs_json(a)})
    write_json(CODE.json_path(CODE.main), {
        "title": CODE.title, "fek": "Α΄ 88/2026", "file": CODE.main, "act": f"Ν. {CODE.law}",
        "published": issue["published"], "source": fek_url(CODE.number, CODE.year), "search_id": issue["search_id"],
        "pages": npages, "ratified_by": "Άρθρο πρώτο του ν. 5306/2026",
        "repeals": "The provisions listed in Annex A (Code article 477)",
        "articles": records})
    print(f"   {CODE.main}: {len(records)} articles, {sum(1 for a in articles if getattr(a, 'missing', False))} "
          f"without parsed text")


def write_crosswalk():
    """Write crosswalk.json from Annex A."""
    links, seen = [], set()
    for r in annex_a.rows():
        para = (r["code_paragraph"] or "").rstrip(")")
        code = f"{CODE.key}:{r['code_article']}" + (f".{para}" if para else "")
        for article, nok_para in annex_a.nok_refs(r["source"]):
            nok = f"{NOK.key}:{article}" + (f".{nok_para}" if nok_para else "")
            if (nok, code) not in seen:
                seen.add((nok, code))
                links.append({"nok": nok, "code": code})
    write_json(CROSSWALK, {
        "from": NOK.root.name, "to": CODE.root.name,
        "source": "Annex A (Παράρτημα Α΄) of ΦΕΚ Α΄ 88/2026: ΠΙΝΑΚΑΣ ΚΩΔΙΚΟΠΟΙΗΤΙΚΩΝ - ΚΩΔΙΚΟΠΟΙΟΥΜΕΝΩΝ ΔΙΑΤΑΞΕΩΝ",
        "ids": "nok:<article>[.<paragraph>] and code:<article>[.<paragraph>]. No paragraph means the whole article. "
               "A NOK paragraph number is the number in the text in force on 8 June 2026, as Annex A cites it. "
               "The 2012 text can lack it. Use the ledger to find the amendment that added or renumbered it.",
        "errata": [{"printed": w, "corrected": c} for w, c in annex_a.ERRATA],
        "generated": datetime.date.today().isoformat(),
        "links": links})
    print(f"-> {CROSSWALK.name}: {len(links)} links")
