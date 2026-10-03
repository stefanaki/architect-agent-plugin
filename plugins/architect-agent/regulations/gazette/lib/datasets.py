"""The two datasets, and the facts that separate and link them.

  nok    the NOK (law 4067/2012), as history until 7 June 2026
  code   the Code «Νικόλαος Ταγαράς» (law 5306/2026), the text in force from 8 June 2026

Each dataset folder holds only data:
  json/<id>.json    the source of truth: text, paragraph ids, metadata
  md/<id>.md        a rendered view of the JSON. No module reads it.
regulations/index.json holds what links the files: the amendments of each article and the
links between NOK and Code provisions (Annex A), with global ids such as "nok:27.5", "code:224.4"
(see ids.py).
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from common import REGULATIONS, issue_record, read_json
import discover

# ΦΕΚ Α΄ 88/2026. The NOK dataset stops before this date. The Code dataset starts on it.
CODE_PUBLISHED = "2026-06-08"


@dataclass(frozen=True)
class Dataset:
    key: str                         # "nok" or "code". Also the prefix of its global ids.
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

    @property
    def json_dir(self) -> Path:
        return self.root / "json"

    @property
    def md_dir(self) -> Path:
        return self.root / "md"

    def json_path(self, ident: str) -> Path:
        return self.json_dir / f"{ident}.json"

    def md_path(self, ident: str) -> Path:
        return self.md_dir / f"{ident}.md"

    def json_paths(self) -> list[Path]:
        return sorted(self.json_dir.glob("FEK-*.json"))

    def load(self, ident: str) -> dict:
        return read_json(self.json_path(ident))


NOK = Dataset(
    key="nok", root=REGULATIONS / "nok-4067-2012", law="4067/2012", main="FEK-A-79-2012", number=79, year=2012,
    title="Νέος Οικοδομικός Κανονισμός (ΝΟΚ)", last_article=48,
    primary=discover.PRIMARY, names=(discover.SECONDARY, discover.ABBREV),
    building_rules=frozenset(set(range(1, 29)) | {34, 35, 48}))

CODE = Dataset(
    key="code", root=REGULATIONS / "kodikas-tagaras-5306-2026", law="5306/2026", main="FEK-A-88-2026",
    number=88, year=2026, title="Κώδικας Χωροταξίας - Πολεοδομίας «Νικόλαος Ταγαράς»", last_article=477,
    # In a later issue, a citation of the NOK instead of the Code is an outdated reference. Keep it as "name".
    primary=discover.CODE, names=(discover.PRIMARY, discover.SECONDARY, discover.ABBREV))

DATASETS = {"nok": NOK, "code": CODE}
INDEX = REGULATIONS / "index.json"

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
    return f"../../{to.root.name}/md/{ident}.md{anchor}"
