"""ringfix_stage.py <lat/lon> [--apply] [entry# ...]
Works on the STAGED copy (env TILE_DATA_DIR must point at it, e.g. mapper/staging/120-110) -- never canonical.
For every ring gap (end of ref i != start of ref i+1, tile-edge jumps ignored) it searches for 1 or 2 existing POL/CST segments that bridge
the gap and inserts them as new refs (count line bumped). Without --apply it only prints the proposals (use that on canonical-sourced data too).
Found 2026-11-11: plan_tile's ring trace can drop tiny closing segments at POL splits (120/110 POL544/POL788); this repairs them."""
import sys, math, os, re
sys.path.insert(0, r'C:\My stuff\ClaudeTest\mapper')
import export_polity_polygons as X, stage_edits as S
if not os.environ.get('TILE_DATA_DIR'):
    sys.exit('ringfix_stage: set TILE_DATA_DIR to the STAGED copy (refuses to run on canonical data)')
X.DATA_DIR = os.environ['TILE_DATA_DIR']
if os.path.normpath(X.DATA_DIR).lower() == os.path.normpath(r'C:\My stuff\mapper').lower():
    sys.exit('ringfix_stage: refusing to touch canonical data')
la, lo = sys.argv[1].split('/'); apply_ = '--apply' in sys.argv; want = {int(a) for a in sys.argv[2:] if a.isdigit()}
TOL = 0.0015; GAP = 0.002
T = X.load_tile(la, lo); pol = T['pol_by_index']; cst = T['cst_by_index']
TILE = (float(lo), float(lo) + 5.0, int(la) / 4.0, int(la) / 4.0 + 5.0)
def edge(p, t=0.0015): return abs(p[0]-TILE[0])<t or abs(p[0]-TILE[1])<t or abs(p[1]-TILE[2])<t or abs(p[1]-TILE[3])<t
def d(a, b): return math.hypot(a[0]-b[0], a[1]-b[1])
segs = {}
for k, v in pol.items(): segs[1000 + k] = (v['points'][0], v['points'][-1])
for k, v in cst.items(): segs[k] = (v['points'][0], v['points'][-1])
def ends(pi, fl):
    if fl in (0, 1):
        a, b = segs[pi]; return (a, b) if fl == 0 else (b, a)
    lat = 0 if fl == 1000 else fl; return (pi, lat), (pi, lat)
def bridge(A, B):
    best = None
    for pi, (p, q) in segs.items():
        for fl, (s, e) in ((0, (p, q)), (1, (q, p))):
            if d(s, A) < TOL and d(e, B) < TOL:
                c = (d(s, A) + d(e, B), [(pi, fl)]); best = min(best, c) if best else c
            if d(s, A) < TOL:
                for pj, (p2, q2) in segs.items():
                    if pj == pi: continue
                    for fl2, (s2, e2) in ((0, (p2, q2)), (1, (q2, p2))):
                        if d(s2, e) < TOL and d(e2, B) < TOL:
                            c = (d(s, A) + d(s2, e) + d(e2, B), [(pi, fl), (pj, fl2)]); best = min(best, c) if best else c
    return best
path = os.path.join(X.DATA_DIR, 'polareas', la, 'PAR%s.ASC' % lo)
L = S.read_lines(path); ents, _ = S.parse_par(L)
plan = []
for e in X.load_tile(la, lo)['par_entries']:
    if e['dotPoint'] or not e['polyRefs'] or (want and e['entryIndex'] not in want): continue
    refs = e['polyRefs']
    if len(refs) < 2: continue
    for i in range(len(refs)):
        A = ends(*refs[i])[1]; B = ends(*refs[(i+1) % len(refs)])[0]
        if d(A, B) > GAP and not (edge(A) and edge(B)):
            br = bridge(A, B)
            plan.append((e['entryIndex'], i, len(refs), A, B, br))
for n, i, N, A, B, br in plan:
    print('#%d gap after ref %d: (%.4f,%.4f)->(%.4f,%.4f) %.3f deg: %s' % (n, i + 1, A[0], A[1], B[0], B[1], d(A, B), ('insert ' + ' '.join('%s%d%s' % ('POL' if p > 1000 else 'CST', p - 1000 if p > 1000 else p, 'r' if f else '') for p, f in br[1])) if br else 'NO BRIDGE FOUND'))
if apply_:
    done = {}
    byent = {}
    for n, i, N, A, B, br in plan:
        if br: byent.setdefault(n, []).append((i, N, br[1]))
    for n in sorted(byent, key=lambda n: -[e for e in ents if e['index'] == n][0]['start']):
        e = [e for e in ents if e['index'] == n][0]; add = 0
        for i, N, ins in sorted(byent[n], key=lambda t: -t[0]):
            pos = e['refs_start'] + i + 1
            L[pos:pos] = ['   %d  ,  %d' % (p, f) for p, f in ins]; add += len(ins)
        L[e['nref_line']] = L[e['nref_line']].replace(str(e['nref']), str(e['nref'] + add), 1)
    S.write_lines(path, L); print('applied to', path)
