"""
Import a hand-authored lecture into the bank. No API call.

    python tools\\import_lecture.py lectures\\ftcm26.json
    python tools\\import_lecture.py lectures\\ftcm26.json --check   # validate only

The rules live in backend/importer.py, which the Material tab's paste-in box
also uses, so the command line and the UI cannot enforce different things.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import app as _app  # noqa: E402,F401  (configures the database)
from backend import db, generate, importer  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", type=Path)
    ap.add_argument("--check", action="store_true",
                    help="validate and report, write nothing")
    ap.add_argument("--label", default=None,
                    help="source label (defaults to the analysis title)")
    args = ap.parse_args()

    if not args.path.exists():
        print(f"No such file: {args.path}")
        return 1

    payload = json.loads(args.path.read_text(encoding="utf-8"))
    analysis = payload.get("analysis") or {}
    questions = payload.get("questions") or []

    errs = importer.validate(analysis, questions)
    print(f"{args.path.name}: {len(analysis.get('concepts', []))} concepts, "
          f"{len(questions)} questions")

    if errs:
        print(f"\n{len(errs)} problem(s) - nothing was written:\n")
        for e in errs[:40]:
            print(f"  - {e}")
        if len(errs) > 40:
            print(f"  ... and {len(errs) - 40} more")
        return 1

    s = importer.summarise(analysis, questions)
    print("  types      : " + ", ".join(f"{k} {v}" for k, v in sorted(s["by_type"].items())))
    print("  DOK        : " + ", ".join(
        f"{k} {generate.DOK_LABELS[int(k)]} {v}" for k, v in sorted(s["by_dok"].items())))
    print(f"  DOK 3-4    : {s['dok_high']}/{s['questions']} "
          f"({s['dok_high_share']:.0%}) - target {s['dok_target']:.0%}")
    if not s["dok_on_target"]:
        print("               ^ below target. Her exams are DOK 3-4; a set that")
        print("                 stops at DOK 2 tests recall she already has.")
    ob = s["objectives"]
    if ob["stated"]:
        print(f"  objectives : {ob['covered']}/{ob['stated']} covered "
              f"({ob['share']:.0%})")
        for u in ob["uncovered"]:
            code = f" [{u['code']}]" if u["code"] else ""
            print(f"               UNCOVERED{code}: {u['text'][:88]}")
        if ob["unmapped_questions"]:
            print(f"               {ob['unmapped_questions']} question(s) map to "
                  "no objective")
    else:
        print("  objectives : none stated in the material")
    print("  validation : all checks passed")

    if args.check:
        print("\n--check: nothing written.")
        return 0

    out = importer.import_payload(payload, label=args.label)
    print(f"\nimported: {out['imported_concepts']} concepts, "
          f"{out['imported_questions']} questions")
    print("bank now: " + str({t: db.q1(f'SELECT COUNT(*) c FROM "{t}"')["c"]
                              for t in ("concept", "question", "attempt")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
