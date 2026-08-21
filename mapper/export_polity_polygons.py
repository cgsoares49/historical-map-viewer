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
  2. filters out "dot" markers, and splits entries into real territory vs.
     transient army/campaign entries (kept, not discarded — see Type below),
  3. for every date-range where an entry's owner matches --polity (at any
     nesting depth — "Parent", "Parent - X", "Parent - X - Y", ...), builds
     that entry's closed ring (porting renderer.js's _buildCombinedPolygon),
  4. finds every year where an entity's set of owned entries changes, and
     for each resulting interval unions the active entries into one
     (Multi)Polygon (shapely.unary_union),
  5. writes one GeoJSON Feature per interval whose merged geometry actually
     differs from the previous interval's — Type="POLITY" for real
     territory, Type="TRANSIENT" for army/campaign entries.

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

import shapely
from shapely.geometry import Polygon, Point, MultiPoint, mapping
from shapely.validation import make_valid
from shapely.ops import unary_union, transform
from pyproj import Transformer

from geo_region import classify_region

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


JS_NUMBER_RE = re.compile(r'\s*([+-]?\d+(?:\.\d+)?)')


def js_parse_number(s, default=0):
    """Lenient numeric parse for PAR polyRef fields (pol_index, flag): skip
    leading whitespace, consume a leading number (int or decimal), stop at
    the first character that isn't part of it, and ignore everything after
    -- unlike Python's strict int()/float(), which raise on trailing
    garbage. Returns int when the matched text has no decimal point, float
    otherwise, so `flag == 0`/`== 1`/`== 1000` sentinel comparisons keep
    working exactly as before while non-integer values are preserved.

    Two real cases found scanning Persian Empire's 54 tiles:
    - polareas/120/PAR035.ASC line 1943: polyRef flag "32.6". This is a
      *synthetic connector point* (build_combined_ring's `else` branch uses
      the flag value directly as that point's latitude), and there's no
      rule requiring a connector point to land on a whole degree -- per
      the user (2026-08-16), this is legitimate data, not a typo, so it
      must be preserved at full precision, not truncated. (An earlier
      version of this function used strict parseInt-style truncation here,
      reasoning it should replicate the live renderer's own lossy parseInt
      -- that reasoning was wrong for geometry, which needs to stay
      accurate for the export's own purpose regardless of what the live
      renderer's rendering happens to do with it. Color/offset truncation,
      e.g. the newoffsets.txt quirk, is a different, correctly-kept case:
      cosmetic display fidelity, not scientific coordinate accuracy.)
    - polareas/125/PAR040.ASC line 283: a comma-less "1012     0" pair --
      fixed at the source by the user (added the missing comma). Kept the
      leniency here anyway in case the same delimiter mistake recurs
      elsewhere in the ~1015-polity dataset; a comma-less single token
      still parses its leading number and the flag correctly defaults to 0
      (no second comma-separated element at all), matching the live
      renderer's own `parts.length > 1 ? parseInt(parts[1]) : 0`."""
    m = JS_NUMBER_RE.match(s)
    if not m:
        return default
    text = m.group(1)
    return float(text) if '.' in text else int(text)


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
    """Returns list of {entryIndex, areaType, dateRanges:[{from,to,name,colorIndex}],
    polyRefs:[(polIndex,flag)], dotPoint:(lon,lat)|None}. areaType=0 ("dot") entries
    have dotPoint set and an empty polyRefs; areaType=1 entries have polyRefs and
    dotPoint=None. Mirrors dataloader.js's dotPoint/dotDiameter handling (diameter
    isn't needed for export purposes, so isn't captured here)."""
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
        dot_point = None
        if num_refs < 0:
            coords = [t for t in re.split(r'[\s,]+', lines[i].strip()) if t]
            i += 1
            if len(coords) >= 2:
                try:
                    dot_point = (float(coords[0]), float(coords[1]))
                except ValueError:
                    dot_point = None
        else:
            for _ in range(int(num_refs)):
                if i >= len(lines):
                    break
                parts = lines[i].split(','); i += 1
                pol_index = js_parse_number(parts[0])
                flag = js_parse_number(parts[1]) if len(parts) > 1 else 0
                poly_refs.append((pol_index, flag))

        entries.append({
            'entryIndex': entry_index, 'areaType': area_type,
            'dateRanges': date_ranges, 'polyRefs': poly_refs, 'dotPoint': dot_point,
        })
    return entries


# ── CIT parser (mirrors dataloader.js _parseCities — Milestone 6) ──────────────
#
# A city tile has none of PAR's polygon/polyRef machinery: each city is one
# fixed (lon, lat) point carrying its own list of date-range entries, which
# can be a real rename/refounding history (e.g. Beijing: Youzhou -> ... ->
# Beijing (1368.0-9999.0), 11 entries for one point) rather than an
# ownership history. Two different literal values (9999.0 and, in a handful
# of entries, 9990.0) are used for the same "still exists today" open-ended
# ToYear -- normalized to 9999.0 here at parse time only, the same
# non-destructive precedent as js_parse_number's handling of other stray
# source typos (canonical data itself is not touched).
def parse_cit_full(lines):
    """Returns list of {entryIndex, dateRanges:[{from,to,name,colorIndex,
    symCode,detCode}], lon, lat}."""
    if not lines:
        return []
    i = 0
    city_count = int(lines[i]); i += 1
    cities = []
    for _ in range(city_count):
        if i >= len(lines):
            break
        entry_index = int(lines[i]); i += 1
        num_ranges = int(lines[i]); i += 1
        date_ranges = []
        for _ in range(num_ranges):
            if i + 4 >= len(lines):
                break
            frm, to = parse_date_range(lines[i]); i += 1
            if to == 9990.0:
                to = 9999.0
            name = lines[i]; i += 1
            color_index = int(lines[i]); i += 1
            sym_code = float(lines[i]); i += 1
            det_code = int(float(lines[i])); i += 1
            date_ranges.append({'from': frm, 'to': to, 'name': name, 'colorIndex': color_index,
                                 'symCode': sym_code, 'detCode': det_code})
        if i >= len(lines):
            break
        i += 1  # numCoords, always 1, ignored
        coords = [t for t in re.split(r'[\s,]+', lines[i].strip()) if t]; i += 1
        cities.append({'entryIndex': entry_index, 'dateRanges': date_ranges,
                        'lon': float(coords[0]), 'lat': float(coords[1])})
    return cities


CIT_FILENAME_RE = re.compile(r'^CIT(\d{3})\.TXT$', re.IGNORECASE)


def discover_city_tiles():
    """Every cities/<latD>/CIT<lon>.TXT tile that actually has >=1 city --
    most of the 1,820-tile grid is empty (population is currently
    concentrated in the Mediterranean/Near East/China core; empty files are
    literally ' 0 \r\n')."""
    cit_dir = os.path.join(DATA_DIR, 'cities')
    tiles = []
    for lat_dir in sorted(os.listdir(cit_dir)):
        lat_path = os.path.join(cit_dir, lat_dir)
        if not os.path.isdir(lat_path):
            continue
        for fname in sorted(os.listdir(lat_path)):
            if not CIT_FILENAME_RE.match(fname):
                continue
            try:
                with open(os.path.join(lat_path, fname), encoding='latin-1') as f:
                    count = int(f.readline().strip())
            except (OSError, ValueError):
                count = 0
            if count > 0:
                tiles.append((lat_dir, fname[3:6]))
    return tiles


def resolve_city_color(color_index, offsets):
    """Ports colormatcher.js resolveCityRgb -- offsets[color_index] used
    directly as the full RGB (VB: intC = intRedoffset(intOffset), no
    primaries-base addition), unlike polity/tribal colors via resolve_color()
    below."""
    if 0 <= color_index < len(offsets):
        return offsets[color_index]
    return (0, 0, 0)


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


def path_of(name):
    """Full dash-chain as a tuple, e.g. 'Roman Ally - Kingdom of Syracuse - Tauromenion'
    -> ('Roman Ally', 'Kingdom of Syracuse', 'Tauromenion'). Chains can go arbitrarily
    deep (confirmed 4+ levels for the Persian Empire) — this is not limited to 2 levels."""
    return tuple(s.strip() for s in name.split(' - '))


# "Convenience" transients: sometimes an existing real polity boundary is
# reused to depict a transient (army/naval movement) rather than digitizing
# a dedicated path, so the POL segment carries real dates and the structural
# is_transient() check can't catch it. Per the user (2026-08-15): in these
# cases the descriptor after the dash is the only reliable signal. Extend
# this list as more categories of "convenience" transient turn up.
TRANSIENT_NAME_KEYWORDS = ('army', 'naval')


def is_keyword_transient(name):
    """Checks every segment after the root (path[0]) at any nesting depth, not just
    the immediate child — a keyword could show up at any level of a deep chain."""
    segments = path_of(name)[1:]
    return any(kw in seg.lower() for seg in segments for kw in TRANSIENT_NAME_KEYWORDS)


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
# The parent polity and each of its nested members (PAR entries named
# "Parent - X", "Parent - X - Y", ... at any depth) run through the same
# find/breakpoints/slice machinery below, parameterized by a name_match
# predicate: prefix match at depth 1 (owner_name(n) == parent) for the
# parent itself, prefix match at depth L (path_of(n)[:L] == path) for a
# member at path length L.

def find_entries_by_predicate(tiles_data, name_match, repair_log):
    """Returns (real_entries, transient_entries) — each a list of
    {tile, entry, ring_polygon}. A PAR entry with at least one date-range
    name satisfying name_match is classified as transient (army/campaign,
    not real territory) if it's structurally transient (is_transient — the
    referenced POL segment carries the -9999.0/-9998.0 marker) OR any of its
    matching date-range names are keyword-flagged (is_keyword_transient —
    the "convenience" case where a real boundary is reused to depict a
    transient). Otherwise it's real territory. Both are kept (not
    discarded) — see main() for how each becomes Type="POLITY" vs
    Type="TRANSIENT" rows."""
    real = []
    transient = []
    for tile in tiles_data:
        for entry in tile['par_entries']:
            if entry['areaType'] != 1:
                continue
            matching_drs = [dr for dr in entry['dateRanges'] if name_match(dr['name'])]
            if not matching_drs:
                continue
            entry_is_transient = (
                is_transient(entry['polyRefs'], tile['pol_by_index'])
                or any(is_keyword_transient(dr['name']) for dr in matching_drs)
            )
            ring, has_segment = build_combined_ring(entry['polyRefs'], tile['cst_by_index'], tile['pol_by_index'])
            if not has_segment or len(ring) < 4:
                continue
            poly = ring_to_polygon(ring, repair_log)
            if poly is None or poly.is_empty:
                continue
            bucket = transient if entry_is_transient else real
            bucket.append({'tile': tile, 'entry': entry, 'ring_polygon': poly})
    return real, transient


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


def slice_into_rows(entries, breakpoints, name_match, seam_log, own_path=None):
    """Each row also carries color_index and color_conflict (used by the
    caller to decide whether to show a real RGB or "various component
    colors").

    own_path (optional): this entity's own exact path tuple, e.g.
    ('Persian Empire', 'Egypt', 'Egypt', 'Egypt'). `entries` is gathered via
    name_match, a PREFIX match that intentionally sweeps in every nested
    descendant too (needed so a composite's geometry includes its children's
    territory, per Cliopatria's composite-duplicates-members convention) --
    but color must NOT be resolved the same inclusive way, or a composite
    can silently show a child's own color as if it were its own (found
    2026-08-21: a Persian Empire > Egypt > Egypt > Egypt row picked up its
    nested Nome 1 child's color this way, with no conflict even flagged,
    because Nome 1 was the *only* active contributor in that narrow window --
    the "own" undivided-Egypt territory had nothing active there at all).
    When own_path is given, color_index is resolved from entries whose own
    path_of(name) exactly equals own_path -- NOT from descendants swept in
    by the prefix match. If *any* descendant is active in a window (whether
    or not an "own" entry is also active alongside it), color_conflict is
    set True, since the row's territory is only correct for its full
    (nomes-included) extent, not a single color -- the caller shows "various
    component colors" for these. If own_path is None (dot/root-level
    TRANSIENT/TRIBAL_AREA callers, where is_parent rows never consult
    color_index at all), falls back to the old any-contributor-disagreement
    check."""
    rows = []
    prev_geom = None
    for i in range(len(breakpoints) - 1):
        b0, b1 = breakpoints[i], breakpoints[i + 1]
        test_year = (b0 + b1) / 2.0
        active = []
        color_indexes = []
        own_color_indexes = []
        has_descendant = False
        for pe in entries:
            m = match_date(pe['entry']['dateRanges'], test_year)
            if m and name_match(m['name']):
                active.append(pe['ring_polygon'])
                color_indexes.append(m['colorIndex'])
                if own_path is not None:
                    if path_of(m['name']) == own_path:
                        own_color_indexes.append(m['colorIndex'])
                    else:
                        has_descendant = True
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
        if own_path is not None:
            color_conflict = has_descendant or len(set(own_color_indexes)) > 1
            color_index = own_color_indexes[0] if own_color_indexes else (color_indexes[0] if color_indexes else None)
        else:
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


# Tribal dot clusters have no polygon at all, so geom.area is always 0 --
# area_km2() alone can't give them a meaningful Area figure. Per the user
# (2026-08-17): compute a hull polygon around each row's active dots and use
# *its* area, but don't store the hull as the row's own displayed geometry --
# dot-cluster rows stay lightweight Point/MultiPoint in the actual delivered
# dataset (minimal bytes), the hull only feeds the Area number. concave_hull
# (ratio=0.3, i.e. moderately tight -- not the full convex sprawl to distant
# outlier dots, not the maximally-jagged 0.0 extreme either) needs >=3
# distinct points to form a polygon; fewer than that has no defined area,
# same as before this feature.
HULL_RATIO = 0.3


def hull_geom(geom, ratio=HULL_RATIO):
    if geom.geom_type not in ('Point', 'MultiPoint'):
        return None
    pts = list(geom.geoms) if geom.geom_type == 'MultiPoint' else [geom]
    if len(pts) < 3:
        return None
    hull = shapely.concave_hull(MultiPoint(pts), ratio=ratio)
    if hull.is_empty or hull.geom_type not in ('Polygon', 'MultiPolygon'):
        return None
    return hull


def hull_area_km2(geom, ratio=HULL_RATIO):
    hull = hull_geom(geom, ratio=ratio)
    return round(area_km2(hull), 1) if hull is not None else 0.0


# ── Tribal dot clusters (Milestone 5) ────────────────────────────────────────
#
# Two genuinely different source representations for tribal territory, per the
# user (2026-08-16): (1) an areaType=1 PAR entry drawn as an ordinary bordered
# polygon -- already fully handled by the pipeline above with zero new code,
# just needs Type="TRIBAL_AREA" instead of "POLITY"; (2) an areaType=0 "dot"
# entry -- one of potentially thousands of individual point markers with no
# polygon in the source at all. For (2), one output row per (name,
# date-interval) as a GeoJSON MultiPoint collecting every active dot's
# coordinate, NOT one row per dot -- ~7,000 raw dots should collapse to
# dozens-to-low-hundreds of rows, not thousands.

def find_dot_entries_by_predicate(tiles_data, name_match):
    """Returns (tribal_dots, transient_dots) -- lists of {tile, entry, point}
    for areaType=0 PAR entries matching name_match. Dots have no polyRefs, so
    is_transient's structural marker check doesn't apply -- but the same
    keyword fallback used for polygon entries does: some campaign positions
    are marked with a single dot instead of a drawn path (confirmed real:
    "Army"/"Consular army" dot entries exist alongside the polygon-path ones
    already handled), so those need Type="TRANSIENT" too, not "TRIBAL_AREA"."""
    tribal = []
    transient = []
    for tile in tiles_data:
        for entry in tile['par_entries']:
            if entry['areaType'] != 0 or entry['dotPoint'] is None:
                continue
            matching_drs = [dr for dr in entry['dateRanges'] if name_match(dr['name'])]
            if not matching_drs:
                continue
            de = {'tile': tile, 'entry': entry, 'point': entry['dotPoint']}
            if any(is_keyword_transient(dr['name']) for dr in matching_drs):
                transient.append(de)
            else:
                tribal.append(de)
    return tribal, transient


def slice_into_dot_rows(dot_entries, breakpoints, name_match, own_path=None):
    """Like slice_into_rows, but collects active dot coordinates per interval
    into a MultiPoint (or Point, if only one) instead of unioning polygon
    rings -- no geometry repair needed, points can't be topologically
    invalid. Same color_index/color_conflict/own_path convention as
    slice_into_rows -- see its docstring for the full reasoning."""
    rows = []
    prev_points = None
    for i in range(len(breakpoints) - 1):
        b0, b1 = breakpoints[i], breakpoints[i + 1]
        test_year = (b0 + b1) / 2.0
        active_points = []
        color_indexes = []
        own_color_indexes = []
        has_descendant = False
        for de in dot_entries:
            m = match_date(de['entry']['dateRanges'], test_year)
            if m and name_match(m['name']):
                active_points.append(de['point'])
                color_indexes.append(m['colorIndex'])
                if own_path is not None:
                    if path_of(m['name']) == own_path:
                        own_color_indexes.append(m['colorIndex'])
                    else:
                        has_descendant = True
        if not active_points:
            prev_points = None
            continue
        points_key = tuple(sorted(active_points))
        if own_path is not None:
            color_conflict = has_descendant or len(set(own_color_indexes)) > 1
            color_index = own_color_indexes[0] if own_color_indexes else (color_indexes[0] if color_indexes else None)
        else:
            color_index = color_indexes[0]
            color_conflict = len(set(color_indexes)) > 1
        if prev_points is not None and points_key == prev_points:
            rows[-1]['ToYear'] = b1
        else:
            geom = MultiPoint(active_points) if len(active_points) > 1 else Point(active_points[0])
            rows.append({'FromYear': b0, 'ToYear': b1, 'geometry': geom,
                         'color_index': color_index, 'color_conflict': color_conflict})
        prev_points = points_key
    return rows


def build_tribal_name_set(tiles_data):
    """Bare names (path_of(name)[-1]) that appear via at least one non-transient
    areaType=0 dot entry anywhere in the loaded tiles -- used to reclassify a
    matching areaType=1 polygon entity as Type="TRIBAL_AREA" instead of
    "POLITY" (the "classic" hand-drawn case: the same tribal group
    later/elsewhere drawn as a real bordered polygon). Keyword-transient dot
    names (e.g. "Army") are excluded so they can't cause an unrelated
    same-named polygon entity to be misclassified."""
    names = set()
    for tile in tiles_data:
        for entry in tile['par_entries']:
            if entry['areaType'] != 0:
                continue
            for dr in entry['dateRanges']:
                if is_keyword_transient(dr['name']):
                    continue
                names.add(path_of(dr['name'])[-1])
    return names


# Manual override for tribal groups whose "classic" hand-drawn polygon uses a
# *different* name than their dot-cluster form (per the user: they "had to
# name them something slightly different" when doing this conversion, so
# build_tribal_name_set's exact-name matching can't catch it). Empty for now
# -- extend as specific renamed conversions are identified, same pattern as
# TRANSIENT_NAME_KEYWORDS.
TRIBAL_NAME_OVERRIDES = ()


def is_tribal_name(name, tribal_names):
    return name in tribal_names or name in TRIBAL_NAME_OVERRIDES


# Known cases where a "near-white terry" bordered polygon (drawn later, often
# just to hold a map label over otherwise-empty space once dots are hidden)
# geographically/temporally overlaps one or more tribal dot-cluster entities
# under a *different* PAR name, so build_tribal_name_set's exact-name
# reclassification can't catch the relationship. Per the user (2026-08-17):
# dots are the original/authoritative data; these borders are a later
# addition and should NOT suppress the dot entities -- overlapping rows are
# kept as-is but flagged (OverlapNote) for a human to curate later. Source:
# `duplicated tribal areas and dots.xlsx`. Extend as more pairs are found.
TRIBAL_CONTAINER_OVERLAPS = {
    'Garamantes': ('Saharan Peoples',),
    'Libyphoenices': ('Libyans',),
    'North Arabian Semites': ('Aramaeans', 'Qedarites', 'Arabs'),
    'Sikeloi': ('Sicels',),
    'Sikanoi': ('Sicans',),
    'Bruttii': ('Italics', 'Bruttians'),
    'Thesprotians': ('Dorians',),
    'Piceni': ('Picentes',),
    'Umbrii': ('Umbri',),
    'Samnium': ('Samnites',),
    'Iapygii': ('Daunians', 'Peucetians', 'Messapians'),
    'Lucani': ('Italics', 'Lucanians'),
    'Messapii': ('Messapians',),
    'Illyrioi': ('Illyrians',),
    'Thraikes': ('Thracians',),
    'Paiones': ('Paeonians',),
}
_OVERLAP_CONTAINER_OF = {}
for _container, _dots in TRIBAL_CONTAINER_OVERLAPS.items():
    for _dot in _dots:
        _OVERLAP_CONTAINER_OF.setdefault(_dot, []).append(_container)


def overlap_note(name):
    """Flag string for entities in a known container/dot-cluster overlap
    (see TRIBAL_CONTAINER_OVERLAPS above), else ''."""
    if name in TRIBAL_CONTAINER_OVERLAPS:
        return 'Overlaps dot-tribe(s): ' + ', '.join(TRIBAL_CONTAINER_OVERLAPS[name])
    if name in _OVERLAP_CONTAINER_OF:
        return 'Contained in border: ' + ', '.join(_OVERLAP_CONTAINER_OF[name])
    return ''


PAR_FILENAME_RE = re.compile(r'^PAR(\d{3})\.ASC$', re.IGNORECASE)


def discover_tiles(polity_name):
    """Scan every polareas/<latD>/PAR<lon>.ASC file for the literal polity_name
    string and return the (lat_str, lon_str) tiles that contain it — automates
    what was previously done by hand via `grep -rl "<name>" polareas/`.

    Filename match must be exact (PAR###.ASC) -- some tile folders also contain
    WIP/backup variants like "PAR040 bad partial fix.ASC" alongside the real
    "PAR040.ASC" (found scanning for Persian Empire, tile 120/040); a loose
    startswith/endswith match would treat those as extra, garbage tiles."""
    par_dir = os.path.join(DATA_DIR, 'polareas')
    tiles = []
    for lat_dir in sorted(os.listdir(par_dir)):
        lat_path = os.path.join(par_dir, lat_dir)
        if not os.path.isdir(lat_path):
            continue
        for fname in sorted(os.listdir(lat_path)):
            if not PAR_FILENAME_RE.match(fname):
                continue
            fpath = os.path.join(lat_path, fname)
            try:
                with open(fpath, encoding='latin-1') as f:
                    text = f.read()
            except OSError:
                continue
            if polity_name in text:
                tiles.append((lat_dir, fname[3:6]))
    return tiles


# ── Cities (Milestone 6) ────────────────────────────────────────────────────
#
# Unlike --polity runs, cities aren't scoped to a top-level name -- every
# populated CIT tile is scanned in one pass and the whole thing is upserted
# into the master as a single SourceRun="Cities" block (see
# merge_into_master.py's --polity flag, which is really just "the SourceRun
# value to upsert" and doesn't care that it isn't a PAR owner name here).
# No breakpoint/union machinery is needed either -- each city is already one
# fixed point, so its date-range entries become output rows directly.
# MemberOf is left blank (per the user, 2026-08-17): correctly attributing a
# city to whichever polity contains it at each moment would need a
# point-in-polygon spatial join against the master's own polygons, which
# isn't worth building yet -- doubly so since no polity coverage in the
# master currently extends into the medieval/modern eras a city's own
# date-ranges can reach anyway.
def export_cities(args, generated):
    tiles = discover_city_tiles()
    print(f"Discovered {len(tiles)} populated city tiles (of 1,820 in the full grid)")
    offsets = load_offsets()

    out_geojson = args.out or os.path.join(MAPPER_DIR, 'exports', f'cities_{generated}.geojson')
    out_csv = os.path.splitext(out_geojson)[0] + '.csv'

    out_rows = []
    city_count = 0
    for lat_dir, lon_code in tiles:
        fpath = os.path.join(DATA_DIR, 'cities', lat_dir, f'CIT{lon_code}.TXT')
        with open(fpath, encoding='latin-1') as f:
            lines = [l.rstrip('\r\n') for l in f.readlines()]
        cities = parse_cit_full(lines)
        city_count += len(cities)
        for c in cities:
            point = Point(c['lon'], c['lat'])
            for dr in c['dateRanges']:
                if args.end_year is not None and dr['from'] >= args.end_year:
                    continue
                to_year = min(dr['to'], args.end_year) if args.end_year is not None else dr['to']
                color_r, color_g, color_b = resolve_city_color(dr['colorIndex'], offsets)
                region, subregion = classify_region(point)
                out_rows.append({
                    'Name': dr['name'], 'FromYear': dr['from'], 'ToYear': to_year,
                    'Area': 0.0, 'Type': 'CITY', 'References': '', 'MemberOf': '',
                    'FullPath': dr['name'], 'Region': region, 'Subregion': subregion,
                    'ColorR': color_r, 'ColorG': color_g, 'ColorB': color_b,
                    'OverlapNote': '', 'geometry': point,
                })
    print(f"Parsed {city_count} cities -> {len(out_rows)} date-range rows")

    for idx, r in enumerate(out_rows, start=1):
        r['Index'] = idx
    for r in out_rows:
        r['Generated'] = generated
        r['SourceRun'] = 'Cities'

    prop_cols = ['Index', 'Name', 'FromYear', 'ToYear', 'Area', 'Type', 'References', 'MemberOf',
                 'FullPath', 'Region', 'Subregion', 'ColorR', 'ColorG', 'ColorB', 'Generated',
                 'SourceRun', 'OverlapNote']

    features = [{
        'type': 'Feature',
        'properties': {k: r[k] for k in prop_cols},
        'geometry': mapping(r['geometry']),
    } for r in out_rows]
    fc = {'type': 'FeatureCollection', 'generated': generated, 'features': features}
    os.makedirs(os.path.dirname(out_geojson), exist_ok=True)
    with open(out_geojson, 'w', encoding='utf-8') as f:
        json.dump(fc, f, ensure_ascii=False)
    print(f"Wrote {len(features)} features to {out_geojson}")

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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--polity', default='Roman Republic')
    ap.add_argument('--tiles', nargs='+', default=None,
                     help='lat:lon pairs, e.g. 125:010 130:012 (default: hardcoded Roman Republic tile list, '
                          'unless --auto-tiles is given)')
    ap.add_argument('--auto-tiles', action='store_true',
                     help='Discover tiles automatically by scanning every PAR file for --polity\'s literal '
                          'name, instead of using --tiles or the hardcoded default.')
    ap.add_argument('--out', default=None,
                     help='GeoJSON output path; a sibling .csv is written alongside it. '
                          'Default: exports/<slug>_<today\'s date>.geojson')
    ap.add_argument('--end-year', type=float, default=None,
                     help='Truncate output at this year (applied to the parent AND every secondary, or to '
                          'every city row if --cities is given). Use when a stray entry (e.g. a garrison '
                          'never relabeled after the dataset\'s tracked period ends) would otherwise '
                          'stretch an entity\'s recorded lifespan misleadingly.')
    ap.add_argument('--cities', action='store_true',
                     help='Export every city (CIT tile data) instead of a --polity run -- one global '
                          'SourceRun="Cities" pass, ignores --polity/--tiles/--auto-tiles.')
    args = ap.parse_args()

    if args.cities:
        export_cities(args, date.today().isoformat())
        return

    if args.tiles:
        tile_pairs = [tuple(t.split(':')) for t in args.tiles]
    elif args.auto_tiles:
        tile_pairs = discover_tiles(args.polity)
        print(f"Auto-discovered {len(tile_pairs)} tiles for {args.polity!r}: {tile_pairs}")
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

    tribal_names = build_tribal_name_set(tiles_data)
    print(f"Tribal (areaType=0 dot) names found in scope: {sorted(tribal_names)}")

    def real_type(name):
        return 'TRIBAL_AREA' if is_tribal_name(name, tribal_names) else 'POLITY'

    # ── Parent ───────────────────────────────────────────────────────────────
    print(f"\n=== {args.polity} (parent) ===")
    repair_log = [0]
    parent_match = lambda n, p=args.polity: owner_name(n) == p
    parent_real, parent_transient = find_entries_by_predicate(tiles_data, parent_match, repair_log)
    parent_dots, parent_dots_transient = find_dot_entries_by_predicate(tiles_data, parent_match)
    print(f"Real territory entries: {len(parent_real)}  |  transient/army entries: {len(parent_transient)}  (kept as Type=TRANSIENT)  |  "
          f"tribal dot entries: {len(parent_dots)}  |  transient dot entries: {len(parent_dots_transient)}  |  ring repairs: {repair_log[0]}")

    parent_breakpoints = build_breakpoints(parent_real, parent_match)
    print(f"Breakpoints: {len(parent_breakpoints)}  range: {parent_breakpoints[0] if parent_breakpoints else None} .. {parent_breakpoints[-1] if parent_breakpoints else None}")
    parent_breakpoints = truncate(parent_breakpoints)

    seam_log = [0]
    parent_rows = slice_into_rows(parent_real, parent_breakpoints, parent_match, seam_log)
    print(f"Output rows: {len(parent_rows)}  |  union geometries needing repair: {seam_log[0]}")

    entities = [{'name': args.polity, 'member_of': '', 'type': real_type(args.polity),
                 'rows': parent_rows, 'is_parent': True, 'path': (args.polity,)}]

    # NOTE: root-level transient/dot rows below all use an EXACT match on the
    # bare polity name (root_bare_match), NOT the prefix-matching parent_match
    # used above for the polygon composite. parent_match/parent_dots fold in
    # every nested descendant's entries (correct for the polygon case,
    # matching Cliopatria's composite-duplicates-members convention), but
    # reusing that same fold-in for a root-level entity would merge e.g.
    # Daunians' own dot point into a row mislabeled "Roman Ally" -- Daunians
    # already gets its own correctly-attributed row from the path loop below.
    # A root-level row should only exist for entries whose name is *exactly*
    # the bare root name, with no further "- X" suffix. (Found and fixed this
    # exact bug testing Roman Ally, 2026-08-16.)
    root_bare_match = lambda n, p=args.polity: n.strip() == p

    # Root-level transients (a bare, undashed polity name itself flagged
    # transient -- e.g. a clan-warfare/revolt event with no real territory of
    # its own) were assumed not to occur based on every sample run through
    # 2026-08-16 (every transient found had been nested, e.g. "Parent - Army
    # of X"). Found real counterexamples running the primaries.txt batch
    # 2026-08-17 ("Fan clan", one of Jin's Six Ministers: 2 real transient
    # entries, 0 output rows because this path didn't exist). The real-
    # territory bucket from this call is intentionally discarded -- any
    # bare-root real entries it would find are already folded into
    # parent_rows above via parent_match's inclusive prefix matching, so
    # keeping them here would double-count as a second entity.
    root_trans_repair_log = [0]
    _, root_level_transient = find_entries_by_predicate(tiles_data, root_bare_match, root_trans_repair_log)
    root_trans_breakpoints = truncate(build_breakpoints(root_level_transient, root_bare_match))
    root_trans_seam_log = [0]
    root_trans_rows = slice_into_rows(root_level_transient, root_trans_breakpoints, root_bare_match, root_trans_seam_log)
    if root_trans_rows:
        print(f"  (root-level transient rows: {len(root_trans_rows)})")
        entities.append({'name': args.polity, 'member_of': '', 'type': 'TRANSIENT',
                          'rows': root_trans_rows, 'is_parent': True, 'path': (args.polity,)})

    root_dots, root_dots_transient = find_dot_entries_by_predicate(tiles_data, root_bare_match)

    root_dot_breakpoints = truncate(build_breakpoints(root_dots, root_bare_match))
    root_dot_rows = slice_into_dot_rows(root_dots, root_dot_breakpoints, root_bare_match)
    if root_dot_rows:
        print(f"  (root-level tribal dot rows: {len(root_dot_rows)})")
        entities.append({'name': args.polity, 'member_of': '', 'type': 'TRIBAL_AREA',
                          'rows': root_dot_rows, 'is_parent': True, 'path': (args.polity,)})

    root_dot_trans_breakpoints = truncate(build_breakpoints(root_dots_transient, root_bare_match))
    root_dot_trans_rows = slice_into_dot_rows(root_dots_transient, root_dot_trans_breakpoints, root_bare_match)
    if root_dot_trans_rows:
        print(f"  (root-level transient dot rows: {len(root_dot_trans_rows)})")
        entities.append({'name': args.polity, 'member_of': '', 'type': 'TRANSIENT',
                          'rows': root_dot_trans_rows, 'is_parent': True, 'path': (args.polity,)})

    # ── Nested members: PAR entries named "Parent - X", "Parent - X - Y", ... ──
    # Every distinct prefix path of length >=2 found among the parent's own
    # candidate entries becomes one output entity, at whatever depth it occurs
    # (Milestone 1: previously this only looked at the first dash, flattening
    # e.g. "Roman Ally - Kingdom of Syracuse - Tauromenion" into one entity
    # instead of a proper 2-level chain). Paths are discovered from real,
    # transient, AND dot entries, since a transient's own name (e.g. "Parent -
    # Consular army" — Milestone 2) or a tribal dot cluster's name (Milestone
    # 5) both need discovering too, not just real territory.
    prefix_paths = set()
    for pe in parent_real + parent_transient + parent_dots + parent_dots_transient:
        for dr in pe['entry']['dateRanges']:
            if owner_name(dr['name']) == args.polity:
                path = path_of(dr['name'])
                for k in range(2, len(path) + 1):
                    prefix_paths.add(path[:k])
    sorted_paths = sorted(prefix_paths)
    print(f"\nDiscovered {len(sorted_paths)} nested member paths:")
    for p in sorted_paths:
        print(f"  {' > '.join(p)}")

    for path in sorted_paths:
        depth = len(path)
        entity_match = lambda n, path=path, depth=depth: path_of(n)[:depth] == path
        ent_repair_log = [0]
        ent_real, ent_transient = find_entries_by_predicate(tiles_data, entity_match, ent_repair_log)
        ent_dots, ent_dots_transient = find_dot_entries_by_predicate(tiles_data, entity_match)

        ent_real_breakpoints = truncate(build_breakpoints(ent_real, entity_match))
        ent_seam_log = [0]
        ent_real_rows = slice_into_rows(ent_real, ent_real_breakpoints, entity_match, ent_seam_log, own_path=path)

        ent_trans_breakpoints = truncate(build_breakpoints(ent_transient, entity_match))
        ent_trans_seam_log = [0]
        ent_trans_rows = slice_into_rows(ent_transient, ent_trans_breakpoints, entity_match, ent_trans_seam_log, own_path=path)

        ent_dot_breakpoints = truncate(build_breakpoints(ent_dots, entity_match))
        ent_dot_rows = slice_into_dot_rows(ent_dots, ent_dot_breakpoints, entity_match, own_path=path)

        ent_dot_trans_breakpoints = truncate(build_breakpoints(ent_dots_transient, entity_match))
        ent_dot_trans_rows = slice_into_dot_rows(ent_dots_transient, ent_dot_trans_breakpoints, entity_match, own_path=path)

        print(f"=== {' > '.join(path)} ===  real={len(ent_real)}(rows={len(ent_real_rows)})  "
              f"transient={len(ent_transient)}(rows={len(ent_trans_rows)})  "
              f"tribal_dots={len(ent_dots)}(rows={len(ent_dot_rows)})  "
              f"transient_dots={len(ent_dots_transient)}(rows={len(ent_dot_trans_rows)})  "
              f"ring_repairs={ent_repair_log[0]}  seam_repairs={ent_seam_log[0]}+{ent_trans_seam_log[0]}")

        if ent_real_rows:
            entities.append({'name': path[-1], 'member_of': f'({path[-2]})', 'type': real_type(path[-1]),
                              'rows': ent_real_rows, 'is_parent': False, 'path': path})
        if ent_trans_rows:
            entities.append({'name': path[-1], 'member_of': f'({path[-2]})', 'type': 'TRANSIENT',
                              'rows': ent_trans_rows, 'is_parent': False, 'path': path})
        if ent_dot_rows:
            entities.append({'name': path[-1], 'member_of': f'({path[-2]})', 'type': 'TRIBAL_AREA',
                              'rows': ent_dot_rows, 'is_parent': False, 'path': path})
        if ent_dot_trans_rows:
            entities.append({'name': path[-1], 'member_of': f'({path[-2]})', 'type': 'TRANSIENT',
                              'rows': ent_dot_trans_rows, 'is_parent': False, 'path': path})

    # ── Assemble final rows with resolved color ────────────────────────────────
    out_rows = []
    hull_features = []  # debug-only, see "Write hull-preview GeoJSON" below
    for ent in entities:
        for row in ent['rows']:
            geom = row['geometry']
            if not geom.is_valid:
                print(f"  WARNING: {ent['name']} row {row['FromYear']}..{row['ToYear']} geometry invalid after repair")
            if geom.geom_type in ('Point', 'MultiPoint'):
                area = hull_area_km2(geom)
                hull = hull_geom(geom)
                if hull is not None:
                    hull_features.append({'type': 'Feature',
                                           'properties': {'Name': ent['name'], 'FromYear': row['FromYear'],
                                                           'ToYear': row['ToYear'], 'Area': area,
                                                           'DotCount': len(list(geom.geoms)) if geom.geom_type == 'MultiPoint' else 1},
                                           'geometry': mapping(hull)})
            else:
                area = round(area_km2(geom), 1)
            if ent['is_parent']:
                color = parent_color
                color_r, color_g, color_b = color if color else (None, None, None)
            elif row['color_conflict']:
                # slice_into_rows/slice_into_dot_rows set this when a nested
                # descendant (e.g. a Nome inside "Egypt") is active alongside
                # -- or, in the narrowest case, IS the only active
                # contributor for -- this row's window. Either way the row's
                # own territory (excluding nomes) doesn't have one single
                # true color here: it's genuinely "own color + various nome
                # colors" or, when nothing of its own is active at all,
                # purely nome colors. Confirmed real 2026-08-21: a Persian
                # Empire > Egypt > Egypt > Egypt row had ONLY its Nome 1
                # child active in a 2-year window and silently inherited
                # Nome 1's own color with no conflict even flagged under the
                # old any-contributor-disagreement check -- own_path-based
                # detection catches this too, not just multi-contributor
                # disagreement.
                print(f"  NOTE: {ent['name']} row {row['FromYear']}..{row['ToYear']} includes nested "
                      f"descendant territory -- various component colors, not resolving to one RGB")
                color_r, color_g, color_b = 'various component colors', '', ''
            else:
                color = resolve_color(args.polity, row['color_index'], primaries_map, offsets)
                color_r, color_g, color_b = color if color else (None, None, None)
            region, subregion = classify_region(geom)
            out_rows.append({
                'Name': ent['name'], 'FromYear': row['FromYear'], 'ToYear': row['ToYear'],
                'Area': area, 'Type': ent['type'], 'References': '',
                'MemberOf': ent['member_of'], 'FullPath': ' - '.join(ent['path']),
                'Region': region, 'Subregion': subregion,
                'ColorR': color_r, 'ColorG': color_g, 'ColorB': color_b,
                'OverlapNote': overlap_note(ent['name']),
                'geometry': geom,
            })

    for idx, r in enumerate(out_rows, start=1):
        r['Index'] = idx

    for r in out_rows:
        r['Generated'] = generated
        # Bookkeeping column (not part of Cliopatria's own schema, same as
        # ColorR/G/B): which top-level --polity run produced this row.
        # Milestone 3's merge_into_master.py upsert keys off this to replace
        # a run's own rows in the master without touching any other run's.
        r['SourceRun'] = args.polity

    prop_cols = ['Index', 'Name', 'FromYear', 'ToYear', 'Area', 'Type', 'References', 'MemberOf',
                 'FullPath', 'Region', 'Subregion', 'ColorR', 'ColorG', 'ColorB', 'Generated',
                 'SourceRun', 'OverlapNote']

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

    # ── Write hull-preview GeoJSON (debug only, not part of the delivered
    # dataset / never merged into the master) ──────────────────────────────
    # Lets the user visually check the concave-hull shapes computed for Area
    # against the actual dot points, side by side in QGIS/geojson.io -- the
    # hull polygon itself is otherwise discarded once Area is read off it.
    if hull_features:
        out_hulls = os.path.splitext(out_geojson)[0] + '_hulls.geojson'
        with open(out_hulls, 'w', encoding='utf-8') as f:
            json.dump({'type': 'FeatureCollection', 'features': hull_features}, f, ensure_ascii=False)
        print(f"Wrote {len(hull_features)} hull-preview feature(s) to {out_hulls}")

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
