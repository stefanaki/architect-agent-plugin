"""Check that NOK discovery and the NOK amendment pointers (index.json) are complete. Compare them with independent sources.

  1. search      discovered.json: issues that contain «4067/2012» or a name of the NOK
  2. citations   «... του ν. 4067/2012, όπως τροποποιήθηκε/ισχύει με το άρθρο Χ του ν. Υ» inside the
                 NOK dataset. Newer laws list the earlier amendments of the NOK. The last law named
                 before «όπως» must be the NOK.
  3. ET.gr       the official modification graph (timeline) of ΦΕΚ Α΄ 79/2012
  4. Annex A     the laws that Annex A of the Code «Νικόλαος Ταγαράς» names as NOK amendments
  5. titles      articles whose title says that they amend the NOK

A law that source 2, 3 or 4 names, but that is missing from source 1, is a coverage gap.
An article of source 5 without an amendment pointer (index.json) is a gap of the matcher.
No source decides alone. Any gap fails the command.

run_fire() checks the fire code (π.δ. 41/2018) the same way, against:
  1. the modification graph of ΦΕΚ Α΄ 80/2018: each series Α issue is in the fire dataset, and its series Β
     issues are the ones datasets.FIRE_SERIES_B lists (read by hand)
  2. «π.δ. 41/2018, όπως τροποποιήθηκε/ισχύει ... ν. X» citations: each law X is discovered
  3. articles whose title amends the decree and names it: each has an amendment pointer
"""
import re
from collections import defaultdict

from common import issue_record, read_json, timeline
from datasets import CODE_PUBLISHED, FIRE, FIRE_SERIES_B, NOK
from discover import ABBREV, FIRE as FIRE_NUMBER, PRIMARY, SECONDARY, load as load_discovered
from ledger import TITLE_VERB
import ids, index
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
    pointed = {ids.split(p["by"]) for g, e in index.load()["articles"].items() if g.startswith("nok:")
               for p in e.get("amended_by", []) if p["by"]}

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

    print("- articles whose title amends the NOK, but index.json has NO amendment pointer to them:")
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
    print(f"- {mentions} files have no amendment pointer. They cite the NOK without amending it "
          f"(see `match` of each article).")
    return 1 if gaps else 0


# «του π.δ. 41/2018 (Α΄ 80), όπως τροποποιήθηκε με το άρθρο 26 του ν. 4710/2020»
FIRE_CITED = re.compile(r"41\s*/\s*2018[^«»]{0,40}?,?\s*όπως\s+[^«»]{0,120}?(?:τροποποιήθηκ|αντικαταστάθηκ|ισχύ)"
                        r"[^«»]{0,120}?(?:ν\.|νόμου)\s*(\d{4})/(\d{4})")


def run_fire() -> int:
    """Print the gaps of the fire dataset. Return 1 if there is a gap, else 0."""
    db = load_discovered()
    found = {i["fek"] for i in db["issues"]}
    laws = {a["number"] for i in db["issues"] for a in i["acts"] if a["number"]}
    docs = {path.stem: read_json(path) for path in FIRE.json_paths() if path.stem != FIRE.main}
    held = {d["fek"] for d in docs.values()}
    gaps = False

    series_a, series_b = set(), set()
    for e in timeline(issue_record(FIRE.number, FIRE.year)["search_id"]):
        label = e["timeline_PrimaryLabel"]
        if e["timeline_Direction"] != "-1":
            continue
        n, y = label[2:].split("/")
        (series_a if label.startswith("Α ") else series_b if label.startswith("Β ") else set()).add(f"{label[0]}΄ {n}/{y}")
    print("- issues in the ET.gr graph of the fire code but NOT in the fire dataset:")
    for fek in sorted(series_a - held):
        gaps = True
        print(f"   MISSING {fek}" + ("   (discovered, but no article was kept)" if fek in found else ""))
    print("- series Β issues in the ET.gr graph but NOT read by hand (datasets.FIRE_SERIES_B):")
    for fek in sorted(series_b - set(FIRE_SERIES_B)):
        gaps = True
        print(f"   UNREAD {fek}")
    for fek in sorted(set(FIRE_SERIES_B) - series_b):
        print(f"   ~ {fek} is in FIRE_SERIES_B but no longer in the graph")

    print("- laws cited as amending the fire code but NOT discovered:")
    for stem, doc in docs.items():
        for m in FIRE_CITED.finditer(texts(doc)):
            if (law := f"{m.group(1)}/{m.group(2)}") not in laws:
                gaps = True
                print(f"   MISSING law {law}   (cited in {stem})")

    print("- articles whose title amends the fire code, but index.json has NO amendment pointer to them:")
    pointed = {ids.split(p["by"]) for g, e in index.load()["articles"].items() if g.startswith("fire:")
               for p in e.get("amended_by", []) if p["by"]}
    for stem, doc in docs.items():
        for a in (a for act in doc["acts"] for a in act["articles"]):
            if TITLE_VERB.search(a["title"]) and FIRE_NUMBER.search(a["title"]) and (stem, a["article"]) not in pointed:
                gaps = True
                print(f"   MISSING pointer {stem} article {a['article']}: {a['title'][:100]}")
    return 1 if gaps else 0
