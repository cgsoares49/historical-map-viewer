#!/usr/bin/env python3
"""
name_check.py -- read-only. Flags date-range names in PAR tiles that look truncated or malformed
(found 2026-10-18: 120/035 #425 had 'Neo Babylonian Empire Tributa' after a copy/paste; the plan file
text was complete, so the cut happened on the way into the PAR file, and it crashed legacy tools).

Flags:
  TRUNCATED?  a name that is a strict prefix of a longer name used in the same tile AND ends mid-word
              (the cut falls inside a word of the longer name), used by few entries
  ODD         leading/trailing space, double space, trailing '-', control or non-ASCII characters
  PLAN-DIFF   (with --plan FILE) any range name in that plan file that is not present verbatim in the tile

  python name_check.py                       # 120:030 120:035
  python name_check.py --tiles 125:020       # other tiles
  python name_check.py --plan exports/edom_plan_pal2.txt
"""
import re
import sys
import argparse
from collections import defaultdict

from export_polity_polygons import load_tile

DEFAULT_TILES = ['120:030', '120:035']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tiles', nargs='+', default=DEFAULT_TILES)
    ap.add_argument('--plan', help='a plan file whose range names must all exist verbatim in the tile data')
    a = ap.parse_args()
    plan_names = set()
    if a.plan:
        lines = open(a.plan, encoding='utf-8').read().split('\n')
        for i in range(len(lines) - 2):
            if re.match(r'^-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*$', lines[i].strip()) and lines[i + 2].strip().isdigit():
                plan_names.add(lines[i + 1])
    bad = 0
    for tl in a.tiles:
        lat, lon = tl.split(':')
        t = load_tile(lat, lon)
        users = defaultdict(set)
        for e in t['par_entries']:
            for d in e['dateRanges']:
                users[d['name']].add(e['entryIndex'])
        names = sorted(users)
        for n in names:
            if n != n.strip() or n.endswith('-') or '  ' in n or re.search(r'[^\x20-\x7e]', n):
                print(f'{tl} ODD         {n!r}  entries {sorted(users[n])[:6]}')
                bad += 1
            if len(users[n]) <= 2:
                for m in names:
                    if m != n and m.startswith(n) and len(m) > len(n):
                        rest = m[len(n):]
                        # truncated mid-word: the char after the cut continues a word (no space / dash boundary)
                        if n[-1].isalnum() and rest[0].isalnum():
                            print(f'{tl} TRUNCATED?  {n!r} (entries {sorted(users[n])[:6]}) looks like a cut of {m!r}')
                            bad += 1
                            break
        for pn in sorted(plan_names):
            if pn not in users:
                print(f'{tl} PLAN-DIFF   plan name not found verbatim in tile: {pn!r}')
                bad += 1
    print(f'{bad} finding(s)')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
