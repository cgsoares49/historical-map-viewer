"""
merge_into_master.py
Upserts one polity export's rows into the cumulative master dataset, stored
as newline-delimited GeoJSON (one Feature-as-JSON per line) at
mapper/exports/cliopatria_master.geojsonl.

Why newline-delimited instead of one big FeatureCollection array: every
upsert into a single JSON array means reading, parsing, and rewriting the
*entire* file. One-Feature-per-line stays append/stream-friendly (this
script never holds more than one line at a time in memory while filtering),
is directly grep/jq-able, and diffs sanely in git (one row changed = one
line changed, not a reformatted array).

Upsert semantics: every line whose SourceRun property equals --polity is
removed (streamed to a temp file, never loaded as a full list), then the
fresh rows from --geojson are appended, and the temp file atomically
replaces the master. This makes re-running a polity idempotent -- it
replaces that polity's own rows without touching any other polity's lines,
and without needing any cross-row deduplication logic.

The .geojsonl master itself is an internal working format, never sent to a
collaborator directly -- see export_master.py for producing a conventional
.geojson/.csv deliverable (optionally filtered) from it.

Usage:
  python export_polity_polygons.py --polity "Foo" --auto-tiles --out exports/_tmp_foo.geojson
  python merge_into_master.py --polity "Foo" --geojson exports/_tmp_foo.geojson
"""

import os
import sys
import json
import argparse
import tempfile

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MASTER = os.path.join(MAPPER_DIR, 'exports', 'cliopatria_master.geojsonl')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--polity', required=True,
                     help='SourceRun value to upsert -- must match the --polity used to generate --geojson')
    ap.add_argument('--geojson', required=True,
                     help='Path to the freshly generated GeoJSON FeatureCollection to merge in')
    ap.add_argument('--master', default=DEFAULT_MASTER)
    args = ap.parse_args()

    with open(args.geojson, encoding='utf-8') as f:
        fc = json.load(f)
    new_features = fc['features']

    for feat in new_features:
        source_run = feat.get('properties', {}).get('SourceRun')
        if source_run != args.polity:
            print(f"ERROR: feature with SourceRun={source_run!r} does not match "
                  f"--polity {args.polity!r} -- refusing to merge (wrong file, or "
                  f"the export was run with a different --polity value).", file=sys.stderr)
            sys.exit(1)

    master_dir = os.path.dirname(args.master) or '.'
    os.makedirs(master_dir, exist_ok=True)

    removed = 0
    tmp_fd, tmp_path = tempfile.mkstemp(dir=master_dir, suffix='.geojsonl.tmp')
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as tmp_f:
            if os.path.exists(args.master):
                with open(args.master, encoding='utf-8') as f:
                    for line in f:
                        stripped = line.strip()
                        if not stripped:
                            continue
                        obj = json.loads(stripped)
                        if obj.get('properties', {}).get('SourceRun') == args.polity:
                            removed += 1
                            continue
                        tmp_f.write(stripped + '\n')
            for feat in new_features:
                tmp_f.write(json.dumps(feat, ensure_ascii=False) + '\n')
        os.replace(tmp_path, args.master)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    print(f"Master: removed {removed} old line(s) for {args.polity!r}, added {len(new_features)} new line(s).")

    total = 0
    with open(args.master, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                total += 1
    print(f"Master now has {total} total line(s) at {args.master}")


if __name__ == '__main__':
    main()
