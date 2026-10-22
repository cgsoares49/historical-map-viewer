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
        self.T = SE.Tile(os.path.join(self.root, self.rel['par']), os.path.join(self.root, self.rel['pol']))
        self.ops, self.manual, self.fixes, self.log, self.notation = [], [], [], [], []
        self.sync()
        self.t0 = self.t
        self.E0 = self.E

    def sync(self):
        self.T.finish()
        SE.write_lines(os.path.join(self.root, self.rel['par']), self.T.par)
        SE.write_lines(os.path.join(self.root, self.rel['pol']), self.T.pol)
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
        """start of the continuous era of entry i that contains time t (consecutive real ranges, gaps < 1 yr, joined)."""
        rs = sorted(self.real_ranges(i), key=lambda r: r['frm'])
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
        """is f newer than e at time t? (later start of the current era; equal: the smaller polygon is the newer)"""
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
                if g.geom_type == 'Point':
                    nodes.add((g.x, g.y))
                elif g.geom_type == 'LineString':
                    c = list(g.coords)
                    nodes.add(c[0])
                    nodes.add(c[-1])
                elif hasattr(g, 'geoms'):
                    for h in g.geoms:
                        if h.geom_type == 'Point':
                            nodes.add((h.x, h.y))
                        elif h.geom_type == 'LineString':
                            c = list(h.coords)
                            nodes.add(c[0])
                            nodes.add(c[-1])
    return nodes


def split_at_nodes(sess, entries, nodes, tol=1e-5):
    out = []
    for node in sorted(nodes):
        for pi, pts in source_polylines(sess, entries):
            if pi <= 1000:
                continue                                   # coastlines are never split
            line = LineString(pts)
            if line.distance(Point(node)) > tol:
                continue
            if any(Point(q).distance(Point(node)) < tol for q in pts):
                continue
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


def build_remainder_ring(sess, e, subs):
    nodes = nodes_between(sess, e, subs)
    split_at_nodes(sess, [e] + list(subs), nodes)
    V = sess.geom(e).difference(unary_union([sess.geom(f) for f in subs]))
    for attempt in range(4):
        if V.geom_type != 'Polygon':
            parts = [g for g in getattr(V, 'geoms', []) if g.geom_type == 'Polygon' and area(g) > MIN_KM2]
            if len(parts) != 1:
                return None, f'remainder is not one polygon ({V.geom_type}, {len(parts)} parts)'
            V = parts[0]
        if len(V.interiors):
            return None, f'remainder has {len(V.interiors)} hole(s)'
        refs, cuts = trace_ring(sess, e, subs, V)
        if refs is None:
            return None, cuts
        if not cuts:
            g = sess.geom_of_refs(refs)
            if area(g.symmetric_difference(V)) > max(1.0, area(V) * 0.002):
                return None, f'traced ring does not reproduce the remainder ({area(g):.1f} vs {area(V):.1f} km2)'
            return refs, V
        did = False
        for pi, vs in cuts.items():
            tab = sess.t['pol_by_index'].get(pi - 1000)
            if not tab:
                return None, f'cannot split coastline CST{pi}'
            ends = {key(tab['points'][0]), key(tab['points'][-1])}
            pts = sorted({key(p) for p in vs} - ends)
            if pts:
                sess.pol_split(pi - 1000, pts)
                did = True
        if not did:
            return None, 'a run uses part of a POL but no interior vertex to split at'
        V = sess.geom(e).difference(unary_union([sess.geom(f) for f in subs]))
    return None, 'ring tracing did not converge'


# ── planning ────────────────────────────────────────────────────────────────
def plan_entry(sess, e, cand):
    """Pieces of E's real ranges with the signature (tuple) of newer overlapping entries alive in each."""
    ge = sess.geom(e)
    near = [f for f in cand if f != e and area(sess.geom(f).intersection(ge)) > MIN_KM2]
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
        if area(V) < MIN_KM2:
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
    built = []
    for sig, ps in gl:
        refs, V = build_remainder_ring(sess, e, list(sig))
        if refs is None:
            sess.manual.append(f'#{e} minus {["#%d" % f for f in sig]} ({min(p["frm"] for p in ps):g}..{max(p["to"] for p in ps):g}): {V}')
            return
        built.append((sig, ps, refs, V))
    ge = sess.geom(e)
    has_full = any(sess.real(r) for r in kept_ranges)
    if not has_full and not built:
        sess.manual.append(f'#{e} is entirely covered by newer entries for its whole life -> delete #{e} (not done automatically)')
        sess.fixes.append(dict(e=e, sig=(), windows=[(p['frm'], p['to']) for p in drop], new=None, kind='cover',
                               pt=ge.representative_point(), by=sorted({f for p in drop for f in p['sig']})))
        return
    swap_first = (not has_full) and bool(built)
    first = True
    for sig, ps, refs, V in built:
        rr = as_ranges(ps)
        win = [(p['frm'], p['to']) for p in ps]
        cutpt = ge.intersection(unary_union([sess.geom(f) for f in sig])).representative_point()
        if swap_first and first:
            sess.set_ranges(e, sorted(rr + nonreal, key=lambda r: r['frm']))
            sess.set_refs(e, refs)
            sess.log.append(f'#{e}: ref swap -> ring of #{e} minus ' + ' & '.join(f'#{f}' for f in sig) + f' ({area(V):.1f} km2), ranges '
                            + ', '.join(f'{a:g}..{b:g}' for a, b in win))
            sess.fixes.append(dict(e=e, sig=sig, windows=win, new=e, kind='swap', pt=cutpt))
        else:
            no = sess.next_no()
            sess.add_entry(no, e, rr, refs)
            new_entries.append(no)
            sess.log.append(f'new #{no} = #{e} minus ' + ' & '.join(f'#{f}' for f in sig) + f' ({area(V):.1f} km2), ranges '
                            + ', '.join(f'{a:g}..{b:g}' for a, b in win))
            sess.fixes.append(dict(e=e, sig=sig, windows=win, new=no, kind='carve', pt=cutpt))
        first = False
    if not swap_first:
        sess.set_ranges(e, kept_ranges)
    if drop:
        sess.log.append(f'#{e}: ' + ', '.join(f'{p["frm"]:g}..{p["to"]:g} dropped (covered by ' + ' & '.join('#%d' % f for f in p['sig']) + ')' for p in drop))
        sess.fixes.append(dict(e=e, sig=(), windows=[(p['frm'], p['to']) for p in drop], new=None, kind='cover',
                               pt=ge.representative_point(), by=sorted({f for p in drop for f in p['sig']})))


def overlaps(sess, cand):
    bps = sorted({v for i in cand for r in sess.real_ranges(i) for v in (r['frm'], r['to'])})
    out = []
    for a, b in zip(bps, bps[1:]):
        if b - a < MIN_YEARS:
            continue
        act = [i for i in cand if sess.alive(i, a, b)]
        for k, i in enumerate(act):
            for j in act[k + 1:]:
                if area(sess.geom(i).intersection(sess.geom(j))) > MIN_KM2:
                    out.append((a, b, i, j))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tile', required=True)
    ap.add_argument('--label', default=None)
    ap.add_argument('--stage', default=os.path.join(HERE, 'staging'))
    a = ap.parse_args()
    lat, lon = a.tile.split(':')
    label = a.label or f't{lat}{lon}'
    subprocess.run([sys.executable, os.path.join(HERE, 'polity_overlay_report.py'), '--tiles', a.tile, '--from', '-9999', '--to', '9999',
                    '--label', label], capture_output=True, text=True, cwd=HERE)
    cand0 = sorted({int(r['EntryIndex']) for r in csv.DictReader(open(os.path.join(EXPORTS, f'polity_overlays_{label}.csv'), encoding='utf-8-sig'))})
    print('candidate entries (detector):', cand0)
    sess = Session(lat, lon, a.stage)
    before = overlaps(sess, cand0)
    new_entries = []
    for e in sorted(cand0, key=lambda i: (min((r['frm'] for r in sess.real_ranges(i)), default=9e9), i)):
        process_entry(sess, e, cand0, new_entries)
    cand = sorted(set(cand0) | set(new_entries))
    left = overlaps(sess, cand)

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
         f'POL file header count: {len(sess.t0["pol_by_index"])} -> {len(sess.t["pol_by_index"])};  PAR file header count: {len(sess.t0["par_entries"])} -> {len(sess.t["par_entries"])}',
         '', 'POL SPLITS (your notation; new POLs keep the date ranges of the POL they are split from):']
    for pol, nums, pts, oldn, counts in sess.notation:
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
        elif op['op'] == 'par_add_entry':
            L.append(f"  NEW #{op['index']} right after #{op['after']}: " + '; '.join(f"{r['from']:g}..{r['to']:g} {r['name']}" for r in op['ranges']) + f" | refs {op['refs']}")
    if sess.manual:
        L += ['', 'NEEDS A HUMAN DECISION:'] + ['  ! ' + m for m in sess.manual]
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
        if f['kind'] == 'cover':
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
    with open(os.path.join(out_dir, 'salient_years.csv'), 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['ViewYear', 'what to look for', 'fix(es) involved', 'centre lon', 'centre lat'])
        w.writerows(rows)
    print('\n'.join(L))
    print(f'\nwrote {out_dir}\\edits.json, plan.txt, salient_years.csv ({len(rows)} rows); staged in {sess.root}')


if __name__ == '__main__':
    main()
