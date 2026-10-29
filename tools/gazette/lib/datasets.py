"""The three datasets, and the facts that separate and link them.

  nok    the NOK (law 4067/2012), as history until 7 June 2026
  code   the Code «Νικόλαος Ταγαράς» (law 5306/2026), the text in force from 8 June 2026
  fire   the fire code «Κανονισμός Πυροπροστασίας Κτιρίων» (π.δ. 41/2018), in force from August 2018

Each dataset folder (skills/regulations/data/<key>/) holds only data:
  <id>.json         the source of truth: text, paragraph ids, metadata
The markdown views (render.py) go to notes/regulations/<key>/<id>.md, outside the plugin.
data/index.json holds what links the files: the amendments of each article and the
links between NOK and Code provisions (Annex A), with global ids such as "nok:27.5", "code:224.4"
(see ids.py).

One Gazette issue can cite the laws of two datasets. Each dataset then has its own file of the issue,
with the articles relevant to it. index.json lists the file once, under its first dataset, with the
others in `also`. The query script reads all copies as one file.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from common import DATA, NOTES, issue_record, read_json
import discover

# ΦΕΚ Α΄ 88/2026. The NOK dataset stops before this date. The Code dataset starts on it.
CODE_PUBLISHED = "2026-06-08"
# ΦΕΚ Α΄ 80/2018. The fire dataset starts on this date: before it, «Κανονισμός Πυροπροστασίας Κτιρίων»
# names π.δ. 71/1988, which had the same name.
FIRE_PUBLISHED = "2018-05-08"


@dataclass(frozen=True)
class Dataset:
    key: str                         # "nok", "code" or "fire". Also the prefix of its global ids.
    root: Path
    law: str                         # "4067/2012"
    main: str                        # The file id of the act itself, e.g. "FEK-A-79-2012".
    number: int                      # Issue number and year of the act itself.
    year: int
    title: str
    last_article: int
    primary: re.Pattern              # The act cited by number.
    names: tuple                     # The act named without its number.
    # Articles of the main act that are building rules (NOK only). The others amend other laws.
    building_rules: frozenset = field(default_factory=frozenset)
    kind: str = "Ν."                 # The kind of act: «Ν.» a law, «Π.Δ.» a presidential decree.

    @property
    def act(self) -> str:
        """«Ν. 4067/2012», «Π.Δ. 41/2018»."""
        return f"{self.kind} {self.law}"

    @property
    def cited(self) -> str:
        """The act in English text: «law 4067/2012», «π.δ. 41/2018»."""
        return f"law {self.law}" if self.kind == "Ν." else f"{self.kind.lower()} {self.law}"

    @property
    def json_dir(self) -> Path:
        return self.root

    @property
    def md_dir(self) -> Path:
        return NOTES / self.key

    def json_path(self, ident: str) -> Path:
        return self.json_dir / f"{ident}.json"

    def md_path(self, ident: str) -> Path:
        return self.md_dir / f"{ident}.md"

    def json_paths(self) -> list[Path]:
        return sorted(self.json_dir.glob("FEK-*.json"))

    def load(self, ident: str) -> dict:
        return read_json(self.json_path(ident))


NOK = Dataset(
    key="nok", root=DATA / "nok", law="4067/2012", main="FEK-A-79-2012", number=79, year=2012,
    title="Νέος Οικοδομικός Κανονισμός (ΝΟΚ)", last_article=48,
    primary=discover.PRIMARY, names=(discover.SECONDARY, discover.ABBREV),
    building_rules=frozenset(set(range(1, 29)) | {34, 35, 48}))

CODE = Dataset(
    key="code", root=DATA / "code", law="5306/2026", main="FEK-A-88-2026",
    number=88, year=2026, title="Κώδικας Χωροταξίας - Πολεοδομίας «Νικόλαος Ταγαράς»", last_article=477,
    # In a later issue, a citation of the NOK instead of the Code is an outdated reference. Keep it as "name".
    primary=discover.CODE, names=(discover.PRIMARY, discover.SECONDARY, discover.ABBREV))

# The articles of each chapter of the fire code. Their numbers start again at 1 in each chapter.
FIRE_CHAPTERS = {"Α": 8, "Β": 11, "Γ": 4}
FIRE = Dataset(
    key="fire", root=DATA / "fire", law="41/2018", main="FEK-A-80-2018", number=80, year=2018,
    title="Κανονισμός Πυροπροστασίας Κτιρίων", last_article=max(FIRE_CHAPTERS.values()),
    primary=discover.FIRE, names=(discover.FIRE_NAME,), kind="Π.Δ.")
# The series Β issues that the modification graph of search.et.gr links to the fire code. The datasets hold
# series Α only. Each was read by hand (2026-10-29): none changes the text of the decree. crosscheck fails
# if the graph lists another one.
FIRE_SERIES_B = {
    "Β΄ 5031/2018": "ΥΠΕΝ/ΔΑΟΚΑ/78625/4900: sets up the committee for deviations of παρ. 2.5 of article 2, Κεφ. Α΄",
    "Β΄ 2998/2020": "ΥΠΕΝ/ΔΕΣΕΔΠ/65826/699: technical guidelines on accessibility of existing buildings; cites the decree",
    "Β΄ 827/2022": "Γ.Π.Δ11 οικ.15171: amends a licensing decision for care centres to require a fire certificate "
                   "under the decree",
    "Β΄ 3509/2022": "Γ.Π.Δ11 οικ.60761: the same for another kind of care centre",
}

DATASETS = {"nok": NOK, "code": CODE, "fire": FIRE}
INDEX = DATA / "index.json"

# Issues that match a needle but do not refer to the NOK. Each entry was checked by hand.
FALSE_MATCHES = {
    "FEK-A-184-2012": "«Ν.Ο.Κ. Καβάλας» is the sailing club of Kavala (Ναυτικός Όμιλος Καβάλας).",
}

# Markdown level of each kind of section heading in the Code. Articles are level 5.
HEADING_LEVEL = {"ΜΕΡΟΣ": 2, "ΤΜΗΜΑ": 3, "ΚΕΦΑΛΑΙΟ": 4}


def heading_level(h: str) -> int:
    return HEADING_LEVEL.get(h.split()[0], 4)


def issues(ds: Dataset) -> list[dict]:
    """Return the discovered issues that belong to a dataset. The main act comes first."""
    db = discover.load()
    if ds is FIRE:
        # The base texts of the other datasets are searched as base texts: the Code names the fire code.
        main, bases = issue_record(FIRE.number, FIRE.year), {NOK.main, CODE.main}
        return [main] + [i for i in db["issues"] if discover.cites_fire(i) and i["published"] > FIRE_PUBLISHED
                         and i["id"] not in FALSE_MATCHES and i["id"] not in bases]
    if ds is NOK:
        main = issue_record(NOK.number, NOK.year)          # The NOK does not cite itself, so discovery lacks it.
        return [main] + [i for i in db["issues"] if discover.cites_nok(i) and i["published"] < CODE_PUBLISHED
                         and i["id"] not in FALSE_MATCHES]
    later = [i for i in db["issues"] if i["published"] >= CODE_PUBLISHED
             and (i["hits"].get("code_5306") or discover.cites_nok(i))]
    return sorted(later, key=lambda i: i["id"] != CODE.main)


def md_link(to: Dataset, ident: str, article: str | None = None) -> str:
    """Return the relative link from any md file to an md file of a dataset, with an article anchor."""
    anchor = f"#άρθρο-{article.lower()}" if article else ""
    return f"../{to.key}/{ident}.md{anchor}"
