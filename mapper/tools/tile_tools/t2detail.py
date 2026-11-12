"""t2detail.py <lat/lon> <entry#> -- one entry's area/centre/dates + every other entry overlapping its footprint (type, km2, % of entry, dates).
Set TILE_DATA_DIR to run on a staged copy."""
import sys, os
sys.path.insert(0, r'C:\My stuff\ClaudeTest\mapper')
import export_polity_polygons as X
X.DATA_DIR = os.environ.get("TILE_DATA_DIR", X.DATA_DIR)
la, lo = sys.argv[1].split('/'); n = int(sys.argv[2])
T = X.load_tile(la, lo); pol = T['pol_by_index']; cst = T['cst_by_index']; rl = [0]
E = {e['entryIndex']: e for e in T['par_entries']}
def poly(e):
    r, _ = X.build_combined_ring(e['polyRefs'], cst, pol); return X.ring_to_polygon(r, rl)
p = poly(E[n]); c = p.representative_point(); A = X.area_km2(p)
print('#%d type %s area %.0f km2 centre %.3fE %.3fN bounds %s' % (n, E[n]['areaType'], A, c.x, c.y, tuple(round(b, 3) for b in p.bounds)))
print('dates:', '; '.join('%g..%g %s' % (d['from'], d['to'], d['name']) for d in E[n]['dateRanges']))
for m, e2 in E.items():
    if m == n or e2['areaType'] == 0 or e2['dotPoint'] or not e2['polyRefs']: continue
    try: q = poly(e2)
    except Exception: continue
    if q is None or q.is_empty: continue
    a = X.area_km2(q.intersection(p))
    if a < 1: continue
    tr = ' TRANSIENT' if X.is_transient(e2['polyRefs'], pol) else ''
    print('  #%d type %s%s %.0f km2 (%.0f%%)  %s' % (m, e2['areaType'], tr, a, 100*a/A, '; '.join('%g..%g %s' % (d['from'], d['to'], d['name']) for d in e2['dateRanges'][:6])))
