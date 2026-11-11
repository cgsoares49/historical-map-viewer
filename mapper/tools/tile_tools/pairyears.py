"""pairyears.py <lat/lon> a:b [a:b ...]  -> for each overlapping pair: overlap area, a spot inside it, overlap years, and who is painted there at first/mid/last visible year (verified)."""
import sys
sys.path.insert(0, r'C:\My stuff\ClaudeTest\mapper')
import export_polity_polygons as X, os
X.DATA_DIR = os.environ.get("TILE_DATA_DIR", X.DATA_DIR)
la, lo = sys.argv[1].split('/'); T = X.load_tile(la, lo); pol = T['pol_by_index']; cst = T['cst_by_index']; rl = [0]
E = {e['entryIndex']: e for e in T['par_entries']}
P = {}
def poly(n):
    if n not in P:
        r, _ = X.build_combined_ring(E[n]['polyRefs'], cst, pol); P[n] = X.ring_to_polygon(r, rl)
    return P[n]
def top(pt, yr):
    out = []
    for e in T['par_entries']:
        if e['areaType'] not in (1, 2) or e['dotPoint'] or not e['polyRefs'] or X.is_transient(e['polyRefs'], pol): continue
        dr = X.match_date(e['dateRanges'], yr)
        if dr and 'UNKNOWN' not in dr['name'].upper() and poly(e['entryIndex']).buffer(0).contains(pt): out.append('#%d %s' % (e['entryIndex'], dr['name'][:20]))
    return out
for ab in sys.argv[2:]:
    a, b = map(int, ab.split(':')); i = poly(a).intersection(poly(b)); pt = i.representative_point()
    segs = []
    for da in E[a]['dateRanges']:
        for db in E[b]['dateRanges']:
            lo_, hi_ = max(da['from'], db['from']), min(da['to'], db['to'])
            if hi_ > lo_: segs.append((lo_, hi_))
    segs.sort(); lo_, hi_ = segs[0][0], segs[-1][1]
    print('#%d x #%d: overlap %.0f km2 at %.3fE %.3fN; years %.1f..%.1f (%d segment(s))' % (a, b, X.area_km2(i), pt.x, pt.y, lo_, hi_, len(segs)))
    for yr in sorted({round(lo_ + 0.1, 1), round((lo_ + hi_) / 2, 1), round(hi_, 1)}):
        print('     %8.1f: %s' % (yr, ', '.join(top(pt, yr)) or '(none)'))
