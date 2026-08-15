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
import csv
import argparse
from datetime import date

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
#
# NOTE: tried broadening this to catch a couple of confirmed leaks (PAR
# entries "Roman Republic - Army" / "- Consular army" whose POL segment is
# *shared* with a real border, so it carries the marker range alongside real
# dates and fails an exact/exclusive match) by flagging any date range fully
# inside the sentinel region, not just an exact (-9999.0,-9998.0) singleton.
# That broke everything: a narrow sentinel-looking OPENING range (e.g.
# (-9998.0,-9997.0) before the segment's real dates start) turns out to be
# the ubiquitous convention for real border segments too ("this line isn't
# drawn before year X"), not something exclusive to transient markers —
# confirmed on Anxur's own real POL segment. Reverted to the exact,
# exclusive-match original; the known leaks can't be distinguished
# structurally from real entries by their POL segment alone and are reported
# to the user instead of guessed at.

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


def secondary_name(name):
    """The part after ' - ', or None if the name has no dash-suffix."""
    parts = name.split(' - ', 1)
    return parts[1].strip() if len(parts) > 1 else None


# "Convenience" transients: sometimes an existing real polity boundary is
# reused to depict a transient (army/naval movement) rather than digitizing
# a dedicated path, so the POL segment carries real dates and the structural
# is_transient() check can't catch it. Per the user (2026-08-15): in these
# cases the descriptor after the dash is the only reliable signal. Extend
# this list as more categories of "convenience" transient turn up.
TRANSIENT_NAME_KEYWORDS = ('army', 'naval')


def is_keyword_transient(name):
    suffix = secondary_name(name)
    if not suffix:
        return False
    lowered = suffix.lower()
    return any(kw in lowered for kw in TRANSIENT_NAME_KEYWORDS)


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


# ── Color resolution (ports dataloader.js loadPrimaries/loadOffsets + colormatcher.js resolve) ──

def load_primaries_map():
    """dict[lowercase_name] -> (r,g,b), mirrors dataloader.js::loadPrimaries."""
    path = os.path.join(DATA_DIR, 'primaries.txt')
    with open(path, encoding='latin-1') as f:
        lines = [l.rstrip('\r\n') for l in f if l.strip()]
    out = {}
    for line in lines[1:]:
        parts = line.split(',')
        if len(parts) >= 5:
            out[parts[1].strip().lower()] = (int(parts[2]), int(parts[3]), int(parts[4]))
    return out


def load_offsets():
    """array[4096] of (r,g,b), mirrors dataloader.js::loadOffsets.

    newoffsets.txt lines are 4 tab-separated fields (index, R, G, B), but the
    live renderer's loadOffsets() only reads the first 3 fields as R/G/B —
    i.e. it treats the leading index column as R and silently drops the real
    B column. Replicated here as-is (not "fixed") so exported colors match
    what MAPPER actually displays, not a corrected palette.
    """
    path = os.path.join(DATA_DIR, 'newoffsets.txt')
    offsets = []
    with open(path, encoding='latin-1') as f:
        for line in f:
            if not line.strip():
                continue
            parts = line.split('\t')
            def to_int(s):
                try:
                    return int(s)
                except (ValueError, IndexError):
                    return 0
            offsets.append((to_int(parts[0] if len(parts) > 0 else ''),
                             to_int(parts[1] if len(parts) > 1 else ''),
                             to_int(parts[2] if len(parts) > 2 else '')))
    while len(offsets) < 4096:
        offsets.append((0, 0, 0))
    return offsets


def resolve_color(lookup_name, color_index, primaries_map, offsets):
    """Ports colormatcher.js ColorLookup.resolve — base(lookup_name) + offsets[color_index]."""
    base = primaries_map.get(lookup_name.strip().lower())
    if base is None:
        return None
    off = offsets[color_index] if 0 <= color_index < len(offsets) else (0, 0, 0)
    r = min(255, base[0] + off[0])
    g = min(255, base[1] + off[1])
    b = min(255, base[2] + off[2])
    if (r, g, b) == (0, 0, 0):
        return None
    return (r, g, b)


# ── Main pipeline ────────────────────────────────────────────────────────────
#
# Both the parent polity and each of its "secondaries" (PAR entries named
# "Parent - X", e.g. "Roman Republic - Anxur") run through the same
# find/breakpoints/slice machinery below, parameterized by a name_match
# predicate: prefix match (owner_name(n) == parent) for the parent itself,
# exact match (n == "Parent - X") for a given secondary X.

def find_entries_by_predicate(tiles_data, name_match, repair_log):
    """Returns (list of {tile, entry, ring_polygon}, transient_count)."""
    result = []
    transient_count = 0
    for tile in tiles_data:
        for entry in tile['par_entries']:
            if entry['areaType'] != 1:
                continue
            if not any(name_match(dr['name']) for dr in entry['dateRanges']):
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


def build_breakpoints(entries, name_match):
    breakpoints = set()
    for pe in entries:
        for dr in pe['entry']['dateRanges']:
            if name_match(dr['name']):
                if dr['from'] > -9990:
                    breakpoints.add(dr['from'])
                if dr['to'] < 9990:
                    breakpoints.add(dr['to'])
    return sorted(breakpoints)


def slice_into_rows(entries, breakpoints, name_match, seam_log):
    """Each row also carries color_index (from the first active contributing
    entry at that interval) and color_conflict (True if active contributors
    disagree on colorIndex — expected to be rare/never in practice)."""
    rows = []
    prev_geom = None
    for i in range(len(breakpoints) - 1):
        b0, b1 = breakpoints[i], breakpoints[i + 1]
        test_year = (b0 + b1) / 2.0
        active = []
        color_indexes = []
        for pe in entries:
            m = match_date(pe['entry']['dateRanges'], test_year)
            if m and name_match(m['name']):
                active.append(pe['ring_polygon'])
                color_indexes.append(m['colorIndex'])
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
        color_index = color_indexes[0]
        color_conflict = len(set(color_indexes)) > 1
        if prev_geom is not None and geoms_equal(geom, prev_geom):
            rows[-1]['ToYear'] = b1
        else:
            rows.append({'FromYear': b0, 'ToYear': b1, 'geometry': geom,
                         'color_index': color_index, 'color_conflict': color_conflict})
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
    ap.add_argument('--out', default=None,
                     help='GeoJSON output path; a sibling .csv is written alongside it. '
                          'Default: exports/<slug>_<today\'s date>.geojson')
    ap.add_argument('--end-year', type=float, default=None,
                     help='Truncate output at this year (applied to the parent AND every secondary). '
                          'Use when a stray entry (e.g. a garrison never relabeled after the dataset\'s '
                          'tracked period ends) would otherwise stretch an entity\'s recorded lifespan '
                          'misleadingly.')
    args = ap.parse_args()

    if args.tiles:
        tile_pairs = [tuple(t.split(':')) for t in args.tiles]
    else:
        tile_pairs = DEFAULT_TILES

    generated = date.today().isoformat()
    slug = re.sub(r'[^a-z0-9]+', '_', args.polity.lower()).strip('_')
    out_geojson = args.out or os.path.join(MAPPER_DIR, 'exports', f'{slug}_{generated}.geojson')
    out_csv = os.path.splitext(out_geojson)[0] + '.csv'

    print(f"Loading {len(tile_pairs)} tiles: {tile_pairs}")
    tiles_data = [load_tile(lat, lon) for lat, lon in tile_pairs]

    primaries_map = load_primaries_map()
    offsets = load_offsets()
    parent_color = primaries_map.get(args.polity.strip().lower())

    def truncate(breakpoints):
        if args.end_year is None or not breakpoints:
            return breakpoints
        before = len(breakpoints)
        bp = sorted(set([b for b in breakpoints if b < args.end_year] + [args.end_year]))
        print(f"  Truncated at --end-year {args.end_year}: {before} -> {len(bp)} breakpoints")
        return bp

    # ── Parent ───────────────────────────────────────────────────────────────
    print(f"\n=== {args.polity} (parent) ===")
    repair_log = [0]
    parent_match = lambda n, p=args.polity: owner_name(n) == p and not is_keyword_transient(n)
    parent_entries, transient_count = find_entries_by_predicate(tiles_data, parent_match, repair_log)
    print(f"Real territory entries: {len(parent_entries)}  |  transient/army entries excluded: {transient_count}  |  ring repairs: {repair_log[0]}")

    parent_breakpoints = build_breakpoints(parent_entries, parent_match)
    print(f"Breakpoints: {len(parent_breakpoints)}  range: {parent_breakpoints[0] if parent_breakpoints else None} .. {parent_breakpoints[-1] if parent_breakpoints else None}")
    parent_breakpoints = truncate(parent_breakpoints)

    seam_log = [0]
    parent_rows = slice_into_rows(parent_entries, parent_breakpoints, parent_match, seam_log)
    print(f"Output rows: {len(parent_rows)}  |  union geometries needing repair: {seam_log[0]}")

    entities = [{'name': args.polity, 'member_of': '', 'rows': parent_rows, 'is_parent': True}]

    # ── Secondaries: PAR entries named "Parent - X" ────────────────────────────
    secondaries = sorted({
        secondary_name(dr['name'])
        for pe in parent_entries
        for dr in pe['entry']['dateRanges']
        if owner_name(dr['name']) == args.polity and secondary_name(dr['name'])
    })
    print(f"\nDiscovered {len(secondaries)} secondaries: {secondaries}")

    for sec in secondaries:
        full_name = f"{args.polity} - {sec}"
        sec_match = lambda n, fn=full_name: n.strip() == fn and not is_keyword_transient(n)
        sec_repair_log = [0]
        sec_entries, sec_transient = find_entries_by_predicate(tiles_data, sec_match, sec_repair_log)
        sec_breakpoints = truncate(build_breakpoints(sec_entries, sec_match))
        sec_seam_log = [0]
        sec_rows = slice_into_rows(sec_entries, sec_breakpoints, sec_match, sec_seam_log)
        print(f"=== {sec} (secondary of {args.polity}) ===  entries={len(sec_entries)}  "
              f"transient_excluded={sec_transient}  ring_repairs={sec_repair_log[0]}  "
              f"rows={len(sec_rows)}  seam_repairs={sec_seam_log[0]}")
        entities.append({'name': sec, 'member_of': f'({args.polity})', 'rows': sec_rows, 'is_parent': False})

    # ── Assemble final rows with resolved color ────────────────────────────────
    out_rows = []
    for ent in entities:
        for row in ent['rows']:
            geom = row['geometry']
            if not geom.is_valid:
                print(f"  WARNING: {ent['name']} row {row['FromYear']}..{row['ToYear']} geometry invalid after repair")
            if ent['is_parent']:
                color = parent_color
            else:
                color = resolve_color(args.polity, row['color_index'], primaries_map, offsets)
                if row['color_conflict']:
                    print(f"  WARNING: {ent['name']} row {row['FromYear']}..{row['ToYear']} has "
                          f"conflicting colorIndex among contributing entries")
            color_r, color_g, color_b = color if color else (None, None, None)
            out_rows.append({
                'Name': ent['name'], 'FromYear': row['FromYear'], 'ToYear': row['ToYear'],
                'Area': round(area_km2(geom), 1), 'Type': 'POLITY', 'References': '',
                'MemberOf': ent['member_of'],
                'ColorR': color_r, 'ColorG': color_g, 'ColorB': color_b,
                'geometry': geom,
            })

    for idx, r in enumerate(out_rows, start=1):
        r['Index'] = idx

    for r in out_rows:
        r['Generated'] = generated

    prop_cols = ['Index', 'Name', 'FromYear', 'ToYear', 'Area', 'Type', 'References', 'MemberOf',
                 'ColorR', 'ColorG', 'ColorB', 'Generated']

    # ── Write GeoJSON ────────────────────────────────────────────────────────
    features = [{
        'type': 'Feature',
        'properties': {k: r[k] for k in prop_cols},
        'geometry': mapping(r['geometry']),
    } for r in out_rows]
    # 'generated' is a GeoJSON "foreign member" — ignored by strict parsers,
    # read by anything that cares (including this script, for provenance).
    fc = {'type': 'FeatureCollection', 'generated': generated, 'features': features}
    os.makedirs(os.path.dirname(out_geojson), exist_ok=True)
    with open(out_geojson, 'w', encoding='utf-8') as f:
        json.dump(fc, f, ensure_ascii=False)
    print(f"\nWrote {len(features)} features to {out_geojson}")

    # ── Write CSV (geometry truncated to a short WKT preview) ─────────────────
    WKT_TRUNCATE = 60
    with open(out_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(prop_cols + ['geometry'])
        for r in out_rows:
            wkt = r['geometry'].wkt
            if len(wkt) > WKT_TRUNCATE:
                wkt = wkt[:WKT_TRUNCATE] + '…'
            w.writerow([r[k] for k in prop_cols] + [wkt])
    print(f"Wrote {len(out_rows)} rows to {out_csv}")

    # ── Continuity check, per entity ────────────────────────────────────────
    for ent in entities:
        rows = ent['rows']
        gaps = 0
        for i in range(len(rows) - 1):
            if rows[i]['ToYear'] != rows[i + 1]['FromYear']:
                gaps += 1
                print(f"  GAP [{ent['name']}]: row {i} ends {rows[i]['ToYear']}, row {i+1} starts {rows[i+1]['FromYear']}")
        print(f"Continuity gaps [{ent['name']}]: {gaps}")


if __name__ == '__main__':
    main()
