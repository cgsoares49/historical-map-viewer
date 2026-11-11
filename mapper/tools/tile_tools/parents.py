"""parents.py <lat/lon> <entry#> [<entry#> ...]  -> every Type 1 non-transient entry whose polygon overlaps that entry's polygon
during the entry's own date ranges (>=3 km2). Use this to build the --entries list for a plan_tile carve test (planner does NOT auto-find parents)."""
import sys
sys.path.insert(0, r'C:\My stuff\ClaudeTest\mapper')
import export_polity_polygons as X, os
X.DATA_DIR = os.environ.get("TILE_DATA_DIR", X.DATA_DIR)
la, lo = sys.argv[1].split('/'); T = X.load_tile(la, lo); pol = T['pol_by_index']; cst = T['cst_by_index']; rl = [0]
def poly(e):
    r, _ = X.build_combined_ring(e['polyRefs'], cst, pol) if e['polyRefs'] else (None, 0)
    return X.ring_to_polygon(r, rl) if r else None
P = {}
for e in T['par_entries']:
    if e['dotPoint'] or not e['polyRefs'] or X.is_transient(e['polyRefs'], pol): continue
    p = poly(e)
    if p is not None and not p.is_empty: P[e['entryIndex']] = (e, p)
for n in map(int, sys.argv[2:]):
    e0, p0 = P[n]; out = {}
    for i, (e, p) in P.items():
        if i == n or e['areaType'] != 1 or not p.intersects(p0): continue
        ar = X.area_km2(p.intersection(p0))
        if ar < 3: continue
        for d0 in e0['dateRanges']:
            for d in e['dateRanges']:
                lo_, hi_ = max(d0['from'], d['from']), min(d0['to'], d['to'])
                if hi_ > lo_ and 'UNKNOWN' not in d['name'].upper():
                    o = out.setdefault(i, [d['name'][:22], lo_, hi_, ar]); o[1] = min(o[1], lo_); o[2] = max(o[2], hi_)
    print('#%d %s' % (n, [(d['from'], d['to']) for d in e0['dateRanges']][:3]))
    for i, o in sorted(out.items()): print('   #%d %s %.1f..%.1f  %.0f km2' % (i, o[0], o[1], o[2], o[3]))
