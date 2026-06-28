"""
build_city_geodata.py
Parses all CIT*.TXT city tile files and produces:
  city_locations.csv  — one row per unique physical city location (reference name + coords + date span)
  city_aliases.csv    — historical names → reference name with their date ranges

Reference name = last non-parenthetical name in the date range sequence.
Parenthetical names like (Gla) or (Pavlopetri) indicate ruins/uncertain sites
and are excluded from aliases but still generate location entries.
Sentinel from-dates (-9999) are floored to -2400 (content range start).
Open-ended to-dates (9999) are written as empty (no end date).
"""

import os, csv, re, unicodedata
from collections import defaultdict

# Characters that don't decompose via NFD but have obvious Latin equivalents
_CHAR_MAP = str.maketrans({
    'Ø': 'O', 'ø': 'o', 'Ð': 'D', 'ð': 'd', 'Þ': 'Th', 'þ': 'th',
    'Æ': 'Ae', 'æ': 'ae', 'Œ': 'Oe', 'œ': 'oe', 'ß': 'ss',
    'Ł': 'L', 'ł': 'l', 'ı': 'i',
    '‘': "'", '’': "'",  # curly apostrophes → straight
    '“': '"', '”': '"',  # curly quotes → straight
})

def to_ascii(s):
    """Replace non-Latin characters with their closest ASCII equivalents."""
    s = s.translate(_CHAR_MAP)
    # NFD decomposition strips combining diacritical marks (é→e, ñ→n, ü→u, etc.)
    decomposed = unicodedata.normalize('NFD', s)
    return ''.join(c for c in decomposed if unicodedata.category(c) != 'Mn' and ord(c) < 128)

DATA_DIR   = r'C:\My stuff\mapper'
MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
CITIES_DIR = os.path.join(DATA_DIR, 'cities')

SENTINEL_FROM  = -9990.0
CONTENT_START  = -2400.0
OPEN_END       = 9990.0   # to-dates >= this treated as open-ended


def parse_date_range(s):
    parts = re.split(r'[,\s]+', s.strip())
    parts = [p for p in parts if p]
    frm = float(parts[0])
    to  = float(parts[1]) if len(parts) > 1 else 9999.0
    return frm, to


def parse_city_file(text):
    lines = [l.strip() for l in re.split(r'\r?\n', text)
             if l.strip() and l.strip() != '\x1a']
    if not lines:
        return []

    i = 0
    try:
        n_cities = int(lines[i]); i += 1
    except (ValueError, IndexError):
        return []
    if n_cities <= 0:
        return []

    cities = []
    for _ in range(n_cities):
        if i >= len(lines):
            break
        i += 1  # entry index (ignored)

        try:
            n_ranges = int(lines[i]); i += 1
        except (ValueError, IndexError):
            break

        date_ranges = []
        for _ in range(n_ranges):
            if i + 4 >= len(lines):
                break
            frm, to    = parse_date_range(lines[i]); i += 1
            name       = lines[i]; i += 1
            i += 1     # colorIndex (ignored)
            try:
                sym_code = float(lines[i]); i += 1
            except (ValueError, IndexError):
                sym_code = 1.0; i += 1
            try:
                det_code = int(lines[i]); i += 1
            except (ValueError, IndexError):
                det_code = 7; i += 1
            date_ranges.append({'from': frm, 'to': to, 'name': name,
                                 'sym': sym_code, 'det': det_code})

        i += 1  # numCoords (always 1, ignored)

        if i >= len(lines):
            break
        parts = re.split(r'[\s,\t]+', lines[i].strip())
        parts = [p for p in parts if p]
        i += 1

        if len(parts) < 2:
            continue
        try:
            lon = float(parts[0])
            lat = float(parts[1])
        except ValueError:
            continue

        if date_ranges:
            cities.append({'dateRanges': date_ranges, 'lon': lon, 'lat': lat})

    return cities


def is_parenthetical(name):
    return name.startswith('(') and name.endswith(')')


def reference_name(date_ranges):
    """Last non-parenthetical name. Fall back to last name if all are parenthetical."""
    candidates = [dr['name'] for dr in date_ranges if not is_parenthetical(dr['name'])]
    if candidates:
        return candidates[-1]
    return date_ranges[-1]['name']


def floor_from(frm):
    return CONTENT_START if frm <= SENTINEL_FROM else frm


def fmt_year(v, is_to=False):
    if is_to and v >= OPEN_END:
        return ''
    return str(int(round(v)))


def main():
    all_locations = []

    for lat_dir in sorted(os.listdir(CITIES_DIR)):
        lat_path = os.path.join(CITIES_DIR, lat_dir)
        if not os.path.isdir(lat_path):
            continue
        for fname in sorted(os.listdir(lat_path)):
            if not fname.upper().endswith('.TXT'):
                continue
            fpath = os.path.join(lat_path, fname)
            with open(fpath, encoding='latin-1') as f:
                text = f.read()

            for city in parse_city_file(text):
                dr = city['dateRanges']
                if not dr:
                    continue

                ref = to_ascii(reference_name(dr))

                # Full date span across all ranges
                from_yr = min(floor_from(r['from']) for r in dr)
                to_yr   = max(r['to'] for r in dr)

                # Collect unique historical names with their combined date spans
                # (same name may appear in multiple date ranges — take min/max)
                # Apply ASCII normalization to all names
                name_spans = defaultdict(lambda: {'from': float('inf'), 'to': float('-inf')})
                for r in dr:
                    n = to_ascii(r['name'])
                    name_spans[n]['from'] = min(name_spans[n]['from'], floor_from(r['from']))
                    name_spans[n]['to']   = max(name_spans[n]['to'],   r['to'])

                # Aliases = all names that are NOT the reference and NOT parenthetical
                aliases = []
                for name, span in name_spans.items():
                    if name == ref:
                        continue
                    if is_parenthetical(name):
                        continue
                    aliases.append({'name': name,
                                    'from': span['from'],
                                    'to':   span['to']})

                all_locations.append({
                    'ref':     ref,
                    'lon':     city['lon'],
                    'lat':     city['lat'],
                    'from_yr': from_yr,
                    'to_yr':   to_yr,
                    'aliases': aliases,
                })

    # Write city_locations.csv
    loc_path = os.path.join(MAPPER_DIR, 'city_locations.csv')
    with open(loc_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['RefName', 'Lon', 'Lat', 'FromYear', 'ToYear'])
        for loc in all_locations:
            w.writerow([
                loc['ref'],
                round(loc['lon'], 6),
                round(loc['lat'], 6),
                fmt_year(loc['from_yr']),
                fmt_year(loc['to_yr'], is_to=True),
            ])
    print(f"Wrote {len(all_locations)} city locations to {loc_path}")

    # Write city_aliases.csv
    alias_path = os.path.join(MAPPER_DIR, 'city_aliases.csv')
    alias_count = 0
    with open(alias_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['RefName', 'AliasName', 'FromYear', 'ToYear'])
        for loc in all_locations:
            for alias in loc['aliases']:
                w.writerow([
                    loc['ref'],
                    alias['name'],
                    fmt_year(alias['from']),
                    fmt_year(alias['to'], is_to=True),
                ])
                alias_count += 1
    print(f"Wrote {alias_count} city aliases to {alias_path}")


if __name__ == '__main__':
    main()
