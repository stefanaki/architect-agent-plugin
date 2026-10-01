"""Find the Gazette issues (series Α') that cite the NOK or the Code that codified it.

The module gets the list of issues for each year from the search.et.gr API.
It does not guess where a year ends. It downloads each issue and searches
the text for these strings:
  4067/2012        the NOK, by number (primary)
  nok_by_name      «Νέου Οικοδομικού Κανονισμού» or «Ν.Ο.Κ.» without the number
  nok_abbrev       «ΝΟΚ» without dots, as a separate word
  code_5306        the Code «Νικόλαος Ταγαράς» (law 5306/2026), from 2026

An issue that names the NOK only by name or abbreviation gets `review: true`.
A failed download is not "no issue". The module records it, and the command exits with an error.
The PDF of each matching issue stays in gazette/pdf. Both datasets use this one pool.

Output: gazette/discovered.json with `scanned` (what was checked) and `issues` (what was found).
Read it only with load(). It converts old formats.
"""
import concurrent.futures as cf
import datetime, json, re, sys
from common import CACHE, DISCOVERED, PDF, degreekify, download, fek_id, fek_url, issues_of_year, pdftotext

LAW = "4067/2012"                      # The hits key of the NOK by number.
PRIMARY = re.compile(r"4067\s*/\s*2012")
SECONDARY = re.compile(r"Νέου\s+Οικοδομικού\s+Κανονισμού|Ν\.\s?Ο\.\s?Κ\.")
# «ΝΟΚ» without dots. A letter before or after it makes it part of another word.
ABBREV = re.compile(r"(?<![^\W\d_])ΝΟΚ(?![^\W\d_])")
CODE = re.compile(r"5306\s*/\s*2026|Κώδικα\s+Χωροταξίας\s*[-–]\s*Πολεοδομίας|Νικόλαος\s+Ταγαράς")
CODE_FROM_YEAR = 2026
# Header of each act in the issue. One issue can hold more than one act.
ACT = re.compile(r"(ΝΟΜΟΣ|ΠΡΟΕΔΡΙΚΟ\s+ΔΙΑΤΑΓΜΑ|ΠΡΑΞΗ\s+ΝΟΜΟΘΕΤΙΚΟΥ\s+ΠΕΡΙΕΧΟΜΕΝΟΥ|ΔΙΟΡΘΩΣΕΙΣ\s+ΣΦΑΛΜΑΤΩΝ)"
                 r"(?:\s+ΥΠ[’'΄]?\s*ΑΡΙΘ\S*\s*(\d+))?")
KIND = {"ΝΟΜΟΣ": "ν.", "ΠΡΟΕΔΡΙΚΟ": "π.δ.", "ΠΡΑΞΗ": "ΠΝΠ", "ΔΙΟΡΘΩΣΕΙΣ": "διορθ."}


def needles(year):
    return ["4067/2012", "nok_by_name", "nok_abbrev"] + (["code_5306"] if year >= CODE_FROM_YEAR else [])


def acts(text, year):
    seen = []
    for m in ACT.finditer(text):
        kind = KIND[m.group(1).split()[0]]
        act = {"kind": kind, "number": f"{m.group(2)}/{year}" if m.group(2) else None}
        if act not in seen:
            seen.append(act)
    return seen


def review(hits):
    """Return True if the issue names the NOK only without its number."""
    return hits.get(LAW, 0) == 0 and (hits.get("nok_by_name", 0) + hits.get("nok_abbrev", 0)) > 0


def cites_nok(issue):
    """Return True if any NOK needle matched. An issue with only Code hits belongs to the Code dataset."""
    return any(issue["hits"].get(k) for k in (LAW, "nok_by_name", "nok_abbrev"))


def scan(issue):
    """Return (issue, record or None, error or None)."""
    n, y = issue["number"], issue["year"]
    dest = CACHE / "issues" / str(y) / f"{n:05d}.pdf"
    try:
        download(fek_url(n, y), dest, min_size=0)
        text = degreekify(pdftotext(dest))
    except Exception as e:
        dest.unlink(missing_ok=True)
        return issue, None, f"{type(e).__name__}: {e}"
    hits = {LAW: len(PRIMARY.findall(text)), "nok_by_name": len(SECONDARY.findall(text)),
            "nok_abbrev": len(ABBREV.findall(text))}
    if y >= CODE_FROM_YEAR:
        hits["code_5306"] = len(CODE.findall(text))
    if not any(hits.values()):
        dest.unlink()                     # Do not keep issues that do not match.
        return issue, None, None
    keep = PDF / f"{fek_id(n, y)}.pdf"
    keep.parent.mkdir(exist_ok=True)
    dest.replace(keep)
    return issue, {**issue, "fek": f"Α΄ {n}/{y}", "id": fek_id(n, y), "acts": acts(text, y),
                   "hits": hits, "review": review(hits)}, None


def scan_year(year, workers=8):
    issues = issues_of_year(year)
    found, failures = [], []
    with cf.ThreadPoolExecutor(workers) as ex:
        for issue, rec, err in ex.map(scan, issues):
            if err:
                failures.append({"number": issue["number"], "error": err})
                print(f"  !! Α΄ {issue['number']}/{year}: {err}", file=sys.stderr)
            elif rec:
                found.append(rec)
                label = ", ".join(f"{a['kind']} {a['number'] or ''}".strip() for a in rec["acts"])
                print(f"  {'?' if rec['review'] else '+'} Α΄ {issue['number']}/{year}  {label}  {rec['hits']}")
    meta = {"issues": len(issues), "max_number": max((i["number"] for i in issues), default=0),
            "failures": failures, "needles": needles(year), "scanned_at": datetime.date.today().isoformat()}
    return found, meta


def load():
    """Read discovered.json and convert old formats. All modules must read the file with this function."""
    db = json.loads(DISCOVERED.read_text(encoding="utf-8")) if DISCOVERED.exists() else {}
    if isinstance(db, list) or not db:                     # Old format: a list of hits only.
        db = {"scanned": {}, "issues": []}
    for i in db["issues"]:                                 # Old key name.
        if "ΝΟΚ-χωρίς-αριθμό" in i.get("hits", {}):
            i["hits"]["nok_by_name"] = i["hits"].pop("ΝΟΚ-χωρίς-αριθμό")
        i["review"] = review(i["hits"])
    for y, m in db["scanned"].items():
        m.setdefault("needles", ["4067/2012", "nok_by_name"])
    return db


def save(db):
    DISCOVERED.write_text(json.dumps(db, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(lo: int, hi: int, force: bool = False) -> int:
    """Scan the years lo to hi. Skip a year scanned cleanly with the same needles, unless force.

    The current year is never skipped. The Printing House adds issues to it.
    Return the number of years with failed downloads.
    """
    db = load()
    this_year = datetime.date.today().year
    for year in range(lo, hi + 1):
        prev = db["scanned"].get(str(year))
        if prev and not prev["failures"] and prev["needles"] == needles(year) and year < this_year and not force:
            continue
        print(f"- ΦΕΚ Α΄ {year}")
        found, meta = scan_year(year)
        db["issues"] = [d for d in db["issues"] if d["year"] != year] + found
        db["scanned"][str(year)] = meta
        db["issues"].sort(key=lambda d: (d["year"], d["number"]))
        save(db)
    save(db)
    bad = {y: len(m["failures"]) for y, m in db["scanned"].items() if m["failures"]}
    print(f"-> discovered.json: {len(db['issues'])} issues, {sum(1 for d in db['issues'] if d['review'])} to review")
    if bad:
        print(f"FAILED downloads per year: {bad}. Run discover again for these years.", file=sys.stderr)
    return len(bad)
