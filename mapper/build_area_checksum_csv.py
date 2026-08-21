"""
build_area_checksum_csv.py
Builds a "flattened tree" CSV for manually verifying in Excel that a parent
polity's Area equals the sum of its children's Area, for one snapshot year.

Input is a GeoJSON snapshot already produced by export_master.py, e.g.:
  python export_master.py --from-year -500 --to-year -500 --type POLITY --type TRIBAL_AREA --out exports/snapshot_-500.geojson
  python build_area_checksum_csv.py --in exports/snapshot_-500.geojson --out exports/area_checksum_-500.csv

Parent/child edges are derived from each row's FullPath (added 2026-08-21
specifically to make this unambiguous -- MemberOf alone collides wherever the
same name repeats at adjacent nesting depths, e.g. the Persian Empire's
"Egypt > Egypt > Egypt" chain). A row is the direct parent of another iff the
child's FullPath equals the parent's FullPath plus " - " plus the child's own
Name -- computed via string suffix matching on FullPath itself (not by
re-splitting it), so it stays correct even in the hypothetical case of a
single segment name that itself contained the literal " - " delimiter.

Output layout: one row per node in the tree (not just leaves), with
Level1 Name/Area .. LevelN Name/Area filled from the root down to that row's
own depth and left blank beyond it. `ID` is that row's own Index in the
input snapshot. N is computed dynamically from the deepest chain actually
present in the snapshot.
"""

import os
import json
import csv
import argparse

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(MAPPER_DIR, 'exports', 'area_checksum.csv')


def load_rows(path):
    with open(path, encoding='utf-8') as f:
        fc = json.load(f)
    return [feat['properties'] for feat in fc['features']]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--in', dest='in_path', required=True, help='GeoJSON snapshot from export_master.py')
    ap.add_argument('--out', default=DEFAULT_OUT)
    args = ap.parse_args()

    rows = load_rows(args.in_path)
    by_fullpath = {}
    for p in rows:
        by_fullpath.setdefault(p['FullPath'], []).append(p)

    # child_index[parent_FullPath] = [child_row, ...] -- direct children only.
    child_index = {}
    roots = []
    orphan_roots = 0  # children whose parent NAME exists in the chain, but has no active row this year
    for p in rows:
        fp = p['FullPath']
        if fp == p['Name']:
            roots.append(p)
            continue
        suffix = ' - ' + p['Name']
        if not fp.endswith(suffix):
            # Shouldn't happen given how FullPath is constructed, but don't
            # silently misfile it as a root if it does -- surface it instead.
            print(f"  WARNING: FullPath {fp!r} doesn't end with \" - {p['Name']}\" as expected; treating as root")
            roots.append(p)
            continue
        parent_fp = fp[:-len(suffix)]
        if parent_fp in by_fullpath:
            child_index.setdefault(parent_fp, []).append(p)
        else:
            # This entity's ancestor chain has a gap at this specific year --
            # the parent name exists structurally but has no row active in
            # this snapshot (its own date-slicing didn't cover this year even
            # though this child's did). Surfaced as its own root so it's
            # still visible in the output rather than silently dropped.
            orphan_roots += 1
            roots.append(p)

    def depth(p):
        return p['FullPath'].count(' - ') + 1

    max_depth = max((depth(p) for p in rows), default=0)
    print(f"{len(rows)} rows, {len(roots)} root row(s) ({orphan_roots} of those are parent-missing-this-year "
          f"orphans, not true top-level polities), max depth {max_depth}.")

    header = ['ID']
    for lvl in range(1, max_depth + 1):
        header += [f'Level{lvl} Name', f'Level{lvl} Area']

    rows_written = 0
    with open(args.out, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(header)

        def emit(node, ancestors):
            nonlocal rows_written
            out = [node['Index']]
            for name, area in ancestors:
                out += [name, area]
            out += [node['Name'], node['Area']]
            out += ['', ''] * (max_depth - len(ancestors) - 1)
            w.writerow(out)
            rows_written += 1
            for kid in sorted(child_index.get(node['FullPath'], []), key=lambda r: r['Name']):
                emit(kid, ancestors + [(node['Name'], node['Area'])])

        for root in sorted(roots, key=lambda r: r['Name']):
            emit(root, [])

    print(f"Wrote {rows_written} rows to {args.out}")


if __name__ == '__main__':
    main()
