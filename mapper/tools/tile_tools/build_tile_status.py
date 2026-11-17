"""build_tile_status.py <out_dir>  -- rebuild the data behind the 'MAPPER tile status' artifact page.

Writes <out_dir>/tile_status.json  (tile -> {status, text}).  Fill the HTML with tile_status_template.html (same folder):
    html = template.replace('__DATA__', json.dumps(data))   then publish with the Artifact tool.

Evidence used (edit the sets below as blocks get finished):
  * China block (lat codes 110-125 x lon 095-125, lat 130 x lon 096-126)  -> 'finished' / 'accepted' (user: China done 2026-11-13)
  * Asia block (lat codes 95-125 x lon 50-95) -> from mapper/exports/asia_block_scan_*.txt (+ ringcheck + registry audit files)
  * everything else -> markers in mapper/exports (targeted*, tileplan_*, borders_sheet_sync_*, polity_overlay_candidates_*)
Statuses: finished (REVIEWED WITH THE USER), accepted, preflight (automated scan clean only, NOT yet reviewed with the user), todo_pairs, todo_scanned, worked, detector, none.
"""
import os, re, sys, json, csv

MAPPER = r'C:\my stuff\claudetest\mapper'
EX = os.path.join(MAPPER, 'exports')
ROOT = r'C:\My stuff\mapper\polareas'
out_dir = sys.argv[1] if len(sys.argv) > 1 else '.'

ACCEPTED = {'120/110': 25, '125/115': 14, '125/110': 1, '130/114': 1, '125/100': 1}   # leftover pairs the user accepted
FINISHED_SINCE = {'125/050', '125/055', '125/060', '125/065', '125/070', '125/075', '125/080', '125/085', '125/090', '125/095', '120/095', '120/090', '120/085', '120/080', '120/075', '120/070', '120/065', '120/060', '120/055', '120/050', '115/050', '115/055', '115/060', '115/065', '115/070', '115/075', '115/080', '115/085', '115/090', '115/095', '110/095', '110/090', '110/085', '110/080', '110/075', '110/070', '110/065', '110/060', '110/055', '110/050', '105/050', '105/055', '105/060', '105/065', '105/070', '105/075', '105/080', '105/085', '100/080', '100/075', '100/070', '095/075', '095/080', '100/045', '105/045', '110/045', '115/045', '120/045', '100/040', '105/040', '110/040', '115/040', '120/040', '125/040', '130/036', '130/042', '100/035', '105/035', '110/035', '115/035', '120/035', '125/035', '130/030', '100/030', '105/030', '110/030', '115/030', '120/030', '125/030', '100/025', '105/025', '110/025', '115/025', '120/025', '125/025', '130/024', '100/020', '105/020', '110/020', '115/020', '120/020', '125/020', '130/018', '125/015', '130/012', '100/015', '105/015', '110/015', '115/015', '120/015', '100/010', '105/010', '110/010', '115/010', '120/010', '115/005', '120/005'}        # Asia-block tiles REVIEWED WITH THE USER (add only after the user has confirmed; automated scans alone do NOT count)
ZOOM_SCAN = 'zoom_scan_2026-11-17.txt'     # tools/tile_tools/zoom_scan.py: lat codes 100-130 x lon 348..045
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
zoom = {}
if os.path.exists(os.path.join(EX, ZOOM_SCAN)):
    for l in open(os.path.join(EX, ZOOM_SCAN)):
        m = re.match(r'(\S+) \((-?\d+), (-?\d+), (\d+), (\d+), (\d+)\)', l)
        if m:
            zoom[m.group(1)] = dict(entries=int(m.group(2)), pairs=int(m.group(3)), type2=int(m.group(4)), maxkm2=int(m.group(5)), ring=int(m.group(6)))
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
    in_asia = 95 <= la <= 125 and 50 <= lo <= 95
    china_block = (la in (110, 115, 120, 125) and 95 <= lo <= 125) or (la == 130 and 96 <= lo <= 126)
    in_china = china_block and not in_asia      # Asia-block tiles (lon 95) count only once reviewed with the user, even if China work assumed them done
    mk = markers.get(t, set())
    if in_china:
        p = ACCEPTED.get(t, 0)
        out[t] = dict(status='accepted' if p else 'finished',
                      text='China, finished.' if not p else 'China, finished; %d leftover pair(s) accepted by you.' % p)
    elif t in FINISHED_SINCE:
        out[t] = dict(status='finished', text='Reviewed with you and confirmed done (see exports/targeted%s_%s).' % (t[:3], t[4:]))
    elif in_asia:
        if t in FINISHED_SINCE:
            out[t] = dict(status='finished', text='Reviewed with you and confirmed done (see exports/targeted%s_%s).' % (t[:3], t[4:]))
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
        auto_clean = bool(a) and a['pairs'] == 0 and a['type2'] == 0 and not ring.get(t) and not reg.get(t)
        if auto_clean:
            out[t] = dict(status='preflight', text='Asia block: automated scan clean (%d entries, 0 pairs, 0 Type 2, 0 ring gaps, no registry drops). NOT yet reviewed with you.' % a['entries'] + (' China work had assumed this tile done; it still needs a fresh check.' if china_block else ''))
        else:
            out[t] = dict(status='todo_pairs' if (a and a['pairs'] > 0) else 'todo_scanned', text='Asia block, to do. ' + ', '.join(bits) + '.')
    elif t in zoom:
        z = zoom[t]
        bits = ['%d entries' % z['entries'], '%d overlap pair(s)' % z['pairs'] + (' (largest %d km2)' % z['maxkm2'] if z['pairs'] else ''),
                '%d Type 2' % z['type2'], '%d non-edge ring jump(s)' % z['ring']]
        sc = 'Scan 17 Nov 2026: ' + ', '.join(bits) + '.'
        if mk & {'tileplan', 'borders', 'targeted'}:
            out[t] = dict(status='worked', text='Worked in earlier sessions (plan or borders files exist). ' + sc + ' Leftovers may be ones you accepted earlier.')
        elif z['pairs'] == 0 and z['type2'] == 0 and z['ring'] == 0:
            out[t] = dict(status='preflight', text='Zoom area. ' + sc + ' Automated scan clean; NOT yet reviewed with you.')
        else:
            out[t] = dict(status='todo_pairs' if z['pairs'] > 0 else 'todo_scanned', text='Zoom area, to do. ' + sc)
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
