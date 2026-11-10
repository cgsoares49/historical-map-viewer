"""ringdetail.py <lat/lon> <pre_continuity.json> [out.txt] -- per proposed fix: entry, dates, jump points, shape difference (sym. diff of ring before/after) with zoom box."""
import sys, json, math
sys.path.insert(0, r'C:\My stuff\ClaudeTest\mapper')
import export_polity_polygons as X
la, lo = sys.argv[1].split('/'); ops = json.load(open(sys.argv[2])); out = open(sys.argv[3], 'w') if len(sys.argv) > 3 else None
T = X.load_tile(la, lo); pol = T['pol_by_index']; cst = T['cst_by_index']; rl = [0]
E = {e['entryIndex']: e for e in T['par_entries']}
def say(s=''):
    print(s); 
    if out: out.write(s + '\n')
def refname(pi, fl): return ('POL%d' % (pi-1000) if pi > 1000 else 'CST%d' % pi) + ('(rev)' if fl == 1 else '')
def seg(ref):
    pi, fl = ref
    poly = cst.get(pi) if pi <= 1000 else pol.get(pi-1000)
    pts = poly['points'] if fl == 0 else poly['points'][::-1]
    return pts[0], pts[-1]
def poly(refs):
    r, _ = X.build_combined_ring(refs, cst, pol); return X.ring_to_polygon(r, rl)
for op in ops:
    n = op['entry']; e = E[n]; old = [tuple(r) for r in e['polyRefs']]
    new = [tuple(r) if not isinstance(r, dict) else (r['lit'][0], r['lit'][1]) for r in op['refs']]
    dr = e['dateRanges']; yrs = '; '.join('%g..%g %s' % (d['from'], d['to'], d['name']) for d in dr[:3]) + (' ...' if len(dr) > 3 else '')
    say('#%d  %s' % (n, yrs)); say('   first visible year %g' % (dr[0]['from'] + 0.1))
    say('   refs before: ' + ' '.join(refname(*r) for r in old))
    say('   refs after : ' + ' '.join(refname(*r) for r in new))
    pts = []
    for k in range(len(old)):
        a, b = seg(old[k])[1], seg(old[(k+1) % len(old)])[0]
        d = math.hypot(a[0]-b[0], a[1]-b[1])
        if d > 0.002:
            if abs(a[0]-lo_) if False else False: pass
            say('   JUMP after %s: from (%.4fE %.4fN) to (%.4fE %.4fN)  %.3f deg' % (refname(*old[k]), a[0], a[1], b[0], b[1], d)); pts += [a, b]
    po, pn = poly(old), poly(new)
    sd = po.symmetric_difference(pn)
    if pts:
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        say('   ZOOM BOX: %.3f..%.3fE  %.3f..%.3fN  (centre %.3fE %.3fN)' % (min(xs), max(xs), min(ys), max(ys), (min(xs)+max(xs))/2, (min(ys)+max(ys))/2))
    say('   area %.1f -> %.1f km2;  shape that changes (sym.diff) = %.2f km2%s' % (X.area_km2(po), X.area_km2(pn), X.area_km2(sd), '' if X.area_km2(sd) > 0.05 else '  -> NO visible fill change (retrace only)'))
    if X.area_km2(sd) > 0.05:
        q = sd.representative_point(); say('   changed area near %.3fE %.3fN  bounds %.3f..%.3fE %.3f..%.3fN' % (q.x, q.y, *[sd.bounds[i] for i in (0, 2, 1, 3)]))
    say()
