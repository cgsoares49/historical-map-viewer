"""ringfix.py <lat/lon> [entry# ...]  -- for each discontinuous entry (all if none given) try simple repairs of its ref list and report the ones that make
the ring continuous: single flag flip, adjacent swap, adjacent swap + flips of both, move one ref elsewhere.  Also prints area before/after.
READ-ONLY: proposes; you (or a staged copy) apply."""
import sys, math, itertools
sys.path.insert(0, r'C:\My stuff\ClaudeTest\mapper')
import export_polity_polygons as X
la, lo = sys.argv[1].split('/'); want = set(map(int, sys.argv[2:]))
T = X.load_tile(la, lo); pol = T['pol_by_index']; cst = T['cst_by_index']; rl = [0]
TILE = (float(lo), float(lo) + 5.0, int(la) / 4.0, int(la) / 4.0 + 5.0)
TOL = 0.002
def on_edge(p, t=0.0015): return abs(p[0]-TILE[0])<t or abs(p[0]-TILE[1])<t or abs(p[1]-TILE[2])<t or abs(p[1]-TILE[3])<t
def seg(ref):
    pi, fl = ref
    if fl in (0, 1):
        poly = cst.get(pi) if pi <= 1000 else pol.get(pi - 1000)
        if not poly or not poly['points']: return None
        pts = poly['points'] if fl == 0 else poly['points'][::-1]
        return pts[0], pts[-1]
    lat = 0 if fl == 1000 else fl
    return (pi, lat), (pi, lat)
def jumps(refs):
    s = [seg(r) for r in refs]; s = [x for x in s if x]
    if len(s) < 2: return 0, 0.0
    n = 0; tot = 0.0
    for k in range(len(s)):
        a, b = s[k][1], s[(k+1) % len(s)][0]
        d = math.hypot(a[0]-b[0], a[1]-b[1])
        if d > TOL and not (on_edge(a) and on_edge(b)): n += 1; tot += d
    return n, tot
def area(refs):
    r, _ = X.build_combined_ring(refs, cst, pol); p = X.ring_to_polygon(r, rl)
    return X.area_km2(p) if p is not None and not p.is_empty else 0.0
def name(pi, fl): return ('POL%d' % (pi-1000) if pi > 1000 else 'CST%d' % pi) + ('r' if fl == 1 else '' ) if fl in (0, 1) else 'lit(%g,%g)' % (pi, fl)
for e in T['par_entries']:
    if e['dotPoint'] or not e['polyRefs']: continue
    if want and e['entryIndex'] not in want: continue
    refs = list(e['polyRefs']); n0, t0 = jumps(refs)
    if n0 == 0: continue
    a0 = area(refs); sols = []
    N = len(refs)
    def flip(r): return (r[0], 1 - r[1]) if r[1] in (0, 1) else r
    cands = []
    for i in range(N): 
        x = list(refs); x[i] = flip(x[i]); cands.append(('flip ref %d %s' % (i+1, name(*refs[i])), x))
    for i in range(N-1):
        x = list(refs); x[i], x[i+1] = x[i+1], x[i]; cands.append(('swap refs %d,%d' % (i+1, i+2), x))
        y = list(x); y[i] = flip(y[i]); y[i+1] = flip(y[i+1]); cands.append(('swap refs %d,%d + flip both' % (i+1, i+2), y))
        for fi in (i, i+1):
            z = list(x); z[fi] = flip(z[fi]); cands.append(('swap refs %d,%d + flip one' % (i+1, i+2), z))
    for i in range(N):
        for j in range(N):
            if i == j or abs(i-j) < 2: continue
            x = list(refs); r = x.pop(i); x.insert(j, r); cands.append(('move ref %d to position %d' % (i+1, j+1), x))
    for lab, x in cands:
        n, t = jumps(x)
        if n == 0: sols.append((lab, x, area(x)))
    nm = e['dateRanges'][0]['name'][:24] if e['dateRanges'] else ''
    print('#%d %s [type%d] %d jumps (%.2f deg), area %.1f' % (e['entryIndex'], nm, e['areaType'], n0, t0, a0))
    for lab, x, a in sols[:4]: print('     FIX: %-34s -> area %.1f (%+.1f)' % (lab, a, a - a0))
    if not sols: print('     no simple fix found (needs manual look)')
