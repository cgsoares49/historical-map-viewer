"""
export_master.py
Reads mapper/exports/cliopatria_master.geojsonl (the internal, append-friendly
working store built by merge_into_master.py) and writes a conventional GeoJSON
FeatureCollection + truncated-WKT CSV -- optionally filtered to a right-sized
subset. This is what actually gets handed to a collaborator (Bennett, Nono,
etc) or dropped into QGIS/converted to KML -- the .geojsonl master itself is
never sent externally.

Filters are all optional and combinable (AND'd together):
  --name "Lucanians"                         (repeatable -- OR'd within this filter; a
                                               row's own Name, regardless of which
                                               SourceRun/parent produced it -- use this to
                                               find every appearance of an entity that
                                               only ever shows up nested under whichever
                                               different top-level polities happened to
                                               touch it, e.g. a tribe that was a Roman
                                               ally in one period and independent/allied
                                               with someone else in another)
  --type POLITY|TRANSIENT|TRIBAL_AREA|CITY   (repeatable -- OR'd within this filter)
  --source-run "Roman Republic"              (repeatable -- OR'd within this filter;
                                               the top-level --polity name a row came from)
  --from-year / --to-year                    (keep rows whose [FromYear,ToYear] overlaps
                                               this range)
  --bbox MINLON MINLAT MAXLON MAXLAT         (keep rows whose geometry's bounding box
                                               intersects this box)

`Index` is renumbered sequentially (1..N) across whatever the filters keep --
the master's own per-row Index values come from independent per-polity runs
and are not globally unique, so they're only meaningful in the delivered
subset, not in the master itself.

Usage:
  python export_master.py --out exports/full_dataset.geojson
  python export_master.py --source-run "Roman Republic" --out exports/rr_only.geojson
  python export_master.py --type TRANSIENT --out exports/all_transients.geojson
  python export_master.py --from-year -300 --to-year -250 --out exports/mid_republic.geojson
  python export_master.py --name "Lucanians" --out exports/lucanians_everywhere.geojson
"""

import os
import json
import csv
import argparse

from shapely.geometry import shape

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MASTER = os.path.join(MAPPER_DIR, 'exports', 'cliopatria_master.geojsonl')

PROP_COLS = ['Index', 'Name', 'FromYear', 'ToYear', 'Area', 'Type', 'References', 'MemberOf',
             'FullPath', 'Region', 'Subregion', 'ColorR', 'ColorG', 'ColorB', 'Generated',
             'SourceRun', 'OverlapNote']
WKT_TRUNCATE = 60


def passes_filters(feat, name_set, type_set, source_set, from_year, to_year, bbox):
    p = feat['properties']
    if name_set and p.get('Name') not in name_set:
        return False
    if type_set and p.get('Type') not in type_set:
        return False
    if source_set and p.get('SourceRun') not in source_set:
        return False
    if from_year is not None and p.get('ToYear', float('inf')) < from_year:
        return False
    if to_year is not None and p.get('FromYear', float('-inf')) > to_year:
        return False
    if bbox is not None:
        minlon, minlat, maxlon, maxlat = bbox
        gminx, gminy, gmaxx, gmaxy = shape(feat['geometry']).bounds
        if gmaxx < minlon or gminx > maxlon or gmaxy < minlat or gminy > maxlat:
            return False
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--master', default=DEFAULT_MASTER)
    ap.add_argument('--out', required=True, help='Output .geojson path; a sibling .csv is written alongside it')
    ap.add_argument('--name', action='append', default=None,
                     help='Keep only rows with this exact Name, regardless of SourceRun/MemberOf; repeatable')
    ap.add_argument('--type', action='append', default=None, help='Keep only this Type; repeatable')
    ap.add_argument('--source-run', action='append', default=None, dest='source_run',
                     help='Keep only this SourceRun (top-level polity name); repeatable')
    ap.add_argument('--from-year', type=float, default=None)
    ap.add_argument('--to-year', type=float, default=None)
    ap.add_argument('--bbox', nargs=4, type=float, default=None, metavar=('MINLON', 'MINLAT', 'MAXLON', 'MAXLAT'))
    args = ap.parse_args()

    name_set = set(args.name) if args.name else None
    type_set = set(args.type) if args.type else None
    source_set = set(args.source_run) if args.source_run else None

    features = []
    total_lines = 0
    if os.path.exists(args.master):
        with open(args.master, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total_lines += 1
                feat = json.loads(line)
                if passes_filters(feat, name_set, type_set, source_set, args.from_year, args.to_year, args.bbox):
                    features.append(feat)
    print(f"Scanned {total_lines} master line(s), kept {len(features)} after filters.")

    for idx, feat in enumerate(features, start=1):
        feat['properties']['Index'] = idx

    fc = {'type': 'FeatureCollection', 'features': features}
    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(fc, f, ensure_ascii=False)
    print(f"Wrote {len(features)} feature(s) to {args.out}")

    out_csv = os.path.splitext(args.out)[0] + '.csv'
    with open(out_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(PROP_COLS + ['geometry'])
        for feat in features:
            p = feat['properties']
            wkt = shape(feat['geometry']).wkt
            if len(wkt) > WKT_TRUNCATE:
                wkt = wkt[:WKT_TRUNCATE] + '…'
            w.writerow([p.get(c, '') for c in PROP_COLS] + [wkt])
    print(f"Wrote {len(features)} row(s) to {out_csv}")


if __name__ == '__main__':
    main()
