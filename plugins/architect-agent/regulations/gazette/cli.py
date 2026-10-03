#!/usr/bin/env python3
"""The Gazette CLI: build the NOK and Code datasets from the Government Gazette (ΦΕΚ Α΄).

    python3 gazette/cli.py discover 2012 2026 [--force]    scan the issues -> gazette/discovered.json, gazette/pdf/
    python3 gazette/cli.py fetch nok|code [ID ...]          PDFs -> <dataset>/json/ (code: also the Code text)
    python3 gazette/cli.py index                            amendments + Annex A links -> regulations/index.json
    python3 gazette/cli.py render nok|code [ID ...]         <dataset>/json/ -> <dataset>/md/
    python3 gazette/cli.py validate nok|code [ID ...]       fails on any error
    python3 gazette/cli.py crosscheck                       NOK completeness against independent sources
    python3 gazette/cli.py build nok|code|all               fetch, index, render, validate (+ crosscheck)

Discovery needs the network. The other commands use the PDFs in gazette/pdf, and download a PDF only if it is missing.
Requirements: pdftotext (poppler) and Python 3.10 or later. No Python packages.
"""
import argparse, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import convert, crosscheck, datasets, discover, index, kodikas, render, validate  # noqa: E402
from datasets import CODE, DATASETS, NOK  # noqa: E402


def fetch(ds, only=frozenset()) -> int:
    """Convert each issue of a dataset into JSON. Return 0."""
    done = 0
    for issue in datasets.issues(ds):
        if only and issue["id"] not in only:
            continue
        if ds is CODE and issue["id"] == CODE.main:
            kodikas.write_text()
            done += 1
        else:
            done += bool(convert.convert(issue, ds))
    print(f"-> {done} files in {ds.root.name}/json/")
    return 0


def build(targets) -> int:
    """Run the pipeline in stages. Each stage runs for all target datasets before the next stage.

    The index comes before the rendering: the md notes of both datasets use it. The index reads
    both datasets, so it and validation come after all fetches.
    """
    for ds in targets:
        fetch(ds)
    index.run()
    for ds in targets:
        render.run(ds)
    failed = sum(validate.run(ds) for ds in targets)
    if NOK in targets:
        failed += crosscheck.run()
    return failed


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("discover", help="scan Gazette issues")
    p.add_argument("first", type=int)
    p.add_argument("last", type=int, nargs="?")
    p.add_argument("--force", action="store_true", help="scan again years that were scanned cleanly")
    for name, help_text in (("fetch", "PDFs -> json/"), ("render", "json/ -> md/"), ("validate", "check a dataset")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("dataset", choices=DATASETS)
        p.add_argument("ids", nargs="*", help="only these files, e.g. FEK-A-245-2020")
    sub.add_parser("index", help="build regulations/index.json")
    sub.add_parser("crosscheck", help="NOK completeness")
    sub.add_parser("build", help="full pipeline").add_argument("dataset", choices=[*DATASETS, "all"])
    args = parser.parse_args()

    if args.command == "discover":
        failed = discover.run(args.first, args.last or args.first, args.force)
    elif args.command == "fetch":
        failed = fetch(DATASETS[args.dataset], set(args.ids))
    elif args.command == "render":
        render.run(DATASETS[args.dataset], set(args.ids))
        failed = 0
    elif args.command == "validate":
        failed = validate.run(DATASETS[args.dataset], set(args.ids))
    elif args.command == "index":
        failed = index.run()
    elif args.command == "crosscheck":
        failed = crosscheck.run()
    else:
        failed = build([CODE, NOK] if args.dataset == "all" else [DATASETS[args.dataset]])
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
