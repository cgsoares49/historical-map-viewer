"""
merge_geodata.py
Replaces the PAR-derived section of js/geodata.js with fresh data from
geodata_from_par.csv.  Hand-curated entries (everything before the PAR
section marker) are left untouched.  Any name already in the hand-curated
section is skipped so it is never overridden.
[minLon, minLat, maxLon, maxLat, earliestYear, latestYear] — years are
floats (negative = BCE); fractional years (e.g. -725.5) are preserved.
Date range also kept as inline comment.
"""

import os, csv, re

MAPPER_DIR  = os.path.dirname(os.path.abspath(__file__))
GEODATA_JS  = os.path.join(MAPPER_DIR, 'js', 'geodata.js')
PAR_CSV     = os.path.join(MAPPER_DIR, 'geodata_from_par.csv')

PAR_MARKER  = '// ── From primaries / PAR tile data'

def parse_year_str(s):
    """Parse '2286 BCE' → -2286, '2286.5 BCE' → -2286.5, '100 CE' → 100, '' → None."""
    s = s.strip()
    if not s:
        return None
    parts = s.split()
    try:
        y = float(parts[0])
    except ValueError:
        return None
    if len(parts) >= 2 and parts[1].upper() == 'BCE':
        return -y
    return y

# ── Read geodata.js — keep only the hand-curated section ─────────────────────
with open(GEODATA_JS, encoding='utf-8') as f:
    js_text = f.read()

par_idx = js_text.find(PAR_MARKER)
if par_idx != -1:
    # Trim back to just before the PAR section comment line
    hand_curated = js_text[:par_idx].rstrip()
else:
    # No PAR section yet — trim closing };
    hand_curated = js_text.rstrip()
    if hand_curated.endswith('};'):
        hand_curated = hand_curated[:-2].rstrip()

# Collect keys already present in the hand-curated section
hand_keys = set(re.findall(r"'((?:[^'\\]|\\.)*)'\\s*:", hand_curated))
# Also use a simpler pass that handles escaped apostrophes
hand_keys = set()
for m in re.finditer(r"'((?:[^'\\]|\\.)*?)'\s*:", hand_curated):
    raw = m.group(1).replace("\\'", "'")
    hand_keys.add(raw.lower())

print(f"Hand-curated entries: {len(hand_keys)}")

# ── Read PAR CSV ──────────────────────────────────────────────────────────────
par_entries = []
with open(PAR_CSV, encoding='utf-8', newline='') as f:
    for row in csv.DictReader(f):
        name = row['Name'].strip()
        if name.lower() in hand_keys:
            continue   # hand-curated entry takes precedence
        try:
            minLon = float(row['MinLon'])
            minLat = float(row['MinLat'])
            maxLon = float(row['MaxLon'])
            maxLat = float(row['MaxLat'])
        except ValueError:
            continue
        earliest    = row['EarliestDate'].strip()
        latest      = row['LatestDate'].strip()
        earliest_yr = parse_year_str(earliest)
        latest_yr   = parse_year_str(latest)
        cent_lon_s  = row.get('CentLon', '').strip()
        cent_lat_s  = row.get('CentLat', '').strip()
        try:
            cent_lon = float(cent_lon_s) if cent_lon_s else None
            cent_lat = float(cent_lat_s) if cent_lat_s else None
        except ValueError:
            cent_lon = cent_lat = None
        par_entries.append((name, minLon, minLat, maxLon, maxLat,
                            earliest, latest, earliest_yr, latest_yr,
                            cent_lon, cent_lat))

print(f"PAR entries to write: {len(par_entries)}")

# ── Build the PAR JS block ────────────────────────────────────────────────────
def fmt(v):
    """Format a coordinate: integer if whole, else 1 decimal."""
    return str(int(v)) if v == int(v) else f"{v:.1f}"

def fmt_year(y):
    """Format a year: integer if whole, else preserve up to 1 decimal place."""
    if y is None:
        return 'null'
    return str(int(y)) if y == int(y) else f"{y:.1f}"

lines = []
lines.append('')
lines.append('    // ── From primaries / PAR tile data ─────────────────────────────────────────')

for (name, minLon, minLat, maxLon, maxLat,
     earliest, latest, earliest_yr, latest_yr,
     cent_lon, cent_lat) in sorted(par_entries, key=lambda x: x[0].lower()):
    key = name.lower().replace("'", "\\'")
    if earliest_yr is not None and latest_yr is not None and cent_lon is not None:
        coords = (f"[{fmt(minLon):>5},{fmt(minLat):>5},{fmt(maxLon):>6},{fmt(maxLat):>5},"
                  f" {fmt_year(earliest_yr)}, {fmt_year(latest_yr)},"
                  f" {cent_lon}, {cent_lat}]")
    elif earliest_yr is not None and latest_yr is not None:
        coords = (f"[{fmt(minLon):>5},{fmt(minLat):>5},{fmt(maxLon):>6},{fmt(maxLat):>5},"
                  f" {fmt_year(earliest_yr)}, {fmt_year(latest_yr)}]")
    elif earliest_yr is not None:
        coords = (f"[{fmt(minLon):>5},{fmt(minLat):>5},{fmt(maxLon):>6},{fmt(maxLat):>5},"
                  f" {fmt_year(earliest_yr)}]")
    else:
        coords = f"[{fmt(minLon):>5},{fmt(minLat):>5},{fmt(maxLon):>6},{fmt(maxLat):>5}]"
    comment = ''
    if earliest or latest:
        comment = (f"  // {earliest}–{latest}" if earliest and latest
                   else f"  // {earliest or latest}")
    lines.append(f"    '{key}':{' ' * max(1, 32 - len(key))}{coords},{comment}")

new_block = '\n'.join(lines)

# ── Write geodata.js ──────────────────────────────────────────────────────────
updated = hand_curated + '\n' + new_block + '\n\n};\n'

with open(GEODATA_JS, 'w', encoding='utf-8') as f:
    f.write(updated)

print(f"Done. geodata.js now has {len(hand_keys) + len(par_entries)} entries.")
