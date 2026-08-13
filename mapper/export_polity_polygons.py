"""
export_polity_polygons.py
Exports a complete standalone polygon (GeoJSON, Cliopatria-style rows) for one
named polity, merging fragments from PAR/POL/CST tile data across tiles and
across ownership-history date ranges.

MAPPER's raw data stores, per tile, fixed vertex-chain geometries ("PAR
entries") each carrying an ownership history: a list of
(fromYear, toYear, ownerName, colorIndex) tuples. When territory changes
hands the boundary never moves — only the owner label swaps. This script:
  1. parses every PAR/POL/CST file for the given tiles (full point geometry,
     not just the bbox/date summary build_geodata.py extracts),
  2. filters out "dot" markers and transient army/campaign entries,
  3. for every date-range where an entry's owner matches --polity, builds
     that entry's closed ring (porting renderer.js's _buildCombinedPolygon),
  4. finds every year where the polity's set of owned entries changes, and
     for each resulting interval unions the active entries into one
     (Multi)Polygon (shapely.unary_union),
  5. writes one GeoJSON Feature per interval whose merged geometry actually
     differs from the previous interval's.

Mirrors parsing conventions from build_geodata.py (par_lines, parse_date_range,
DATA_DIR, latin-1 file encoding) and porting logic from
mapper/js/dataloader.js (_parsePar, _parseCstPol) and
mapper/js/renderer.js (_buildCombinedPolygon, _isTransientEntry) and
mapper/js/colormatcher.js (matchDate).
"""

import os
import re
import json
import argparse

from shapely.geometry import Polygon, mapping
from shapely.validation import make_valid
from shapely.ops import unary_union, transform
from pyproj import Transformer

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = r'C:\My stuff\mapper'  # canonical data — read-only

# Default test scope: the only 2 tiles containing "Roman Republic" text.
DEFAULT_TILES = [
    ('125', '005'), ('125', '010'), ('125', '015'),
    ('130', '006'), ('130', '012'), ('130', '018'),
]

TO_EQUAL_AREA = Transformer.from_crs('EPSG:4326', 'EPSG:6933', always_xy=True).transform


# ── Text/line helpers (mirrors dataloader.js _lines / build_geodata.py par_lines) ──

def read_lines(path):
    with open(path, encoding='latin-1') as f:
        text = f.read()
    return [l.strip() for l in re.split(r'\r?\n', text)
            if l.strip() and l.strip() != '\x1a']


def parse_date_range(line):
    parts = [p for p in re.split(r'[,\s]+', line.strip()) if p]
    frm = float(parts[0])
    to = float(parts[1]) if len(parts) > 1 else 9999.0
    return frm, to


# ── CST/POL parser (mirrors dataloader.js _parseCstPol) ────────────────────────

def parse_cst_pol_full(lines):
    """Returns dict[polyIndex] -> {polyType, dateRanges:[(from,to)], points:[(lon,lat)]}"""
    if not lines:
        return {}
    i = 0
    poly_count = int(lines[i]); i += 1
    polys = {}
    for _ in range(poly_count):
        if i >= len(lines):
            break
        header = lines[i].split(); i += 1
        poly_type = int(header[0])
        poly_index = int(header[1]) if len(header) > 1 else 1

        num_dates = int(lines[i]); i += 1
        date_ranges = []
        for _ in range(num_dates):
            if i >= len(lines):
                break
            date_ranges.append(parse_date_range(lines[i])); i += 1

        point_count = int(lines[i]); i += 1
        points = []
        logical_pt = 0
        while logical_pt < point_count:
            if i >= len(lines):
                break
            raw = [t for t in re.split(r'[\s,]+', lines[i].strip()) if t]; i += 1
            off, repeat = 0, 1
            if raw and raw[0].startswith('['):
                m = re.match(r'\[x(\d+)\]', raw[0], re.IGNORECASE)
                if m:
                    repeat = int(m.group(1))
                off = 1
            if len(raw) - off >= 2:
                try:
                    lon = float(raw[off]); lat = float(raw[off + 1])
                except ValueError:
                    logical_pt += repeat
                    continue
                for _ in range(repeat):
                    if logical_pt >= point_count:
                        break
                    points.append((lon, lat))
                    logical_pt += 1
            else:
                logical_pt += 1

        polys[poly_index] = {'polyType': poly_type, 'dateRanges': date_ranges, 'points': points}
    return polys


# ── PAR parser (mirrors dataloader.js _parsePar — full version, keeps polyRefs) ──

def parse_par_full(lines):
    """Returns list of {entryIndex, areaType, dateRanges:[{from,to,name,colorIndex}], polyRefs:[(polIndex,flag)]}"""
    if not lines:
        return []
    i = 0
    entry_count = int(lines[i]); i += 1
    entries = []
    for _ in range(entry_count):
        if i >= len(lines):
            break
        entry_index = int(lines[i]); i += 1
        area_type = int(lines[i]); i += 1

        num_ranges = int(lines[i]); i += 1
        date_ranges = []
        for _ in range(num_ranges):
            if i + 2 >= len(lines):
                break
            frm, to = parse_date_range(lines[i]); i += 1
            name = lines[i]; i += 1
            color_index = int(lines[i]); i += 1
            date_ranges.append({'from': frm, 'to': to, 'name': name, 'colorIndex': color_index})

        num_refs = float(lines[i]); i += 1
        poly_refs = []
        if num_refs < 0:
            i += 1  # dot coordinate line — not a polygon, skip
        else:
            for _ in range(int(num_refs)):
                if i >= len(lines):
                    break
                parts = lines[i].split(','); i += 1
                pol_index = int(parts[0])
                flag = int(parts[1]) if len(parts) > 1 else 0
                poly_refs.append((pol_index, flag))

        entries.append({
            'entryIndex': entry_index, 'areaType': area_type,
            'dateRanges': date_ranges, 'polyRefs': poly_refs,
        })
    return entries


# ── Ring assembly (ports renderer.js _buildCombinedPolygon) ────────────────────

def build_combined_ring(poly_refs, cst_by_index, pol_by_index):
    combined = []
    has_segment = False
    for pol_index, flag in poly_refs:
        if flag == 0 or flag == 1:
            if pol_index <= 1000:
                poly = cst_by_index.get(pol_index)
            else:
                poly = pol_by_index.get(pol_index - 1000)
            if not poly or not poly['points']:
                continue
            has_segment = True
            pts = poly['points']
            combined.extend(pts if flag == 0 else list(reversed(pts)))
        else:
            lat = 0 if flag == 1000 else flag
            combined.append((pol_index, lat))
    if len(combined) > 1 and combined[0] != combined[-1]:
        combined.append(combined[0])
    return combined, has_segment


# ── Transient-entry filter (ports renderer.js _isTransientEntry) ───────────────

def is_transient(poly_refs, pol_by_index):
    saw_pol = False
    for pol_index, _flag in poly_refs:
        if pol_index <= 1000:
            continue
        saw_pol = True
        poly = pol_by_index.get(pol_index - 1000)
        if not poly:
            return False
        dr = poly['dateRanges']
        if not (len(dr) == 1 and dr[0][0] == -9999.0 and dr[0][1] == -9998.0):
            return False
    return saw_pol


# ── Date matching (ports colormatcher.js matchDate) ─────────────────────────────

def match_date(date_ranges, year):
    match = None
    for dr in date_ranges:
        if year > dr['from'] and year <= dr['to']:
            match = dr
    return match


def owner_name(name):
    return name.split(' - ')[0].strip()


# ── Geometry repair helpers ──────────────────────────────────────────────────

def to_polygonal(geom):
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type in ('Polygon', 'MultiPolygon'):
        return geom
    if geom.geom_type == 'GeometryCollection':
        polys = [g for g in geom.geoms if g.geom_type in ('Polygon', 'MultiPolygon')]
        if not polys:
            return None
        return unary_union(polys)
    return None


def ring_to_polygon(ring_points, repair_log):
    if len(ring_points) < 4:
        return None
    poly = Polygon(ring_points)
    if not poly.is_valid:
        repair_log[0] += 1
        poly = to_polygonal(make_valid(poly))
    return poly


def geoms_equal(a, b, tol=1e-9):
    if a is None or b is None:
        return a is b
    try:
        return a.symmetric_difference(b).area < tol
    except Exception:
        return False


# ── Tile loading ────────────────────────────────────────────────────────────

def load_tile(lat_str, lon_str):
    par_path = os.path.join(DATA_DIR, 'polareas', lat_str, f'PAR{lon_str}.ASC')
    pol_path = os.path.join(DATA_DIR, 'pols', lat_str, f'POL{lon_str}.PRN')
    cst_path = os.path.join(DATA_DIR, 'coasts', lat_str, f'CST{lon_str}.PRN')

    par_entries = parse_par_full(read_lines(par_path)) if os.path.exists(par_path) else []
    pol_by_index = parse_cst_pol_full(read_lines(pol_path)) if os.path.exists(pol_path) else {}
    cst_by_index = parse_cst_pol_full(read_lines(cst_path)) if os.path.exists(cst_path) else {}

    return {
        'lat_str': lat_str, 'lon_str': lon_str,
        'par_entries': par_entries, 'pol_by_index': pol_by_index, 'cst_by_index': cst_by_index,
    }


# ── Primaries color lookup ───────────────────────────────────────────────────

def load_primary_color(polity_name):
    path = os.path.join(DATA_DIR, 'primaries.txt')
    with open(path, encoding='latin-1') as f:
        lines = [l.rstrip('\r\n') for l in f if l.strip()]
    target = polity_name.strip().lower()
    for line in lines[1:]:
        parts = line.split(',')
        if len(parts) >= 5 and parts[1].strip().lower() == target:
            return int(parts[2]), int(parts[3]), int(parts[4])
    return None


# ── Main pipeline ────────────────────────────────────────────────────────────

def find_polity_entries(tiles_data, polity_name, repair_log):
    """Returns list of {tile, entry, ring (shapely Polygon or None)}."""
    result = []
    transient_count = 0
    for tile in tiles_data:
        for entry in tile['par_entries']:
            if entry['areaType'] != 1:
                continue
            if not any(owner_name(dr['name']) == polity_name for dr in entry['dateRanges']):
                continue
            if is_transient(entry['polyRefs'], tile['pol_by_index']):
                transient_count += 1
                continue
            ring, has_segment = build_combined_ring(entry['polyRefs'], tile['cst_by_index'], tile['pol_by_index'])
            if not has_segment or len(ring) < 4:
                continue
            poly = ring_to_polygon(ring, repair_log)
            if poly is None or poly.is_empty:
                continue
            result.append({'tile': tile, 'entry': entry, 'ring_polygon': poly})
    return result, transient_count


def build_breakpoints(polity_entries, polity_name):
    breakpoints = set()
    for pe in polity_entries:
        for dr in pe['entry']['dateRanges']:
            if owner_name(dr['name']) == polity_name:
                if dr['from'] > -9990:
                    breakpoints.add(dr['from'])
                if dr['to'] < 9990:
                    breakpoints.add(dr['to'])
    return sorted(breakpoints)


def slice_into_rows(polity_entries, breakpoints, polity_name, seam_log):
    rows = []
    prev_geom = None
    for i in range(len(breakpoints) - 1):
        b0, b1 = breakpoints[i], breakpoints[i + 1]
        test_year = (b0 + b1) / 2.0
        active = []
        for pe in polity_entries:
            m = match_date(pe['entry']['dateRanges'], test_year)
            if m and owner_name(m['name']) == polity_name:
                active.append(pe['ring_polygon'])
        if not active:
            prev_geom = None
            continue
        geom = unary_union(active) if len(active) > 1 else active[0]
        geom = to_polygonal(geom)
        if geom is not None and not geom.is_valid:
            seam_log[0] += 1
            geom = to_polygonal(make_valid(geom))
        if geom is None or geom.is_empty:
            prev_geom = None
            continue
        if prev_geom is not None and geoms_equal(geom, prev_geom):
            rows[-1]['ToYear'] = b1
        else:
            rows.append({'FromYear': b0, 'ToYear': b1, 'geometry': geom})
        prev_geom = geom
    return rows


def area_km2(geom):
    projected = transform(TO_EQUAL_AREA, geom)
    return projected.area / 1_000_000.0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--polity', default='Roman Republic')
    ap.add_argument('--tiles', nargs='+', default=None,
                     help='lat:lon pairs, e.g. 125:010 130:012 (default: hardcoded Roman Republic tile list)')
    ap.add_argument('--out', default=None)
    ap.add_argument('--end-year', type=float, default=None,
                     help='Truncate output at this year. Use when a stray entry (e.g. a '
                          'garrison never relabeled after the dataset\'s tracked period ends) '
                          'would otherwise stretch the polity\'s recorded lifespan misleadingly.')
    args = ap.parse_args()

    if args.tiles:
        tile_pairs = [tuple(t.split(':')) for t in args.tiles]
    else:
        tile_pairs = DEFAULT_TILES

    slug = re.sub(r'[^a-z0-9]+', '_', args.polity.lower()).strip('_')
    out_path = args.out or os.path.join(MAPPER_DIR, 'exports', f'{slug}.geojson')

    print(f"Loading {len(tile_pairs)} tiles: {tile_pairs}")
    tiles_data = [load_tile(lat, lon) for lat, lon in tile_pairs]

    repair_log = [0]
    polity_entries, transient_count = find_polity_entries(tiles_data, args.polity, repair_log)
    print(f"Real territory entries: {len(polity_entries)}  |  transient/army entries excluded: {transient_count}  |  ring repairs: {repair_log[0]}")

    breakpoints = build_breakpoints(polity_entries, args.polity)
    print(f"Breakpoints: {len(breakpoints)}  range: {breakpoints[0] if breakpoints else None} .. {breakpoints[-1] if breakpoints else None}")

    if args.end_year is not None:
        before = len(breakpoints)
        breakpoints = [b for b in breakpoints if b < args.end_year]
        breakpoints.append(args.end_year)
        breakpoints = sorted(set(breakpoints))
        print(f"Truncated at --end-year {args.end_year}: {before} -> {len(breakpoints)} breakpoints")

    seam_log = [0]
    rows = slice_into_rows(polity_entries, breakpoints, args.polity, seam_log)
    print(f"Output rows: {len(rows)}  |  union geometries needing repair: {seam_log[0]}")

    color = load_primary_color(args.polity)
    color_r, color_g, color_b = color if color else (None, None, None)

    features = []
    for idx, row in enumerate(rows, start=1):
        geom = row['geometry']
        valid = geom.is_valid
        if not valid:
            print(f"  WARNING: row {idx} ({row['FromYear']}..{row['ToYear']}) geometry invalid after repair")
        features.append({
            'type': 'Feature',
            'properties': {
                'Index': idx,
                'Name': args.polity,
                'FromYear': row['FromYear'],
                'ToYear': row['ToYear'],
                'Area': round(area_km2(geom), 1),
                'Type': 'POLITY',
                'References': '',
                'MemberOf': '',
                'ColorR': color_r,
                'ColorG': color_g,
                'ColorB': color_b,
            },
            'geometry': mapping(geom),
        })

    fc = {'type': 'FeatureCollection', 'features': features}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(fc, f, ensure_ascii=False)
    print(f"\nWrote {len(features)} features to {out_path}")

    # Continuity check
    gaps = 0
    for i in range(len(rows) - 1):
        if rows[i]['ToYear'] != rows[i + 1]['FromYear']:
            gaps += 1
            print(f"  GAP: row {i} ends {rows[i]['ToYear']}, row {i+1} starts {rows[i+1]['FromYear']}")
    print(f"Continuity gaps: {gaps}")


if __name__ == '__main__':
    main()
