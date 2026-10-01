"""Shared paths and helpers for the Gazette tooling."""
import json, re, subprocess, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # gazette/
REGULATIONS = ROOT.parent                              # regulations/: one folder per dataset
PDF, CACHE = ROOT / "pdf", ROOT / ".cache"
DISCOVERED = ROOT / "discovered.json"

# search.et.gr serves Gazette PDFs from public blob storage at a predictable URL.
BLOB = "https://ia37rg02wpsa01.blob.core.windows.net/fek"
# The backend of search.et.gr: issue lists per year and the modification graph.
API = "https://searchetv99.azurewebsites.net/api"
UA = {"User-Agent": "Mozilla/5.0", "Origin": "https://search.et.gr", "Referer": "https://search.et.gr/"}


def fek_url(number: int, year: int, issue: int = 1) -> str:
    """Return the PDF URL of an issue. Series Α' is issue group 1."""
    return f"{BLOB}/{issue:02d}/{year}/{year}{issue:02d}{number:05d}.pdf"


def fek_id(number: int, year: int) -> str:
    """Return the identifier and file name of an issue, e.g. FEK-A-79-2012."""
    return f"FEK-A-{number}-{year}"


def _get(req, attempts=5):
    """Send a GET request with retries.

    Only HTTP 404 means "does not exist". The function retries all other errors.
    After the last attempt, it raises the error. It never ignores an error.
    """
    for k in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404 or k == attempts - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if k == attempts - 1:
                raise
        time.sleep(2 ** k)


def download(url: str, dest: Path, min_size: int = 10_000) -> Path:
    """Download a file once. Keep an existing file if it is larger than min_size."""
    if dest.exists() and dest.stat().st_size > min_size:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(_get(urllib.request.Request(url, headers=UA)))
    tmp.rename(dest)
    return dest


def api(path: str, body: dict | None = None):
    """Call the search.et.gr API. The "data" field is JSON inside a string."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {**UA, "Content-Type": "application/json"} if body is not None else UA
    w = json.loads(_get(urllib.request.Request(f"{API}/{path}", data=data, headers=headers)))
    if w.get("status") != "ok":
        raise RuntimeError(f"{path}: {w.get('message')}")
    d = w.get("data") or "[]"
    return json.loads(d) if isinstance(d, str) else d


def issues_of_year(year: int) -> list[dict]:
    """Return all issues of series Α' for one year, as the Printing House lists them."""
    hits = api("simplesearch", {"selectYear": [str(year)], "selectIssue": ["1"], "documentNumber": "",
                                "searchText": "", "datePublished": "", "dateReleased": ""})
    out = {}
    for h in hits:
        m, d, y = h["search_PublicationDate"].split()[0].split("/")
        out[int(h["search_DocumentNumber"])] = {
            "number": int(h["search_DocumentNumber"]), "year": year, "search_id": int(h["search_ID"]),
            "published": f"{y}-{m}-{d}", "pages": int(h["search_Pages"] or 0)}
    return [out[k] for k in sorted(out)]


def issue_record(number: int, year: int) -> dict:
    """Return the issue list record of one issue."""
    hit = api("simplesearch", {"selectYear": [str(year)], "selectIssue": ["1"], "documentNumber": str(number),
                               "searchText": "", "datePublished": "", "dateReleased": ""})[0]
    m, d, y = hit["search_PublicationDate"].split()[0].split("/")
    return {"number": number, "year": year, "id": fek_id(number, year), "search_id": int(hit["search_ID"]),
            "published": f"{y}-{m}-{d}", "pages": int(hit["search_Pages"] or 0)}


def timeline(search_id: int) -> list[dict]:
    """Return the official modification graph of one issue. Use it as a hint, not as proof."""
    return api(f"timeline/{search_id}/0")


# Latin letters that the Gazette uses in place of Greek letters (NOMOΣ, TΗΣ, ∆).
_LATIN_CHARS = "ABEHIKMNOPTXYZaeiopxyv∆"
_LATIN = str.maketrans(_LATIN_CHARS, "ΑΒΕΗΙΚΜΝΟΡΤΧΥΖαειορχυνΔ")
_MIXED = re.compile(r"[A-Za-z∆]+(?=[Ͱ-Ͽἀ-῿])|(?<=[Ͱ-Ͽἀ-῿])[A-Za-z∆]+")


def degreekify(text: str) -> str:
    """Replace look-alike Latin letters, but only inside words that are already Greek.

    Latin words that do not touch Greek letters (MWh, TEE) stay unchanged.
    """
    return _MIXED.sub(lambda m: m.group(0).translate(_LATIN)
                      if all(c in _LATIN_CHARS for c in m.group(0)) else m.group(0), text)


def pdftotext(pdf: Path, *args: str) -> str:
    return subprocess.run(["pdftotext", "-enc", "UTF-8", *args, str(pdf), "-"],
                          capture_output=True, text=True, check=True, timeout=600).stdout


def frontmatter(**fields) -> str:
    """Return YAML frontmatter. Lists are inline. Strings are quoted. None values are left out."""
    def fmt(v):
        if isinstance(v, (list, tuple)):
            return "[" + ", ".join(fmt(x) for x in v) + "]"
        if isinstance(v, bool):
            return str(v).lower()
        if isinstance(v, (int, float)):
            return str(v)
        return '"' + str(v).replace('"', '\\"') + '"'
    body = "\n".join(f"{k}: {fmt(v)}" for k, v in fields.items() if v is not None)
    return f"---\n{body}\n---\n"


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, obj, indent: int = 1):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8")


def num_key(s: str):
    """Sort key for ids such as "27", "27Α", "224.3.β": numbers first, in numeric order."""
    return [(0, int(x), "") if x.isdigit() else (1, 0, x) for x in re.findall(r"\d+|[^\d.]+", s)]
