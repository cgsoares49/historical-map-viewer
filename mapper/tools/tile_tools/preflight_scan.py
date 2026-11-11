import sys, collections
sys.path.insert(0, r'C:\My stuff\ClaudeTest\mapper')
import export_polity_polygons as X, os
X.DATA_DIR = os.environ.get("TILE_DATA_DIR", X.DATA_DIR)
from shapely.strtree import STRtree
lat, lon = sys.argv[1].split('/')
lo = float(sys.argv[2]) if len(sys.argv) > 2 else -2100
hi = float(sys.argv[3]) if len(sys.argv) > 3 else 0
minkm = float(sys.argv[4]) if len(sys.argv) > 4 else 3
T = X.load_tile(lat, lon)
ents = T['par_entries']; pol = T['pol_by_index']; cst = T['cst_by_index']
idxs = [e['entryIndex'] for e in ents]
print('entries', len(ents), 'dups', [i for i,c in collections.Counter(idxs).items() if c>1],
      'missing', sorted(set(range(1, max(idxs)+1)) - set(idxs)))
print('types', collections.Counter(e['areaType'] for e in ents), 'POL', len(pol), 'CST', len(cst))
print('Type2:', [(e['entryIndex'], e['dateRanges'][0]['name'][:25]) for e in ents if e['areaType']==2])
print('type1 dots:', [(e['entryIndex'], e['dateRanges'][0]['name'][:25]) for e in ents if e['areaType']==1 and e['dotPoint']])
polys = {}
rl = [0]
for e in ents:
    if e['areaType'] != 1 or e['dotPoint'] or not e['polyRefs']: continue
    if X.is_transient(e['polyRefs'], pol): continue
    ring, _h = X.build_combined_ring(e["polyRefs"], cst, pol)
    p = X.ring_to_polygon(ring, rl) if ring else None
    if p is None or p.is_empty: continue
    polys[e['entryIndex']] = (e, p)
bps = sorted({d[k] for e,_ in polys.values() for d in e['dateRanges'] for k in ('from','to') if lo <= d[k] <= hi})
bps = [b for b in bps if b > -9990]
found = {}
for a, b in zip(bps, bps[1:]):
    y = (a+b)/2
    act = []
    for i,(e,p) in polys.items():
        dr = X.match_date(e['dateRanges'], y)
        if dr and 'UNKNOWN' not in dr['name'].upper(): act.append((i, dr['name'], p))
    tree = STRtree([x[2] for x in act])
    for ai,(i,n,p) in enumerate(act):
        for j in tree.query(p):
            if j <= ai: continue
            k, n2, q = act[j]
            ar = X.area_km2(p.intersection(q))
            if ar >= minkm:
                f = found.setdefault((i,k), [n,n2,a,b,ar,0])
                f[3] = b; f[4] = max(f[4], ar)
print('pairs', len(found))
for (i,k),f in sorted(found.items(), key=lambda kv: kv[1][2]):
    print('#%d %s x #%d %s  %.1f..%.1f (%.1fy) max %.0f km2' % (i,f[0][:28],k,f[1][:28],f[2],f[3],f[3]-f[2],f[4]))
