"""
export_geodata_csv.py
Reads ALL entries from js/geodata.js (hand-curated + PAR-derived), joins
with refs.json for WHE and Wikipedia URLs, and writes refs_export.csv.

Columns: Search Term, Date From, Date To, Center Lat, Center Lon,
         WHE 1, WHE 2, Wiki 1, Wiki 2
Dates: plain integers; negative = BC; blank if no date; 1990 for modern sentinel.
Centroids: from entry[6]/[7] if present (PAR entries after Step 4+5), else bbox midpoint.
"""

import os, re, json, csv

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
GEODATA_JS = os.path.join(MAPPER_DIR, 'js', 'geodata.js')
REFS_JSON  = os.path.join(MAPPER_DIR, 'refs.json')
OUT_CSV    = os.path.join(MAPPER_DIR, 'refs_export.csv')

# ── Parse geodata.js ─────────────────────────────────────────────────────────
with open(GEODATA_JS, encoding='utf-8') as f:
    js_text = f.read()

entries = []
for m in re.finditer(r"'((?:[^'\\]|\\.)*?)'\s*:\s*\[([^\]]+)\]", js_text):
    key = m.group(1).replace("\\'", "'")
    nums = [float(x) for x in re.findall(r'-?\d+(?:\.\d+)?', m.group(2))]
    if len(nums) < 4:
        continue
    entries.append((key, nums))

print(f"Parsed {len(entries)} geodata entries")

# ── Load refs.json ────────────────────────────────────────────────────────────
with open(REFS_JSON, encoding='utf-8') as f:
    refs = json.load(f)

def split_refs(url_list):
    whe, wiki = [], []
    for u in (url_list or []):
        if 'worldhistory.org' in u:
            whe.append(u)
        elif 'wikipedia.org' in u:
            wiki.append(u)
    return whe[:2], wiki[:2]

def fmt_date(v):
    if v is None:
        return ''
    if abs(v - 1990.1) < 0.5:
        return '1990'
    return str(int(round(v)))

# ── Write CSV ─────────────────────────────────────────────────────────────────
with open(OUT_CSV, 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['Search Term', 'Date From', 'Date To',
                'Center Lat', 'Center Lon',
                'WHE 1', 'WHE 2', 'Wiki 1', 'Wiki 2'])
    for key, nums in entries:
        min_lon, min_lat, max_lon, max_lat = nums[0], nums[1], nums[2], nums[3]
        from_yr  = nums[4] if len(nums) >= 5 else None
        to_yr    = nums[5] if len(nums) >= 6 else None
        cent_lon = nums[6] if len(nums) >= 8 else round((min_lon + max_lon) / 2, 1)
        cent_lat = nums[7] if len(nums) >= 8 else round((min_lat + max_lat) / 2, 1)

        whe, wiki = split_refs(refs.get(key, []))
        w.writerow([
            key,
            fmt_date(from_yr),
            fmt_date(to_yr),
            round(cent_lat, 1),
            round(cent_lon, 1),
            whe[0]  if len(whe)  > 0 else '',
            whe[1]  if len(whe)  > 1 else '',
            wiki[0] if len(wiki) > 0 else '',
            wiki[1] if len(wiki) > 1 else '',
        ])

print(f"Wrote {len(entries)} rows to {OUT_CSV}")
