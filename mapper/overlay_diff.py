"""
overlay_diff.py
Forward-check for PAR edits: snapshot a region's overlay state, edit your PAR
data, then diff -- you get ONLY what your edit changed, from a date onward,
instead of re-stepping the whole span looking for knock-on effects.

  python overlay_diff.py snapshot              # save the current state as the baseline
  python overlay_diff.py diff                  # compare now vs the baseline
  python overlay_diff.py diff --since -993.5   # only effects at/after that year
  python overlay_diff.py diff --accept         # after reviewing, make "now" the new baseline

What is compared (per tile in --tiles, window --from..--to, blobs kept):
  ENTRY level (every real-territory entry in the tiles, not just reported ones)
    added / removed entries; date-range additions, removals, edits (with the
    exact dates); area change > 1%; polyRef (geometry) change; areaType change;
    ring validity (new/cleared self-intersection or flip-fixable border).
  OVERLAP level (the overlay pairs polity_overlay_report finds)
    NEW pairs, GONE pairs, and pairs whose windows / % overlap changed.

A change is reported when its affected dates reach --since (default: all).
Geometry changes affect every date the entry is active, so they are always
listed with that entry's active span.

READ-ONLY w.r.t. PAR data. Snapshots live in exports/overlay_snapshots/.
Writes exports/overlay_diff_<label>.csv for the last diff run.
"""

import os
import sys
import csv
import json
import glob
import argparse
import contextlib
import io
from datetime import datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export_polity_polygons import load_tile, build_combined_ring, DATA_DIR
from find_polity_overlays import load_candidates, load_transient_registry
from polity_overlay_report import build, polyrefs_text, EXPORTS
from mark_blob_overlays import direction_scan_entry, DEFAULT_MAX_AREA
from overlay_steplist import parse_windows
from shapely.geometry import Polygon

SNAPDIR = os.path.join(EXPORTS, 'overlay_snapshots')
DEFAULT_TILES = ['120:030', '120:035']


def tile_files(lat, lon):
    return [os.path.join(DATA_DIR, 'polareas', lat, f'PAR{lon}.ASC'),
            os.path.join(DATA_DIR, 'pols', lat, f'POL{lon}.PRN'),
            os.path.join(DATA_DIR, 'coasts', lat, f'CST{lon}.PRN')]


def capture(args):
    """Current state as a JSON-able dict."""
    ent, pairs, rngs, stats, _ = build(args)
    registry = load_transient_registry()
    entries, files = {}, {}
    for t in args.tiles:
        lat, lon = t.split(':')
        tile_key = f'{lat}/{lon}'
        for p in tile_files(lat, lon):
            files[p] = os.path.getmtime(p) if os.path.exists(p) else None
        tile = load_tile(lat, lon)
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink):
            cands, _, _, _ = load_candidates(tile, tile_key, *registry)
        for c in cands:
            e = c['entry']
            try:
                ring, _ = build_combined_ring(e['polyRefs'], tile['cst_by_index'], tile['pol_by_index'])
                bad = not Polygon(ring).is_valid
            except Exception:
                bad = False
            flip = bool(direction_scan_entry(e, tile))
            entries[f"{tile_key}#{e['entryIndex']}"] = {
                'ranges': [[dr['from'], dr['to'], dr['name'], dr['colorIndex']] for dr in e['dateRanges']],
                'area': round(c['area_km2'], 1), 'polyrefs': polyrefs_text(e, tile),
                'areaType': e['areaType'], 'selfIntersecting': bad, 'flipFixable': flip,
            }
    pair_state = {}
    for p in pairs:
        key = f"{p['Tile']}#{p['A']}|#{p['B']}"
        pair_state[key] = {'windows': [list(w) for w in parse_windows(p['OverlapWindows'])],
                           'pctA': p['PctOfA'], 'pctB': p['PctOfB'], 'relation': p['Relation'],
                           'aName': p['A_Name'], 'bName': p['B_Name']}
    return {'created': datetime.now().isoformat(timespec='seconds'), 'tiles': args.tiles,
            'from': args.from_year, 'to': args.to_year, 'files': files,
            'entries': entries, 'pairs': pair_state}


def snap_paths(label):
    os.makedirs(SNAPDIR, exist_ok=True)
    return os.path.join(SNAPDIR, f'{label}_latest.json')


def save(state, label, stamp=True):
    latest = snap_paths(label)
    with open(latest, 'w', encoding='utf-8') as f:
        json.dump(state, f)
    if stamp:
        arch = os.path.join(SNAPDIR, f"{label}_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
        with open(arch, 'w', encoding='utf-8') as f:
            json.dump(state, f)
        return arch
    return latest


def range_tuple(r):
    return (float(r[0]), float(r[1]), r[2], int(r[3]))


def span_of(ranges):
    ok = [r for r in ranges if r[2].strip().upper() != 'UNKNOWN']
    ok = ok or ranges
    return (min(r[0] for r in ok), max(r[1] for r in ok)) if ok else (None, None)


def compare(old, new, since):
    out = []   # dicts: Kind, Where, Detail, From, To

    wlo, whi = new.get('from', -1e9), new.get('to', 1e9)

    def add(kind, where, detail, lo, hi):
        if hi is not None and hi < since:
            return
        # outside the review window entirely (e.g. a 1990 CE range) -> not relevant here
        if (hi is not None and hi < wlo) or (lo is not None and lo > whi):
            return
        out.append({'Kind': kind, 'Where': where, 'Detail': detail,
                    'AffectedFrom': '' if lo is None else round(lo, 1),
                    'AffectedTo': '' if hi is None else round(hi, 1)})

    oe, ne = old['entries'], new['entries']
    for k in sorted(set(ne) - set(oe)):
        lo, hi = span_of(ne[k]['ranges'])
        add('ENTRY ADDED', k, f"{ne[k]['ranges'][0][2]} ; {ne[k]['area']} km2 ; {len(ne[k]['ranges'])} date-range(s)", lo, hi)
    for k in sorted(set(oe) - set(ne)):
        lo, hi = span_of(oe[k]['ranges'])
        add('ENTRY REMOVED', k, f"{oe[k]['ranges'][0][2]} ; was {oe[k]['area']} km2", lo, hi)
    for k in sorted(set(oe) & set(ne)):
        a, b = oe[k], ne[k]
        ra = {range_tuple(r) for r in a['ranges']}
        rb = {range_tuple(r) for r in b['ranges']}
        for r in sorted(ra - rb):
            add('RANGE REMOVED/EDITED', k, f"{r[0]:g}..{r[1]:g} '{r[2]}' color {r[3]}", r[0], r[1])
        for r in sorted(rb - ra):
            add('RANGE ADDED/EDITED', k, f"{r[0]:g}..{r[1]:g} '{r[2]}' color {r[3]}", r[0], r[1])
        lo, hi = span_of(b['ranges'])
        if a['polyrefs'] != b['polyrefs']:
            add('GEOMETRY CHANGED (polyRefs)', k, f"{a['polyrefs'][:70]} -> {b['polyrefs'][:70]}", lo, hi)
        if a['area'] and abs(b['area'] - a['area']) / a['area'] > 0.01:
            add('AREA CHANGED', k, f"{a['area']} -> {b['area']} km2 ({(b['area']-a['area'])/a['area']*100:+.1f}%)", lo, hi)
        if a['areaType'] != b['areaType']:
            add('AREATYPE CHANGED', k, f"{a['areaType']} -> {b['areaType']}", lo, hi)
        for fld, lab in (('selfIntersecting', 'self-intersecting ring'), ('flipFixable', 'flip-fixable border')):
            if a[fld] != b[fld]:
                add('RING SUSPECT ' + ('NEW' if b[fld] else 'CLEARED'), k, lab, lo, hi)

    op, np_ = old['pairs'], new['pairs']
    def wspan(p):
        w = p['windows']
        return (min(x[0] for x in w), max(x[1] for x in w)) if w else (None, None)
    def wtxt(p):
        return '; '.join(f'{x[0]:g}..{x[1]:g}' for x in p['windows'])
    for k in sorted(set(np_) - set(op)):
        p = np_[k]; lo, hi = wspan(p)
        add('OVERLAP NEW', k, f"{p['aName']} / {p['bName']} : {p['relation']} {p['pctA']:.0f}%/{p['pctB']:.0f}% during {wtxt(p)}", lo, hi)
    for k in sorted(set(op) - set(np_)):
        p = op[k]; lo, hi = wspan(p)
        add('OVERLAP GONE', k, f"{p['aName']} / {p['bName']} : was {p['relation']} during {wtxt(p)}", lo, hi)
    for k in sorted(set(op) & set(np_)):
        a, b = op[k], np_[k]
        if a['windows'] != b['windows'] or abs(a['pctA'] - b['pctA']) > 1 or abs(a['pctB'] - b['pctB']) > 1:
            lo = min(wspan(a)[0], wspan(b)[0]); hi = max(wspan(a)[1], wspan(b)[1])
            add('OVERLAP CHANGED', k, f"{b['aName']} / {b['bName']} : {wtxt(a)} ({a['pctA']:.0f}%/{a['pctB']:.0f}%) -> "
                                       f"{wtxt(b)} ({b['pctA']:.0f}%/{b['pctB']:.0f}%)", lo, hi)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=['snapshot', 'diff'])
    ap.add_argument('--tiles', nargs='+', default=DEFAULT_TILES)
    ap.add_argument('--from', dest='from_year', type=float, default=-1200.0)
    ap.add_argument('--to', dest='to_year', type=float, default=-800.0)
    ap.add_argument('--label', default='palestine')
    ap.add_argument('--since', type=float, default=-1e9, help='only report effects reaching this year or later')
    ap.add_argument('--against', help='snapshot file to compare with (default: <label>_latest.json)')
    ap.add_argument('--accept', action='store_true', help='after diff: save the current state as the new baseline')
    a = ap.parse_args()
    args = SimpleNamespace(tiles=a.tiles, from_year=a.from_year, to_year=a.to_year, label=a.label,
                           include_blobs=True, max_area=DEFAULT_MAX_AREA)

    if a.command == 'snapshot':
        state = capture(args)
        path = save(state, a.label)
        print(f"Snapshot saved: {len(state['entries'])} entries, {len(state['pairs'])} overlap pairs "
              f"-> {path} (also {snap_paths(a.label)})")
        return

    base = a.against or snap_paths(a.label)
    if not os.path.exists(base):
        print(f"No baseline at {base} -- run 'snapshot' first.")
        sys.exit(1)
    old = json.load(open(base, encoding='utf-8'))
    new = capture(args)
    print(f"Baseline: {old['created']}   Now: {new['created']}"
          + (f"   (effects reaching {a.since:g} or later)" if a.since > -1e8 else ''))
    changed_files = [os.path.relpath(p, DATA_DIR) for p, m in new['files'].items()
                     if m != old['files'].get(p)]
    print("Source files modified since baseline:", ', '.join(changed_files) if changed_files else '(none)')

    res = compare(old, new, a.since)
    out = os.path.join(EXPORTS, f'overlay_diff_{a.label}.csv')
    if res:
        with open(out, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=list(res[0].keys()))
            w.writeheader(); w.writerows(res)
    from collections import Counter
    if not res:
        print("No differences.")
    else:
        print(f"{len(res)} difference(s): " + ', '.join(f"{n} {k}" for k, n in sorted(Counter(r['Kind'] for r in res).items())))
        for r in sorted(res, key=lambda r: (r['Kind'].startswith('OVERLAP') is False, r['AffectedFrom'] if r['AffectedFrom'] != '' else -1e9)):
            span = f"{r['AffectedFrom']}..{r['AffectedTo']}" if r['AffectedFrom'] != '' else ''
            print(f"  [{r['Kind']}] {r['Where']}  {span}\n      {r['Detail'][:170]}")
        print(f"Wrote {out}")
    if a.accept:
        path = save(new, a.label)
        print(f"Baseline updated -> {path}")


if __name__ == '__main__':
    main()
