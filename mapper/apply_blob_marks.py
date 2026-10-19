"""
apply_blob_marks.py
The "veto & apply" half of the blob-overlay plan (see mark_blob_overlays.py,
which only PROPOSES). Takes the AUTO rows of a proposal CSV, removes anything
on the veto list, and flips each remaining entry's areaType 1 -> 2 in its PAR
file. That one line is the only thing it ever edits.

SAFE BY DEFAULT -- three levels:
  (nothing)      PREVIEW: prints exactly which entries would change and the
                 exact PAR line before/after. Writes nothing anywhere.
  --scratch DIR  copies each affected tile's PAR/POL/CST into DIR (same
                 polareas/<lat>/PAR<lon>.ASC layout) and edits the COPY, so you
                 can look at it / re-run the detector against it
                 (DATA_DIR can be pointed at DIR) without touching real data.
  --canonical    edits the real files under DATA_DIR. Backs every file up first
                 (exports/par_backups/<timestamp>/...), then verifies. Only
                 run after you have reviewed the preview and said go.

Every write (scratch or canonical) is verified before it is trusted:
  * the edited PAR must parse to exactly the original entries, except that the
    chosen entries go areaType 1 -> 2
  * only those areaType lines differ, line for line (CRLF, trailing blanks,
    the Ctrl-Z byte and all other text are preserved byte-for-byte)
  * an entry index that appears twice in a tile is skipped, never guessed at
A change log CSV (Tile, EntryIndex, Name, line number, before, after) is written
next to the backups / scratch copy.

VETO FILE (exports/blob_veto.csv, default): columns Tile,EntryIndex,Reason.
An AUTO entry listed there is left alone. Lines starting with # are ignored.
Use it for real polities the shape rules mistook for blobs (modern enclaves,
Judah-sized states, ...).

Usage:
  python apply_blob_marks.py --tiles 125:030                      (preview)
  python apply_blob_marks.py --tiles 125:030 --scratch exports/blob_apply_demo
  python apply_blob_marks.py --all-tiles --canonical               (after go-ahead)
"""

import os
import re
import sys
import csv
import shutil
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export_polity_polygons as epp
from export_polity_polygons import parse_par_full, read_lines

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORTS = os.path.join(MAPPER_DIR, 'exports')
DEFAULT_PROPOSAL = os.path.join(EXPORTS, 'blob_overlay_proposal.csv')
DEFAULT_VETO = os.path.join(EXPORTS, 'blob_veto.csv')


def load_proposal(path, tiles):
    rows = {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            if r['Tier'] != 'AUTO':
                continue
            if tiles is not None and r['Tile'] not in tiles:
                continue
            rows[(r['Tile'], int(r['EntryIndex']))] = r
    return rows


def load_veto(path):
    veto = {}
    if not path or not os.path.exists(path):
        return veto
    with open(path, encoding='utf-8-sig', newline='') as f:
        lines = [l for l in f if l.strip() and not l.lstrip().startswith('#')]
    for r in csv.DictReader(lines):
        veto[(r['Tile'].strip(), int(r['EntryIndex']))] = (r.get('Reason') or '').strip()
    return veto


def split_keepends(text):
    # NOT str.splitlines(): latin-1 text contains \x85 etc. that it would split on.
    return re.findall(r'[^\n]*\n|[^\n]+', text)


def locate_area_type_lines(lines):
    """{entryIndex: [(line_number, entry_ordinal), ...]} for the areaType line of
    every entry, walking the file exactly as parse_par_full does (blank lines and
    the Ctrl-Z byte are skipped, as read_lines does)."""
    real = [n for n, l in enumerate(lines) if l.strip() and l.strip() != '\x1a']
    out = {}
    p = 0
    count = int(lines[real[p]]); p += 1
    for ordinal in range(count):
        if p >= len(real):
            break
        idx = int(lines[real[p]]); p += 1
        at_line = real[p]; p += 1
        out.setdefault(idx, []).append(at_line)
        nr = int(lines[real[p]]); p += 1
        p += 3 * nr
        num_refs = float(lines[real[p]]); p += 1
        p += 1 if num_refs < 0 else int(num_refs)
    return out


def tile_paths(root, lat, lon):
    return {
        'par': os.path.join(root, 'polareas', lat, f'PAR{lon}.ASC'),
        'pol': os.path.join(root, 'pols', lat, f'POL{lon}.PRN'),
        'cst': os.path.join(root, 'coasts', lat, f'CST{lon}.PRN'),
    }


def plan_tile(src_par, wanted):
    """Returns (new_text, changes, skipped) for one tile. wanted = set of entryIndex."""
    with open(src_par, 'rb') as f:
        raw = f.read()
    text = raw.decode('latin-1')
    lines = split_keepends(text)
    at = locate_area_type_lines(lines)
    changes, skipped = [], []
    for idx in sorted(wanted):
        locs = at.get(idx, [])
        if len(locs) != 1:
            skipped.append((idx, f'entry index appears {len(locs)} times in the file -- not touched'))
            continue
        n = locs[0]
        if lines[n].strip() != '1':
            skipped.append((idx, f'areaType line is {lines[n].strip()!r}, not 1 -- not touched'))
            continue
        before = lines[n]
        after = before.replace('1', '2', 1)
        lines[n] = after
        changes.append((idx, n + 1, before, after))
    return ''.join(lines), changes, skipped, text


def verify(orig_text, new_text, changes):
    """Raises AssertionError unless the ONLY differences are the planned lines."""
    a, b = split_keepends(orig_text), split_keepends(new_text)
    assert len(a) == len(b), 'line count changed'
    diff = [n for n in range(len(a)) if a[n] != b[n]]
    assert diff == sorted(c[1] - 1 for c in changes), f'differing lines {diff} != planned'
    import tempfile
    def parse(t):
        with tempfile.NamedTemporaryFile('wb', suffix='.ASC', delete=False) as tf:
            tf.write(t.encode('latin-1')); name = tf.name
        try:
            return parse_par_full(read_lines(name))
        finally:
            os.unlink(name)
    pa, pb = parse(orig_text), parse(new_text)
    assert len(pa) == len(pb)
    want = {c[0] for c in changes}
    for ea, eb in zip(pa, pb):
        if ea['entryIndex'] in want:
            assert ea['areaType'] == 1 and eb['areaType'] == 2
            ea2 = dict(ea, areaType=2)
            assert ea2 == eb
        else:
            assert ea == eb
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tiles', nargs='+', help='lat:lon pairs, e.g. 125:030')
    ap.add_argument('--all-tiles', action='store_true')
    ap.add_argument('--proposal', default=DEFAULT_PROPOSAL)
    ap.add_argument('--veto', default=DEFAULT_VETO)
    ap.add_argument('--scratch', help='edit COPIES under this directory instead of the real data')
    ap.add_argument('--canonical', action='store_true', help='edit the real files under DATA_DIR (backs up first)')
    args = ap.parse_args()
    if args.scratch and args.canonical:
        ap.error('choose --scratch or --canonical, not both')
    if not args.tiles and not args.all_tiles:
        ap.error('give --tiles or --all-tiles')

    tiles = None if args.all_tiles else {t.replace(':', '/') for t in args.tiles}
    proposal = load_proposal(args.proposal, tiles)
    veto = load_veto(args.veto)
    mode = 'CANONICAL WRITE' if args.canonical else ('SCRATCH COPY' if args.scratch else 'PREVIEW (no writes)')
    print(f'Mode: {mode}')
    print(f'Proposal AUTO rows in scope: {len(proposal)}   veto list entries: {len(veto)} ({args.veto})')

    vetoed = {k: v for k, v in veto.items() if k in proposal}
    for (tile, idx), why in sorted(vetoed.items()):
        r = proposal[(tile, idx)]
        print(f'  VETOED  {tile} #{idx} {r["Name"]} ({r["AreaKm2"]} km2): {why or "(no reason given)"}')
    todo = {k: r for k, r in proposal.items() if k not in vetoed}

    by_tile = {}
    for (tile, idx) in todo:
        by_tile.setdefault(tile, set()).add(idx)

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    log_rows, total = [], 0
    for tile in sorted(by_tile):
        lat, lon = tile.split('/')
        src = tile_paths(epp.DATA_DIR, lat, lon)
        new_text, changes, skipped, orig_text = plan_tile(src['par'], by_tile[tile])
        print(f'\n{tile}  ({src["par"]})')
        for idx, why in skipped:
            print(f'  SKIPPED #{idx}: {why}')
        for idx, ln, before, after in changes:
            r = todo[(tile, idx)]
            print(f'  #{idx:<4} {r["Name"][:34]:<34} {r["AreaKm2"]:>8} km2  inside {r["Overlays"][:38]:<38}'
                  f'  line {ln}: {before.strip()!r} -> {after.strip()!r}')
            log_rows.append([tile, idx, r['Name'], ln, before.rstrip('\r\n'), after.rstrip('\r\n')])
        if not changes:
            continue
        verify(orig_text, new_text, changes)
        print(f'  verified: only {len(changes)} areaType line(s) differ; every entry otherwise identical')
        total += len(changes)

        if args.scratch or args.canonical:
            if args.canonical:
                bdir = os.path.join(EXPORTS, 'par_backups', stamp)
                dst_par = src['par']
                bpath = os.path.join(bdir, 'polareas', lat, os.path.basename(src['par']))
                os.makedirs(os.path.dirname(bpath), exist_ok=True)
                shutil.copy2(src['par'], bpath)
                print(f'  backup -> {bpath}')
            else:
                dst = tile_paths(os.path.abspath(args.scratch), lat, lon)
                dst_par = dst['par']
                for k in ('pol', 'cst'):                    # so the detector can run against the copy
                    if os.path.exists(src[k]):
                        os.makedirs(os.path.dirname(dst[k]), exist_ok=True)
                        shutil.copy2(src[k], dst[k])
            os.makedirs(os.path.dirname(dst_par), exist_ok=True)
            with open(dst_par, 'wb') as f:
                f.write(new_text.encode('latin-1'))
            with open(dst_par, 'rb') as f:                   # read back what was written
                assert f.read().decode('latin-1') == new_text
            print(f'  wrote {dst_par}')

    print(f'\nTotal: {total} entr{"y" if total == 1 else "ies"} {"changed" if (args.scratch or args.canonical) else "would change"} (areaType 1 -> 2).')
    if log_rows and (args.scratch or args.canonical):
        ldir = os.path.abspath(args.scratch) if args.scratch else os.path.join(EXPORTS, 'par_backups', stamp)
        os.makedirs(ldir, exist_ok=True)
        lp = os.path.join(ldir, f'blob_changes_{stamp}.csv')
        with open(lp, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f); w.writerow(['Tile', 'EntryIndex', 'Name', 'Line', 'Before', 'After']); w.writerows(log_rows)
        print(f'Change log -> {lp}')
    if not (args.scratch or args.canonical):
        print('Preview only -- nothing was written. Add --scratch DIR to try it on copies.')


if __name__ == '__main__':
    main()
