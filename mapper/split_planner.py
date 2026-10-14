"""
split_planner.py
Plans a polity split so you don't have to assign every parent POL by hand.

Given a PAR entry (the parent), the date of the split, and the separator --
one or more EXISTING POL/CST segments forming a path, or a coordinate cut --
it works out:

  * for each of the parent's polyRefs: which child (A or B) it belongs to,
    or that the separator CROSSES it (it must be split into two POLs),
  * the polyRef list of each child, ready to paste,
  * the parent's trimmed date ranges and the children's date ranges,
  * what the separator's own draw windows must cover,
  * for any crossed segment: the new POL text and the replacement refs for
    EVERY entry that references it (parent included),
  * a geometric check: A + B == parent, both rings valid, no overlap, and
    whether a child is identical to an entry that already exists.

READ-ONLY. Nothing is written to any PAR/POL file. The plan is printed and
saved to exports/split_plan_<tile>_<parent>.txt as paste-ready text.

Terminology: the separator runs between two points X and Y on the parent's
boundary. Child A = the boundary arc X->Y (in ring order) closed by the
separator; child B = the other arc closed by the same separator.

Usage:
  python split_planner.py --tile 120:035 --parent 203 --date -1135.5 --separator POL101
  python split_planner.py --tile 120:035 --parent 203 --date -1135.5 --separator POL101 POL102
  python split_planner.py --tile 120:035 --parent 77 --date -500 --cut "35.1,31.2 35.3,31.4 35.5,31.5"
  options: --a-name NAME --b-name NAME   (rename every date range of that child)
           --tol 0.001                   (degrees: separator end -> boundary snap distance)
"""

import os
import sys
import re
import math
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export_polity_polygons import (
    load_tile, build_combined_ring, ring_to_polygon, TO_EQUAL_AREA, owner_name,
)
from shapely.ops import transform
from shapely.geometry import Polygon

EXPORTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'exports')
EPS = 1e-9


# ── small geometry helpers ─────────────────────────────────────────────────

def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def seg_project(p, a, b):
    """(distance, t, projected point) of p onto segment a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return dist(p, a), 0.0, a
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    q = (a[0] + t * dx, a[1] + t * dy)
    return dist(p, q), t, q


def area_km2(poly):
    return transform(TO_EQUAL_AREA, poly).area / 1e6 if poly is not None and not poly.is_empty else 0.0


def fmt_pt(p):
    return f"{p[0]:.5f}      {p[1]:.5f}"


# ── model of the parent ring as an ordered list of pieces ──────────────────
# piece = {'kind': 'seg'|'pt', 'src': pol_or_cst_index (>1000 => POL), 'flag': 0|1,
#          'spts': stored-orientation points (seg), 'pt': (lon,lat) for 'pt',
#          'dup': bool (a connector point inserted at a boundary shared by both arcs)}

def oriented(piece):
    if piece['kind'] == 'pt':
        return [piece['pt']]
    return piece['spts'] if piece['flag'] == 0 else list(reversed(piece['spts']))


def make_pieces(entry, tile):
    pieces = []
    for pi, fl in entry['polyRefs']:
        if fl in (0, 1):
            seg = tile['cst_by_index'].get(pi) if pi <= 1000 else tile['pol_by_index'].get(pi - 1000)
            if not seg or not seg['points']:
                continue
            pieces.append({'kind': 'seg', 'src': pi, 'flag': fl, 'spts': list(seg['points']), 'dup': False})
        else:
            pieces.append({'kind': 'pt', 'pt': (float(pi), 0.0 if fl == 1000 else float(fl)), 'src': None,
                           'flag': None, 'dup': False})
    return pieces


def cut_at(pieces, p, tol, label):
    """Make sure there is a piece boundary at (the snapped point nearest to) p.
    Mutates `pieces`. Returns (boundary_index, snapped_point, gap_distance).
    boundary_index = index of the first piece AFTER the boundary."""
    n = len(pieces)
    best = None   # (dist, kind, i, j, point, t)
    for i, pc in enumerate(pieces):
        pts = oriented(pc)
        for v, q in enumerate(pts):
            d = dist(p, q)
            if best is None or d < best[0] - EPS:
                best = (d, 'vertex', i, v, q, 0.0)
        for v in range(len(pts) - 1):
            d, t, q = seg_project(p, pts[v], pts[v + 1])
            if d < best[0] - EPS:
                best = (d, 'edge', i, v, q, t)
        nxt = pieces[(i + 1) % n]
        a, b = pts[-1], oriented(nxt)[0]
        if a != b:
            d, t, q = seg_project(p, a, b)
            if d < best[0] - EPS:
                best = (d, 'joint', i, 0, q, t)
    d, kind, i, v, q, t = best
    if d > tol:
        raise SystemExit(f"Separator end {label} ({p[0]:.5f},{p[1]:.5f}) is {d:.5f} deg from the parent boundary "
                         f"(tolerance {tol}). Extend/snap the separator to the boundary, or raise --tol.")
    pc = pieces[i]
    if kind == 'vertex':
        pts = oriented(pc)
        if pc['kind'] == 'pt' or v == 0:
            return i, q, d
        if v == len(pts) - 1:
            return (i + 1) % n if i + 1 < n else 0, q, d
        return _split_piece(pieces, i, v, None), q, d
    if kind == 'edge':
        return _split_piece(pieces, i, v, q), q, d
    # joint: insert a connector point between piece i and i+1
    newpc = {'kind': 'pt', 'pt': q, 'src': None, 'flag': None, 'dup': True}
    pieces.insert(i + 1, newpc)
    return i + 1, q, d


def _split_piece(pieces, i, v, q):
    """Split pieces[i] after oriented vertex v (inserting q if given). Returns
    the index of the TAIL piece."""
    pc = pieces[i]
    pts = oriented(pc)
    head = pts[:v + 1] + ([q] if q is not None else [])
    tail = ([q] + pts[v + 1:]) if q is not None else pts[v:]
    def mk(opts):
        sp = opts if pc['flag'] == 0 else list(reversed(opts))
        return {'kind': 'seg', 'src': pc['src'], 'flag': pc['flag'], 'spts': sp, 'dup': False}
    h, tl = mk(head), mk(tail)
    pieces[i:i + 1] = [h, tl]
    return i + 1


# ── separator path ─────────────────────────────────────────────────────────

def parse_token(tok):
    m = re.fullmatch(r'(?i)(POL|CST)?\s*(\d+)', tok.strip())
    if not m:
        raise SystemExit(f"Can't read separator '{tok}' (use e.g. POL101 or CST12)")
    kind = (m.group(1) or 'POL').upper()
    n = int(m.group(2))
    return (n + 1000) if kind == 'POL' else n


def chain_separators(tokens, tile, tol):
    """-> list of (src_index, stored_pts, flag_in_travel_direction)."""
    segs = []
    for tk in tokens:
        src = parse_token(tk)
        seg = tile['cst_by_index'].get(src) if src <= 1000 else tile['pol_by_index'].get(src - 1000)
        if not seg or not seg['points']:
            raise SystemExit(f"{tk} not found in tile")
        segs.append((src, list(seg['points'])))
    if len(segs) == 1:
        return [(segs[0][0], segs[0][1], 0)]
    out = []
    # orient first so its END touches the next segment
    s0, s1 = segs[0], segs[1]
    ends0 = [s0[1][0], s0[1][-1]]
    ends1 = [s1[1][0], s1[1][-1]]
    best = min(((dist(a, b), ia, ib) for ia, a in enumerate(ends0) for ib, b in enumerate(ends1)))
    if best[0] > tol * 5:
        raise SystemExit(f"{tokens[0]} and {tokens[1]} don't connect (gap {best[0]:.5f} deg)")
    first_flag = 0 if best[1] == 1 else 1      # want END (stored last) touching => forward if stored-last touches
    out.append((s0[0], s0[1], first_flag))
    cur = s0[1][-1] if first_flag == 0 else s0[1][0]
    for src, pts in segs[1:]:
        if dist(cur, pts[0]) <= dist(cur, pts[-1]):
            gap, fl = dist(cur, pts[0]), 0
        else:
            gap, fl = dist(cur, pts[-1]), 1
        if gap > tol * 5:
            raise SystemExit(f"separator chain breaks before POL{src - 1000 if src > 1000 else src} (gap {gap:.5f} deg)")
        out.append((src, pts, fl))
        cur = pts[-1] if fl == 0 else pts[0]
    return out


def path_points(chain):
    pts = []
    for src, sp, fl in chain:
        seq = sp if fl == 0 else list(reversed(sp))
        pts.extend(seq if not pts else seq[1:] if dist(pts[-1], seq[0]) < 1e-9 else seq)
    return pts


# ── text emitters (PAR / POL file style) ───────────────────────────────────

def par_block(idx, area_type, ranges, refs):
    L = [f" {idx} ", f" {area_type} ", f" {len(ranges)} "]
    for lo, hi, name, col in ranges:
        L += [f"{lo:g}   ,   {hi:g}", name, f" {col} "]
    L.append(f" {len(refs)} ")
    for pi, fl in refs:
        L.append(f"   {pi:g}  ,  {fl:g}")
    return '\n'.join(L)


def pol_block(idx, ptype, ranges, pts):
    L = [f" {ptype}             {idx} ", f" {len(ranges)} "]
    for lo, hi in ranges:
        L.append(f"{lo:.1f}  ,   {hi:.1f}")
    L.append(f" {len(pts)} ")
    L += [fmt_pt(p) for p in pts]
    return '\n'.join(L)


def clip_ranges(parent_ranges, split):
    before, after = [], []
    for dr in parent_ranges:
        lo, hi, nm, col = dr['from'], dr['to'], dr['name'], dr['colorIndex']
        if lo < split:
            before.append((lo, min(hi, split), nm, col))
        if hi > split:
            after.append((max(lo, split), hi, nm, col))
    return before, after


def merge_cover(ranges):
    spans = sorted((lo, hi) for lo, hi, *_ in ranges if hi > lo)
    out = []
    for lo, hi in spans:
        if out and lo <= out[-1][1] + 1e-9:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return out


def subtract(cover, have):
    """parts of `cover` spans not inside `have` spans"""
    missing = []
    for lo, hi in cover:
        cur = lo
        for a, b in sorted(have):
            if b <= cur or a >= hi:
                continue
            if a > cur:
                missing.append((cur, a))
            cur = max(cur, b)
        if cur < hi:
            missing.append((cur, hi))
    return missing


# ── main planning ──────────────────────────────────────────────────────────

def plan(args):
    lat, lon = args.tile.split(':')
    tile = load_tile(lat, lon)
    entries = {e['entryIndex']: e for e in tile['par_entries']}
    if args.parent not in entries:
        raise SystemExit(f"entry #{args.parent} not in tile {args.tile}")
    parent = entries[args.parent]
    out = []
    P = out.append

    max_pol = max(tile['pol_by_index']) if tile['pol_by_index'] else 0
    next_pol = max_pol + 1
    next_entry = max(entries) + 1
    new_pols = {}          # pol index -> dict(points, ranges, type)
    P(f"SPLIT PLAN  tile {args.tile}  parent #{args.parent}  split date {args.date:g}")
    P("=" * 78)
    P("Parent date ranges now:")
    for dr in parent['dateRanges']:
        P(f"    {dr['from']:g} .. {dr['to']:g}  {dr['name']}  (colour {dr['colorIndex']})")

    # separator
    virtual_cut = None
    if args.cut:
        pts = [tuple(float(x) for x in c.split(',')) for c in args.cut.split()]
        if len(pts) < 2:
            raise SystemExit("--cut needs at least two lon,lat points")
        chain = None
        sep_pts = pts
    else:
        chain = chain_separators(args.separator, tile, args.tol)
        sep_pts = path_points(chain)
    X, Y = sep_pts[0], sep_pts[-1]

    pieces = make_pieces(parent, tile)
    bX, Xs, gx = cut_at(pieces, X, args.tol, 'X (start)')
    bY, Ys, gy = cut_at(pieces, Y, args.tol, 'Y (end)')
    bX, Xs, gx = cut_at(pieces, X, args.tol, 'X (start)')      # re-locate after Y inserted pieces
    n = len(pieces)
    if bX == bY:
        raise SystemExit("separator start and end snap to the same boundary position -- not a split")
    def arc(b0, b1):
        out_ = []
        i = b0
        while i != b1:
            out_.append(pieces[i]); i = (i + 1) % n
        return out_
    arcA, arcB = arc(bX, bY), arc(bY, bX)
    # shared connector points inserted on a straight joint edge belong to both arcs
    if pieces[bX]['dup']:
        arcB = arcB + [dict(pieces[bX])]
    if pieces[bY]['dup']:
        arcA = arcA + [dict(pieces[bY])]

    # ── name the sub-segments of crossed POLs ──
    groups = defaultdict(list)      # src -> pieces (in ring order); stored order = ring order if flag 0
    for pc in pieces:
        if pc['kind'] == 'seg':
            groups[(pc['src'])].append(pc)
    pol_ref = {}                    # id(piece) -> pol index used in refs (src number incl. +1000 offset for POL)
    replacements = {}               # src -> [ (stored-order list of (refindex, points)) ]
    for src, pcs in groups.items():
        if len(pcs) == 1:
            pol_ref[id(pcs[0])] = src
            continue
        if src <= 1000:
            raise SystemExit(f"The separator crosses coastline CST{src} -- splitting coast segments is not "
                             f"supported. Snap the separator end to a CST vertex/end.")
        # distinct stored sub-pieces in stored order
        subs = sorted({id(pc): pc for pc in pcs}.values(),
                      key=lambda pc: (pcs.index(pc) if pc['flag'] == 0 else -pcs.index(pc)))
        assigned = []
        for k, pc in enumerate(subs):
            if k == 0:
                ref = src
            else:
                ref = next_pol + 1000
                new_pols[next_pol] = {'points': pc['spts'], 'src_pol': src - 1000}
                next_pol += 1
            pol_ref[id(pc)] = ref
            assigned.append((ref, pc['spts']))
        replacements[src] = assigned

    def refs_of(arc_pieces, tail):
        refs = []
        for pc in arc_pieces:
            if pc['kind'] == 'pt':
                refs.append((pc['pt'][0], 1000 if pc['pt'][1] == 0 else pc['pt'][1]))
            else:
                # dup'ed copies are shallow dicts: look up by object or by content
                refs.append((pol_ref[id(pc)], pc['flag']))
        return refs + tail

    # separator refs
    sep_new_pol = None
    if args.cut:
        sep_new_pol = next_pol
        new_pols[next_pol] = {'points': sep_pts, 'src_pol': None, 'virtual_cut': True}
        next_pol += 1
        chain_for_refs = [(sep_new_pol + 1000, sep_pts, 0)]
    else:
        chain_for_refs = chain
    sep_forward = [(src, fl) for src, _, fl in chain_for_refs]                   # X -> Y
    sep_backward = [(src, 1 - fl) for src, _, fl in reversed(chain_for_refs)]    # Y -> X

    # dup'ed connector points are 'pt' pieces (no pol_ref needed); real seg pieces keep identity
    refsA = refs_of(arcA, sep_backward)
    refsB = refs_of(arcB, sep_forward)

    # ── virtual tile for verification ──
    pol_v = dict(tile['pol_by_index'])
    for src, assigned in replacements.items():
        base = src - 1000
        pol_v[base] = dict(pol_v[base]); pol_v[base]['points'] = assigned[0][1]
        for ref, pts in assigned[1:]:
            pol_v[ref - 1000] = {'polyType': pol_v[base].get('polyType', 1), 'dateRanges': pol_v[base]['dateRanges'],
                                 'points': pts}
    if sep_new_pol is not None:
        pol_v[sep_new_pol] = {'polyType': 1, 'dateRanges': [], 'points': sep_pts}

    def poly_of(refs):
        ring, _ = build_combined_ring(refs, tile['cst_by_index'], pol_v)
        return ring_to_polygon(ring, [0]), ring
    # the parent's footprint must come from the ORIGINAL tile data, not the virtual (split) POLs
    _r0, _ = build_combined_ring(parent['polyRefs'], tile['cst_by_index'], tile['pol_by_index'])
    pP = ring_to_polygon(_r0, [0])
    pA, rA = poly_of(refsA)
    pB, rB = poly_of(refsB)
    aP, aA, aB = area_km2(pP), area_km2(pA), area_km2(pB)
    try:
        inter = area_km2(pA.intersection(pB))
        union_diff = area_km2(pA.union(pB).symmetric_difference(pP))
    except Exception:
        inter, union_diff = float('nan'), float('nan')

    # ── assignment table ──
    P("")
    P("ASSIGNMENT of the parent's polyRefs (ring order)")
    names = {}
    for i, (pi, fl) in enumerate(parent['polyRefs']):
        label = f"POL{pi - 1000}" if pi > 1000 else f"CST{pi}" if fl in (0, 1) else f"pt({pi:g},{0 if fl == 1000 else fl:g})"
        names[i] = label
    inA = {id(pc) for pc in arcA}; inB = {id(pc) for pc in arcB}
    seen_src = set()
    for pc in pieces:
        if pc['kind'] == 'pt':
            who = 'A' if id(pc) in inA else 'B' if id(pc) in inB else 'A and B'
            P(f"    connector point ({pc['pt'][0]:g}, {pc['pt'][1]:g})  ->  child {who}")
            continue
        src = pc['src']
        lab = f"POL{src - 1000}" if src > 1000 else f"CST{src}"
        who = 'A' if id(pc) in inA else 'B'
        if src in replacements:
            k = [x[0] for x in replacements[src]].index(pol_ref[id(pc)])
            ref = pol_ref[id(pc)]
            sub = f"{lab} (kept part)" if k == 0 else f"NEW POL{ref - 1000} (part of {lab})"
            P(f"    {lab}{'r' if pc['flag'] else ''}  CROSSED by the separator -> {sub}  ->  child {who}")
        else:
            P(f"    {lab}{'r' if pc['flag'] else ' '}  ->  child {who}")
    P(f"    separator: {' + '.join((f'POL{s-1000}' if s > 1000 else f'CST{s}') for s, _, _ in chain_for_refs)}"
      f"{' (NEW, from --cut)' if args.cut else ''}   X=({Xs[0]:.5f},{Xs[1]:.5f})  Y=({Ys[0]:.5f},{Ys[1]:.5f})"
      f"   snap gaps {gx:.5f}/{gy:.5f} deg")

    # ── date ranges ──
    before, after = clip_ranges(parent['dateRanges'], args.date)
    def renamed(rs, nm):
        return [(lo, hi, nm if nm else n_, c) for lo, hi, n_, c in rs]
    rangesA = renamed(after, args.a_name)
    rangesB = renamed(after, args.b_name)

    # existing identical entries
    matches = {}
    for tag, poly in (('A', pA), ('B', pB)):
        for idx, e in entries.items():
            if idx == args.parent or not e['polyRefs'] or e['areaType'] not in (1, 2):
                continue
            ring, hs = build_combined_ring(e['polyRefs'], tile['cst_by_index'], tile['pol_by_index'])
            if not hs or len(ring) < 4:
                continue
            try:
                pe = ring_to_polygon(ring, [0])
                if pe is None or pe.is_empty or area_km2(pe) <= 0:
                    continue
                if abs(area_km2(pe) - area_km2(poly)) / max(area_km2(poly), 1e-9) < 0.01 and \
                        area_km2(pe.symmetric_difference(poly)) / max(area_km2(poly), 1e-9) < 0.01:
                    matches[tag] = idx
                    break
            except Exception:
                pass

    P("")
    P("RESULT")
    for tag, poly, a, refs in (('A', pA, aA, refsA), ('B', pB, aB, refsB)):
        if tag in matches:
            me = entries[matches[tag]]
            drs = me['dateRanges']
            span = f"{min(d['from'] for d in drs):g}..{max(d['to'] for d in drs):g}"
            extra = (f"   == existing entry #{matches[tag]} '{drs[0]['name'][:34]}' alive {span} "
                     f"(same footprint -- check it is the RIGHT entity, not just the same shape)")
        else:
            extra = ''
        c = poly.centroid
        P(f"    child {tag}: {a:,.1f} km2   valid={poly.is_valid}   centre ({c.x:.2f} E, {c.y:.2f} N){extra}")
    ok_area = abs(aA + aB - aP) / aP < 0.005 if aP else False
    P(f"    parent  : {aP:,.1f} km2   A+B = {aA + aB:,.1f} km2   overlap A&B = {inter:,.2f} km2   "
      f"(A+B) vs parent mismatch = {union_diff:,.2f} km2   -> {'OK' if ok_area and union_diff < 0.005 * aP else 'CHECK'}")

    # ── parent edit ──
    P("")
    P("1) PARENT #%d  ->  keep only the part before the split:" % args.parent)
    if before:
        for lo, hi, nm, col in before:
            P(f"       {lo:g} .. {hi:g}  {nm}  (colour {col})")
    else:
        P("       (nothing remains before the split date -- the parent entry can be retired/reused)")

    # ── children ──
    idx = next_entry
    P("")
    P("2) NEW ENTRIES (paste into the PAR file; indices are the next free numbers)")
    blocks = []
    for tag, refs, rngs in (('A', refsA, rangesA), ('B', refsB, rangesB)):
        if tag in matches:
            P(f"   child {tag}: already exists as #{matches[tag]} -- no new entry. Check that its date ranges start at "
              f"{args.date:g} and its polyRefs are:")
            P("       " + ' '.join(f"{int(r):d},{int(f)}" if float(r).is_integer() else f"{r:g},{f}" for r, f in refs))
            continue
        blk = par_block(idx, 1, rngs, [(r, f) for r, f in refs])
        blocks.append(blk)
        P(f"   child {tag}  ->  new entry #{idx}  ({len(refs)} refs)")
        idx += 1
    for blk in blocks:
        P("")
        for line in blk.split('\n'):
            P("       | " + line)

    # ── separator draw windows ──
    P("")
    P("3) SEPARATOR DRAW WINDOWS (border lines are drawn only while a POL's own ranges include the year)")
    life = merge_cover(rangesA + rangesB)
    if not life:
        P("       (the parent has no date range after the split date -- nothing to draw yet)")
    if args.cut:
        P(f"       new POL{sep_new_pol} needs ranges: (-9998.0, -9997.0) + " + ', '.join(f"({lo:g}, {hi:g})" for lo, hi in life))
    else:
        for src, _, _ in chain_for_refs:
            pol = tile['pol_by_index'][src - 1000] if src > 1000 else tile['cst_by_index'][src]
            have = [(a, b) for a, b in pol['dateRanges'] if b > a and not (a <= -9990 and b <= -9990)]
            miss = subtract(life, have)
            lab = f"POL{src - 1000}" if src > 1000 else f"CST{src}"
            P(f"       {lab} draws: " + ('; '.join(f'{a:g}..{b:g}' for a, b in have) or '(sentinel only)'))
            if miss:
                P(f"       {lab} MISSING (children alive, border not drawn): " + '; '.join(f'{a:g}..{b:g}' for a, b in miss))
            else:
                P(f"       {lab}: covers the children's whole life -- OK")

    # ── crossed segments ──
    P("")
    if new_pols:
        P("4) POL FILE EDITS")
        for k, info in new_pols.items():
            if info.get('virtual_cut'):
                P(f"   NEW POL{k} (the separator you cut):")
                P('\n'.join('       | ' + l for l in pol_block(
                    k, 1, [(-9998.0, -9997.0)] + [(lo, hi) for lo, hi in life], info['points']).split('\n')))
        for src, assigned in replacements.items():
            base = src - 1000
            old = tile['pol_by_index'][base]
            P(f"   POL{base} is CROSSED by the separator and must be split in two:")
            for ref, pts in assigned:
                if ref == src:
                    P(f"     keep POL{base}, now only these {len(pts)} points (was {len(old['points'])}):")
                    P('\n'.join('       | ' + fmt_pt(p) for p in pts))
                else:
                    P(f"     NEW POL{ref - 1000}, same date ranges as POL{base}:")
                    P('\n'.join('       | ' + l for l in pol_block(
                        ref - 1000, old.get('polyType', 1), old['dateRanges'], pts).split('\n')))
            P(f"   Every entry that references POL{base} must be updated -- replace the ref as shown:")
            order = [r for r, _ in assigned]
            for e in tile['par_entries']:
                for pos, (pi, fl) in enumerate(e['polyRefs']):
                    if pi == src and fl in (0, 1):
                        seq = order if fl == 0 else list(reversed(order))
                        rep = '  '.join(f"{r},{fl}" for r in seq)
                        who = 'PARENT' if e['entryIndex'] == args.parent else ''
                        P(f"       entry #{e['entryIndex']:<4} ref #{pos + 1}: {pi},{fl}  ->  {rep}   {who}")
    else:
        P("4) POL FILE EDITS: none -- no existing POL is crossed by the separator.")

    P("")
    P("AFTER YOU APPLY IT:  python overlay_diff.py diff --since %g" % args.date)
    return '\n'.join(out), dict(areaA=aA, areaB=aB, parent=aP, overlap=inter, mismatch=union_diff,
                                matches=matches, replacements=len(replacements))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tile', required=True, help='lat:lon, e.g. 120:035')
    ap.add_argument('--parent', type=int, required=True, help='PAR entry number of the parent')
    ap.add_argument('--date', type=float, required=True, help='split date (children start here)')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--separator', nargs='+', help='existing POL/CST segment(s), e.g. POL101 or POL101 POL102')
    g.add_argument('--cut', help='coordinate cut: "lon,lat lon,lat ..." (a NEW separator POL is generated)')
    ap.add_argument('--a-name'); ap.add_argument('--b-name')
    ap.add_argument('--tol', type=float, default=0.001)
    args = ap.parse_args()
    text, info = plan(args)
    print(text)
    os.makedirs(EXPORTS, exist_ok=True)
    path = os.path.join(EXPORTS, f"split_plan_{args.tile.replace(':', '-')}_{args.parent}.txt")
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text + '\n')
    print(f"\n(saved to {path})")


if __name__ == '__main__':
    main()
