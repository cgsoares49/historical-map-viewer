#!/usr/bin/env python3
"""
borders_sheet_sync.py -- compare the POL file of a tile with the 'borders' sheet of  C:\\My stuff\\VID\\ancient index.xlsx  and print what the
sheet needs (the POL file always wins; the workbook is only read).

    python borders_sheet_sync.py --tile 120/040 [--date 2026-10-22] [--reason "overlay fix"]

For every POL of the tile:
  * no sheet row and POL number above the sheet's last row -> NEW ROW (paste-ready line in borders_sheet_sync_<tile>.tsv, columns A..AK);
    if the POL is the tail of a split (same date ranges as another POL, which ends where it starts) the row says 'split from #parent';
  * sheet row exists but vertex count / stop point differ -> PARENT EDIT (new F, I, J) plus the split note
    'split m/d/yy for <reason>: #p => p, c1[, c2...]' for the first open cell from Q rightwards;
  * everything else is left alone; POLs numbered at or below the sheet's last row but missing from it are only listed.
Column layout (from the sheet): A id (A1 = last id), B date, C 'POLBND', D tile, E POL#, F vertices, G,H start lon/lat, I,J stop lon/lat,
K..N and T..AK draw-window years (the POL's date ranges without the -9998..-9997 sentinel), O description, P notes.
"""
import argparse
import datetime
import os
import sys

import openpyxl
from openpyxl.utils import get_column_letter as COL

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export_polity_polygons as X

WB = r'C:\My stuff\VID\ancient index.xlsx'
HERE = os.path.dirname(os.path.abspath(__file__))
NCOL = 37
WINDOW_COLS = [10, 11, 12, 13] + list(range(19, 37))      # K..N, T..AK (0-based)


def fmt(v):
    if v is None:
        return ''
    if isinstance(v, float):
        return ('%.5f' % v).rstrip('0').rstrip('.')
    if hasattr(v, 'strftime'):
        return v.strftime('%Y-%m-%d')
    return str(v)


def close(a, b, tol=2e-4):
    return a is not None and b is not None and abs(float(a) - float(b)) < tol


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tile', required=True, help='as in the sheet, e.g. 120/040')
    ap.add_argument('--date', default=datetime.date.today().isoformat())
    ap.add_argument('--reason', default='overlay fix')
    ap.add_argument('--workbook', default=WB)
    a = ap.parse_args()
    lat, lon = a.tile.split('/')
    d = datetime.date.fromisoformat(a.date)
    md = f'{d.month}/{d.day}/{d.year % 100}'

    t = X.load_tile(lat, lon)
    pol = t['pol_by_index']
    wb = openpyxl.load_workbook(a.workbook, read_only=True, data_only=True)
    rows = [list(r) + [None] * (NCOL - len(r)) for r in wb['borders'].iter_rows(values_only=True)]
    counter = int(rows[0][0])
    sheet = {}
    for i, r in enumerate(rows):
        if i > 0 and r[3] == a.tile and isinstance(r[4], (int, float)):
            sheet[int(r[4])] = (i, r)
    last_no = max(sheet)
    last_row = sheet[last_no][0] + 1
    print(f'sheet: {len(sheet)} rows for {a.tile}, last POL {last_no} (Excel row {last_row}); POL file: {len(pol)} POLs, last {max(pol)}; A1 = {counter}')

    def ranges_of(n):
        return [(round(x, 1), round(y, 1)) for x, y in pol[n]['dateRanges']]

    def windows(n):
        return [(x, y) for x, y in ranges_of(n) if not (x == -9998.0 and y == -9997.0)]

    new = [n for n in sorted(pol) if n not in sheet and n > last_no]
    unlogged = [n for n in sorted(pol) if n not in sheet and n <= last_no]
    by_start = {}
    for n in pol:
        pts = pol[n]['points']
        if pts:
            by_start.setdefault((round(pts[0][0], 4), round(pts[0][1], 4)), []).append(n)

    def parent_of(n):
        pts = pol[n]['points']
        # a POL p whose LAST point is this POL's FIRST point and which has identical date ranges
        cands = []
        for p in pol:
            if p == n or not pol[p]['points']:
                continue
            e = pol[p]['points'][-1]
            if close(e[0], pts[0][0], 1e-5) and close(e[1], pts[0][1], 1e-5) and ranges_of(p) == ranges_of(n) and p < n:
                cands.append(p)
        return max(cands) if cands else None            # the nearest older piece (chain: c2's parent is c1)

    def root_of(n):
        seen = set()
        while n in new and n not in seen:
            seen.add(n)
            p = parent_of(n)
            if p is None:
                return n
            n = p
        return n

    children = {}
    for n in new:
        p = parent_of(n)
        if p is not None:
            children.setdefault(root_of(n), []).append(n)
    for k in children:
        children[k].sort()

    out_rows, edits, notes = [], [], []
    for n in new:
        counter += 1
        pts = pol[n]['points']
        p = parent_of(n)
        r = [None] * NCOL
        r[0], r[1], r[2], r[3], r[4] = counter, d, 'POLBND', a.tile, n
        r[5] = len(pts)
        r[6], r[7], r[8], r[9] = pts[0][0], pts[0][1], pts[-1][0], pts[-1][1]
        flat = [v for w in windows(n) for v in w]
        for col, v in zip(WINDOW_COLS, flat):
            r[col] = v
        r[14] = '(' + a.reason + ')'
        r[15] = f'split from #{root_of(n)}' if p is not None else None
        if p is None:
            notes.append(f'POL {n}: no parent found (not a split?) -- row has no description/notes')
        out_rows.append(r)

    # parent rows whose stored count / stop differ from the POL file
    for n, (i, r) in sorted(sheet.items()):
        if n not in pol:
            notes.append(f'POL {n}: in the sheet but NOT in the POL file')
            continue
        pts = pol[n]['points']
        diffs = []
        if r[5] != len(pts):
            diffs.append(f'F{i + 1}: {fmt(r[5])} -> {len(pts)}')
        if not (close(r[8], pts[-1][0]) and close(r[9], pts[-1][1])):
            diffs.append(f'I{i + 1}/J{i + 1}: {fmt(r[8])}, {fmt(r[9])} -> {fmt(pts[-1][0])}, {fmt(pts[-1][1])}')
        if not diffs:
            continue
        kids = children.get(n)
        note = None
        if kids:
            pos = next((k for k in range(16, 19) if r[k] is None), None)
            txt = f'split {md} for {a.reason}: #{n} => {n}, ' + ', '.join(str(k) for k in kids)
            note = (f'{COL(pos + 1)}{i + 1} = "{txt}"' if pos is not None else f'NOTE "{txt}" -> Q..S taken, decide where it goes')
        edits.append((n, i + 1, diffs, note))

    base = f'borders_sheet_sync_{a.tile.replace("/", "-")}'
    os.makedirs(os.path.join(HERE, 'exports'), exist_ok=True)
    with open(os.path.join(HERE, 'exports', base + '.tsv'), 'w', encoding='utf-8', newline='') as f:
        for r in out_rows:
            f.write('\t'.join(fmt(v) for v in r) + '\n')
    L = [f'BORDERS SHEET sync for tile {a.tile}, {a.date}   (POL file wins; workbook only read: {a.workbook})', '',
         f'1) NEW ROWS: {len(out_rows)} lines in exports/{base}.tsv (columns A..AK), POL {new[0] if new else "-"}..{new[-1] if new else "-"}. '
         f'Insert after Excel row {last_row} (POL {last_no}), in order. A1: {int(rows[0][0])} -> {counter}', '',
         f'2) PARENT ROW EDITS ({len(edits)}): Excel row, cell: old -> new, then the split note']
    for n, row, diffs, note in edits:
        L.append(f'   POL {n:>4} (row {row}): ' + '; '.join(diffs) + (f';  {note}' if note else '   [no new child POL found: changed by hand?]'))
    if unlogged:
        L += ['', f'3) POLs in the file but not in the sheet, numbered BELOW its last row (old, unlogged; left out): {unlogged[:40]}']
    if notes:
        L += ['', 'NOTES:'] + ['   ' + x for x in notes]
    L += ['', '4) NEW ROW PREVIEW (A..P):']
    for r in out_rows:
        flat = [fmt(r[c]) for c in WINDOW_COLS if r[c] is not None]
        L.append('   ' + ' | '.join(fmt(v) for v in r[:16]) + '   windows: ' + ', '.join(flat))
    open(os.path.join(HERE, 'exports', base + '.txt'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print('\n'.join(L[:12 + len(edits)]))
    print(f'... wrote exports\\{base}.tsv and .txt')


if __name__ == '__main__':
    main()
