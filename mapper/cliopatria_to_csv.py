"""
cliopatria_to_csv.py
Streams the user's downloaded Cliopatria/Seshat reference export
(C:\\my stuff\\cliopatria\\cliopatria_polities_only.geojson.txt -- confirmed
one Feature per line, ~165MB/13,772 features) into a plain CSV for a quick
coverage skim in Excel, without needing GIS software or a full-file JSON
parse.

Only lines starting with '{' are treated as Feature objects (skips the
FeatureCollection wrapper's opening/closing lines); a trailing comma, if
present, is stripped before parsing each line as JSON.

Usage:
  python cliopatria_to_csv.py
  python cliopatria_to_csv.py --source "C:\\my stuff\\cliopatria\\cliopatria_polities_only.geojson.txt" --out exports/cliopatria_reference.csv
"""

import os
import json
import csv
import argparse

from shapely.geometry import shape

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SOURCE = r'C:\my stuff\cliopatria\cliopatria_polities_only.geojson.txt'
DEFAULT_OUT = os.path.join(MAPPER_DIR, 'exports', 'cliopatria_reference.csv')

PROP_COLS = ['Name', 'FromYear', 'ToYear', 'Area', 'Type', 'Wikipedia', 'Wikidata',
             'SeshatID', 'Components', 'MemberOf']


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--source', default=DEFAULT_SOURCE)
    ap.add_argument('--out', default=DEFAULT_OUT)
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    feature_count = 0
    skipped = 0
    with open(args.source, encoding='utf-8') as fin, \
         open(args.out, 'w', newline='', encoding='utf-8') as fout:
        w = csv.writer(fout)
        w.writerow(PROP_COLS + ['CentroidLon', 'CentroidLat'])
        for line in fin:
            stripped = line.strip()
            if not stripped.startswith('{'):
                continue
            if stripped.endswith(','):
                stripped = stripped[:-1]
            try:
                feat = json.loads(stripped)
            except json.JSONDecodeError:
                skipped += 1
                continue
            p = feat.get('properties', {})
            geom = feat.get('geometry')
            lon, lat = ('', '')
            if geom:
                try:
                    c = shape(geom).centroid
                    lon, lat = round(c.x, 4), round(c.y, 4)
                except Exception:
                    pass
            w.writerow([p.get(c, '') for c in PROP_COLS] + [lon, lat])
            feature_count += 1
            if feature_count % 2000 == 0:
                print(f"  ...{feature_count} features written")

    print(f"Wrote {feature_count} rows to {args.out} ({skipped} unparseable line(s) skipped)")


if __name__ == '__main__':
    main()
