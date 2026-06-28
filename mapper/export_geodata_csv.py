"""
export_geodata_csv.py
Reads ALL entries from js/geodata.js and writes geodata.csv.
Columns: Search Term, Date From, Date To, Center Lat, Center Lon
Dates: plain integers; negative = BC; blank if no date; 1990 for modern sentinel.
Centroids: entry[6]/[7] if present (PAR entries), else bbox midpoint.
"""

import os, re, csv

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
GEODATA_JS = os.path.join(MAPPER_DIR, 'js', 'geodata.js')
OUT_CSV    = os.path.join(MAPPER_DIR, 'geodata.csv')

with open(GEODATA_JS, encoding='utf-8') as f:
    js_text = f.read()

entries = []
for m in re.finditer(r"'((?:[^'\\]|\\.)*?)'\s*:\s*\[([^\]]+)\]", js_text):
    key  = m.group(1).replace("\\'", "'")
    nums = [float(x) for x in re.findall(r'-?\d+(?:\.\d+)?', m.group(2))]
    if len(nums) < 4:
        continue
    entries.append((key, nums))

print(f"Parsed {len(entries)} geodata entries")

def fmt_date(v):
    if v is None:
        return ''
    if abs(v - 1990.1) < 0.5 or (v >= 1990 and v < 1991):
        return '1990'
    return str(int(round(v)))

with open(OUT_CSV, 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['Search Term', 'Date From', 'Date To', 'Center Lat', 'Center Lon'])
    for key, nums in entries:
        min_lon, min_lat, max_lon, max_lat = nums[0], nums[1], nums[2], nums[3]
        from_yr  = nums[4] if len(nums) >= 5 else None
        to_yr    = nums[5] if len(nums) >= 6 else None
        cent_lon = nums[6] if len(nums) >= 8 else round((min_lon + max_lon) / 2, 1)
        cent_lat = nums[7] if len(nums) >= 8 else round((min_lat + max_lat) / 2, 1)
        w.writerow([key, fmt_date(from_yr), fmt_date(to_yr),
                    round(cent_lat, 1), round(cent_lon, 1)])

print(f"Wrote {len(entries)} rows to {OUT_CSV}")
