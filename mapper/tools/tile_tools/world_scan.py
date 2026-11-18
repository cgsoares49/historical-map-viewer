"""world_scan.py <out_file> [workers] -- run preflight_scan.py (pairs between polities, years -2100..0 only, so modern-only overlaps never show)
over EVERY tile that has a PAR file and write one line per tile:  <lat>/<lon> (entries, pairs, ancient_type2, maxkm2)
Empty tiles (6-byte PAR) are skipped.  ancient_type2 = Type 2 entries whose first date range starts before year 0."""
import os, re, sys, subprocess
from concurrent.futures import ThreadPoolExecutor
ROOT = r'C:\My stuff\mapper\polareas'
HERE = os.path.dirname(os.path.abspath(__file__))
env = dict(os.environ, TILE_DATA_DIR=r'C:\My stuff\mapper')
tiles = []
for la in sorted(os.listdir(ROOT)):
    if not la.isdigit(): continue
    for f in sorted(os.listdir(os.path.join(ROOT, la))):
        m = re.fullmatch(r'PAR(\d{3})\.ASC', f)
        if m and os.path.getsize(os.path.join(ROOT, la, f)) > 20: tiles.append('%s/%s' % (la, m.group(1)))
def scan(t):
    p = subprocess.run([sys.executable, os.path.join(HERE, 'preflight_scan.py'), t], capture_output=True, text=True, env=env).stdout
    m = re.search(r'entries (\d+)', p); n = int(m.group(1)) if m else -1
    pm = re.search(r'^pairs (\d+)', p, re.M); pairs = int(pm.group(1)) if pm else -1
    mx = max([int(x) for x in re.findall(r'max (\d+) km2', p)] or [0])
    return '%s (%d, %d, %d)' % (t, n, pairs, mx) + '\n' + ''.join(l + '\n' for l in p.splitlines() if l.startswith('#') and ' x #' in l)
out = open(sys.argv[1], 'w')
with ThreadPoolExecutor(int(sys.argv[2]) if len(sys.argv) > 2 else 4) as ex:
    for r in ex.map(scan, tiles):
        out.write(r); out.flush()
out.write('DONE %d tiles\n' % len(tiles))
