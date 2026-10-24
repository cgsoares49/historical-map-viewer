#!/usr/bin/env python3
"""
stage_edits.py -- apply PAR / POL edits to STAGED COPIES of one tile's files (the canonical data is never written).

    python stage_edits.py --tile 125:035 --edits edits.json [--stage staging] [--keep]

Reads  <DATA_DIR>\\polareas\\LAT\\PARLON.ASC, pols\\LAT\\POLLON.PRN, coasts\\LAT\\CSTLON.PRN  (DATA_DIR = export_polity_polygons.DATA_DIR),
copies them to  <stage>\\...  (same relative layout, fresh each run), applies the edit list, bumps the two header counts, then verifies:
  * both files re-parse, entry / POL counts are right, validate_par.js passes (if node is installed);
  * every entry whose polygon should NOT have changed (all entries not named by a par_* op) has the identical area and validity,
    entries whose refs were rewritten by a pol_split must be area-neutral (max difference is printed).
Untouched lines are preserved byte for byte (CRLF, latin-1, trailing ^Z).  You review the staged files and copy them in yourself
(the script prints the copy commands).

Edit list (JSON array), operations applied in order:
  {"op":"pol_split","pol":216,"points":[[39.0464,35.53638],[39.13929,35.75373]]}
        split POL216 at the given point(s) (in path order along the POL) into 216 (head) + NEW POLs numbered max+1, max+2 ...
        (same date ranges); every PAR entry citing the POL gets the extra refs (flag 0: old,new..; flag 1: new reversed..,old),
        its ref count is bumped.  A point that equals an existing vertex splits there without inserting a point.
  {"op":"par_set_ranges","entry":452,"ranges":[{"from":-550.5,"to":-522.1,"name":"...","color":10}, ...]}
        replace the whole date-range section of an entry (range count updated).
  {"op":"par_delete_entry","entry":348}
        remove an entry (its number is not reused unless you add one explicitly).
  {"op":"par_move","entry":136,"after":219}
        move an entry's block to right after another entry (file order = draw order; e.g. so an UNKNOWN placeholder never paints over it).
  {"op":"par_set_refs","entry":231,"refs":[[1017,0],[1018,0],{"lit":[40,35]}]}
        replace the whole ref list of an entry (keeps its number: a "ref swap" to a remainder ring).
  {"op":"par_trim","entry":452,"keep":5,"last_to":null}
        keep the first N ranges of an entry (optionally set the new last range's end).
  {"op":"par_add_entry","index":532,"after":452,"areaType":1,"ranges":[...],"refs":[[1469,1],[1505,1],{"lit":[40,40]}]}
        insert a new entry in the file RIGHT AFTER entry `after` (required; normally the parent).  File order is draw order and the
        transients / tribal dots live at the end of the file, so polities must never be appended at the end.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export_polity_polygons as X
from shapely.geometry import LineString, Point
from shapely.ops import transform

CRLF = '\r\n'
HERE = os.path.dirname(os.path.abspath(__file__))


def num(v):
    r = round(float(v), 1)
    return ('%.1f' % r) if abs(r - float(v)) < 1e-9 else ('%g' % float(v))


# ── file helpers ────────────────────────────────────────────────────────────
def read_lines(path):
    return open(path, 'rb').read().decode('latin-1').split(CRLF)


def write_lines(path, lines):
    open(path, 'wb').write(CRLF.join(lines).encode('latin-1'))


# ── PAR structure ───────────────────────────────────────────────────────────
def parse_par(lines):
    ents, i = [], 1
    while i < len(lines) and '\x1a' not in lines[i] and lines[i].strip():
        e = {'start': i, 'index': int(lines[i]), 'area': int(lines[i + 1]), 'nr_line': i + 2}
        nr = int(lines[i + 2])
        j = i + 3
        e['ranges_start'] = j
        for _ in range(nr):
            j += 3
        e['ranges_end'] = j
        e['nref_line'] = j
        nref = int(float(lines[j]))
        e['refs_start'] = j + 1
        e['dot'] = nref < 0                       # negative count: ONE literal 'lon lat' line follows (dot marker)
        e['end'] = j + 1 + (1 if nref < 0 else nref)
        e['nr'], e['nref'] = nr, nref
        ents.append(e)
        i = e['end']
    return ents, i      # i = index of the terminator line (contains ^Z)


def par_refs(lines, e):
    out = []
    if e.get('dot'):
        return out
    for k in range(e['refs_start'], e['end']):
        a, b = lines[k].split(',')
        try:
            out.append((int(a), int(b), k))
        except ValueError:                       # a literal coordinate pair with a non-integer value (reported, never edited): not a POL/CST ref
            out.append((float(a), float(b), k))
    return out


# ── POL structure ───────────────────────────────────────────────────────────
def parse_pol(lines):
    blocks, i = [], 1
    while i < len(lines) and '\x1a' not in lines[i] and lines[i].strip():
        t, idx = lines[i].split()
        nr = int(lines[i + 1])
        rs = i + 2
        npt_line = rs + nr
        npt = int(lines[npt_line])
        b = {'start': i, 'type': int(t), 'index': int(idx), 'nr_line': i + 1, 'ranges': lines[rs:rs + nr],
             'npt_line': npt_line, 'pts_start': npt_line + 1, 'end': npt_line + 1 + npt, 'npt': npt}
        blocks.append(b)
        i = b['end']
    return blocks, i


def pt_of(line):
    a, b = [t for t in re.split(r'[\s,]+', line.strip()) if t][:2]
    return float(a), float(b)


def fmt_pt(p, style='space'):
    if style == 'comma':
        return '%.5f , %.5f' % p
    if style == 'tab':
        return '%.5f	%.5f' % p
    return '%.5f      %.5f ' % p


# ── operations ──────────────────────────────────────────────────────────────
class Tile:
    def __init__(self, par_path, pol_path, cst_path=None):
        self.par = read_lines(par_path)
        self.pol = read_lines(pol_path)
        self.cst = read_lines(cst_path) if cst_path and os.path.exists(cst_path) else None
        self.touched = set()        # PAR entries named by par_* ops
        self.rewritten = set()      # PAR entries whose refs were rewritten by a pol_split
        self.log = []

    def pol_blocks(self):
        return parse_pol(self.pol)[0]

    def cst_split(self, cst, points):
        """split a coast segment (same file layout as POL; PAR refs are the bare index, no +1000; no bookkeeping beyond the PAR refs)"""
        return self.pol_split(cst, points, coast=True)

    def pol_split(self, pol, points, coast=False):
        lines_attr, base = ('cst', 0) if coast else ('pol', 1000)
        if coast:
            self.pol, self.cst = self.cst, self.pol          # operate on the coast lines with the POL code, swap back at the end
        try:
            return self._split(pol, points, base, coast)
        finally:
            if coast:
                self.pol, self.cst = self.cst, self.pol

    def _split(self, pol, points, base, coast):
        blocks, term = parse_pol(self.pol)
        by = {b['index']: b for b in blocks}
        if pol not in by:
            raise SystemExit(f'{"CST" if coast else "POL"} {pol} not found')
        b = by[pol]
        plines = self.pol[b['pts_start']:b['end']]
        style = 'comma' if ',' in plines[0] else ('tab' if '	' in plines[0] else 'space')
        pts = [pt_of(l) for l in plines]
        # locate each split point: at an existing vertex, or inside a segment
        cuts = []
        for p in points:
            vi = next((v for v, q in enumerate(pts) if Point(q).distance(Point(p)) < 1e-5), None)   # snap to a vertex within ~1 m (5-decimal rounding)
            if vi is not None:
                cuts.append((float(vi), 'v', vi, tuple(p)))
                continue
            best = None
            for k in range(len(pts) - 1):
                d = LineString([pts[k], pts[k + 1]]).distance(Point(p))
                if best is None or d < best[0]:
                    best = (d, k)
            if best[0] > 1e-4:
                raise SystemExit(f'point {p} is {best[0]:.6f} deg from POL{pol}')
            k = best[1]
            cuts.append((k + Point(pts[k]).distance(Point(p)) / Point(pts[k]).distance(Point(pts[k + 1])), 'e', k, tuple(p)))
        cuts.sort()
        out_pieces, carry, cur = [], None, 0
        for _, kind, k, p in cuts:
            pre = [carry] if carry is not None else []
            if kind == 'v':
                piece = pre + plines[cur:k + 1]
                carry = plines[k]
            else:
                piece = pre + plines[cur:k + 1] + [fmt_pt(p, style)]
                carry = fmt_pt(p, style)
            cur = k + 1
            out_pieces.append(piece)
        out_pieces.append(([carry] if carry is not None else []) + plines[cur:])
        if any(len(pc) < 2 for pc in out_pieces):
            raise SystemExit(f'split of POL{pol} would leave a piece with fewer than 2 points')
        newnums = []
        nxt = max(by) + 1
        for _ in out_pieces[1:]:
            newnums.append(nxt)
            nxt += 1
        # rewrite the original block: head only
        head_lines = out_pieces[0]
        old_block_end = b['end']
        new_blocks_text = []
        for nn, pl in zip(newnums, out_pieces[1:]):
            blk = [f' {b["type"]}             {nn} ', self.pol[b['nr_line']]] + b['ranges'] + [f' {len(pl)} '] + pl
            new_blocks_text += blk
        self.pol[b['npt_line']] = f' {len(head_lines)} '
        self.pol[b['pts_start']:old_block_end] = head_lines
        # append new blocks before the terminator
        blocks2, term2 = parse_pol(self.pol)
        self.pol[term2:term2] = new_blocks_text
        self.pol[0] = f' {len(parse_pol(self.pol)[0])} '
        # ref updates in the PAR file
        ents, _ = parse_par(self.par)
        changed = []
        for e in reversed(ents):                                     # bottom-up keeps line numbers valid
            refs = par_refs(self.par, e)
            hit = [(a, f, k) for (a, f, k) in refs if a == base + pol and f in (0, 1)]
            if not hit:
                continue
            for (a, f, k) in reversed(hit):
                if f == 0:
                    rep = [self.par[k]] + [f'   {base + n}  ,  0' for n in newnums]
                else:
                    rep = [f'   {base + n}  ,  1' for n in reversed(newnums)] + [self.par[k]]
                self.par[k:k + 1] = rep
            self.par[e['nref_line']] = f' {e["nref"] + len(hit) * len(newnums)} '
            changed.append(e['index'])
            self.rewritten.add(e['index'])
        self.log.append(f'{"cst" if coast else "pol"}_split {"CST" if coast else "POL"}{pol} at {len(points)} point(s): kept {len(head_lines)} pts, new POL {newnums} '
                        f'({", ".join(str(len(p)) for p in out_pieces[1:])} pts); refs rewritten in {len(changed)} entries '
                        f'({", ".join("#%d" % i for i in sorted(changed))})')
        return newnums

    def _entry(self, idx):
        ents, _ = parse_par(self.par)
        c = [e for e in ents if e['index'] == idx]
        if not c:
            raise SystemExit(f'PAR entry #{idx} not found')
        return c[0]

    @staticmethod
    def range_lines(rs):
        out = []
        for r in rs:
            out += [f'{num(r["from"])}   ,   {num(r["to"])} ', r['name'], str(int(r['color']))]
        return out

    def par_set_ranges(self, idx, ranges):
        e = self._entry(idx)
        self.par[e['ranges_start']:e['ranges_end']] = self.range_lines(ranges)
        self.par[e['nr_line']] = f' {len(ranges)} '
        self.touched.add(idx)
        self.log.append(f'par_set_ranges #{idx}: {e["nr"]} -> {len(ranges)} ranges')

    def par_trim(self, idx, keep, last_to=None):
        e = self._entry(idx)
        rs = []
        for k in range(e['nr']):
            a, b = self.par[e['ranges_start'] + 3 * k].split(',')
            rs.append({'from': float(a), 'to': float(b), 'name': self.par[e['ranges_start'] + 3 * k + 1],
                       'color': int(self.par[e['ranges_start'] + 3 * k + 2])})
        rs = rs[:keep]
        if last_to is not None:
            rs[-1]['to'] = last_to
        # keep untouched ranges byte-exact: rewrite only when changed
        if last_to is None:
            self.par[e['ranges_start'] + 3 * keep:e['ranges_end']] = []
            self.par[e['nr_line']] = f' {keep} '
        else:
            self.par_set_ranges(idx, rs)
            return
        self.touched.add(idx)
        self.log.append(f'par_trim #{idx}: {e["nr"]} -> {keep} ranges')

    def par_renumber(self, idx, occurrence, new):
        """give the occurrence-th (1-based) PAR entry that carries index idx a new, unique index (duplicate-index repair)"""
        ents, _ = parse_par(self.par)
        src = [e for e in ents if e['index'] == idx]
        if len(src) < occurrence:
            raise SystemExit(f'par_renumber #{idx}: occurrence {occurrence} not found')
        if any(e['index'] == new for e in ents):
            raise SystemExit(f'par_renumber: #{new} already in use')
        self.par[src[occurrence - 1]['start']] = f' {new} '
        self.touched.add(new)
        self.log.append(f'par_renumber #{idx} (occurrence {occurrence}) -> #{new}')

    def par_set_areatype(self, idx, areatype):
        """change an entry's areaType (0 dot, 1 polity, 2 semi-transient overlay)"""
        e = self._entry(idx)
        self.par[e['start'] + 1] = f' {areatype} '
        self.touched.add(idx)
        self.log.append(f'par_set_areatype #{idx} -> {areatype}')

    def par_delete_entry(self, idx):
        ents, _ = parse_par(self.par)
        src = [e for e in ents if e['index'] == idx]
        if not src:
            raise SystemExit(f'par_delete_entry #{idx}: entry not found')
        del self.par[src[0]['start']:src[0]['end']]
        self.touched.add(idx)
        self.log.append(f'par_delete_entry #{idx}')

    def par_move(self, idx, after):
        """Move the whole block of entry idx to right after entry `after` (file order = draw order)."""
        ents, _ = parse_par(self.par)
        src = [e for e in ents if e['index'] == idx]
        dst = [e for e in ents if e['index'] == after]
        if not src or not dst:
            raise SystemExit(f'par_move #{idx} after #{after}: entry not found')
        src, dst = src[0], dst[0]
        block = self.par[src['start']:src['end']]
        if src['start'] == dst['end']:
            return                                          # already right after it
        if src['start'] < dst['start']:
            ins = dst['end'] - len(block)                  # removing the block shifts the target up
            del self.par[src['start']:src['end']]
            self.par[ins:ins] = block
        else:
            del self.par[src['start']:src['end']]
            self.par[dst['end']:dst['end']] = block
        self.touched.add(idx)
        self.log.append(f'par_move #{idx}: now right after #{after}')

    def par_set_refs(self, idx, refs):
        e = self._entry(idx)
        lines = []
        for r in refs:
            if isinstance(r, dict):
                lines.append(f'     {int(r["lit"][0]):>2}  ,  {int(r["lit"][1])}')
            else:
                lines.append(f'   {int(r[0])}  ,  {int(r[1])}')
        self.par[e['refs_start']:e['end']] = lines
        self.par[e['nref_line']] = f' {len(lines)} '
        self.touched.add(idx)
        self.log.append(f'par_set_refs #{idx}: {e["nref"]} -> {len(lines)} refs')

    def par_add_entry(self, idx, area, ranges, refs, after=None):
        ents, term = parse_par(self.par)
        if any(e['index'] == idx for e in ents):
            raise SystemExit(f'PAR entry #{idx} already exists')
        # File order is DRAW ORDER: later entries paint over earlier ones, and the transients / tribal dots sit at the end of the
        # file.  A polity entry must therefore go right after its parent (`after`), never at the end.
        if after is None:
            raise SystemExit(f'par_add_entry #{idx}: "after" (the entry it goes under, normally its parent) is required')
        par = [e for e in ents if e['index'] == after]
        if not par:
            raise SystemExit(f'par_add_entry #{idx}: entry #{after} not found')
        term = par[0]['end']
        blk = [f' {idx} ', f'   {area}', f' {len(ranges)} '] + self.range_lines(ranges) + [f' {len(refs)} ']
        for r in refs:
            if isinstance(r, dict):
                blk.append(f'     {int(r["lit"][0]):>2}  ,  {int(r["lit"][1])}')
            else:
                blk.append(f'   {int(r[0])}  ,  {int(r[1])}')
        self.par[term:term] = blk
        self.touched.add(idx)
        self.log.append(f'par_add_entry #{idx}: {len(ranges)} ranges, {len(refs)} refs, placed right after #{after}')

    def finish(self):
        ents, _ = parse_par(self.par)
        self.par[0] = f' {len(ents)} '
        blocks, _ = parse_pol(self.pol)
        self.pol[0] = f' {len(blocks)} '
        return len(ents), len(blocks)


# ── verification ────────────────────────────────────────────────────────────
def areas(data_dir, lat, lon):
    old = X.DATA_DIR
    X.DATA_DIR = data_dir
    try:
        t = X.load_tile(lat, lon)
    finally:
        X.DATA_DIR = old
    out = {}
    for e in t['par_entries']:
        try:
            r = X.build_combined_ring(e['polyRefs'], t['cst_by_index'], t['pol_by_index'])
            r = r[0] if isinstance(r, tuple) else r
            g = X.ring_to_polygon(r, [0])
            out[e['entryIndex']] = (round(transform(X.TO_EQUAL_AREA, g).area / 1e6, 4), bool(g.is_valid)) if g is not None else None
        except Exception:
            out[e['entryIndex']] = None
    return t, out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tile', required=True, help='lat:lon, e.g. 125:035')
    ap.add_argument('--edits', required=True, help='JSON file with the edit list')
    ap.add_argument('--stage', default=os.path.join(HERE, 'staging'))
    ap.add_argument('--data-dir', default=X.DATA_DIR)
    a = ap.parse_args()
    lat, lon = a.tile.split(':')
    rel = {'par': os.path.join('polareas', lat, f'PAR{lon}.ASC'), 'pol': os.path.join('pols', lat, f'POL{lon}.PRN'),
           'cst': os.path.join('coasts', lat, f'CST{lon}.PRN')}
    stage = os.path.join(a.stage, f'{lat}-{lon}')
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    for k, r in rel.items():
        os.makedirs(os.path.dirname(os.path.join(stage, r)), exist_ok=True)
        src = os.path.join(a.data_dir, r)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(stage, r))
    T = Tile(os.path.join(stage, rel['par']), os.path.join(stage, rel['pol']), os.path.join(stage, rel['cst']))
    ops = json.load(open(a.edits, encoding='utf-8'))
    for op in ops:
        o = op['op']
        if o == 'pol_split':
            T.pol_split(op['pol'], [tuple(p) for p in op['points']])
        elif o == 'cst_split':
            T.cst_split(op['cst'], [tuple(p) for p in op['points']])
        elif o == 'par_set_ranges':
            T.par_set_ranges(op['entry'], op['ranges'])
        elif o == 'par_renumber':
            T.par_renumber(op['entry'], op['occurrence'], op['new'])
        elif o == 'par_set_areatype':
            T.par_set_areatype(op['entry'], op['areatype'])
        elif o == 'par_delete_entry':
            T.par_delete_entry(op['entry'])
        elif o == 'par_move':
            T.par_move(op['entry'], op['after'])
        elif o == 'par_set_refs':
            T.par_set_refs(op['entry'], op['refs'])
        elif o == 'par_trim':
            T.par_trim(op['entry'], op['keep'], op.get('last_to'))
        elif o == 'par_add_entry':
            T.par_add_entry(op['index'], op.get('areaType', 1), op['ranges'], op['refs'], op.get('after'))
        else:
            raise SystemExit(f'unknown op {o}')
    n_ent, n_pol = T.finish()
    write_lines(os.path.join(stage, rel['par']), T.par)
    write_lines(os.path.join(stage, rel['pol']), T.pol)
    if T.cst is not None:
        write_lines(os.path.join(stage, rel['cst']), T.cst)
    print('STAGED in', stage)
    for l in T.log:
        print('  ', l)
    print(f'   headers: PAR {n_ent} entries, POL {n_pol} POLs')

    # verification
    problems = []
    t0, a0 = areas(a.data_dir, lat, lon)
    t1, a1 = areas(stage, lat, lon)
    if len(t1['par_entries']) != n_ent:
        problems.append(f'staged PAR parses to {len(t1["par_entries"])} entries, header says {n_ent}')
    if len(t1['pol_by_index']) != n_pol:
        problems.append(f'staged POL parses to {len(t1["pol_by_index"])} POLs, header says {n_pol}')
    maxd = 0.0
    for i, v0 in a0.items():
        if i in T.touched:
            continue
        v1 = a1.get(i)
        if v0 is None or v1 is None:
            if v0 != v1:
                problems.append(f'#{i}: polygon {v0} -> {v1}')
            continue
        d = abs(v0[0] - v1[0])
        maxd = max(maxd, d)
        if d > 0.01 or v0[1] != v1[1]:
            problems.append(f'#{i}: area/validity changed {v0} -> {v1}')
    print(f'   untouched entries ({len(a0) - len(T.touched & set(a0))}): max area change {maxd:.6f} km2; '
          f'{len(T.rewritten)} had refs rewritten')
    for i in sorted(T.touched):
        v = a1.get(i)
        print(f'   edited/new #{i}: {"area %.1f km2, valid=%s" % v if v else "NO POLYGON"}   (before: {a0.get(i)})')
        if v is None or not v[1]:
            problems.append(f'#{i} has no valid polygon')
    js = os.path.join(HERE, 'tools', 'validate_par.js')
    if shutil.which('node') and os.path.exists(js):
        r = subprocess.run(['node', js, os.path.join('polareas', lat, f'PAR{lon}.ASC')], cwd=stage, capture_output=True, text=True)
        line = (r.stdout.strip().splitlines() or ['(no output)'])
        print('   validate_par.js:', ' | '.join(l for l in line if 'OK' in l or 'ERROR' in l or 'desync' in l.lower() or 'resolve' in l)[:200] or line[:3])
        if r.returncode != 0:
            problems.append('validate_par.js failed')
    if problems:
        print('PROBLEMS:')
        for p in problems:
            print('   -', p)
    else:
        print('VERIFIED: no problems found.')
    print('\nTo apply (review the staged files first):')
    for k in ('par', 'pol'):
        print(f'   copy "{os.path.join(stage, rel[k])}" "{os.path.join(a.data_dir, rel[k])}"')


if __name__ == '__main__':
    main()
