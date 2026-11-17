"""zoom_scan.py <out_file> -- scan every tile of the status-chart zoom area (lat codes 100-130 x lon 348..045) with
preflight_scan.py + ringcheck.py and write one line per tile:  <lat>/<lon> (entries, pairs, type2, maxkm2, nonedge_ring_jumps)
Non-edge ring jumps = jumps > 0.03 deg whose location is not on the tile boundary (tile = 5 deg, 6 deg for lat code 130)."""
import os, re, sys, subprocess
ROOT = r'C:\My stuff\mapper\polareas'
HERE = os.path.dirname(os.path.abspath(__file__))
env = dict(os.environ, TILE_DATA_DIR=r'C:\My stuff\mapper')
def run(tool, tile):
    return subprocess.run([sys.executable, os.path.join(HERE, tool), tile], capture_output=True, text=True, env=env).stdout
tiles = []
for la in sorted(os.listdir(ROOT)):
    if not la.isdigit() or not 100 <= int(la) <= 130: continue
    for f in sorted(os.listdir(os.path.join(ROOT, la))):
        m = re.fullmatch(r'PAR(\d{3})\.ASC', f)
        if not m: continue
        lo = int(m.group(1)); sl = lo if lo < 180 else lo - 360
        if (int(la) == 130 and -12 <= sl <= 42) or (int(la) != 130 and -10 <= sl <= 45): tiles.append((int(la), lo))
out = open(sys.argv[1], 'w')
for la, lo in tiles:
    t = '%03d/%03d' % (la, lo)
    p = run('preflight_scan.py', t)
    m = re.search(r'entries (\d+)', p); n = int(m.group(1)) if m else -1
    pm = re.search(r'^pairs (\d+)', p, re.M); pairs = int(pm.group(1)) if pm else -1
    t2 = re.search(r'Type2: \[(.*)\]', p); type2 = len(re.findall(r'\(\d+,', t2.group(1))) if t2 else 0
    mx = max([int(x) for x in re.findall(r'max (\d+) km2', p)] or [0])
    w = 6 if la == 130 else 5; x0 = lo if lo < 180 else lo - 360; y1 = la - 85; y0 = y1 - 5
    bad = 0
    for line in run('ringcheck.py', t).splitlines():
        for d, x, y in re.findall(r'(\d+\.\d+) deg at \((-?\d+\.\d+),(-?\d+\.\d+)\)', line):
            x = float(x); y = float(y)
            if x < 0 and lo >= 180: pass
            xx = x if x < 180 else x - 360
            edge = any(abs(xx - e) < 0.003 for e in (x0, x0 + w)) or any(abs(y - e) < 0.003 for e in (y0, y1))
            if float(d) > 0.03 and not edge: bad += 1
    out.write('%s (%d, %d, %d, %d, %d)\n' % (t, n, pairs, type2, mx, bad)); out.flush()
