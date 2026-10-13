"""
overlay_steplist.py
Chronological "step list" for walking a region's map through time: one row per
DATE on which anything changes, instead of one per 0.1-year step. Built from
polity_overlay_report.build() plus your authoring log.

Each row (a date) carries:
  * LogActions      -- animation actions.xlsx rows whose start date is that date
  * EntryChanges    -- date-range boundaries of the entries in the overlay report
                       (begins / ends / name or owner changes)
  * OverlapsOpening / OverlapsClosing -- polity overlays that start or stop
  * ActiveOverlaps  -- every overlay still active just after this date
  * ViewYear        -- the first 0.1-year step at which the change is VISIBLE
                       (MAPPER matches  from < year <= to , so a change dated t
                       first shows at t+0.1)
  * CenterLon/Lat   -- where to look
  * Priority        -- OVERLAP (an overlay opens/closes) > ENTRY (a reported
                       entry changes) > LOG (log row only)

READ-ONLY. Writes exports/overlay_steplist_<label>.csv

Usage:
  python overlay_steplist.py
  python overlay_steplist.py --tiles 120:030 120:035 --from -1200 --to -800 --label palestine
"""

import os
import sys
import csv
import argparse
from types import SimpleNamespace
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from polity_overlay_report import build, load_all_log_rows, EXPORTS
from mark_blob_overlays import DEFAULT_MAX_AREA

DEFAULT_TILES = ['120:030', '120:035']


def tile_center(tile_key):
    la, lo = tile_key.split('/')
    lat = int(la) - 90 + 2.5
    lon = int(lo) + 2.5
    if lon > 180:
        lon -= 360
    return lat, lon


def disp(year):
    return f"{abs(year):g} {'BCE' if year < 0 else 'CE'}"


def r1(x):
    return round(x + 1e-9, 1)


def parse_windows(text):
    out = []
    for seg in text.split(';'):
        seg = seg.strip()
        if '..' in seg:
            lo, hi = seg.split('..')
            out.append((float(lo), float(hi)))
    return out


def make_steplist(args):
    ent, pairs, rngs, stats, _ = build(args)
    tiles = [t.replace(':', '/') for t in args.tiles]

    center = {}
    for r in ent:
        center.setdefault((r['Tile'], int(r['EntryIndex'])), (float(r['CenterLat']), float(r['CenterLon']), r['Name']))
    name_of = lambda tile, idx: center.get((tile, idx), (0, 0, '?'))[2]

    steps = defaultdict(lambda: {'log': [], 'entry': [], 'open': [], 'close': [], 'pts': [], 'tiles': set()})

    # 1. authoring-log actions
    all_log = load_all_log_rows()
    seen = set()
    for t in tiles:
        for s, e, d, _src in all_log.get(t, []):
            if args.from_year <= s <= args.to_year and (r1(s), d) not in seen:
                seen.add((r1(s), d))
                st = steps[r1(s)]
                st['log'].append(d if e is None or abs(e - s) < 0.05 else f"{d} (to {e:g})")
                st['tiles'].add(t)

    # 2. date-range boundaries of the entries in the report
    per_entry = defaultdict(dict)
    for r in rngs:
        per_entry[(r['Tile'], int(r['EntryIndex']))][(float(r['From']), float(r['To']), r['Name'])] = r
    for (tile, idx), ranges in per_entry.items():
        rs = sorted(ranges)
        starts = {r1(f): n for f, t, n in rs}
        ends = {r1(t): n for f, t, n in rs}
        lat, lon, nm = center.get((tile, idx), (None, None, '?'))
        for f, t, n in rs:
            for edge, kind in ((r1(f), 'start'), (r1(t), 'end')):
                if not (args.from_year <= edge <= args.to_year):
                    continue
                if kind == 'start':
                    prev = ends.get(edge)
                    txt = (f"{tile} #{idx}: '{prev}' -> '{n}'" if prev and prev != n else
                           f"{tile} #{idx}: begins '{n}'" if not prev else None)
                else:
                    nxt = starts.get(edge)
                    txt = f"{tile} #{idx}: '{n}' ends" if not nxt else None
                if txt:
                    st = steps[edge]
                    if txt not in st['entry']:
                        st['entry'].append(txt)
                    st['tiles'].add(tile)
                    if lat is not None:
                        st['pts'].append((lat, lon))

    # 3. overlay windows
    active_defs = []   # (gid, tile, a, b, lo, hi, label)
    for p in pairs:
        tile = p['Tile']
        la, lb = name_of(tile, p['A']), name_of(tile, p['B'])
        rel = {'A INSIDE B': f"{la} inside {lb}", 'B INSIDE A': f"{lb} inside {la}",
               'NEAR-IDENTICAL': f"{la} = {lb}"}.get(p['Relation'], f"{la} x {lb} partial")
        label = f"G{p['GroupID']} {tile} #{p['A']}/#{p['B']} {rel} ({p['PctOfA']:.0f}%/{p['PctOfB']:.0f}%)"
        for lo, hi in parse_windows(p['OverlapWindows']):
            active_defs.append((lo, hi, label))
            for edge, kind in ((r1(lo), 'open'), (r1(hi), 'close')):
                if args.from_year <= edge <= args.to_year:
                    st = steps[edge]
                    st[kind].append(label)
                    st['tiles'].add(tile)
                    for idx in (p['A'], p['B']):
                        c = center.get((tile, idx))
                        if c:
                            st['pts'].append((c[0], c[1]))

    rows = []
    for d in sorted(steps):
        st = steps[d]
        view = r1(d + 0.1)
        active = sorted({lab for lo, hi, lab in active_defs if lo < view <= hi})
        if st['pts']:
            lat = sum(p[0] for p in st['pts']) / len(st['pts'])
            lon = sum(p[1] for p in st['pts']) / len(st['pts'])
        else:
            lat, lon = tile_center(sorted(st['tiles'])[0]) if st['tiles'] else (31.5, 35.0)
        pri = 'OVERLAP' if (st['open'] or st['close']) else 'ENTRY' if st['entry'] else 'LOG'
        rows.append({
            'Date': d, 'ViewYear': view, 'Display': disp(view), 'Priority': pri,
            'Tiles': ' '.join(sorted(st['tiles'])),
            'LogActions': ' || '.join(st['log']),
            'EntryChanges': ' || '.join(st['entry']),
            'OverlapsOpening': ' || '.join(sorted(st['open'])),
            'OverlapsClosing': ' || '.join(sorted(st['close'])),
            'NumActiveOverlaps': len(active),
            'ActiveOverlaps': ' || '.join(active),
            'CenterLat': round(lat, 2), 'CenterLon': round(lon, 2),
        })
    return rows, stats


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tiles', nargs='+', default=DEFAULT_TILES)
    ap.add_argument('--from', dest='from_year', type=float, default=-1200.0)
    ap.add_argument('--to', dest='to_year', type=float, default=-800.0)
    ap.add_argument('--label', default='palestine')
    ap.add_argument('--exclude-blobs', action='store_true', help='drop blob-tier (AUTO) entries (default: keep them)')
    a = ap.parse_args()
    args = SimpleNamespace(tiles=a.tiles, from_year=a.from_year, to_year=a.to_year, label=a.label,
                           include_blobs=not a.exclude_blobs, max_area=DEFAULT_MAX_AREA)
    rows, _ = make_steplist(args)
    out = os.path.join(EXPORTS, f'overlay_steplist_{a.label}.csv')
    with open(out, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    from collections import Counter
    c = Counter(r['Priority'] for r in rows)
    span = (a.to_year - a.from_year) / 0.1
    print(f"{len(rows)} dates to visit (vs {span:.0f} steps of 0.1 yr): "
          f"{c['OVERLAP']} where an overlay opens/closes, {c['ENTRY']} where a reported entry changes, "
          f"{c['LOG']} log-only.")
    print(f"Wrote {out}")


if __name__ == '__main__':
    main()
