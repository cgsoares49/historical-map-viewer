"""ringcheck.py <lat/lon> [tol_deg=0.002] [--swap entry:i:j]
Ring-continuity check for every PAR entry with POL/CST refs: walks the refs in order and reports every place where the END of one
segment (after applying its reverse flag) is not within tol of the START of the next, and where the ring does not close.
An out-of-order POL (e.g. PAR110 #377 refs 8/9 swapped) shows up as two big jumps. Literal 'lon,lat' pairs (flag != 0/1) are treated as points."""
import sys, math
sys.path.insert(0, r'C:\My stuff\ClaudeTest\mapper')
import export_polity_polygons as X, os
X.DATA_DIR = os.environ.get("TILE_DATA_DIR", X.DATA_DIR)
la, lo = sys.argv[1].split('/'); tol = float(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else 0.002
T = X.load_tile(la, lo); pol = T['pol_by_index']; cst = T['cst_by_index']
swap = None
TILE = (float(lo), float(lo) + 5.0, int(la) / 4.0, int(la) / 4.0 + 5.0)   # tile = 5x5 deg; lat label 120 -> 30..35, 125 -> 35..40 (lon label = west edge; NOTE: assumes eastern/northern hemisphere tiles)
if '--swap' in sys.argv:
    swap = tuple(map(int, sys.argv[sys.argv.index('--swap') + 1].split(':')))
E0, E1 = float(lo) - 0.0, float(lo) + 5.0      # tile = 5x5 deg: lon lo..lo+5, lat la-5..la (lat label = southern? see below)
def on_edge(pt, t=0.0015):
    x, y = pt
    return (abs(x - TILE[0]) < t or abs(x - TILE[1]) < t or abs(y - TILE[2]) < t or abs(y - TILE[3]) < t)
bad = 0
for e in T['par_entries']:
    if e['dotPoint'] or not e['polyRefs']: continue
    refs = list(e['polyRefs'])
    if swap and e['entryIndex'] == swap[0]: refs[swap[1]-1], refs[swap[2]-1] = refs[swap[2]-1], refs[swap[1]-1]
    segs = []
    for pi, fl in refs:
        if fl in (0, 1):
            poly = cst.get(pi) if pi <= 1000 else pol.get(pi - 1000)
            if not poly or not poly['points']: continue
            pts = poly['points'] if fl == 0 else list(reversed(poly['points']))
            segs.append(('%s%d' % ('CST' if pi <= 1000 else 'POL', pi if pi <= 1000 else pi - 1000), pts[0], pts[-1]))
        else:
            lat = 0 if fl == 1000 else fl
            segs.append(('lit', (pi, lat), (pi, lat)))
    if len(segs) < 2: continue
    jumps = []
    for k in range(len(segs)):
        a, b = segs[k], segs[(k + 1) % len(segs)]
        d = math.hypot(a[2][0] - b[1][0], a[2][1] - b[1][1])
        if d > tol and not (on_edge(a[2]) and on_edge(b[1])): jumps.append('%s->%s %.3f deg at (%.3f,%.3f)' % (a[0], b[0], d, a[2][0], a[2][1]))
    if jumps:
        bad += 1
        nm = e['dateRanges'][0]['name'][:22] if e['dateRanges'] else ''
        print('#%d %s [type%d]: %d jump(s): %s' % (e['entryIndex'], nm, e['areaType'], len(jumps), '; '.join(jumps[:4])))
print('entries with discontinuities:', bad)
