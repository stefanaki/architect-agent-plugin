"""Global ids: one grammar for index.json, the build and scripts/regulations.py.

  code:224.3.β            the Code text (law 5306/2026, ΦΕΚ Α΄ 88/2026)
  nok:27.5                the NOK text (law 4067/2012, ΦΕΚ Α΄ 79/2012)
  FEK-A-108-2026:133.1    an article or paragraph of another issue
  FEK-A-108-2026          a whole issue

The part after ":" is the paragraph id of the JSON file (gazette README, "Paragraph ids").
Its first part is the article. «#», «~» and «@» mark unnumbered text, quoted text and repeats.
This module uses the standard library only: the query script imports it from an installed plugin.
"""
import re

SCOPES = ("code", "nok")
GRAMMAR = {
    "code:<article>[.<paragraph>[.<case>...]]": "the Code text (law 5306/2026, ΦΕΚ Α΄ 88/2026), e.g. code:224.3.β",
    "nok:<article>[.<paragraph>...]": "the NOK text (law 4067/2012, ΦΕΚ Α΄ 79/2012), e.g. nok:27.5",
    "FEK-A-<n>-<year>:<article>[...]": "another Gazette issue, e.g. FEK-A-108-2026:133.1",
    "#k / ~ / @k": "unnumbered text after a numbered part / quoted text of another provision / k-th repeat",
    "ASCII": "clause letters can be typed in ASCII: code:224.3.b = code:224.3.β, nok:10a = nok:10Α",
}
FILE = re.compile(r"FEK-A-\d+-\d{4}")
MARKS = ".#~@"
KERAIA = "΄"                                       # «΄» as the Gazette prints «Α΄ 88/2026».
_GREEK_ACCENTS = str.maketrans("άέήίόύώϊΐϋΰς", "αεηιουωιιυυσ")

# ASCII input for Greek numerals: «b» or «beta» -> «β», «id» -> «ιδ», «st» -> «στ».
_NAMES = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "stigma": "στ", "zeta": "ζ",
          "eta": "η", "theta": "θ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ",
          "omicron": "ο", "pi": "π"}
_LETTERS = [("th", "θ"), ("st", "στ"), ("ks", "ξ"), ("a", "α"), ("b", "β"), ("v", "β"), ("g", "γ"), ("d", "δ"),
            ("e", "ε"), ("z", "ζ"), ("h", "η"), ("i", "ι"), ("k", "κ"), ("l", "λ"), ("m", "μ"), ("n", "ν"),
            ("x", "ξ"), ("o", "ο"), ("p", "π")]


def acts(doc: dict) -> list[dict]:
    """Return the acts of a JSON file. The Code file holds one act as top-level "act" and "articles"."""
    return doc["acts"] if "acts" in doc else [{"act": doc["act"], "articles": doc["articles"]}]


def fold(text: str) -> str:
    """Return lower-case Greek without accents and with «ς» as «σ». The length does not change."""
    return text.lower().translate(_GREEK_ACCENTS)


def make(scope: str, local: str = "") -> str:
    return f"{scope}:{local}" if local else scope


def split(gid: str) -> tuple[str, str]:
    """Split a canonical id: "code:224.3.β" -> ("code", "224.3.β"), "FEK-A-1-2026" -> ("FEK-A-1-2026", "")."""
    scope, _, local = gid.partition(":")
    if scope not in SCOPES and not FILE.fullmatch(scope):
        raise ValueError(f"unknown id scope «{scope}»: use code:, nok: or FEK-A-<n>-<year>:")
    if scope in SCOPES and not local:
        raise ValueError(f"«{gid}» names no article: use {scope}:<article>[.<paragraph>...]")
    return scope, local


def article(local: str) -> str:
    """Return the article of a local id: "224.3.β" -> "224", "120#1~4" -> "120"."""
    return re.split(r"[.#~@]", local, maxsplit=1)[0]


def numbered(local: str) -> str:
    """Return the numbered part of a local id, before unnumbered or quoted text: "120#1~4" -> "120"."""
    return re.split(r"[#~@]", local, maxsplit=1)[0]


def within(gid: str, ancestor: str) -> bool:
    """Return True if gid is ancestor, or inside it: within("code:224.3.β", "code:224.3")."""
    return gid == ancestor or (gid.startswith(ancestor) and gid[len(ancestor)] in MARKS)


def related(a: str, b: str) -> bool:
    return within(a, b) or within(b, a)


def _segment(seg: str, first: bool) -> str:
    """Normalize one part of a local id that a person or an agent typed."""
    seg = re.sub(r"[΄'’)]", "", seg)
    if not seg or seg.upper().startswith("Π-"):        # An annex of an issue: «Π-», «Π-Γ».
        return seg.upper()
    if (m := re.fullmatch(r"(\d+)([^\d]*)", seg)):
        # A letter after a number is an added article or paragraph: «10Α», «7Α» (Greek capitals).
        return m.group(1) + _greek(m.group(2)).upper() if m.group(2) else seg
    if first:
        raise ValueError(f"«{seg}» is not an article number")
    return _greek(seg)


def _greek(s: str) -> str:
    s = s.lower()
    if re.fullmatch(r"[α-ωά-ώϊΐϋΰ]+", s):
        return fold(s)
    if s in _NAMES:
        return _NAMES[s]
    out, i = "", 0
    while i < len(s):
        for latin, greek in _LETTERS:
            if s.startswith(latin, i):
                out, i = out + greek, i + len(latin)
                break
        else:
            raise ValueError(f"cannot read «{s}» as a Greek numeral (use α, β, ... or a, b, ...)")
    return out


def normalize(text: str) -> str:
    """Return the canonical id of typed input.

    «code:224.3.b», «CODE:224.3.beta», «code:224.3.β΄» -> "code:224.3.β".
    «fek-a-108-2026:133.1» -> "FEK-A-108-2026:133.1". «nok:10a» -> "nok:10Α".
    """
    text = re.sub(r"\s+", "", text.strip())
    scope, sep, local = text.partition(":")
    scope = scope.upper() if scope.lower().startswith("fek") else scope.lower()
    if not sep:
        return make(*split(scope))
    if re.search(r"^[.#~@]|\.$|[#~@]$|\.[.#~@]|[#~@]\.", local):
        raise ValueError(f"«{local}» has an empty part")
    parts = re.split(r"([.#~@])", local)
    out, first = [], True
    for p in parts:
        if p and p in MARKS:
            out.append(p)
        else:
            out.append(_segment(p, first and scope in SCOPES) if p and not p.isdigit() else p)
            first = False
    return make(*split(f"{scope}:{''.join(out)}"))


def _act_label(act: str) -> str:
    """«Ν. 5306/2026» -> «ν. 5306/2026», «Π.Δ. 94/2025» -> «π.δ. 94/2025». Other labels stay."""
    return re.sub(r"^(Ν\.|Π\.Δ\.|Π\.\s?Δ\.)", lambda m: m.group(1).lower(), act)


def cite(local: str, act: str, fek: str, label: str | None = None) -> str:
    """Return the legal citation of a local id, from its numbered part.

    cite("224.3.β", "Ν. 5306/2026", "Α΄ 88/2026") -> "άρθ. 224 παρ. 3 περ. β΄ ν. 5306/2026 (ΦΕΚ Α΄ 88/2026)".
    The first number after the article is a paragraph, the next level a case (περ.), deeper levels
    sub-cases (υποπερ.). Unnumbered or quoted text cites its nearest numbered ancestor.
    `label` replaces «άρθ. N» for an annex («Παράρτημα Α΄»).
    """
    parts = numbered(local).split(".")
    words = [label or f"άρθ. {parts[0]}"]
    level = 0
    for p in parts[1:]:
        mark = p + KERAIA if re.fullmatch(r"[α-ω]+", p) else p
        if level == 0 and p[0].isdigit():
            words.append(f"παρ. {mark}")
            level = 1
        elif level <= 1:
            words.append(f"περ. {mark}")
            level = 2
        elif level == 2:
            words.append(f"υποπερ. {mark}")
            level = 3
        else:
            words[-1] += f".{mark}"
    return f"{' '.join(words)} {_act_label(act)} (ΦΕΚ {fek})"
