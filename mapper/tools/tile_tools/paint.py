"""paint.py <lat/lon tile> <year> <lon> <lat>  -> entries covering the point at that year, file order (last = painted on top).
   Add --rep <entry#> to use that entry's representative point instead of lon lat (year then is first arg after tile)."""
import sys
sys.path.insert(0, r'C:\My stuff\ClaudeTest\mapper')
import export_polity_polygons as X, os
X.DATA_DIR = os.environ.get("TILE_DATA_DIR", X.DATA_DIR)
from shapely.geometry import Point
tile, year = sys.argv[1], float(sys.argv[2])
la, lo = tile.split('/')
T = X.load_tile(la, lo); pol = T['pol_by_index']; cst = T['cst_by_index']; rl = [0]
cache = {}
def poly(e):
    k = e['entryIndex']
    if k not in cache:
        ring, _ = X.build_combined_ring(e['polyRefs'], cst, pol) if e['polyRefs'] else (None, 0)
        cache[k] = X.ring_to_polygon(ring, rl) if ring else None
    return cache[k]
if sys.argv[3] == '--rep':
    n = int(sys.argv[4]); e0 = [e for e in T['par_entries'] if e['entryIndex'] == n][0]
    pt = poly(e0).representative_point()
else:
    pt = Point(float(sys.argv[3]), float(sys.argv[4]))
print('point %.3fE %.3fN year %s' % (pt.x, pt.y, year))
for e in T['par_entries']:
    if e['areaType'] not in (1, 2) or e['dotPoint'] or not e['polyRefs']: continue
    dr = X.match_date(e['dateRanges'], year)
    if not dr: continue
    p = poly(e)
    if p is not None and p.buffer(0).contains(pt):
        print('  #%d type%d %s' % (e['entryIndex'], e['areaType'], dr['name']))
