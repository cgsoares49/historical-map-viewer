"""build_tile_status.py <out_dir>  -- rebuild the data behind the 'MAPPER tile status' artifact page.

Writes <out_dir>/tile_status.json  (tile -> {status, text}).  Fill the HTML with tile_status_template.html (same folder):
    html = template.replace('__DATA__', json.dumps(data))   then publish with the Artifact tool.

Evidence used (edit the sets below as blocks get finished):
  * China block (lat codes 110-125 x lon 095-125, lat 130 x lon 096-126)  -> 'finished' / 'accepted' (user: China done 2026-11-13)
  * Asia block (lat codes 95-125 x lon 50-95) -> from mapper/exports/asia_block_scan_*.txt (+ ringcheck + registry audit files)
  * everything else -> markers in mapper/exports (targeted*, tileplan_*, borders_sheet_sync_*, polity_overlay_candidates_*)
Statuses: finished, accepted, todo_pairs, todo_scanned, worked, detector, none.
"""
import os, re, sys, json, csv

MAPPER = r'C:\my stuff\claudetest\mapper'
EX = os.path.join(MAPPER, 'exports')
ROOT = r'C:\My stuff\mapper\polareas'
out_dir = sys.argv[1] if len(sys.argv) > 1 else '.'

ACCEPTED = {'120/110': 25, '125/115': 14, '125/110': 1, '130/114': 1, '125/100': 1}   # leftover pairs the user accepted
FINISHED_SINCE = {'125/050'}        # Asia-block tiles finished so far (add each as it is cleared)
ASIA_SCAN = 'asia_block_scan_2026-11-13.txt'
ASIA_RING = 'asia_block_ringcheck_2026-11-13.txt'
ASIA_REG = 'asia_block_registry_audit_2026-11-13.csv'


def tid(la, lo):
    return '%03d/%03d' % (la, lo)


tiles = []
for la in sorted(os.listdir(ROOT)):
    if la.isdigit():
        for f in os.listdir(os.path.join(ROOT, la)):
            m = re.fullmatch(r'PAR(\d{3})\.ASC', f)
            if m:
                tiles.append((int(la), int(m.group(1))))

markers = {}
for n in os.listdir(EX):
    for pat, kind in ((r'targeted(\d{2,3})_(\d{3})', 'targeted'), (r'tileplan_(\d{2,3})-(\d{3})', 'tileplan'),
                      (r'borders_sheet_sync_(\d{2,3})-(\d{3})\.tsv', 'borders'),
                      (r'polity_overlay_candidates_(\d{2,3})-(\d{3})\.csv', 'candidates')):
        m = re.fullmatch(pat, n)
        if m:
            markers.setdefault(tid(int(m.group(1)), int(m.group(2))), set()).add(kind)

asia = {}
for l in open(os.path.join(EX, ASIA_SCAN)):
    m = re.match(r'(\S+) \((-?\d+), (-?\d+), (\d+), (\d+)\)', l)
    if m:
        asia[m.group(1)] = dict(entries=int(m.group(2)), pairs=int(m.group(3)), type2=int(m.group(4)), maxkm2=int(m.group(5)))
ring = {}
for l in open(os.path.join(EX, ASIA_RING)):
    m = re.match(r'(\d{3}/\d{3}) (\d+)$', l.strip())
    if m:
        ring[m.group(1)] = int(m.group(2))
reg = {}
for r in csv.DictReader(open(os.path.join(EX, ASIA_REG), encoding='utf-8-sig')):
    reg.setdefault(r['Tile'], []).append('#%s %s (%s km2, %sy)' % (r['EntryIndex'], r['Name'], r['AreaKm2'], r['LifeYears']))

out = {}
for la, lo in tiles:
    t = tid(la, lo)
    in_china = (la in (110, 115, 120, 125) and 95 <= lo <= 125) or (la == 130 and 96 <= lo <= 126)
    in_asia = 95 <= la <= 125 and 50 <= lo <= 95
    mk = markers.get(t, set())
    if in_china:
        p = ACCEPTED.get(t, 0)
        out[t] = dict(status='accepted' if p else 'finished',
                      text='China, finished.' if not p else 'China, finished; %d leftover pair(s) accepted by you.' % p)
    elif in_asia:
        if t in FINISHED_SINCE:
            out[t] = dict(status='finished', text='Cleared (see exports/targeted%s_%s).' % (t[:3], t[4:]))
            continue
        a = asia.get(t)
        bits = []
        if a:
            bits.append('%d entries' % a['entries'])
            bits.append('%d overlap pair(s)' % a['pairs'] + (' (largest %d km2)' % a['maxkm2'] if a['pairs'] else ''))
            if a['type2']:
                bits.append('%d Type 2 to review' % a['type2'])
        if ring.get(t):
            bits.append('%d possible ring gap(s)' % ring[t])
        if reg.get(t):
            bits.append('registry drops: ' + '; '.join(reg[t]))
        out[t] = dict(status='todo_pairs' if (a and a['pairs'] > 0) else 'todo_scanned', text='Asia block, to do. ' + ', '.join(bits) + '.')
    else:
        if mk:
            worked = bool(mk & {'tileplan', 'borders', 'targeted'})
            out[t] = dict(status='worked' if worked else 'detector',
                          text='Earlier sessions: plan/borders files exist.' if worked else 'Only the overlay detector has run; not worked.')
        else:
            out[t] = dict(status='none', text='No work or scan on record.')

os.makedirs(out_dir, exist_ok=True)
json.dump(out, open(os.path.join(out_dir, 'tile_status.json'), 'w'))
from collections import Counter
print(Counter(v['status'] for v in out.values()))
