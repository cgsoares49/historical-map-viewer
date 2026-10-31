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
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) < tol
    except ValueError:   # text cell (e.g. 'lon  lat' pasted into one cell): counts as a mismatch
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tile', required=True, help='as in the sheet, e.g. 120/040')
    ap.add_argument('--date', default=datetime.date.today().isoformat())
    ap.add_argument('--reason', default='overlay fix')
    ap.add_argument('--workbook', default=WB)
    ap.add_argument('--first-id', type=int, default=None, help='column-A number of the first new row (overrides the workbook A1, which lags unsaved pastes)')
    a = ap.parse_args()
    lat, lon = a.tile.split('/')
    d = datetime.date.fromisoformat(a.date)
    md = f'{d.month}/{d.day}/{d.year % 100}'

    t = X.load_tile(lat, lon)
    # POLs whose first date range is the sentinel (-9999, -9998) are TRANSIENT / blob borders: they are logged on the 'transients' and
    # 'tribal dots' sheets, never on 'borders' (whose POLs start with the sentinel (-9998, -9997)).  Only real borders are synced.
    all_pol = t['pol_by_index']
    pol = {n: p for n, p in all_pol.items() if not (p['dateRanges'] and tuple(p['dateRanges'][0]) == (-9999.0, -9998.0))}
    n_trans = len(all_pol) - len(pol)
    import json
    ign_path = os.path.join(HERE, 'borders_sheet_ignore.json')
    ignore = {int(k) for k in json.load(open(ign_path, encoding='utf-8')).get(a.tile, {})} if os.path.exists(ign_path) else set()
    def modern(p):
        rs = [r for r in p['dateRanges'] if tuple(r) != (-9998.0, -9997.0)]
        return bool(rs) and all(r[0] >= 1900 for r in rs)
    pol = {n: p for n, p in pol.items() if n not in ignore and not modern(p)}
    wb = openpyxl.load_workbook(a.workbook, read_only=True, data_only=True)
    rows = [list(r) + [None] * (NCOL - len(r)) for r in wb['borders'].iter_rows(values_only=True)]
    counter = int(rows[0][0]) if a.first_id is None else a.first_id - 1
    sheet = {}
    for i, r in enumerate(rows):
        if i > 0 and r[3] == a.tile and isinstance(r[4], (int, float)):
            sheet[int(r[4])] = (i, r)
    last_no = max(sheet)
    last_row = sheet[last_no][0] + 1
    print(f'sheet: {len(sheet)} rows for {a.tile}, last POL {last_no} (Excel row {last_row}); POL file: {len(all_pol)} POLs = {len(pol)} borders + {n_trans} transient/blob (ignored); A1 = {counter}')

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

    changed = set()                                  # border POLs whose sheet row no longer matches the POL file (truncated parents)
    for n, (i, r) in sheet.items():
        if n in pol:
            pts = pol[n]['points']
            if r[5] != len(pts) or not (close(r[8], pts[-1][0]) and close(r[9], pts[-1][1])):
                changed.add(n)

    def span(n):
        return {v for w in windows(n) for v in w}

    def parent_of(n):
        """The POL this one was split from: it ENDS where this one STARTS and is either a truncated parent (sheet row differs) or itself a
        new piece (chain of a multi-point split).  Date ranges are only used to choose between several candidates (they may have been
        adjusted by hand after the split)."""
        pts = pol[n]['points']
        cands = []
        for p in pol:
            if p == n or not pol[p]['points']:
                continue
            e = pol[p]['points'][-1]
            if close(e[0], pts[0][0], 1e-5) and close(e[1], pts[0][1], 1e-5) and (p in changed or p in new):
                cands.append(p)
        if not cands:
            return None
        return max(cands, key=lambda p: (len(span(p) & span(n)), p))

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
        if parent_of(n) is not None:
            children.setdefault(root_of(n), []).append(n)
    for r0 in list(children):
        pending, seq, cur = set(children[r0]), [], r0
        while pending:
            end = pol[cur]['points'][-1]
            nxt = [c for c in pending if close(pol[c]['points'][0][0], end[0], 1e-5) and close(pol[c]['points'][0][1], end[1], 1e-5)]
            if not nxt:
                seq += sorted(pending)
                break
            c = min(nxt)
            seq.append(c)
            pending.discard(c)
            cur = c
        children[r0] = seq          # path order along the original POL: head, then each piece in turn

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
            if n not in ignore:
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

    # ---- full parent rows, ready to paste over the existing ones (one contiguous block, untouched rows repeated verbatim) ----
    mod = {}
    shifted = []
    for n, (i, r) in sorted(sheet.items()):
        if n not in pol:
            continue
        pts = pol[n]['points']
        if not (r[5] != len(pts) or not (close(r[8], pts[-1][0]) and close(r[9], pts[-1][1]))):
            continue
        row = list(r)
        row[5] = len(pts)
        row[8], row[9] = pts[-1][0], pts[-1][1]
        kids = children.get(n)
        if kids:
            txt = f'split {md} for {a.reason}: #{n} => {n}, ' + ', '.join(str(k) for k in kids)
            pos = next((k for k in range(16, 19) if row[k] is None), None)
            if pos is None:                                 # Q..S taken: the note goes to T and the date cells move right by 2
                for k in range(NCOL - 3, 18, -1):
                    row[k + 2] = row[k]
                row[19], row[20] = None, None
                pos = 19
                shifted.append(n)
            row[pos] = txt
        mod[i] = row
    block_rows = sorted(mod)
    split_rows = [i for i in block_rows if children.get(next(n for n, (ii, _) in sheet.items() if ii == i))]
    hand_rows = [i for i in block_rows if i not in split_rows]
    block = [(i + 1, mod[i]) for i in split_rows]
    hand = [(i + 1, mod[i]) for i in hand_rows]
    base = f'borders_sheet_sync_{a.tile.replace("/", "-")}'
    if block:
        with open(os.path.join(HERE, 'exports', base + '_parents.tsv'), 'w', encoding='utf-8', newline='') as f:
            for xl, r in block:
                f.write(chr(9).join(fmt(v) for v in r[:NCOL]) + chr(10))
    if hand:
        with open(os.path.join(HERE, 'exports', base + '_other_changed_rows.tsv'), 'w', encoding='utf-8', newline='') as f:
            for xl, r in hand:
                f.write(chr(9).join(fmt(v) for v in r[:NCOL]) + chr(10))
    os.makedirs(os.path.join(HERE, 'exports'), exist_ok=True)
    with open(os.path.join(HERE, 'exports', base + '.tsv'), 'w', encoding='utf-8', newline='') as f:
        for r in out_rows:
            f.write('\t'.join(fmt(v) for v in r) + '\n')
    L = [f'BORDERS SHEET sync for tile {a.tile}, {a.date}   (POL file wins; workbook only read: {a.workbook})', '',
         f'1) NEW ROWS: {len(out_rows)} lines in exports/{base}.tsv (columns A..AK), POL {new[0] if new else "-"}..{new[-1] if new else "-"}. '
         f'Insert after Excel row {last_row} (POL {last_no}), in order. (A1 is =MAX(A2:A14168), so it updates itself: {int(rows[0][0])} -> {counter})', '',
         f'2) PARENT ROW EDITS ({len(edits)}): Excel row, cell: old -> new, then the split note']
    for n, row, diffs, note in edits:
        L.append(f'   POL {n:>4} (row {row}): ' + '; '.join(diffs) + (f';  {note}' if note else '   [no new child POL found: changed by hand?]'))
    if unlogged:
        L += ['', f'3) BORDER POLs (not transient/blob) in the file but missing from the sheet, numbered below its last row: {unlogged[:60]}']
    if notes:
        L += ['', 'NOTES:'] + ['   ' + x for x in notes]
    if block:
        L += ['', f'2b) SPLIT PARENT ROWS TO PASTE: exports/{base}_parents.tsv = {len(block)} lines (columns A..AK), one per split parent, in Excel-row order.',
              '    Paste each line over the existing row (select A<row>):']
        for k, (xl, r) in enumerate(block, 1):
            L.append(f'      line {k:>2} -> A{xl}   (POL {int(r[4])}: F={r[5]}, stop {fmt(r[8])}, {fmt(r[9])})')
        if shifted:
            L += [f'    NOTE: POL(s) {shifted} had Q..S full: the note went to T and the date cells moved right by 2 columns.']
    if hand:
        L += ['', f'2c) OTHER ROWS WHOSE COUNT/STOP DIFFER FROM THE POL FILE (no split child found; your own edits): exports/{base}_other_changed_rows.tsv']
        for k, (xl, r) in enumerate(hand, 1):
            L.append(f'      line {k} -> A{xl}   (POL {int(r[4])}: F={r[5]})')
    L += ['', '4) NEW ROW PREVIEW (A..P):']
    for r in out_rows:
        flat = [fmt(r[c]) for c in WINDOW_COLS if r[c] is not None]
        L.append('   ' + ' | '.join(fmt(v) for v in r[:16]) + '   windows: ' + ', '.join(flat))
    open(os.path.join(HERE, 'exports', base + '.txt'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print('\n'.join(L[:12 + len(edits)]))
    print(f'... wrote exports\\{base}.tsv and .txt')


if __name__ == '__main__':
    main()
