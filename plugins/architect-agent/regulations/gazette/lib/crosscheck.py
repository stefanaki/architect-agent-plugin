"""Check that NOK discovery and the NOK ledger are complete. Compare them with independent sources.

  1. search      discovered.json: issues that contain «4067/2012» or a name of the NOK
  2. citations   «... του ν. 4067/2012, όπως τροποποιήθηκε/ισχύει με το άρθρο Χ του ν. Υ» inside the
                 NOK dataset. Newer laws list the earlier amendments of the NOK. The last law named
                 before «όπως» must be the NOK.
  3. ET.gr       the official modification graph (timeline) of ΦΕΚ Α΄ 79/2012
  4. Annex A     the laws that Annex A of the Code «Νικόλαος Ταγαράς» names as NOK amendments
  5. titles      articles whose title says that they amend the NOK

A law that source 2, 3 or 4 names, but that is missing from source 1, is a coverage gap.
An article of source 5 without a ledger pointer is a gap of the matcher.
No source decides alone. Any gap fails the command.
"""
import re
from collections import defaultdict

from common import issue_record, read_json, timeline
from datasets import CODE_PUBLISHED, NOK
from discover import ABBREV, PRIMARY, SECONDARY, load as load_discovered
from ledger import TITLE_VERB
import annex_a

# «όπως (η παρ. ...) τροποποιήθηκε/αντικαταστάθηκε/προστέθηκε/ισχύει ... με το άρθρο 58 του ν. 4964/2022 (Α΄ 150)»
CITED = re.compile(r"όπως\s+[^«»]{0,200}?(?:τροποποιήθηκ|αντικαταστάθηκ|προστέθηκ|συμπληρώθηκ|ισχύ)"
                   r"[^«»]{0,160}?(?:ν\.|νόμου)\s*(\d{4})/(\d{4})(?:\s*\(Α[΄’']\s*(\d+)\))?")
CITED_BEFORE = 250                      # Characters before «όπως» that can name the amended law.


def names_nok(text: str) -> bool:
    return bool(PRIMARY.search(text) or SECONDARY.search(text) or ABBREV.search(text))


def texts(doc: dict) -> str:
    parts = [act["title"] for act in doc["acts"]] + [t["text"] for act in doc["acts"] for t in act.get("text", [])]
    for act in doc["acts"]:
        for a in act["articles"]:
            parts += [a["title"], *(p["text"] for p in a["paragraphs"])]
    return re.sub(r"\s+", " ", " ".join(parts))


def run() -> int:
    """Print the gaps. Return 1 if there is a gap, else 0."""
    db = load_discovered()
    found = {a["number"]: i["fek"] for i in db["issues"] for a in i["acts"] if a["number"]}
    found_fek = {i["fek"] for i in db["issues"]}
    docs = {path.stem: read_json(path) for path in NOK.json_paths()}

    cited = defaultdict(set)                     # law -> files that name it as an amendment of the NOK
    for stem, doc in docs.items():
        text = texts(doc)
        for m in CITED.finditer(text):
            # The citation must be about the NOK, not about another law. The text names the amended
            # law before «όπως»: «του άρθρου 4 του ν. 4067/2012, όπως τροποποιήθηκε με ...».
            # The last law named before «όπως» must be the NOK.
            before = re.findall(r"\d{4}/\d{4}", text[max(0, m.start() - CITED_BEFORE):m.start()])
            about_nok = (before and before[-1] == NOK.law) or names_nok(m.group(0)) \
                or "Οικοδομικού Κανονισμού" in m.group(0)
            if not about_nok or int(m.group(2)) < NOK.year:      # A law older than the NOK cannot amend it.
                continue
            if (law := f"{m.group(1)}/{m.group(2)}") != NOK.law:
                cited[law].add(stem)

    et = {}
    for e in timeline(issue_record(NOK.number, NOK.year)["search_id"]):
        label = e["timeline_PrimaryLabel"]
        if e["timeline_Direction"] == "-1" and label.startswith("Α "):
            n, y = label[2:].split("/")
            et[f"Α΄ {n}/{y}"] = e["timeline_EnglishLabel"]

    _, amended_by = annex_a.parse()
    annex_laws = {law for pairs in amended_by.values() for law, _ in pairs}
    pointed = {(p["source"], p["article"]) for e in read_json(NOK.ledger)["articles"].values() for p in e["amended_in"]}

    gaps = False
    print("- laws that Annex A names as NOK amendments but NOT discovered:")
    for law in sorted(annex_laws - set(found), key=lambda s: s[::-1]):
        gaps = True
        print(f"   MISSING law {law}")
    print("- laws cited as amending the NOK but NOT discovered:")
    for law in sorted(cited, key=lambda s: s[::-1]):
        if law not in found:
            gaps = True
            print(f"   MISSING law {law}   (cited in: {', '.join(sorted(cited[law])[:4])})")
    print("- issues in the ET.gr graph but NOT discovered:")
    for fek in sorted(set(et) - found_fek):
        gaps = True
        print(f"   MISSING {fek}   ({et[fek]})")

    print("- articles whose title amends the NOK, but the ledger has NO pointer to them:")
    mentions = 0
    for stem, doc in docs.items():
        if stem == NOK.main or doc["published"] >= CODE_PUBLISHED:
            continue
        arts = [a for act in doc["acts"] for a in act["articles"]]
        if not any((stem, a["article"]) in pointed for a in arts):
            mentions += 1
        for a in arts:
            if TITLE_VERB.search(a["title"]) and names_nok(a["title"]) and (stem, a["article"]) not in pointed:
                gaps = True
                print(f"   MISSING pointer {stem} article {a['article']}: {a['title'][:100]}")
    print(f"- {mentions} files have no ledger pointer. They cite the NOK without amending it "
          f"(see `match` of each article).")
    return 1 if gaps else 0
