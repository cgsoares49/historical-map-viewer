#!/usr/bin/env python3
"""
plan_tile.py -- plan the overlay fixes of a WHOLE TILE over all time and stage them.

    python plan_tile.py --tile 120:040 [--label NAME]

Rule (yours): where polity entries overlap, the NEWER entry takes what lies inside its border and the OLDER one is carved.
"Newer" = later origin (first real date range of the entry); equal origin: the smaller polygon is the newer one.

For every candidate entry E (the entries the overlay detector reports for the tile) and every piece of its date ranges (cut wherever a
newer overlapping entry starts or stops) it works out what is left of E after removing every newer entry alive in that piece:
    V = polygon(E) - union(polygon(newer entries alive))
  * V == polygon(E)  -> the piece stays in E,
  * V is empty       -> the piece is dropped from E (the newer entries fully cover it),
  * otherwise        -> the piece moves to a REMAINDER entry whose ring is V (inserted right under E in file order, new number;
                        if E keeps no full piece at all, E itself is re-pointed to the first remainder ring = a "ref swap").
The remainder rings are traced from existing POLs: the POLs are split where boundaries cross (area-neutral), the ring is the run of POL
pieces along the boundary of V.  Everything is applied to a staged copy and verified: no polity area is lost or gained at any year.

Writes  exports/tileplan_<tile>/ : edits.json (replayable with stage_edits.py), plan.txt, salient_years.csv ; staged files in
staging/<lat>-<lon>/ .  Canonical data is never written.  A case it cannot do safely is listed under NEEDS A HUMAN DECISION.
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export_polity_polygons as X
import stage_edits as SE
from shapely.geometry import LineString, Point
from shapely.ops import transform, unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORTS = os.path.join(HERE, 'exports')
MIN_YEARS = 0.05
MIN_KM2 = 0.5
SLIVER = 0.001            # a leftover smaller than 0.1% of the entry counts as covered (dropped)
MIN_PAIR_YEARS = 10.0     # an overlap counts when it lasts >= 10 years without a break (shorter = transient-like overlay; reported, not touched)
ERA_RULE = False
FORCE_ENTRIES = set()     # entries whose overlaps always count, whatever their duration (e.g. a province that expands for a few years)
FORCE_PAIRS = set()       # (i, j) pairs treated as real overlays whatever their duration
BIG_KM2 = 50000.0         # entries larger than this (tribal / background layers) are never carved automatically; such pairs are only reported
MIN_RATIO = 0.05          # an overlap counts when it is >= 5% of the smaller entry (the detector's threshold)


def area(g):
    return transform(X.TO_EQUAL_AREA, g).area / 1e6 if g is not None and not g.is_empty else 0.0


def key(p):
    return (round(p[0], 6), round(p[1], 6))


def to_polygon(pts):
    return X.ring_to_polygon(pts, [0])


class Session:
    def __init__(self, lat, lon, stage_root):
        self.lat, self.lon = lat, lon
        self.root = os.path.join(stage_root, f'{lat}-{lon}')
        if os.path.isdir(self.root):
            shutil.rmtree(self.root)
        self.rel = {'par': os.path.join('polareas', lat, f'PAR{lon}.ASC'), 'pol': os.path.join('pols', lat, f'POL{lon}.PRN'),
                    'cst': os.path.join('coasts', lat, f'CST{lon}.PRN')}
        for r in self.rel.values():
            os.makedirs(os.path.dirname(os.path.join(self.root, r)), exist_ok=True)
            src = os.path.join(X.DATA_DIR, r)
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(self.root, r))
        self.T = SE.Tile(os.path.join(self.root, self.rel['par']), os.path.join(self.root, self.rel['pol']), os.path.join(self.root, self.rel['cst']))
        self.disagree = {}
        self.ops, self.manual, self.fixes, self.log, self.notation, self.warn, self.moved = [], [], [], [], [], [], []
        self.sync()
        self.t0 = self.t
        self.E0 = self.E

    def sync(self):
        self.T.finish()
        SE.write_lines(os.path.join(self.root, self.rel['par']), self.T.par)
        SE.write_lines(os.path.join(self.root, self.rel['pol']), self.T.pol)
        if self.T.cst is not None:
            SE.write_lines(os.path.join(self.root, self.rel['cst']), self.T.cst)
        old = X.DATA_DIR
        X.DATA_DIR = self.root
        try:
            self.t = X.load_tile(self.lat, self.lon)
        finally:
            X.DATA_DIR = old
        self.E = {e['entryIndex']: e for e in self.t['par_entries']}
        self._g = {}

    def ring(self, refs):
        r = X.build_combined_ring(refs, self.t['cst_by_index'], self.t['pol_by_index'])
        return list(r[0] if isinstance(r, tuple) else r)

    def geom_of_refs(self, refs):
        return to_polygon(self.ring(refs))

    def geom(self, i):
        if i not in self._g:
            self._g[i] = self.geom_of_refs(self.E[i]['polyRefs'])
        return self._g[i]

    def ranges(self, i):
        return [dict(frm=d['from'], to=d['to'], name=d['name'], color=d['colorIndex']) for d in self.E[i]['dateRanges']]

    def real(self, r):
        return r['name'].strip().upper() != 'UNKNOWN' and r['to'] - r['frm'] > MIN_YEARS

    def real_ranges(self, i):
        return [r for r in self.ranges(i) if self.real(r)]

    def run_start(self, i, t):
        """start of the continuous ERA of entry i that contains time t: consecutive date ranges with gaps < 1 yr, UNKNOWN placeholder
        ranges included (an entry that was an UNKNOWN placeholder before becoming a province is old, not new)."""
        rs = sorted((r for r in self.ranges(i) if r['to'] - r['frm'] > MIN_YEARS), key=lambda r: r['frm'])
        cur = None
        for r in rs:
            if cur is None or r['frm'] - cur[1] > 1.0:
                cur = [r['frm'], r['to']]
            else:
                cur[1] = max(cur[1], r['to'])
            if cur[0] <= t <= cur[1] + 1e-9:
                return cur[0]
        return None

    def newer(self, f, e, t):
        """is f the winner over e at time t?  Default = MAPPER paint order (the entry later in the PAR file is drawn on top, so it keeps the
        area); the old era rule (later start of the current era; equal: the smaller polygon) is used with --era-rule, and the pairs where
        the two rules disagree are listed in the plan."""
        pf, pe = self.pos(f), self.pos(e)
        era = self.newer_era(f, e, t)
        if era != (pf > pe) and (min(f, e), max(f, e)) not in self.disagree:
            self.disagree[(min(f, e), max(f, e))] = (f, e, t)
        return era if ERA_RULE else pf > pe

    def newer_era(self, f, e, t):
        of, oe = self.run_start(f, t), self.run_start(e, t)
        if of is None or oe is None:
            return False
        if abs(of - oe) > 0.05:
            return of > oe
        af, ae = area(self.geom(f)), area(self.geom(e))
        if abs(af - ae) > 1.0:
            return af < ae
        return f > e

    def alive(self, i, a, b):
        m = (a + b) / 2
        return any(r['frm'] < m <= r['to'] for r in self.real_ranges(i))

    # ── recorded ops ────────────────────────────────────────────────────────
    def pol_split(self, pol, points):
        oldn = len(self.t['pol_by_index'][pol]['points'])
        nums = self.T.pol_split(pol, [tuple(p) for p in points])
        self.ops.append({'op': 'pol_split', 'pol': pol, 'points': [[round(c, 5) for c in p] for p in points]})
        self.sync()
        counts = [len(self.t['pol_by_index'][pol]['points'])] + [len(self.t['pol_by_index'][n]['points']) for n in nums]
        self.notation.append((pol, nums, points, oldn, counts))
        return nums

    def cst_split(self, cst, points):
        oldn = len(self.t['cst_by_index'][cst]['points'])
        nums = self.T.cst_split(cst, [tuple(p) for p in points])
        self.ops.append({'op': 'cst_split', 'cst': cst, 'points': [[round(c, 5) for c in p] for p in points]})
        self.sync()
        counts = [len(self.t['cst_by_index'][cst]['points'])] + [len(self.t['cst_by_index'][n]['points']) for n in nums]
        self.notation.append((f'CST{cst}', nums, points, oldn, counts))
        return nums

    def set_ranges(self, idx, rs):
        rr = [{'from': r['frm'], 'to': r['to'], 'name': r['name'], 'color': r['color']} for r in rs]
        self.T.par_set_ranges(idx, rr)
        self.ops.append({'op': 'par_set_ranges', 'entry': idx, 'ranges': rr})
        self.sync()

    @staticmethod
    def jrefs(refs):
        return [{'lit': [a, b]} if (b not in (0, 1) and abs(a) <= 1000) else [a, b] for a, b in refs]

    def set_refs(self, idx, refs):
        j = self.jrefs(refs)
        self.T.par_set_refs(idx, j)
        self.ops.append({'op': 'par_set_refs', 'entry': idx, 'refs': j})
        self.sync()

    def add_entry(self, idx, after, rs, refs):
        rr = [{'from': r['frm'], 'to': r['to'], 'name': r['name'], 'color': r['color']} for r in rs]
        j = self.jrefs(refs)
        self.T.par_add_entry(idx, 1, rr, j, after)
        self.ops.append({'op': 'par_add_entry', 'index': idx, 'after': after, 'areaType': 1, 'ranges': rr, 'refs': j})
        self.sync()

    def apply_op(self, op):
        o = op['op']
        if o == 'pol_split':
            self.pol_split(op['pol'], [tuple(q) for q in op['points']])
        elif o == 'cst_split':
            self.cst_split(op['cst'], [tuple(q) for q in op['points']])
        elif o == 'par_set_ranges':
            self.set_ranges(op['entry'], [dict(frm=r['from'], to=r['to'], name=r['name'], color=r['color']) for r in op['ranges']])
        elif o == 'par_set_refs':
            self.T.par_set_refs(op['entry'], op['refs']); self.ops.append(op); self.sync()
        elif o == 'par_delete_entry':
            self.T.par_delete_entry(op['entry']); self.ops.append(op); self.sync()
        elif o == 'par_renumber':
            self.T.par_renumber(op['entry'], op['occurrence'], op['new']); self.ops.append(op); self.sync()
        elif o == 'par_move':
            self.move_entry(op['entry'], op['after'])
        elif o == 'par_add_entry':
            self.T.par_add_entry(op['index'], op.get('areaType', 1), op['ranges'], op['refs'], op.get('after')); self.ops.append(op); self.sync()
        else:
            raise SystemExit(f'unknown pre-edit op {o}')

    def move_entry(self, idx, after):
        self.T.par_move(idx, after)
        self.ops.append({'op': 'par_move', 'entry': idx, 'after': after})
        self.sync()

    def pos(self, i):
        return [e['entryIndex'] for e in self.t['par_entries']].index(i)

    def fix_duplicate_indices(self):
        """PAR entries sharing an index (a data bug: everything keyed by index sees only one of them) -> later occurrences get new indices"""
        ents, _ = SE.parse_par(self.T.par)
        seen, dups = {}, []
        for e in ents:
            seen[e['index']] = seen.get(e['index'], 0) + 1
            if seen[e['index']] > 1:
                dups.append((e['index'], seen[e['index']]))
        nxt = max(seen) + 1
        for idx, occ in dups:
            op = {'op': 'par_renumber', 'entry': idx, 'occurrence': occ, 'new': nxt}
            self.apply_op(op)
            self.log.append(f'DUPLICATE INDEX: PAR entry #{idx} (occurrence {occ}, later in the file) renumbered to #{nxt}')
            nxt += 1

    def next_no(self):
        return max(self.E) + 1


# ── ring tracing ────────────────────────────────────────────────────────────
def source_polylines(sess, entries):
    """(src, points) for every POL/CST cited by the entries; src = ref number as in the PAR (1000+pol, or coast number)."""
    seen, out = set(), []
    for e in entries:
        for pi, fl in sess.E[e]['polyRefs']:
            if fl in (0, 1) and pi not in seen:
                seen.add(pi)
                tab = sess.t['pol_by_index'].get(pi - 1000) if pi > 1000 else sess.t['cst_by_index'].get(pi)
                if tab and len(tab['points']) >= 2:
                    out.append((pi, [tuple(p) for p in tab['points']]))
    return out


def nodes_between(sess, e, subs):
    """Points where boundaries of E and the subtractors meet / cross (and where subtractors cross each other inside E)."""
    nodes = set()
    geoms = [sess.geom(e)] + [sess.geom(f) for f in subs]
    ge = geoms[0]
    for a in range(len(geoms)):
        for b in range(a + 1, len(geoms)):
            inter = geoms[a].boundary.intersection(geoms[b].boundary)
            if a > 0 and not ge.intersects(inter):
                continue
            stack = list(inter.geoms) if hasattr(inter, 'geoms') else [inter]
            for g in stack:
                if g.is_empty:
                    continue
                if g.geom_type == 'Point':
                    nodes.add((g.x, g.y))
                elif g.geom_type == 'LineString':
                    c = list(g.coords)
                    if c:
                        nodes.add(c[0])
                        nodes.add(c[-1])
                elif hasattr(g, 'geoms'):
                    for h in g.geoms:
                        if h.is_empty:
                            continue
                        if h.geom_type == 'Point':
                            nodes.add((h.x, h.y))
                        elif h.geom_type == 'LineString':
                            c = list(h.coords)
                            if c:
                                nodes.add(c[0])
                                nodes.add(c[-1])
    return nodes


def split_at_nodes(sess, entries, nodes, tol=1e-5):
    out = []
    for node in sorted(nodes):
        for pi, pts in source_polylines(sess, entries):
            line = LineString(pts)
            if line.distance(Point(node)) > tol:
                continue
            if any(Point(q).distance(Point(node)) < tol for q in pts):
                continue
            if pi <= 1000:
                nums = sess.cst_split(pi, [node])
                out.append((pi, nums[0]))
            else:
                nums = sess.pol_split(pi - 1000, [node])
                out.append((pi - 1000, nums[0]))
    return out


def trace_ring(sess, e, subs, V):
    """(refs, cuts): refs = list of (pi, flag) or literal (a, b); cuts = {src: [vertices]} when a run uses only part of a POL."""
    srcs = []
    for pi, pts in source_polylines(sess, [e] + list(subs)):
        dd = [pts[0]]
        for p in pts[1:]:
            if key(p) != key(dd[-1]):
                dd.append(p)                      # (duplicate consecutive vertices are ignored for matching)
        srcs.append((pi, dd))
    lookup = {}
    for pi, pts in srcs:
        for k in range(len(pts) - 1):
            lookup.setdefault((key(pts[k]), key(pts[k + 1])), []).append((pi, k, +1, len(pts)))
            lookup.setdefault((key(pts[k + 1]), key(pts[k])), []).append((pi, k, -1, len(pts)))
    lits = {key((a, b)) for a, b in sess.E[e]['polyRefs'] if b not in (0, 1) and abs(a) <= 1000}
    coords = list(V.exterior.coords)[:-1]
    n = len(coords)
    pri = {pi: r for r, (pi, _) in enumerate(srcs)}
    edges = []
    for i in range(n):
        c = lookup.get((key(coords[i]), key(coords[(i + 1) % n])))
        edges.append(None if not c else min(c, key=lambda x: pri[x[0]]))

    def continues(prev, cur):
        return prev is not None and cur is not None and prev[0] == cur[0] and prev[2] == cur[2] and 1 <= (cur[1] - prev[1]) * cur[2] <= 4

    start = 0
    for i in range(n):
        if not continues(edges[i - 1], edges[i]):
            start = i
            break
    order = [(start + k) % n for k in range(n)]
    refs, cuts, run = [], {}, None

    ends_of = {pi: (key(pts[0]), key(pts[-1])) for pi, pts in srcs}

    def close(r):
        pi, d, k0, k1, nlen, vs, ve = r
        first, last = ends_of[pi]
        # full when the run starts and ends at the POL's own end points (zero-area spikes inside a POL are tolerated)
        full = (d == 1 and key(vs) == first and key(ve) == last) or (d == -1 and key(vs) == last and key(ve) == first)
        refs.append((pi, 0 if d == 1 else 1))
        if not full:
            cuts.setdefault(pi, []).extend([vs, ve])

    for idx in order:
        ed = edges[idx]
        v0, v1 = coords[idx], coords[(idx + 1) % n]
        if run is not None and ed is not None and ed[0] == run[0] and ed[2] == run[1] and 1 <= (ed[1] - run[3]) * run[1] <= 4:
            run[3] = ed[1]
            run[6] = v1
            continue
        if run is not None:
            close(run)
            run = None
        if ed is None:
            if key(v0) in lits:
                refs.append((int(round(v0[0])), int(round(v0[1]))))
            continue                          # otherwise an implicit straight connector between consecutive refs
        run = [ed[0], ed[2], ed[1], ed[1], ed[3], v0, v1]
    if run is not None:
        close(run)
    return refs, cuts


def build_remainder_rings(sess, e, subs):
    """Generator: yields (refs, V_part) for each connected part of V = E - union(subs), or (None, reason).  The caller must write each
    ring into the PAR file BEFORE asking for the next one (later POL splits rewrite the refs of every entry, written ones included)."""
    nodes = nodes_between(sess, e, subs)
    split_at_nodes(sess, [e] + list(subs), nodes)

    def parts_of(V):
        gs = [g for g in (V.geoms if hasattr(V, 'geoms') else [V]) if g.geom_type == 'Polygon']
        return sorted([g for g in gs if area(g) >= 5.0], key=lambda g: (-area(g), g.centroid.x))      # parts of >= 5 km2 get a ring

    def remainder():
        return sess.geom(e).difference(unary_union([sess.geom(f) for f in subs]))

    nparts = len(parts_of(remainder()))
    for k in range(nparts):
        parts = parts_of(remainder())
        if k >= len(parts):
            yield None, 'remainder part vanished after a POL split'
            return
        P = parts[k]
        done = False
        for attempt in range(5):
            if len(P.interiors):
                yield None, f'a remainder part has {len(P.interiors)} hole(s)'
                return
            refs, cuts = trace_ring(sess, e, subs, P)
            if refs is None:
                yield None, cuts
                return
            if not cuts:
                g = sess.geom_of_refs(refs)
                if area(g.symmetric_difference(P)) > max(1.0, area(P) * 0.002):
                    yield None, f'traced ring does not reproduce the remainder ({area(g):.1f} vs {area(P):.1f} km2)'
                    return
                yield refs, P
                done = True
                break
            did = False
            for pi, vs in cuts.items():
                tab = sess.t['pol_by_index'].get(pi - 1000) if pi > 1000 else sess.t['cst_by_index'].get(pi)
                if not tab:
                    yield None, f'cannot find {"POL" if pi > 1000 else "CST"} {pi}'
                    return
                ends = {key(tab['points'][0]), key(tab['points'][-1])}
                pts = sorted({key(q) for q in vs} - ends)
                if pts:
                    if pi > 1000:
                        sess.pol_split(pi - 1000, pts)
                    else:
                        sess.cst_split(pi, pts)
                    did = True
            if not did:
                yield None, 'a run uses part of a POL but no interior vertex to split at'
                return
            parts = parts_of(remainder())
            if k >= len(parts):
                yield None, 'remainder part vanished after a POL split'
                return
            P = parts[k]
        if not done:
            yield None, 'ring tracing did not converge'
            return


# ── planning ────────────────────────────────────────────────────────────────
def pair_years(sess, i, j):
    """longest unbroken stretch in which both entries are alive"""
    iv = sorted((max(r['frm'], q['frm']), min(r['to'], q['to'])) for r in sess.real_ranges(i) for q in sess.real_ranges(j) if min(r['to'], q['to']) > max(r['frm'], q['frm']))
    best, cur = 0.0, None
    for lo, hi in iv:
        if cur is not None and lo <= cur[1] + 1e-6:
            cur[1] = max(cur[1], hi)
        else:
            cur = [lo, hi]
        best = max(best, cur[1] - cur[0])
    return best


def significant(sess, i, j):
    gi, gj = sess.geom(i), sess.geom(j)
    if gi is None or gj is None or not gi.intersects(gj):
        return False
    o = area(gi.intersection(gj))
    return o > MIN_KM2 and o >= MIN_RATIO * min(area(gi), area(gj))


def counts(sess, i, j):
    """a pair counts as an overlay to fix: significant in space, >= MIN_PAIR_YEARS in time, neither entry a giant."""
    forced = (min(i, j), max(i, j)) in FORCE_PAIRS or i in FORCE_ENTRIES or j in FORCE_ENTRIES
    if pair_years(sess, i, j) < MIN_PAIR_YEARS and not forced:
        return False
    if not significant(sess, i, j):
        return False
    return area(sess.geom(i)) <= BIG_KM2 and area(sess.geom(j)) <= BIG_KM2


def short_pairs(sess, cand):
    out = []
    for k, i in enumerate(cand):
        for j in cand[k + 1:]:
            y = pair_years(sess, i, j)
            if 0.5 <= y < MIN_PAIR_YEARS and (min(i, j), max(i, j)) not in FORCE_PAIRS and i not in FORCE_ENTRIES and j not in FORCE_ENTRIES and significant(sess, i, j) and area(sess.geom(i)) <= BIG_KM2 and area(sess.geom(j)) <= BIG_KM2:
                out.append((i, j, y))
    return out


def skipped_pairs(sess, cand):
    out = []
    for k, i in enumerate(cand):
        for j in cand[k + 1:]:
            if pair_years(sess, i, j) >= MIN_PAIR_YEARS and significant(sess, i, j) and (area(sess.geom(i)) > BIG_KM2 or area(sess.geom(j)) > BIG_KM2):
                out.append((i, j))
    return out


def plan_entry(sess, e, cand):
    """Pieces of E's real ranges with the signature (tuple) of newer overlapping entries alive in each."""
    ge = sess.geom(e)
    near = [f for f in cand if f != e and counts(sess, e, f)]
    if not near:
        return None
    pieces = []
    for r in sess.ranges(e):
        if not sess.real(r):
            continue
        bps = {r['frm'], r['to']}
        for f in near:
            for fr in sess.real_ranges(f):
                for v in (fr['frm'], fr['to']):
                    if r['frm'] < v < r['to']:
                        bps.add(v)
        bps = sorted(bps)
        for a, b in zip(bps, bps[1:]):
            if b - a < 1e-9:
                continue
            mid = (a + b) / 2
            sig = tuple(sorted(f for f in near if sess.alive(f, a, b) and sess.newer(f, e, mid)))
            p = {'frm': a, 'to': b, 'sig': sig, 'name': r['name'], 'color': r['color'], 'rid': id(r)}
            if pieces and pieces[-1]['sig'] == sig and pieces[-1]['rid'] == p['rid'] and abs(pieces[-1]['to'] - a) < 1e-9:
                pieces[-1]['to'] = b
            else:
                pieces.append(p)
    return pieces


def as_ranges(ps):
    return [dict(frm=p['frm'], to=p['to'], name=p['name'], color=p['color']) for p in ps]


def process_entry(sess, e, cand, new_entries):
    pieces = plan_entry(sess, e, cand)
    if not pieces:
        return
    ge = sess.geom(e)
    groups, keep, drop = {}, [], []
    for p in pieces:
        if not p['sig']:
            keep.append(p)
            continue
        V = ge.difference(unary_union([sess.geom(f) for f in p['sig']]))
        if area(V) < max(MIN_KM2, SLIVER * area(ge)):
            drop.append(p)
        elif area(ge) - area(V) < MIN_KM2:
            keep.append(p)
        else:
            groups.setdefault(p['sig'], []).append(p)
    if not drop and not groups:
        return
    nonreal = [r for r in sess.ranges(e) if not sess.real(r)]
    kept_ranges = sorted(as_ranges(keep) + nonreal, key=lambda r: r['frm'])
    gl = sorted(groups.items(), key=lambda kv: min(p['frm'] for p in kv[1]))
    has_full = any(sess.real(r) for r in kept_ranges)
    swap_first = (not has_full) and bool(gl)
    first = True
    n_built = 0
    for sig, ps in gl:
        rr = as_ranges(ps)
        win = [(q['frm'], q['to']) for q in ps]
        got = False
        for refs, V in build_remainder_rings(sess, e, list(sig)):
            if refs is None:
                sess.manual.append(f'#{e} minus {["#%d" % f for f in sig]} ({min(q["frm"] for q in ps):g}..{max(q["to"] for q in ps):g}): {V}')
                return
            got = True
            ge = sess.geom(e)
            cutpt = ge.intersection(unary_union([sess.geom(f) for f in sig])).representative_point()
            if swap_first and first:
                sess.set_ranges(e, sorted(rr + nonreal, key=lambda r: r['frm']))
                sess.set_refs(e, refs)
                sess.log.append(f'#{e}: ref swap -> ring of #{e} minus ' + ' & '.join(f'#{f}' for f in sig) + f' ({area(V):.1f} km2), ranges '
                                + ', '.join(f'{x:g}..{y:g}' for x, y in win))
                sess.fixes.append(dict(e=e, sig=sig, windows=win, new=e, kind='swap', pt=cutpt))
            else:
                no = sess.next_no()
                sess.add_entry(no, e, rr, refs)
                new_entries.append(no)
                sess.log.append(f'new #{no} = #{e} minus ' + ' & '.join(f'#{f}' for f in sig) + f' ({area(V):.1f} km2), ranges '
                                + ', '.join(f'{x:g}..{y:g}' for x, y in win))
                sess.fixes.append(dict(e=e, sig=sig, windows=win, new=no, kind='carve', pt=cutpt))
            first = False
            n_built += 1
        if not got:
            drop += ps
    ge = sess.geom(e)
    if not has_full and n_built == 0:
        sess.manual.append(f'#{e} is entirely covered by newer entries for its whole life -> delete #{e} (not done automatically)')
        sess.fixes.append(dict(e=e, sig=(), windows=[(q['frm'], q['to']) for q in drop], new=None, kind='cover',
                               pt=ge.representative_point(), by=sorted({f for q in drop for f in q['sig']})))
        return
    if not swap_first:
        sess.set_ranges(e, kept_ranges)
    if drop:
        sess.log.append(f'#{e}: ' + ', '.join(f'{p["frm"]:g}..{p["to"]:g} dropped (covered by ' + ' & '.join('#%d' % f for f in p['sig']) + ')' for p in drop))
        sess.fixes.append(dict(e=e, sig=(), windows=[(p['frm'], p['to']) for p in drop], new=None, kind='cover',
                               pt=ge.representative_point(), by=sorted({f for p in drop for f in p['sig']})))


def draw_order_fixes(sess, cand, moves):
    """UNKNOWN placeholders are meant to be painted UNDER real polities.  An entry that overlaps a placeholder (in space and while the
    placeholder is UNKNOWN) but sits BEFORE it in the file is blanked by it.  Only the moves you ask for (--move ENTRY:AFTER) are applied;
    every other case is reported as a warning (a short UNKNOWN over a polity may be deliberate)."""
    for e, after in moves:
        unk = [d for d in sess.E[after]['dateRanges'] if d['name'].strip().upper() == 'UNKNOWN']
        wins = [(max(r['frm'], d['from']), min(r['to'], d['to'])) for r in sess.real_ranges(e) for d in unk if min(r['to'], d['to']) - max(r['frm'], d['from']) > MIN_YEARS]
        sess.fixes.append(dict(e=e, sig=(after,), windows=wins or [(r['frm'], r['to']) for r in sess.real_ranges(e)], new=None, kind='order',
                               pt=sess.geom(e).intersection(sess.geom(after)).representative_point()))
    ph = [i for i, e in sess.E.items() if e.get('areaType') == 1 and any(d['name'].strip().upper() == 'UNKNOWN' and d['to'] - d['from'] > MIN_YEARS for d in e['dateRanges'])
          and e.get('polyRefs') and e.get('dotPoint') is None]
    for e in cand:
        if e not in sess.E:
            continue
        for u in ph:
            if u == e or sess.pos(u) < sess.pos(e):
                continue
            unk = [d for d in sess.E[u]['dateRanges'] if d['name'].strip().upper() == 'UNKNOWN' and d['to'] - d['from'] > MIN_YEARS]
            ov = [(max(r['frm'], d['from']), min(r['to'], d['to'])) for r in sess.real_ranges(e) for d in unk if min(r['to'], d['to']) - max(r['frm'], d['from']) > MIN_YEARS]
            if ov and significant(sess, e, u):
                sess.warn.append(f'#{e} is drawn BEFORE UNKNOWN placeholder #{u} and overlaps it ({area(sess.geom(e).intersection(sess.geom(u))):.0f} km2, '
                                 f'{min(o[0] for o in ov):g}..{max(o[1] for o in ov):g}): the placeholder paints over it (blank). Fix: --move {e}:{u}')


def overlaps(sess, cand):
    bps = sorted({v for i in cand for r in sess.real_ranges(i) for v in (r['frm'], r['to'])})
    out = []
    for a, b in zip(bps, bps[1:]):
        if b - a < MIN_YEARS:
            continue
        act = [i for i in cand if sess.alive(i, a, b)]
        for k, i in enumerate(act):
            for j in act[k + 1:]:
                if counts(sess, i, j):
                    out.append((a, b, i, j))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tile', required=True)
    ap.add_argument('--label', default=None)
    ap.add_argument('--stage', default=os.path.join(HERE, 'staging'))
    ap.add_argument('--pre-edits', default=None, help='JSON edit list applied (and recorded) before planning, e.g. an undo of an earlier plan')
    ap.add_argument('--move', action='append', default=[], help='ENTRY:AFTER = move that entry right below another in the file (draw order); repeatable')
    ap.add_argument('--all', action='store_true', help='candidates = every polity entry of the tile (pairs overlapping < 3 years or involving entries > 50,000 km2 are not touched, only reported)')
    ap.add_argument('--big-km2', type=float, default=None, help='raise the giant-entry limit (default 50000 km2) to let a pair of big entries be carved')
    ap.add_argument('--era-rule', action='store_true', help='decide who keeps an overlap by era start (old rule) instead of MAPPER paint order')
    ap.add_argument('--force-pair', action='append', default=[], help='A:B = treat that pair as a real overlay even if it lasts < 10 years (e.g. a 6-year Kassite overlay); repeatable')
    ap.add_argument('--force-entry', action='append', default=[], help='E = every overlap involving entry E counts as real even if short (< 10 yrs); repeatable')
    ap.add_argument('--min-ratio', type=float, default=None, help='an overlap counts when it is >= this fraction of the smaller entry (default 0.05); lower it to catch small slivers/hatching')
    ap.add_argument('--entries', default=None, help='explicit candidate entries (comma list): no auto seeds and no neighbour hop')
    ap.add_argument('--audit-levels', default='HIGH,MED', help='registry-dropped entries rated at these levels count as real polities')
    a = ap.parse_args()
    global BIG_KM2, ERA_RULE, MIN_RATIO
    if a.min_ratio is not None:
        MIN_RATIO = a.min_ratio
    ERA_RULE = a.era_rule
    FORCE_ENTRIES.update(int(v) for v in a.force_entry)
    for fp in a.force_pair:
        x, y = (int(v) for v in fp.split(':'))
        FORCE_PAIRS.add((min(x, y), max(x, y)))
    if a.big_km2:
        BIG_KM2 = a.big_km2
    lat, lon = a.tile.split(':')
    label = a.label or f't{lat}{lon}'
    sess = None
    # candidates: every areaType-1 entry with a real date range, MINUS the ones the registry rules dropped as transients unless the
    # audit (exports/registry_exclusion_audit.csv) rates them HIGH/MED (big or long-lived = real polities the detector wrongly drops)
    audit = {}
    ap_csv = os.path.join(EXPORTS, 'registry_exclusion_audit.csv')
    if os.path.exists(ap_csv):
        for r in csv.DictReader(open(ap_csv, encoding='utf-8-sig')):
            if r['Tile'].replace('/', ':') == a.tile:
                audit[int(r['EntryIndex'])] = r['Suspicion'].split(':')[0]
    levels = set(x.strip().upper() for x in a.audit_levels.split(','))
    sess = Session(lat, lon, a.stage)
    if a.pre_edits:
        for op in json.load(open(a.pre_edits, encoding='utf-8')):
            sess.apply_op(op)
        print(f'applied {len(sess.ops)} pre-edit operations from {a.pre_edits}')
    sess.fix_duplicate_indices()
    for m in a.move:                                      # draw-order moves go FIRST so remainders are inserted under the moved parent
        e_, after_ = (int(x) for x in m.split(':'))
        sess.move_entry(e_, after_)
        sess.log.append(f'draw order: #{e_} moved to right after #{after_} (requested)')
        sess.moved.append((e_, after_))
    # seeds: the detector's entries (overlap groups on the CURRENT data) + the registry-dropped entries the audit rates HIGH/MED;
    # one hop outward: every other polity entry that overlaps a seed (in space and time) joins, so each cluster is planned whole.
    subprocess.run([sys.executable, os.path.join(HERE, 'polity_overlay_report.py'), '--tiles', a.tile, '--from', '-9999', '--to', '9999',
                    '--label', label], capture_output=True, text=True, cwd=HERE)
    det = {int(r['EntryIndex']) for r in csv.DictReader(open(os.path.join(EXPORTS, f'polity_overlays_{label}.csv'), encoding='utf-8-sig'))}
    seeds = sorted(det | {i for i, lv in audit.items() if lv in levels and i in sess.E})
    if a.entries:
        seeds = sorted({int(x) for x in a.entries.split(',')})
    polity = [i for i, e in sess.E.items() if e.get('areaType') in (1, 2) and e.get('dotPoint') is None and e['polyRefs'] and sess.real_ranges(i)]
    def time_overlap(i, j):
        return any(min(r['to'], q['to']) - max(r['frm'], q['frm']) > MIN_YEARS for r in sess.real_ranges(i) for q in sess.real_ranges(j))
    if a.all:
        seeds = sorted(polity)
    cand0 = set(seeds)
    for i in ([] if (a.entries or a.all) else polity):
        if i in cand0 or (i in audit and audit[i] not in levels):
            continue
        if any(time_overlap(i, f) and significant(sess, i, f) for f in seeds if f in sess.E):
            cand0.add(i)
    cand0 = sorted(cand0)
    print(f'seeds {seeds}')
    print(f'candidates (seeds + overlapping neighbours): {len(cand0)}')
    before = overlaps(sess, cand0)
    new_entries = []
    for e in sorted(cand0, key=lambda i: (min((r['frm'] for r in sess.real_ranges(i)), default=9e9), i)):
        process_entry(sess, e, cand0, new_entries)
    cand = sorted(set(cand0) | set(new_entries))
    left = overlaps(sess, cand)
    draw_order_fixes(sess, cand, sess.moved)

    orig = Session.__new__(Session)
    orig.t, orig.E, orig._g = sess.t0, sess.E0, {}
    bps = sorted({v for i in cand for r in sess.real_ranges(i) for v in (r['frm'], r['to'])})
    cov_bad = []
    for x, y in zip(bps, bps[1:]):
        if y - x < MIN_YEARS:
            continue
        g0 = [orig.geom(i) for i in cand0 if i in orig.E and orig.alive(i, x, y)]
        g1 = [sess.geom(i) for i in cand if i in sess.E and sess.alive(i, x, y)]
        u0 = unary_union(g0) if g0 else None
        u1 = unary_union(g1) if g1 else None
        d = area(u0.symmetric_difference(u1)) if (u0 is not None and u1 is not None) else (area(u0) + area(u1))
        if d > 1.0:
            cov_bad.append((round((x + y) / 2, 1), round(d, 1)))

    out_dir = os.path.join(EXPORTS, f'tileplan_{lat}-{lon}')
    os.makedirs(out_dir, exist_ok=True)
    json.dump(sess.ops, open(os.path.join(out_dir, 'edits.json'), 'w', encoding='utf-8'), indent=1)
    L = [f'WHOLE-TILE PLAN {a.tile}   (newer entry takes its area; older entry carved)', '',
         f'{len(sess.ops)} edit operations; candidates {cand0}; overlap windows before: {len(before)}, after: {len(left)}',
         f'POL file header count: {len(sess.t0["pol_by_index"])} -> {len(sess.t["pol_by_index"])};  PAR file header count: {len(sess.t0["par_entries"])} -> {len(sess.t["par_entries"])};  CST file header count: {len(sess.t0["cst_by_index"])} -> {len(sess.t["cst_by_index"])}',
         '', 'POL SPLITS (your notation; new POLs keep the date ranges of the POL they are split from):']
    for pol, nums, pts, oldn, counts in sess.notation:
        if isinstance(pol, str):
            L.append(f"{pol} => {pol[3:]}, " + ', '.join(str(n) for n in nums) + "   (COAST: CST file)")
        else:
            L.append(f"#{pol} => {pol}, " + ', '.join(str(n) for n in nums))
        for p in pts:
            L.append(f" {p[0]:.5f}    {p[1]:.5f}")
        L.append(f"{oldn} > " + ' & '.join(str(c) for c in counts))
    L += ['', 'DECISIONS / STEPS:'] + ['  - ' + l for l in sess.log]
    L += ['', 'PAR EDITS (in order):']
    for op in sess.ops:
        if op['op'] == 'par_set_ranges':
            L.append(f"  #{op['entry']}: ranges = " + '; '.join(f"{r['from']:g}..{r['to']:g} {r['name']}" for r in op['ranges']))
        elif op['op'] == 'par_set_refs':
            L.append(f"  #{op['entry']}: refs = {op['refs']}")
        elif op['op'] == 'par_move':
            L.append(f"  MOVE #{op['entry']} to right after #{op['after']} (draw order)")
        elif op['op'] == 'par_add_entry':
            L.append(f"  NEW #{op['index']} right after #{op['after']}: " + '; '.join(f"{r['from']:g}..{r['to']:g} {r['name']}" for r in op['ranges']) + f" | refs {op['refs']}")
    if sess.manual:
        L += ['', 'NEEDS A HUMAN DECISION:'] + ['  ! ' + m for m in sess.manual]
    if sess.disagree and not ERA_RULE:
        L += ['', 'PAINT ORDER vs OLD ERA RULE disagree for these pairs (paint order = what MAPPER shows was used):'] + [f"  #{f} vs #{e} (first noticed at {t:.1f})" for (_, _), (f, e, t) in sorted(sess.disagree.items())]
    if sess.warn:
        L += ['', 'DRAW-ORDER WARNINGS (not changed):'] + ['  ? ' + m for m in sess.warn]
    sh = short_pairs(sess, cand)
    if sh:
        L += ['', f'SHORT OVERLAPS (< {MIN_PAIR_YEARS:g} yrs without a break; treated as transient-like overlays, NOT touched):'] +              [f"  #{i} x #{j}: {y:.1f} yrs, {area(sess.geom(i).intersection(sess.geom(j))):.0f} km2" for i, j, y in sh]
    sk = skipped_pairs(sess, cand)
    if sk:
        L += ['', f'NOT TOUCHED (overlap >= {MIN_PAIR_YEARS:g} yrs but one entry is a giant > {BIG_KM2:.0f} km2 -- probably intended background/tribal layers):'] +              [f"  #{i} ({area(sess.geom(i)):.0f} km2) x #{j} ({area(sess.geom(j)):.0f} km2)" for i, j in sk]
    L += ['', f'Overlaps left: {len(left)}', 'Coverage (union of polity polygons before vs after, every year): ' + ('identical' if not cov_bad else f'DIFFERENCES {cov_bad[:12]}')]
    open(os.path.join(out_dir, 'plan.txt'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')

    def merge_spans(ws):
        out = []
        for lo, hi in sorted(ws):
            if out and lo <= out[-1][1] + 1e-6:
                out[-1][1] = max(out[-1][1], hi)
            else:
                out.append([lo, hi])
        return out
    by_year = {}
    for f in sess.fixes:
        pt = f.get('pt')
        ll = (round(pt.x, 3), round(pt.y, 3)) if pt is not None and not pt.is_empty else ('', '')
        if f['kind'] == 'order':
            what = f"#{f['e']} now drawn above UNKNOWN placeholder #{f['sig'][0]} (must show its colour, not blank)"
        elif f['kind'] == 'cover':
            what = f"#{f['e']} removed where covered by " + ', '.join('#%d' % x for x in f.get('by', []))
        else:
            what = f"#{f['e']} minus " + ' & '.join('#%d' % x for x in f['sig']) + (f" -> new #{f['new']}" if f['kind'] == 'carve' else ' (ref swap)')
        for lo, hi in merge_spans(f['windows']):
            pts = [(lo - 0.1, 'year just BEFORE the fixed span: must be unchanged (no gap)'),
                   (lo + 0.1, 'first year of the fixed span: no overlay hatching now, area still covered')]
            if hi - lo > 30:
                pts.append(((lo + hi) / 2, 'middle of the fixed span'))
            pts += [(hi, 'last year of the fixed span'), (hi + 0.1, 'year just AFTER the fixed span: unchanged')]
            for yr, tag in pts:
                by_year.setdefault(round(yr, 1), []).append((tag, what, ll))
    rows = []
    for yr in sorted(by_year):
        items = by_year[yr]
        rows.append((yr, ' / '.join(sorted({t for t, _, _ in items})), ' | '.join(sorted({w for _, w, _ in items})), items[0][2][0], items[0][2][1]))
    sy = os.path.join(out_dir, 'salient_years.csv')
    try:
        fh = open(sy, 'w', encoding='utf-8-sig', newline='')
    except PermissionError:                           # (e.g. open in Excel) -> write a numbered copy instead
        n = 2
        while True:
            sy = os.path.join(out_dir, f'salient_years_v{n}.csv')
            try:
                fh = open(sy, 'w', encoding='utf-8-sig', newline='')
                break
            except PermissionError:
                n += 1
    with fh:
        w = csv.writer(fh)
        w.writerow(['ViewYear', 'what to look for', 'fix(es) involved', 'centre lon', 'centre lat'])
        w.writerows(rows)
    print('\n'.join(L))
    print(f'\nwrote {out_dir}\\edits.json, plan.txt, salient_years.csv ({len(rows)} rows); staged in {sess.root}')


if __name__ == '__main__':
    main()
