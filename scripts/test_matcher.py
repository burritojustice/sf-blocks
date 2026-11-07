#!/usr/bin/env python3
# sf-blocks 2026.11.07.4: master copy.
"""
Check match_blocks.py against the fixes people made in Matcher.

Every CSV in tests/corrections/ (Matcher's "Save fixes" writes them) lists descriptions and the CNNs a
person picked for them on the map. This runs each description through the matcher and compares.

  python3 scripts/test_matcher.py              # report; exits 1 if a case that used to pass now fails
  python3 scripts/test_matcher.py --update     # accept the current results as the new baseline
  python3 scripts/test_matcher.py --failing    # also list every case the matcher still gets wrong

A case passes when the matcher finds the same CNNs (blocks or intersections) for that part of the
description, or finds nothing when the fix was "no match". Cases that fail are what to work on next;
tests/corrections/baseline.json records which pass, so a change that breaks one is caught.

Columns: text, part, expected_type, expected_cnn (";"-separated), matcher_cnn, matcher_confidence,
source, fixed_on, note. Only text, part and expected_cnn are needed.

Standard library only.
"""
import argparse
import csv
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import match_blocks as mb  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "tests", "corrections")
BASELINE = os.path.join(DIR, "baseline.json")


def cnns(v):
    return frozenset(c for c in str(v or "").replace(",", ";").split(";") if c.strip().isdigit())


def load_cases():
    cases = []
    for path in sorted(glob.glob(os.path.join(DIR, "*.csv"))):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for i, row in enumerate(csv.DictReader(f), 2):
                text = (row.get("text") or "").strip()
                if not text:
                    continue
                part = int(row.get("part") or 1)
                cases.append(dict(file=os.path.basename(path), line=i, text=text, part=part,
                                  want=cnns(row.get("expected_cnn")), note=row.get("note", "")))
    return cases


def run(st, case):
    results = mb.match_text(st, case["text"])
    if case["part"] > len(results):
        return frozenset(), "", f"only {len(results)} part(s) found"
    f = mb.output_fields(st, results[case["part"] - 1])
    return cnns(f["cnn"]), f["confidence"], f["notes"]


def key(case):
    return f'{case["text"]}#{case["part"]}'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=os.path.join(ROOT, "data", "streets.json"))
    ap.add_argument("--update", action="store_true", help="save which cases pass now as the baseline")
    ap.add_argument("--failing", action="store_true", help="list every failing case, not just new failures")
    a = ap.parse_args()
    cases = load_cases()
    if not cases:
        print("no cases in tests/corrections/")
        return
    st = mb.Streets(*mb.load(a.data))
    before = json.load(open(BASELINE)) if os.path.exists(BASELINE) else {}
    now, broke, fixed, failing = {}, [], [], []
    for c in cases:
        got, conf, notes = run(st, c)
        ok = got == c["want"]
        now[key(c)] = ok
        line = (c, got, conf, notes)
        if not ok:
            failing.append(line)
            if before.get(key(c)):
                broke.append(line)
        elif key(c) in before and not before[key(c)]:
            fixed.append(line)

    def show(title, lines):
        if not lines:
            return
        print(f"\n{title}:")
        for c, got, conf, notes in lines:
            want = ";".join(sorted(c["want"])) or "no match"
            print(f'  {c["file"]}:{c["line"]}  "{c["text"][:70]}"' + (f' (part {c["part"]})' if c["part"] > 1 else ""))
            print(f'      wanted {want}; matcher says {";".join(sorted(got)) or "no match"} ({conf or "none"}){f" - {notes}" if notes else ""}')

    passed = sum(now.values())
    print(f"{passed} of {len(cases)} fixes match ({len(cases) - passed} still wrong)")
    show("Used to pass, now wrong", broke)
    show("Newly right", fixed)
    if a.failing:
        show("Still wrong", [x for x in failing if x not in broke])
    if a.update:
        os.makedirs(DIR, exist_ok=True)
        with open(BASELINE, "w") as f:
            json.dump(dict(sorted(now.items())), f, indent=1)
            f.write("\n")
        print(f"\nbaseline saved: {passed} passing")
    elif broke:
        sys.exit(1)


if __name__ == "__main__":
    main()
