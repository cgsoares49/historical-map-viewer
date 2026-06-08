"""
build_geodata.py
Scans all PAR tile files and builds a geodata CSV keyed on primaries.txt entries.
Columns: Name, MinLon, MinLat, MaxLon, MaxLat, EarliestDate, LatestDate
"""

import os, csv, re
from collections import defaultdict

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = r'C:\My stuff\mapper'  # canonical data lives here, not in ClaudeTest

# ── Tile geometry ─────────────────────────────────────────────────────────────
# Must match N_VALUES in tiles.js exactly
N_VALUES = [
    8,  8, 18, 24, 30, 36, 45, 45,   # latD  0– 35  (-90° to -55°)
    60, 60, 72, 72, 72, 72, 72, 72,   # latD 40– 75  (-50° to -15°)
    72, 72, 72, 72, 72, 72, 72, 72,   # latD 80–115  (-10° to +25°)
    72, 72, 60, 60, 45, 45, 36, 30,   # latD 120–155 (+30° to +65°)
    24, 18,  8,  8                    # latD 160–175 (+70° to +85°)
]

def tile_bounds(lat_str, lon_str):
    """Return (lat_bottom, lat_top, lon_left, lon_right) for a tile."""
    latD    = int(lat_str)
    fileLon = int(lon_str)
    lat_bottom = latD - 90
    lat_top    = lat_bottom + 5
    n_tiles    = N_VALUES[latD // 5]
    tile_width = 360.0 / n_tiles
    geo_lon_left  = fileLon - 360 if fileLon > 180 else fileLon
    geo_lon_right = geo_lon_left + tile_width
    return lat_bottom, lat_top, geo_lon_left, geo_lon_right

# ── PAR file parser (mirrors dataloader.js _lines / _parseDateRange / _parsePar) ──

def par_lines(text):
    """Split, trim, drop blank lines and EOF markers — same as JS _lines()."""
    return [l.strip() for l in re.split(r'\r?\n', text)
            if l.strip() and l.strip() != '\x1a']

def parse_date_range(line):
    # Split on comma OR whitespace (some files use spaces instead of commas)
    parts = re.split(r'[,\s]+', line.strip())
    parts = [p for p in parts if p]
    frm = float(parts[0])
    to  = float(parts[1]) if len(parts) > 1 else 9999.0
    return frm, to

def parse_par(text):
    """
    Returns list of (dateRanges, is_dot) where dateRanges = [(from, to, name), ...].
    Mirrors _parsePar() in dataloader.js.
    """
    lines = par_lines(text)
    if not lines:
        return []

    i = 0
    try:
        entry_count = int(lines[i]); i += 1
    except (ValueError, IndexError):
        return []
    if not entry_count:
        return []

    entries = []
    for _ in range(entry_count):
        if i >= len(lines):
            break

        i += 1  # entryIndex  (ignored)
        i += 1  # areaType    (ignored for our purposes)

        # numDateRanges
        try:
            num_ranges = int(lines[i]); i += 1
        except (ValueError, IndexError):
            break

        date_ranges = []
        for _ in range(num_ranges):
            if i + 2 >= len(lines):
                break
            frm, to = parse_date_range(lines[i]); i += 1
            name     = lines[i]; i += 1
            i += 1  # colorIndex
            date_ranges.append((frm, to, name))

        # numRefs — use float() like JS parseFloat (handles -0.9 etc.)
        try:
            num_refs = float(lines[i]); i += 1
        except (ValueError, IndexError):
            break

        is_dot = num_refs < 0
        if is_dot:
            i += 1  # skip dot coordinate line
        else:
            i += int(num_refs)  # skip polyRef lines

        entries.append((date_ranges, is_dot))

    return entries

# ── Load primaries ─────────────────────────────────────────────────────────────
# Format: index, Name, R, G, B

def load_primaries(path):
    """Returns dict: lowercase_name → display_name"""
    primaries = {}
    with open(path, encoding='latin-1') as f:
        lines = [l.rstrip('\r\n') for l in f if l.strip()]
    count = int(lines[0].strip())
    for line in lines[1:count+1]:
        parts = line.split(',')
        if len(parts) >= 5:
            name = parts[1].strip()
            primaries[name.lower()] = name
    return primaries

# ── Aggregation ───────────────────────────────────────────────────────────────

SENTINEL_FROM = -9990   # below this → content-creation sentinel, skip
MIN_SPAN      = 1.0     # date ranges shorter than this (years) are transitions/revolts;
                        # ignored for min/max date calculation (but not for bounding box)

def fmt_date(val, is_to):
    """Format a date float as readable string, preserving fractional years."""
    if val is None:
        return ''
    if is_to and val >= 9990:
        return 'present'
    if val < 0:
        y = abs(val)
        return f'{y:.1f} BCE' if y != int(y) else f'{int(y)} BCE'
    elif val > 0:
        return f'{val:.1f} CE' if val != int(val) else f'{int(val)} CE'
    else:
        return '1 BCE'

def main():
    primaries = load_primaries(os.path.join(DATA_DIR, 'primaries.txt'))
    print(f"Loaded {len(primaries)} primaries")

    # results[display_name] = {min_lon, max_lon, min_lat, max_lat, min_date, max_date}
    # min_date_exact / max_date_exact: same but only from entries whose full name
    # equals the primary (no " - sub-region" suffix).  Preferred over min_date when
    # available, so sub-region entries don't shift the canonical start/end date.
    INF = float('inf')
    results = {name: {'min_lon': INF, 'max_lon': -INF,
                      'min_lat': INF, 'max_lat': -INF,
                      'min_date': INF, 'max_date': -INF,
                      'min_date_exact': INF, 'max_date_exact': -INF}
               for name in primaries.values()}

    par_dir = os.path.join(DATA_DIR, 'polareas')
    files_scanned = 0
    entries_matched = 0

    for lat_dir in sorted(os.listdir(par_dir)):
        lat_path = os.path.join(par_dir, lat_dir)
        if not os.path.isdir(lat_path):
            continue
        for fname in sorted(os.listdir(lat_path)):
            if not (fname.startswith('PAR') and fname.endswith('.ASC')):
                continue
            lon_str = fname[3:6]       # "PAR005.ASC" → "005"
            lat_str = lat_dir          # "090"
            lat_bot, lat_top, lon_left, lon_right = tile_bounds(lat_str, lon_str)

            fpath = os.path.join(lat_path, fname)
            try:
                with open(fpath, encoding='latin-1') as f:
                    text = f.read()
            except Exception as e:
                print(f"  ERROR reading {fpath}: {e}")
                continue

            files_scanned += 1
            for date_ranges, is_dot in parse_par(text):
                for frm, to, name in date_ranges:
                    if name == 'UNKNOWN':
                        continue
                    first_name = name.split(' - ')[0].strip()
                    key = first_name.lower()
                    if key not in primaries:
                        continue

                    span = to - frm
                    # Skip dummy entries where start == end (zero span)
                    if span == 0:
                        continue

                    display = primaries[key]
                    r = results[display]

                    # Bounding box — include all non-dummy ranges
                    r['min_lon'] = min(r['min_lon'], lon_left)
                    r['max_lon'] = max(r['max_lon'], lon_right)
                    r['min_lat'] = min(r['min_lat'], lat_bot)
                    r['max_lat'] = max(r['max_lat'], lat_top)

                    # Date range — skip sentinel from values and short-span
                    # transition/revolt entries (< MIN_SPAN years) so they
                    # don't contaminate the earliest/latest dates.
                    # Also track exact-name matches separately: sub-region entries
                    # like "Roman Republic - Anxur" should not shift the canonical
                    # start date of "Roman Republic".
                    is_exact = (name.strip() == first_name)
                    if span >= MIN_SPAN and frm > SENTINEL_FROM:
                        r['min_date'] = min(r['min_date'], frm)
                        if is_exact:
                            r['min_date_exact'] = min(r['min_date_exact'], frm)
                    if span >= MIN_SPAN:
                        r['max_date'] = max(r['max_date'], to)
                        if is_exact:
                            r['max_date_exact'] = max(r['max_date_exact'], to)

                    entries_matched += 1

    print(f"Scanned {files_scanned} PAR files, matched {entries_matched} date-range entries")

    # Write CSV
    out_path = os.path.join(MAPPER_DIR, 'geodata_from_par.csv')
    found = 0
    not_found = []
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['Name', 'MinLon', 'MinLat', 'MaxLon', 'MaxLat', 'EarliestDate', 'LatestDate'])
        for display_name in sorted(results.keys()):
            r = results[display_name]
            if r['min_lon'] == INF:
                not_found.append(display_name)
                continue
            w.writerow([
                display_name,
                round(r['min_lon'], 1),
                round(r['min_lat'], 1),
                round(r['max_lon'], 1),
                round(r['max_lat'], 1),
                # Prefer exact-name dates; fall back to any-suffix dates
                fmt_date(r['min_date_exact'] if r['min_date_exact'] != INF
                         else r['min_date'] if r['min_date'] != INF else None, False),
                fmt_date(r['max_date_exact'] if r['max_date_exact'] != -INF
                         else r['max_date'] if r['max_date'] != -INF else None, True),
            ])
            found += 1

    print(f"\nWrote {found} entries to {out_path}")
    if not_found:
        print(f"\n{len(not_found)} primaries with NO PAR matches:")
        for n in not_found:
            print(f"  {n}")

if __name__ == '__main__':
    main()
