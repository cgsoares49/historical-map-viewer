"""ownermap.py <lat/lon> <year> <lon0> <lat0> <lon1> <lat1> [cols]  -> ASCII map of the top-painted entry per cell (file order; types 1/2, UNKNOWN shown as '.'; transients skipped)."""
import sys
sys.path.insert(0, r'C:\My stuff\ClaudeTest\mapper')
import export_polity_polygons as X, os
X.DATA_DIR = os.environ.get("TILE_DATA_DIR", X.DATA_DIR)
from shapely.geometry import Point
la, lo = sys.argv[1].split('/'); yr = float(sys.argv[2]); x0, y0, x1, y1 = map(float, sys.argv[3:7]); cols = int(sys.argv[7]) if len(sys.argv) > 7 else 70
T = X.load_tile(la, lo); pol = T['pol_by_index']; cst = T['cst_by_index']; rl = [0]
act = []
for e in T['par_entries']:
    if e['areaType'] not in (1, 2) or e['dotPoint'] or not e['polyRefs'] or X.is_transient(e['polyRefs'], pol): continue
    dr = X.match_date(e['dateRanges'], yr)
    if not dr: continue
    r, _ = X.build_combined_ring(e['polyRefs'], cst, pol); p = X.ring_to_polygon(r, rl) if r else None
    if p is None or p.is_empty or not p.intersects(__import__('shapely.geometry').geometry.box(x0, y0, x1, y1)): continue
    act.append((e['entryIndex'], dr['name'], p))
sym = {}; chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
rows = int(cols * (y1 - y0) / (x1 - x0) * 0.5)
for j in range(rows):
    y = y1 - (j + .5) * (y1 - y0) / rows; line = ''
    for i in range(cols):
        x = x0 + (i + .5) * (x1 - x0) / cols; top = None
        for n, nm, p in act:
            if p.contains(Point(x, y)): top = (n, nm)
        if top is None or 'UNKNOWN' in top[1].upper(): line += '.'
        else:
            if top[0] not in sym: sym[top[0]] = (chars[len(sym) % len(chars)], top[1])
            line += sym[top[0]][0]
    print(line)
print('lon %.2f..%.2f lat %.2f..%.2f year %s' % (x0, x1, y0, y1, yr))
for n, (c, nm) in sym.items(): print(c, '#%d %s' % (n, nm))
