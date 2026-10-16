#!/usr/bin/env python3
"""
audit_registry_exclusions.py
Which areaType=1 entries does find_polity_overlays.load_candidates silently drop because the
Ancient Index registry says they are a "known transient" (is_known_transient)?  The POL-number
rule has no size / richness gate (found 2026-10-15: 120/035 #192 Israelites, 9409 km2, dropped
because it shares POL233/234 with logged transients), so big real polities can vanish from the
overlap detector.

READ-ONLY.  Writes exports/registry_exclusion_audit.csv, one row per dropped entry:
  Tile, EntryIndex, Name (longest-lived owner), AreaKm2, DateRanges, LifeFrom, LifeTo, LifeYears,
  Rule (POL / DATE / BOTH), PolHits (the POL numbers that matched), Suspicion (HIGH/MED/LOW + why)
and, with --check-impact, ImpactEvents = number of overlap events the entry would take part in
if it were kept (scan_tile re-run with the registry test bypassed for the flagged entries of that tile).

  python audit_registry_exclusions.py                    # all tiles
  python audit_registry_exclusions.py --tiles 120:035    # a few tiles
  python audit_registry_exclusions.py --check-impact     # also count the overlaps each would join
"""
import os
import sys
import csv
import argparse
import contextlib
import io

import find_polity_overlays as fpo
from find_polity_overlays import (
    is_transient, is_keyword_transient, is_placeholder_entry, is_semitransient_entry,
    is_known_transient, load_transient_registry, discover_all_tiles, scan_tile,
    DEFAULT_MIN_OVERLAP_RATIO, MAX_DATE_RANGES_FOR_FALLBACK,
)
from export_polity_polygons import (
    load_tile, build_combined_ring, ring_to_polygon, TO_EQUAL_AREA, owner_name,
)
from shapely.ops import transform

EXPORTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'exports')


def area_km2(entry, tile):
    ring, has_seg = build_combined_ring(entry['polyRefs'], tile['cst_by_index'], tile['pol_by_index'])
    if not has_seg or len(ring) < 4:
        return None
    try:
        poly = ring_to_polygon(ring, [0])
        if poly is None or poly.is_empty or not poly.is_valid:
            return None
        return transform(TO_EQUAL_AREA, poly).area / 1e6
    except Exception:
        return None


def longest_owner(entry):
    best = max(entry['dateRanges'], key=lambda d: d['to'] - d['from'])
    return owner_name(best['name'])


def which_rule(tile_key, entry, pol_registry, date_registry):
    pol_hits = pol_registry.get(tile_key) or {}
    hits = sorted({pi - 1000 for pi, fl in entry['polyRefs'] if pi > 1000 and (pi - 1000) in pol_hits})
    date_hit = False
    if len(entry['dateRanges']) <= MAX_DATE_RANGES_FOR_FALLBACK:
        for s, e, _d in date_registry.get(tile_key, []):
            lo, hi = s - 1.0, e + 1.0
            if any(lo <= dr['from'] and dr['to'] <= hi for dr in entry['dateRanges']):
                date_hit = True
                break
    if hits and date_hit:
        return 'BOTH', hits
    if hits:
        return 'POL', hits
    return 'DATE', hits


def suspicion(area, nranges, life):
    why = []
    if area is not None and area >= 1000:
        why.append(f'area {area:,.0f} km2')
    if nranges > MAX_DATE_RANGES_FOR_FALLBACK:
        why.append(f'{nranges} date ranges')
    if life >= 30:
        why.append(f'lives {life:.0f}y')
    if len(why) >= 2 or (area is not None and area >= 5000):
        return 'HIGH: ' + ', '.join(why)
    if why:
        return 'MED: ' + ', '.join(why)
    return 'LOW'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tiles', nargs='+', help='lat:lon pairs (default: every populated tile)')
    ap.add_argument('--check-impact', action='store_true',
                    help='re-run the overlap scan per affected tile with the flagged entries kept')
    a = ap.parse_args()
    registry = load_transient_registry()
    pol_registry, date_registry = registry
    tiles = [tuple(t.split(':')) for t in a.tiles] if a.tiles else discover_all_tiles()
    rows = []
    n_tiles = 0
    for lat, lon in tiles:
        n_tiles += 1
        key = f'{lat}/{lon}'
        if key not in pol_registry and key not in date_registry:
            continue                       # no logged transients here => nothing can be dropped
        try:
            tile = load_tile(lat, lon)
        except Exception as ex:
            print(f'  {key}: load failed ({ex})', file=sys.stderr)
            continue
        flagged = []
        for e in tile['par_entries']:
            if e['areaType'] != 1 or not e['polyRefs'] or not e['dateRanges']:
                continue
            if is_semitransient_entry(e):
                continue
            if is_transient(e['polyRefs'], tile['pol_by_index']) or \
                    any(is_keyword_transient(d['name']) for d in e['dateRanges']):
                continue
            if is_placeholder_entry(e):
                continue
            if not is_known_transient(key, e, pol_registry, date_registry):
                continue
            rule, hits = which_rule(key, e, pol_registry, date_registry)
            ar = area_km2(e, tile)
            lf = min(d['from'] for d in e['dateRanges'])
            lt = max(d['to'] for d in e['dateRanges'])
            rows.append({
                'Tile': key, 'EntryIndex': e['entryIndex'], 'Name': longest_owner(e),
                'AreaKm2': '' if ar is None else round(ar, 1), 'DateRanges': len(e['dateRanges']),
                'LifeFrom': lf, 'LifeTo': lt, 'LifeYears': round(lt - lf, 1), 'Rule': rule,
                'PolHits': ' '.join(f'POL{h}' for h in hits),
                'Suspicion': suspicion(ar, len(e['dateRanges']), lt - lf), 'ImpactEvents': '',
            })
            flagged.append(e['entryIndex'])
        if flagged and a.check_impact:
            forced = {(key, i) for i in flagged}
            orig = fpo.is_known_transient
            fpo.is_known_transient = lambda tk, ent, *r, **kw: False if (tk, ent['entryIndex']) in forced \
                else orig(tk, ent, *r, **kw)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    _, events = scan_tile(lat, lon, DEFAULT_MIN_OVERLAP_RATIO, *registry)
            finally:
                fpo.is_known_transient = orig
            for r in rows:
                if r['Tile'] == key:
                    r['ImpactEvents'] = sum(1 for ev in events
                                            if (lat, lon, r['EntryIndex']) in (ev['a'], ev['b']))
        if n_tiles % 200 == 0:
            print(f'  ... {n_tiles}/{len(tiles)} tiles, {len(rows)} dropped entries so far', flush=True)

    rows.sort(key=lambda r: (r['Suspicion'][:4] != 'HIGH', r['Suspicion'][:3] != 'MED',
                             -(r['AreaKm2'] or 0)))
    os.makedirs(EXPORTS, exist_ok=True)
    out = os.path.join(EXPORTS, 'registry_exclusion_audit.csv')
    with open(out, 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ['Tile'])
        w.writeheader()
        w.writerows(rows)
    hi = sum(1 for r in rows if r['Suspicion'].startswith('HIGH'))
    me = sum(1 for r in rows if r['Suspicion'].startswith('MED'))
    print(f'{len(tiles)} tiles scanned; {len(rows)} entries dropped by the registry rule '
          f'(HIGH {hi}, MED {me}, LOW {len(rows) - hi - me})')
    print(f'by rule: ' + ', '.join(f'{k} {sum(1 for r in rows if r["Rule"] == k)}' for k in ('POL', 'DATE', 'BOTH')))
    print(f'Wrote {out}')


if __name__ == '__main__':
    main()
