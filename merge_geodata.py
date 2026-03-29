"""
merge_geodata.py
Merges geodata_from_par.csv into js/geodata.js.
Hand-curated entries win; PAR entries are added only if the name
(case-insensitive) is not already present.
Dates from the PAR data are appended as inline comments.
"""

import os, csv, re

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
GEODATA_JS  = os.path.join(MAPPER_DIR, 'js', 'geodata.js')
PAR_CSV     = os.path.join(MAPPER_DIR, 'geodata_from_par.csv')

# ── Read existing keys from geodata.js ───────────────────────────────────────
with open(GEODATA_JS, encoding='utf-8') as f:
    js_text = f.read()

existing_keys = set(re.findall(r"'([^']+)'\s*:", js_text))
print(f"Existing geodata.js entries: {len(existing_keys)}")

# ── Read PAR CSV ──────────────────────────────────────────────────────────────
new_entries = []   # (name, minLon, minLat, maxLon, maxLat, earliest, latest)
with open(PAR_CSV, encoding='utf-8', newline='') as f:
    for row in csv.DictReader(f):
        name = row['Name'].strip()
        if name.lower() in existing_keys:
            continue   # already covered by hand-curated entry
        try:
            minLon = float(row['MinLon'])
            minLat = float(row['MinLat'])
            maxLon = float(row['MaxLon'])
            maxLat = float(row['MaxLat'])
        except ValueError:
            continue
        earliest = row['EarliestDate'].strip()
        latest   = row['LatestDate'].strip()
        new_entries.append((name, minLon, minLat, maxLon, maxLat, earliest, latest))

print(f"New entries to add: {len(new_entries)}")

# ── Build the new JS block ────────────────────────────────────────────────────
def fmt(v):
    """Format a coordinate: integer if whole, else 1 decimal."""
    return str(int(v)) if v == int(v) else f"{v:.1f}"

lines = []
lines.append('')
lines.append('    // ── From primaries / PAR tile data ─────────────────────────────────────────')

for name, minLon, minLat, maxLon, maxLat, earliest, latest in sorted(new_entries, key=lambda x: x[0].lower()):
    key    = name.lower().replace("'", "\\'")   # escape apostrophes in JS string
    coords = f"[{fmt(minLon):>5},{fmt(minLat):>5},{fmt(maxLon):>6},{fmt(maxLat):>5}]"
    comment = ''
    if earliest or latest:
        comment = f"  // {earliest}–{latest}" if earliest and latest else f"  // {earliest or latest}"
    lines.append(f"    '{key}':{' ' * max(1, 32 - len(key))}{coords},{comment}")

new_block = '\n'.join(lines)

# ── Splice into geodata.js before the closing "};" ───────────────────────────
if '};' not in js_text:
    print("ERROR: could not find '}; ' in geodata.js")
    raise SystemExit(1)

updated = js_text.rstrip()
# Remove trailing "};" then add new block then close
if updated.endswith('};'):
    updated = updated[:-2].rstrip()
updated += '\n' + new_block + '\n\n};\n'

with open(GEODATA_JS, 'w', encoding='utf-8') as f:
    f.write(updated)

print(f"Done. geodata.js now has {len(existing_keys) + len(new_entries)} entries.")
