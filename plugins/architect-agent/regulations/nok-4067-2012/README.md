# ΝΟΚ — Greek New Building Code (Law 4067/2012)

This dataset holds the Greek building code (ΝΟΚ, law 4067/2012) as published
in the Government Gazette. It also holds the relevant articles of every Gazette
issue (ΦΕΚ Α΄) that cites the code, from 2012 to 7 June 2026.

**The NOK is history since 8 June 2026.** Law 5306/2026 (ΦΕΚ Α΄ 88/2026)
ratified the Spatial Planning and Urban Planning Code «Νικόλαος Ταγαράς».
The building rules are now in Part Δ, Section I of the Code (from Code article 195).
Article 477 of the Code repealed the provisions that its Annex A lists, and only those.
Use this dataset for what applied before that date, and to find where a rule
came from. Use the Code dataset ([`../kodikas-tagaras-5306-2026`](../kodikas-tagaras-5306-2026/README.md))
for the rules in force today. Its README explains the relation between the NOK, the Code and Annex A.

The legal text is Greek and is not translated. The tooling is in [`../gazette`](../gazette/README.md).

## Layout

```
json/
  FEK-A-79-2012.json    the NOK, 48 articles: text, paragraph ids, pages, metadata (source of truth)
  FEK-A-<n>-<year>.json each other issue that cites the NOK: only the relevant articles
md/
  FEK-A-<n>-<year>.md   the same files for reading, with notes (rendered from json/ and the ledger)
ledger.json             for each NOK article: the Gazette articles that amended it
```

The links to the Code are in the Code dataset: `../kodikas-tagaras-5306-2026/crosswalk.json`.

## How to use it

**Read the NOK.** Open `md/FEK-A-79-2012.md`. Articles have the heading `##### Άρθρο N`.
The text is the 2012 text as published. It is not a consolidation. An amended article has notes
under its title:

```
##### Άρθρο 27

**Ειδικές διατάξεις**

> Amended in: [FEK-A-174-2013](FEK-A-174-2013.md) άρθ. 48 (48.5), superseded by FEK-A-245-2020 άρθ. 120 · ...
> Full text as restated on 2020-12-10: [FEK-A-245-2020](FEK-A-245-2020.md) άρθ. 120. Later amendments in the list above still apply.
> Now in the Code «Νικόλαος Ταγαράς»: [άρθ. 224](...) (παρ. 1 → 224.1 · παρ. 5 → 224.4 · ...)
> Not in Annex A of the Code: παρ. 4. Code article 477 repeals only the provisions that Annex A lists. Check whether this text still applies.
```

**Cite a paragraph.** Use `json/FEK-A-79-2012.json`. `11.6.ιδ` is article 11, paragraph 6,
clause ιδ. The id rules are in the [gazette README](../gazette/README.md#paragraph-ids). Each
paragraph has its Gazette page. Articles 1–28, 34, 35 and 48 have `scope: building_rules`. The
other articles amend other laws or regulate separate planning matters (`scope: other`).

Each JSON file has the metadata of its issue: `title`, `fek`, `published`, `source` (the PDF URL),
`search_id`, `pages`, and for amending issues `cites`, `extract` and `review`.

**Find the amendments of an article.** Use `ledger.json`:

```json
"27": {
  "title": "Ειδικές διατάξεις",
  "not_codified": ["4"],
  "amended_in": [
    { "source": "FEK-A-174-2013", "act": "Ν. 4178/2013", "article": "48", "published": "2013-08-08",
      "paragraphs": ["48.5"], "targets": ["27.4"], "status": "superseded",
      "superseded_by": "FEK-A-245-2020 άρθ. 120" },
    { "source": "FEK-A-245-2020", "act": "Ν. 4759/2020", "article": "120", "published": "2020-12-10",
      "paragraphs": ["120#1"], "targets": ["27.2", "27.4", "27.6", "27.7"], "restates": true,
      "status": "confirmed" }
  ]
}
```

The ledger says where to look, not what changed. `source` is a file in `json/` and `md/`.

| field | meaning |
|---|---|
| `targets` | The NOK provisions that the amending sentence names: `27` (whole article), `27.4`, `11.6.ιδ`. Best effort. |
| `restates` | The amending article gives the full new text of the NOK article. Read it for the article as it stood then. |
| `not_codified` | Paragraphs that Annex A does not list and that no pointer repeals. The Code did not repeal them. Check them by hand. |
| `repealed_in` | The pointer that repeals the whole article. |

| status | meaning |
|---|---|
| `confirmed` | The amending article names the NOK article, and Annex A of the Code lists it. |
| `superseded` | Only the text matcher found it, and a later `confirmed` pointer rewrote the same text (`superseded_by`). |
| `unchecked` | The NOK article is not in Annex A, so there is no second source. |
| `repeal` | A repeal. Annex A cannot list it, because repealed text is not in the Code. |
| `title` | The title of the amending article names the NOK article. Annex A does not list it. |
| `matcher` | Only the text matcher found it. Review it. |
| `annex_a` | Only Annex A lists it. Review it. |

**Find where a NOK paragraph is in the Code.** Use `../kodikas-tagaras-5306-2026/crosswalk.json`.
It links `nok:27.5` to `code:224.4`. A link without a paragraph (`nok:3`) covers the whole article.
The paragraph number is the number in the text in force on 8 June 2026, not in the 2012 text.
Paragraph 27 §5 is not in `json/FEK-A-79-2012.json`: ν. 4315/2014 added it. The ledger entry of
the article names that amendment.

**Read an amending issue.** Open `md/FEK-A-<n>-<year>.md`. The `match` of each article:

| `match` | article |
|---|---|
| `number` | cites law 4067/2012 by number |
| `name` | names the NOK only as «Ν.Ο.Κ.», «ΝΟΚ» or «Νέου Οικοδομικού Κανονισμού» (the file gets `review: true`) |
| `related` | an article of the same law that refers to an amending article (transitional rules, exceptions) |
| `commencement` | the commencement article of the law |
| `title` | the whole act is about the NOK (e.g. π.δ. 94/2025 on the environmental offset of its incentives) |
| `annex` | an annex that a kept article refers to |

## Limits

- The pointers say that an article changed. They do not give the text in force
  on a given date. The text in force since 8 June 2026 is the Code.
- `not_codified` compares the paragraph numbers of the 2012 text, and the paragraphs
  that amendments added, with Annex A. It does not see renumbered paragraphs. Today it
  lists two paragraphs. 27 §4 (mosques in Thrace, text of ν. 4759/2020 άρθ. 120) and
  28 §11 (ministerial decision on the conditions of 12 §4 περ. θ) and 20 §9, added by
  ν. 5037/2023 άρθ. 227). Annex A does not list them and the Code has no such text, so
  Code article 477 did not repeal them. Get legal advice before you rely on this.
- Coverage is as good as discovery (`../gazette/discovered.json`). Each year was checked issue
  by issue against the Printing House issue list, with zero download failures.
- Paragraph ids depend on the numbering markers in the text. Irregular
  numbering can give ids that differ from the way lawyers cite a provision.
  Ν. 4254/2014 (`FEK-A-85-2014`) has one article («Άρθρο πρώτο») with paragraphs and
  sub-paragraphs instead of articles. Its ids are long, and its table pages read in
  the wrong order.
- ΦΕΚ Α΄ 67/2026, page 169, holds a second copy of its text in another layout. The
  parser mixes the two copies in article 52. `validate` reports it as a warning.

## Build

```
python3 gazette/cli.py build nok      # from regulations/
```

See [`../gazette/README.md`](../gazette/README.md) for the commands, discovery, extraction and checks.

## Licence

Greek legislative texts are excluded from copyright protection (law 2121/1993,
article 2 §5). You can store and redistribute them. Third-party consolidations
are protected works, and this dataset does not include them.
