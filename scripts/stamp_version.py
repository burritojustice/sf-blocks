#!/usr/bin/env python3
# sf-blocks 2026.11.19
"""Stamp a version after pull requests merge, so they never conflict over VERSION and CHANGELOG.md.

Each pull request adds its notes as a file in changes/ (changes/<branch or id>.md: one "- " line per change,
in plain words). When it merges, the "Stamp version" action runs this on main:

  1. VERSION becomes today's date (2026.11.19), or the next of today's (2026.11.19.2);
  2. the notes in changes/ go to the top of CHANGELOG.md under that version, oldest file first;
  3. each script in scripts/ changed since the last stamp gets the version in its first comment line
     ("# sf-blocks 2026.11.19");
  4. the files in changes/ are removed (README.md stays).

    python3 scripts/stamp_version.py            stamp (does nothing when changes/ is empty)
    python3 scripts/stamp_version.py --dry-run  show what it would do

Standard library only.
"""
import argparse, re, subprocess, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGES = ROOT / 'changes'


def git(*a):
    return subprocess.run(['git', *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def next_version(old, today=None):
    today = today or date.today().strftime('%Y.%m.%d')
    if old == today or old.startswith(today + '.'):
        return f'{today}.{int(old.split(".")[3]) + 1 if old.count(".") == 3 else 2}'
    return today


def added(p):
    # when the file first came in, so notes keep their merge order
    t = git('log', '--diff-filter=A', '--format=%ct', '--', str(p.relative_to(ROOT)))
    return int(t.splitlines()[-1]) if t else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--today', help=argparse.SUPPRESS)
    a = ap.parse_args()
    files = sorted((p for p in CHANGES.glob('*.md') if p.name != 'README.md'), key=lambda p: (added(p), p.name))
    if not files: print('Nothing in changes/.'); return
    old = (ROOT / 'VERSION').read_text().strip()
    new = next_version(old, a.today)
    notes = []
    for p in files:
        for line in p.read_text().strip().splitlines():
            if line.strip(): notes.append(line if line.startswith(('-', ' ', '\t')) else '- ' + line)
    # scripts changed since VERSION last changed
    since = git('log', '-1', '--format=%H', '--', 'VERSION')
    changed = [ROOT / f for f in git('diff', '--name-only', since, 'HEAD', '--', 'scripts').splitlines()] if since else []
    stamped = []
    for p in changed:
        if not p.exists() or p.suffix != '.py': continue
        lines = p.read_text().split('\n')
        for i in range(min(3, len(lines))):
            if re.match(r'#\s*sf-blocks \d{4}\.\d\d\.\d\d', lines[i]):
                lines[i] = re.sub(r'\d{4}\.\d\d\.\d\d(\.\d+)?', new, lines[i], count=1); stamped.append(p.name)
                if not a.dry_run: p.write_text('\n'.join(lines))
                break
    print(f'{old} → {new}: {len(notes)} notes from {len(files)} files; scripts stamped: {", ".join(stamped) or "none"}')
    if a.dry_run:
        print('\n'.join(notes)); return
    (ROOT / 'VERSION').write_text(new + '\n')
    log = ROOT / 'CHANGELOG.md'; s = log.read_text()
    log.write_text(s.replace('# Changelog\n\n', f'# Changelog\n\n## {new}\n' + '\n'.join(notes) + '\n\n', 1))
    for p in files: p.unlink()


if __name__ == '__main__':
    sys.exit(main())
