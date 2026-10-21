#!/usr/bin/env python3
"""
borders_sheet_updates.py
Paste-ready updates for the 'borders' sheet of  C:\\My stuff\\VID\\ancient index.xlsx  after POL splits.

READ-ONLY on the workbook (openpyxl read_only). Input is the split list in the user's notation, as written in the plan files:

    #216 => 216, 541, 542            (old => kept, new [, new2])
     39.04640    35.53638            (split point(s), in path order)
     39.13929    35.75373
    8 > 2 & 6 & 4                    (old vertex count > kept & new [& new2])

Usage:
  python borders_sheet_updates.py --tile 125/035 --plan exports/media_plan_125-035.txt [--date 2026-10-21] [--reason "overlay fix"]
  python borders_sheet_updates.py --tile 125/035 --text "<notation block>"

Writes exports/borders_sheet_<tile>_<date>.tsv (new rows, columns A..AK, one per line, ready to paste) and
exports/borders_sheet_<tile>_<date>.txt (parent-row edits, where to insert, new A1 counter value).

Row conventions (from the sheet): one row per POL; A = running id (A1 holds the last used id); B = creation date; C = 'POLBND';
D = tile; E = POL#; F = vertex count; G,H = start lon,lat; I,J = stop lon,lat; K..N and T..AK = draw-window start/stop years;
O = description; P = notes.  New rows go after the last row of the same tile (sheet is sorted by tile, then POL#).
A split note goes in the first open cell from Q rightwards in the parent row (never overwrites a note); if Q..S are all taken the
script flags the row instead of guessing how to shift the date cells.
"""
import argparse
import datetime
import os
import re
import sys

import openpyxl
from openpyxl.utils import get_column_letter as COL

WB = r'C:\My stuff\VID\ancient index.xlsx'
EXPORTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'exports')
NCOL = 37   # A..AK
IDX = {'F': 5, 'G': 6, 'H': 7, 'I': 8, 'J': 9, 'O': 14, 'P': 15}   # 0-based column indexes of the cells we touch


def parse_splits(text):
    lines = [l.rstrip() for l in text.splitlines()]
    out = []
    i = 0
    while i < len(lines):
        m = re.match(r'^#(\d+)\s*=>\s*(\d+)\s*,\s*([\d,\s]+)$', lines[i].strip())
        if not m:
            i += 1
            continue
        old, kept = int(m.group(1)), int(m.group(2))
        news = [int(x) for x in re.split(r'[,\s]+', m.group(3).strip()) if x]
        pts = []
        j = i + 1
        while j < len(lines):
            mp = re.match(r'^\s*(-?\d+\.\d+)\s+(-?\d+\.\d+)\s*$', lines[j])
            if not mp:
                break
            pts.append((float(mp.group(1)), float(mp.group(2))))
            j += 1
        mc = re.match(r'^\s*(\d+)\s*>\s*([\d\s&]+)$', lines[j].strip()) if j < len(lines) else None
        if not mc or len(pts) != len(news):
            raise SystemExit(f"Can't read the split starting at line {i + 1}: {lines[i]!r} "
                             f"({len(pts)} points, {len(news)} new POLs, count line {'ok' if mc else 'missing'})")
        counts = [int(x) for x in re.split(r'[&\s]+', mc.group(2).strip()) if x]
        if len(counts) != len(news) + 1:
            raise SystemExit(f"Count line for #{old} has {len(counts)} numbers, expected {len(news) + 1}")
        out.append(dict(old=old, kept=kept, news=news, pts=pts, n_old=int(mc.group(1)), counts=counts))
        i = j + 1
    return out


def fmt(v):
    if v is None:
        return ''
    if isinstance(v, float):
        return ('%.5f' % v).rstrip('0').rstrip('.')
    if hasattr(v, 'strftime'):
        return v.strftime('%Y-%m-%d')
    return str(v)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tile', required=True, help="tile as in the sheet, e.g. 125/035")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--plan')
    g.add_argument('--text')
    ap.add_argument('--date', default=datetime.date.today().isoformat())
    ap.add_argument('--reason', default='overlay fix')
    ap.add_argument('--workbook', default=WB)
    a = ap.parse_args()

    text = open(a.plan, encoding='utf-8').read() if a.plan else a.text
    splits = parse_splits(text)
    if not splits:
        raise SystemExit('no splits found in the input')
    d = datetime.date.fromisoformat(a.date)
    md = f"{d.month}/{d.day}/{d.year % 100}"

    wb = openpyxl.load_workbook(a.workbook, read_only=True, data_only=True)
    rows = [list(r) + [None] * (NCOL - len(r)) for r in wb['borders'].iter_rows(values_only=True)]
    counter = int(rows[0][0])
    tile_rows = [i for i, r in enumerate(rows) if i > 0 and r[3] == a.tile and isinstance(r[4], (int, float))]
    if not tile_rows:
        raise SystemExit(f"tile {a.tile} not found in the borders sheet")
    last_row_idx = max(tile_rows, key=lambda i: rows[i][4])          # excel row = index + 1
    have = {int(rows[i][4]) for i in tile_rows}

    new_rows, edits, flags = [], [], []
    for s in splits:
        cand = [i for i in tile_rows if int(rows[i][4]) == s['old']]
        if not cand:
            raise SystemExit(f"POL {s['old']} of tile {a.tile} not found in the sheet")
        pi = cand[0]
        par = rows[pi]
        old_stop = (par[8], par[9])
        stops = list(s['pts']) + [old_stop]                           # stop point of kept piece, piece1, piece2 ...
        starts = [None] + list(s['pts'])
        # the kept parent piece: new stop = first split point, new vertex count
        note = f"split {md} for {a.reason}: #{s['old']} => {s['kept']}, " + ', '.join(str(n) for n in s['news'])
        # first open cell from Q (index 16) rightwards, restricted to Q..S; flag otherwise
        pos = next((k for k in range(16, 19) if par[k] is None), None)
        flags_row = None
        if pos is None:
            flags_row = 'Q..S already taken - decide where the note goes / which date cells to shift'
        edits.append(dict(row=pi + 1, tile=a.tile, pol=s['old'], F=(par[5], s['counts'][0]), stop=(old_stop, s['pts'][0]),
                          note=note, col=COL(pos + 1) if pos is not None else None, flag=flags_row))
        if flags_row:
            flags.append(f"POL {s['old']}: {flags_row}")
        windows = {k: par[k] for k in list(range(10, 14)) + list(range(19, NCOL)) if par[k] is not None}
        for n_i, newpol in enumerate(s['news']):
            if newpol in have:
                raise SystemExit(f"POL {newpol} already exists in tile {a.tile} - already logged?")
            counter += 1
            r = [None] * NCOL
            r[0], r[1], r[2], r[3], r[4] = counter, d, 'POLBND', a.tile, newpol
            r[5] = s['counts'][n_i + 1]
            r[6], r[7] = starts[n_i + 1]
            r[8], r[9] = stops[n_i + 1]
            for k, v in windows.items():
                r[k] = v
            r[14] = '(' + a.reason + ')'
            r[15] = f"split from #{s['old']}"
            new_rows.append(r)
            have.add(newpol)

    base = f"borders_sheet_{a.tile.replace('/', '-')}_{a.date}"
    os.makedirs(EXPORTS, exist_ok=True)
    with open(os.path.join(EXPORTS, base + '.tsv'), 'w', encoding='utf-8', newline='') as f:
        for r in new_rows:
            f.write('\t'.join(fmt(v) for v in r) + '\n')
    lines = [f"BORDERS SHEET updates, tile {a.tile}, {a.date}   (workbook read only: {a.workbook})", '',
             f"1) NEW ROWS: {len(new_rows)} lines in {base}.tsv  (columns A..AK). Insert them AFTER Excel row {last_row_idx + 1} "
             f"(tile {a.tile}, POL {int(rows[last_row_idx][4])}), in the order given.",
             f"   Cell A1 (running id): {int(rows[0][0])} -> {counter}", '',
             '2) PARENT ROW EDITS (Excel row, cell: old -> new):']
    for e in edits:
        lines.append(f"   POL {e['pol']:>4}  row {e['row']}:  F{e['row']}: {fmt(e['F'][0])} -> {e['F'][1]};  "
                     f"I{e['row']}/J{e['row']}: {fmt(e['stop'][0][0])}, {fmt(e['stop'][0][1])} -> "
                     f"{fmt(e['stop'][1][0])}, {fmt(e['stop'][1][1])};  "
                     + (f"{e['col']}{e['row']} = \"{e['note']}\"" if e['col'] else f"NOTE \"{e['note']}\" -> {e['flag']}"))
    if flags:
        lines += ['', 'FLAGS:'] + ['   ' + x for x in flags]
    lines += ['', '3) NEW ROW PREVIEW (A..P):']
    for r in new_rows:
        lines.append('   ' + ' | '.join(fmt(v) for v in r[:16]) + '   windows: ' +
                     ', '.join(f"{COL(k + 1)}={fmt(r[k])}" for k in list(range(10, 14)) + list(range(19, NCOL)) if r[k] is not None))
    open(os.path.join(EXPORTS, base + '.txt'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    print(f"\nwrote {os.path.join(EXPORTS, base + '.tsv')} and .txt")


if __name__ == '__main__':
    main()
