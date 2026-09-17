"""
find_polity_overlays.py
Scoping pilot for the "polity overlay" authoring pattern (plan approved
2026-09-16, see mapper/exports/... conversation history): sometimes, instead
of properly terminating a parent polity's PAR date range when it's split,
an earlier-era shortcut painted a new child entry over a portion of the
untouched parent, relying on MAPPER's paint order (child drawn after parent)
for the child to be visible. The export pipeline has no paint-order concept
-- it unions everything a polity owns at a date -- so the parent's untouched
entry still claims (and areas) the child's territory too, double-counting it.

This script's job is SCOPING, not fixing: flag candidate PAR entry pairs/
groups in a tile that look like this pattern -- overlapping active date
ranges, different top-level owners, and substantial geometric overlap
between their resolved polygons -- for human review. No auto-fix, no
canonical data writes. The user's actual repair (terminating the parent's
date range, re-authoring clean children) stays a manual step.

Small stuff is deliberately excluded per the plan ("neglect small areas like
city-state dots, transients"): areaType=0 dot entries, and any entry
classified transient (structural sentinel or keyword) -- reuses
export_polity_polygons.py's own classifiers rather than reimplementing them.

A real true-negative case confirmed in this repo's own PAR035 data: entries
#86 ("Amorite Mari"/"Amorite Ebla") and #87 ("Kingdom of Qatna") share one
polyRef for ordinary border-stitching, not an overlay -- that's exactly why
this uses actual geometric intersection area, not a raw shared-polyRef
count, as the overlap signal.

Usage:
  python find_polity_overlays.py
  python find_polity_overlays.py --tiles 120:030 120:035 --min-overlap-ratio 0.7
"""

import os
import sys
import csv
import math
import argparse
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export_polity_polygons import (
    load_tile, build_combined_ring, ring_to_polygon, is_transient,
    is_keyword_transient, owner_name, path_of, TO_EQUAL_AREA, DATA_DIR,
)
import glob
import re
from shapely.ops import transform

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TILES = ['120:030', '120:035']

# The user's own authoring log, going back to 2017 -- entries they
# deliberately flagged "(overlay)"/"(temp overlay)" in the description while
# creating them (28 such rows found 2026-09-17). Real ground truth, not a
# guess: used as a cross-reference, never a requirement -- this whole script
# still works, just without the ConfirmedByLog column, if the file is
# missing/unreadable/moved (a personal file outside this repo, not something
# to depend on hard-failing over).
ANIMATION_LOG_PATH = r'C:\My stuff\VID\animation actions.xlsx'


def load_logged_overlays(path=ANIMATION_LOG_PATH):
    """Returns {tile ('120/030' form): [(start_year, end_year_or_None,
    description), ...]} for every row in the log whose description mentions
    "overlay" -- these are entries the user explicitly remembers authoring
    as an overlay, independent of anything this script detects geometrically.
    Silently returns {} if the file or openpyxl isn't available."""
    try:
        import openpyxl
    except ImportError:
        return {}
    if not os.path.exists(path):
        return {}
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb['data']
        rows = ws.iter_rows(values_only=True, max_col=25)
        next(rows)  # header
        by_tile = {}
        for row in rows:
            desc = row[4] if len(row) > 4 else None
            if not isinstance(desc, str) or 'overlay' not in desc.lower():
                continue
            start_year, end_year = row[2], row[5]
            for cell in row[6:10]:
                if not isinstance(cell, str) or '/' not in cell:
                    continue
                lat_str, lon_str = cell.split('/', 1)
                norm_tile = f"{lat_str}/{lon_str.zfill(3)}"
                by_tile.setdefault(norm_tile, []).append((start_year, end_year, desc))
        return by_tile
    except Exception:
        return {}


def match_logged_overlays(logged_by_tile, tile, group_from, group_to, tolerance=2.0):
    """Logged descriptions whose start year falls within [group_from -
    tolerance, group_to + tolerance] -- a loose match, since the log's dates
    are the user's own manually-typed record, not necessarily byte-identical
    to the eventually-digitized PAR date-range boundaries (confirmed exact
    in every case checked 2026-09-17, but a small tolerance costs nothing
    and guards against the cases that aren't)."""
    hits = []
    for start_year, end_year, desc in logged_by_tile.get(tile, []):
        if isinstance(start_year, (int, float)) and group_from - tolerance <= start_year <= group_to + tolerance:
            hits.append(desc)
    return hits

# Started at 0.6 (near-total containment only). Revised 2026-09-17 after the
# user spotted a real miss by checking the map directly: the "Revolt of
# Inaros" entry (120/030 #281) visibly overlays PORTIONS of Nomes 4 and 6 too,
# not just the three (Nomes 3/5/7) that hit 0.6. Checked directly: Nome 4
# overlaps at ratio 0.083, one of the two Nome 6 pieces at 0.345 -- both real,
# both missed by 0.6. Lowered to 0.05, which pulls both in while still
# correctly excluding the OTHER Nome 6 piece (genuinely 0.0 overlap, not
# just below-threshold) and the known true-negative border-stitch case
# (PAR035 #86/#87, confirmed exactly 0.0 -- a shared boundary LINE has no
# area, so it can never appear above 0 regardless of how low this goes).
DEFAULT_MIN_OVERLAP_RATIO = 0.05

# "UNKNOWN" is a known data-artifact name, not a real polity (same class
# incremental_update_master.py's own SKIP_NAMES already excludes, for a
# different reason -- exporting it hangs). Found here 2026-09-17: tile
# 120/030 entry #74 and 120/035 entry #11 are both a single dateRange
# {from: -9999.0, to: 1990.0, name: 'UNKNOWN'} covering a huge area (72,682
# km^2 and 248,458 km^2) -- almost certainly a background/unclaimed-territory
# fill, not political content. Left in, it geometrically contains dozens of
# real entries (nomes) at ratio=1.0 and, being active across virtually the
# entire dataset's date range, chains all of them into one meaningless
# mega-cluster via event-level connectivity -- confirmed as the actual root
# cause of an initial 81-entity cluster in this same tile pair.
#
# Important: do NOT exclude every entry that has UNKNOWN anywhere in its own
# ownership history -- checked, and 72 of 138 candidate entries in 120/030
# alone have exactly one brief UNKNOWN gap among 30+ otherwise-real
# date-ranges (a normal "unclear who ruled this for a few years" annotation,
# not a placeholder entry). Only entries that are ENTIRELY the placeholder
# pattern -- a single dateRange, owned by UNKNOWN, covering nearly the whole
# dataset -- get dropped; a genuine entry's occasional UNKNOWN gap is instead
# handled in date_overlap_windows() below (that specific window just isn't
# treated as evidence of a different, real owner).
SKIP_NAMES = {'UNKNOWN'}


def is_placeholder_entry(entry):
    return len(entry['dateRanges']) == 1 and owner_name(entry['dateRanges'][0]['name']) in SKIP_NAMES


def load_candidates(tile):
    """Real-territory (non-dot, non-transient) areaType=1 entries with a
    resolved ring polygon, projected geometry, and cached area/bounds --
    everything the pairwise scan needs, computed once per entry."""
    repair_log = [0]
    load_errors = 0
    out = []
    for entry in tile['par_entries']:
        if entry['areaType'] != 1:
            continue
        if is_transient(entry['polyRefs'], tile['pol_by_index']) or \
                any(is_keyword_transient(dr['name']) for dr in entry['dateRanges']):
            continue
        if is_placeholder_entry(entry):
            continue
        ring, has_segment = build_combined_ring(entry['polyRefs'], tile['cst_by_index'], tile['pol_by_index'])
        if not has_segment or len(ring) < 4:
            continue
        try:
            poly = ring_to_polygon(ring, repair_log)
            if poly is None or poly.is_empty or not poly.is_valid:
                continue
            proj = transform(TO_EQUAL_AREA, poly)
            area_km2 = proj.area / 1_000_000.0
            if not math.isfinite(area_km2) or area_km2 <= 0:
                # Found scanning the full tile grid, 2026-09-17: a handful of
                # rings pass is_valid but still produce a NaN/non-finite area
                # (a different, quieter failure mode than the GEOSException
                # caught above -- same underlying degenerate-ring cause,
                # just surfaces as a bad number instead of a raised error).
                # A NaN area breaks every downstream ratio/comparison
                # silently, so treat it the same as a hard geometry error.
                load_errors += 1
                continue
        except Exception:
            # Same class of rare GEOS failure on a degenerate ring as the
            # pairwise intersection guard below -- skip this one entry
            # rather than crash the whole tile.
            load_errors += 1
            continue
        out.append({
            'entry': entry, 'proj': proj,
            'area_km2': area_km2,
            'bounds': poly.bounds,
        })
    return out, repair_log[0], load_errors


def date_overlap_windows(entry_a, entry_b):
    """Every window where entry_a and entry_b are BOTH active with DIFFERENT
    top-level owner names -- the temporal+ownership half of the overlay
    signal. Cheap: no geometry involved, checked before any intersection
    test. A window where either side's owner is UNKNOWN is skipped -- an
    "unclear who ruled this" gap in one entry's own history isn't evidence
    the other entry is a different real owner.

    Returns (lo, hi, dur_a, dur_b) tuples -- dur_a/dur_b are the FULL span of
    the specific contributing date-range on each side (not just the window,
    which is their intersection), used by the stack-depth heuristic below:
    in every manually-confirmed real case so far, the shorter-lived side of
    a conflicting pair turned out to be the overlay (a brief event) and the
    longer-lived side the base territory it was drawn over."""
    windows = []
    for dr_a in entry_a['dateRanges']:
        owner_a = owner_name(dr_a['name'])
        if owner_a in SKIP_NAMES:
            continue
        for dr_b in entry_b['dateRanges']:
            owner_b = owner_name(dr_b['name'])
            if owner_b in SKIP_NAMES:
                continue
            lo, hi = max(dr_a['from'], dr_b['from']), min(dr_a['to'], dr_b['to'])
            if lo < hi and owner_a != owner_b:
                windows.append((lo, hi, dr_a['to'] - dr_a['from'], dr_b['to'] - dr_b['from']))
    return windows


def bbox_overlap(b1, b2):
    return not (b1[2] < b2[0] or b2[2] < b1[0] or b1[3] < b2[1] or b2[3] < b1[1])


def entry_names(entry):
    return sorted(set(owner_name(dr['name']) for dr in entry['dateRanges']))


def active_last_segment_during(date_ranges, windows):
    """The entry's own place/nome name (LAST dash-segment) actually active
    during the given windows -- e.g. 'Lower Egypt Nome 3 Ahment/Ament',
    regardless of which empire currently governs it -- not its whole
    history. Added per user request, to let the entry be matched against
    nome numbers/names on the map or a POL # reference. NOT perfectly
    stable across an entry's whole history -- checked #113: its own last
    segment reads 'Lower Egypt Nome 3 Ahment/Ament' for most of its
    ~3000-year history but 'Prospithes' in the Ptolemaic-Greek-naming era
    and 'Libu and Meshwesh' during a Libyan interregnum -- so this is
    deliberately scoped to the given windows, not just "the first name
    found", to report the name actually in use at the relevant moment.
    Returns '(no active entry -- data gap here)' if none of the entry's
    date-ranges cover any of the windows at all (a real, informative case:
    found 2026-09-17, a nome entry can have a genuine gap in its own
    recorded history that happens to coincide with the window)."""
    segs = []
    for lo, hi in windows:
        for dr in date_ranges:
            if max(dr['from'], lo) < min(dr['to'], hi):
                segs.append(path_of(dr['name'])[-1])
    if not segs:
        return '(no active entry -- data gap here)'
    return '; '.join(sorted(set(segs)))


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def discover_all_tiles():
    """Every PAR<lon>.ASC file under DATA_DIR/polareas/<lat>/ -- the full
    populated tile grid (1822 tiles as of 2026-09-17), not just the two
    pilot tiles. Mirrors export_polity_polygons.py's own --auto-tiles
    discovery pattern, scoped globally instead of by polity name."""
    pattern = os.path.join(DATA_DIR, 'polareas', '*', 'PAR*.ASC')
    tiles = []
    for path in glob.glob(pattern):
        lat = os.path.basename(os.path.dirname(path))
        m = re.match(r'PAR(\d+)\.ASC$', os.path.basename(path), re.IGNORECASE)
        if m:
            tiles.append((lat, m.group(1)))
    return sorted(tiles)


def format_window(windows):
    return f"{min(w[0] for w in windows):.1f}..{max(w[1] for w in windows):.1f}"


def compute_stack(entities, ids, all_events):
    """Assigns each entity in a group a STACK DEPTH (1 = base/bottom, higher
    = drawn later/on top) via a directed "shorter-lived side is above"
    graph, built PER EVENT (not per aggregated entity-pair, since the same
    two entities can be on either side of that relationship at different
    points in their shared history): for every event, whichever side's OWN
    specific date-range (dur_a/dur_b) is shorter is treated as drawn on top
    of the longer-lived side. Confirmed against three real, manually
    cross-checked cases (Revolt of Inaros over 5 nomes: 8 years vs.
    centuries; a brief "Israelites" entry over 4 Levantine polities: 5 years
    vs. centuries; a brief "Rebel Israelites" entry nested inside a longer
    Israelites/Philistines border dispute: 2 years vs. decades) and against
    the user's own authoring log (animation actions.xlsx) confirming these
    as deliberately-created overlays -- every one had the overlay (child)
    side measured in single-digit-to-low-double-digit years, its base
    (parent) side in decades to centuries. Generalizes past the old
    single-hub heuristic: a genuine 3+-layer stack (grandparent -> parent ->
    child) resolves to depths 1/2/3 automatically, since depth(e) = 1 for a
    pure base (never the shorter side of anything in this group) and
    1 + max(depth of everything e is above) otherwise -- standard DAG
    longest-path layering.

    Returns (depth, above, overlaid_by, cyclic):
      depth: {entity: int}, empty if the group contains a genuine cycle
        (e above f above ... above e -- a real contradiction, not just "this
        needs multiple levels") -- the caller falls back to a flat
        AMBIGUOUS report for a cyclic group rather than trust a broken order.
      above[e] = {f: {'pct': max %, 'windows': [...]}}: what e sits on top of.
      overlaid_by[e] = {g: {...}}: the reverse -- what sits on top of e.
      cyclic: bool.
    """
    above = {e: {} for e in entities}
    for i in ids:
        ev = all_events[i]
        a, b = ev['a'], ev['b']
        if a not in entities or b not in entities:
            continue
        if ev['dur_a'] < ev['dur_b'] or (ev['dur_a'] == ev['dur_b'] and a < b):
            hi_e, lo_e, pct_hi = a, b, ev['pct_a']
        else:
            hi_e, lo_e, pct_hi = b, a, ev['pct_b']
        rec = above[hi_e].setdefault(lo_e, {'pct': 0.0, 'windows': []})
        rec['pct'] = max(rec['pct'], pct_hi)
        rec['windows'].append((ev['lo'], ev['hi']))

    overlaid_by = {e: {} for e in entities}
    for e in entities:
        for f in above[e]:
            overlaid_by[f][e] = above[e][f]

    # Cycle detection (plain DFS, recursion-stack based) before trusting any
    # depth -- a real contradiction (inconsistent duration ordering across
    # different windows) must not silently produce a wrong/meaningless order.
    state = {}  # 0=unvisited, 1=on stack, 2=done
    cyclic = False

    def has_cycle(e):
        nonlocal cyclic
        state[e] = 1
        for f in above[e]:
            if state.get(f, 0) == 1:
                cyclic = True
                return
            if state.get(f, 0) == 0:
                has_cycle(f)
                if cyclic:
                    return
        state[e] = 2

    for e in entities:
        if state.get(e, 0) == 0:
            has_cycle(e)
        if cyclic:
            return {}, above, overlaid_by, True

    depth = {}

    def compute_depth(e):
        if e in depth:
            return depth[e]
        best = max((compute_depth(f) for f in above[e]), default=0)
        depth[e] = 1 + best
        return depth[e]

    for e in entities:
        compute_depth(e)
    return depth, above, overlaid_by, False


def scan_tile(lat, lon, min_ratio):
    """Returns (entry_info, events) for this tile:
    entry_info: {(lat,lon,entryIndex): {'names', 'area_km2'}} for every
      candidate entry (not just flagged ones -- cheap, and useful context).
    events: one dict per (entry pair, qualifying date-range sub-window) --
      {'a', 'b', 'lo', 'hi', 'ratio'}. A single long-lived entry pair with
      several ownership-history date-ranges can contribute several events at
      different points in time; kept separate (not collapsed into one
      envelope per pair) so the caller can cluster on genuine temporal
      overlap between events, not just "these two entries matched somewhere,
      sometime" -- collapsing to one envelope per pair was found to silently
      bridge matches thousands of years apart into one meaningless cluster
      (two long-lived, mostly-independently-redigitized "Egypt" boundary
      entries whose dynasty-transition years never quite lined up matched at
      scattered points across their whole ~3000-year shared history, which a
      naive per-pair envelope reported as one continuous -9999..-1 "overlap").
    """
    tile = load_tile(lat, lon)
    candidates, repairs, load_errors = load_candidates(tile)
    print(f"  {lat}/{lon}: {len(candidates)} candidate entries (dots/transients excluded, {repairs} ring repairs)"
          + (f"  [{load_errors} geometry error(s) skipped]" if load_errors else ""))

    entry_info = {}
    for c in candidates:
        key = (lat, lon, c['entry']['entryIndex'])
        entry_info[key] = {'names': entry_names(c['entry']), 'area_km2': round(c['area_km2'], 1),
                            'dateRanges': c['entry']['dateRanges']}

    events = []
    n = len(candidates)
    checked, geom_checked, pairs_flagged, geos_errors = 0, 0, 0, 0
    for i in range(n):
        for j in range(i + 1, n):
            ca, cb = candidates[i], candidates[j]
            if not bbox_overlap(ca['bounds'], cb['bounds']):
                continue
            checked += 1
            windows = date_overlap_windows(ca['entry'], cb['entry'])
            if not windows:
                continue
            geom_checked += 1
            try:
                inter = ca['proj'].intersection(cb['proj'])
            except Exception:
                # GEOS can throw on a degenerate ring (e.g. "Edge direction
                # cannot be determined because endpoints are equal") even
                # when shapely's own .is_valid reported the polygon fine --
                # found scanning tile 125/025 during the full-tile sweep,
                # 2026-09-17. Skip this one pair rather than crash the whole
                # run; geos_errors is reported per-tile so real data quality
                # issues stay visible instead of silently vanishing.
                geos_errors += 1
                continue
            inter_area_km2 = (inter.area / 1_000_000.0) if not inter.is_empty else 0.0
            smaller = min(ca['area_km2'], cb['area_km2'])
            if smaller <= 0:
                continue
            ratio = inter_area_km2 / smaller
            if ratio < min_ratio:
                continue
            pairs_flagged += 1
            key_a = (lat, lon, ca['entry']['entryIndex'])
            key_b = (lat, lon, cb['entry']['entryIndex'])
            # pct_a/pct_b: what fraction of EACH side's own area the overlap
            # covers -- asymmetric and both kept (unlike `ratio`, which only
            # keeps the smaller-side fraction) because compute_stack() below
            # needs to know, for a given ordered (X,Y) pair, specifically
            # "how much of X does Y cover", not just the generic match strength.
            pct_a = inter_area_km2 / ca['area_km2'] * 100 if ca['area_km2'] > 0 else 0.0
            pct_b = inter_area_km2 / cb['area_km2'] * 100 if cb['area_km2'] > 0 else 0.0
            for lo, hi, dur_a, dur_b in windows:
                events.append({'a': key_a, 'b': key_b, 'lo': lo, 'hi': hi, 'ratio': ratio,
                                'pct_a': pct_a, 'pct_b': pct_b, 'dur_a': dur_a, 'dur_b': dur_b})
    print(f"    {checked} bbox-overlapping pair(s), {geom_checked} passed temporal+ownership, "
          f"{pairs_flagged} pair(s) passed the {min_ratio:.2f} overlap-ratio threshold "
          f"({len(events)} distinct overlap event(s) from those pairs)"
          + (f"  [{geos_errors} GEOS error(s) skipped]" if geos_errors else ""))
    return entry_info, events


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tiles', nargs='+', default=DEFAULT_TILES,
                     help='lat:lon pairs to scan (default: the two pilot tiles)')
    ap.add_argument('--all-tiles', action='store_true',
                     help='Scan every populated PAR tile (discovered from disk) instead of --tiles')
    ap.add_argument('--min-overlap-ratio', type=float, default=DEFAULT_MIN_OVERLAP_RATIO,
                     help='Flag a pair when intersection_area / smaller_entry_area >= this (default 0.6)')
    ap.add_argument('--out', default=os.path.join(MAPPER_DIR, 'exports', 'polity_overlay_candidates.csv'))
    args = ap.parse_args()

    if args.all_tiles:
        tile_pairs = discover_all_tiles()
        print(f"Discovered {len(tile_pairs)} populated tiles.")
    else:
        tile_pairs = [tuple(t.split(':')) for t in args.tiles]

    all_entry_info = {}
    all_events = []
    for lat, lon in tile_pairs:
        print(f"Scanning {lat}/{lon} ...")
        entry_info, events = scan_tile(lat, lon, args.min_overlap_ratio)
        all_entry_info.update(entry_info)
        all_events.extend(events)

    # Cluster at the EVENT level, not the entity level: two events merge only
    # if they share an entry AND their own windows actually overlap in time.
    # A plain entity-level union-find (merge any two entities that were EVER
    # flagged together, regardless of when) was tried first and produced two
    # meaningless tile-spanning clusters of 52 and 99 entries each, with a
    # reported overlap window of -9999..-1 -- the entire dataset's date
    # range. Root cause: several long-lived, independently-redigitized
    # boundary entries (multiple "Egypt" entries covering ~3000 years of
    # dynasty changes each) matched each other at scattered, mutually
    # unrelated points across their shared history (non-synchronized
    # dynasty-transition years), and entity-level union-find chained all of
    # those scattered, unrelated matches into one blob. Event-level
    # clustering keeps genuinely simultaneous overlaps (the real "one parent,
    # several children at once" pattern this pilot is looking for) together
    # while keeping centuries-apart coincidental matches separate.
    uf = UnionFind()
    n_events = len(all_events)
    for idx in range(n_events):
        uf.find(idx)
    for i in range(n_events):
        ei = all_events[i]
        for j in range(i + 1, n_events):
            ej = all_events[j]
            if ei['a'] not in (ej['a'], ej['b']) and ei['b'] not in (ej['a'], ej['b']):
                continue
            if ei['lo'] < ej['hi'] and ej['lo'] < ei['hi']:
                uf.union(i, j)

    event_clusters = {}
    for idx in range(n_events):
        event_clusters.setdefault(uf.find(idx), []).append(idx)

    cluster_entities = []
    for ids in event_clusters.values():
        entities = set()
        for i in ids:
            entities.add(all_events[i]['a'])
            entities.add(all_events[i]['b'])
        cluster_entities.append((entities, ids))

    # Same entity-set can legitimately produce several temporally-coherent
    # clusters in a row -- e.g. "Edomites" vs "Judah" overlapping across 9
    # separate adjacent-but-non-touching date sub-windows, because their many
    # ownership-history date-ranges chop what's really one persistent
    # relationship into several strictly-non-overlapping chunks. Reporting
    # each chunk as its own cluster inflates the volume count and buries the
    # real number of distinct relationships needing review, so merge same-
    # entity-set clusters into one reportable group here -- this is safe
    # (unlike the earlier entity-level union-find bug) because it only merges
    # groups that are ALREADY identical in membership, never pulls in a third
    # party via a shared-but-unrelated entity.
    groups_by_entities = {}
    for entities, ids in cluster_entities:
        key = frozenset(entities)
        groups_by_entities.setdefault(key, []).extend(ids)
    groups = sorted(groups_by_entities.items(), key=lambda kv: -len(kv[0]))

    size_counts = Counter(len(entities) for entities, _ in groups)
    print(f"\n{n_events} overlap event(s) -> {len(cluster_entities)} temporally-coherent cluster(s) "
          f"-> {len(groups)} distinct relationship(s) after merging same-entity-set clusters:")
    for size in sorted(size_counts):
        label = 'pair' if size == 2 else f'{size}-way group'
        print(f"  {size_counts[size]} relationship(s) of size {size} ({label})")
    if not groups:
        print("  (nothing flagged at this threshold)")

    logged_by_tile = load_logged_overlays()
    if logged_by_tile:
        n_logged = sum(len(v) for v in logged_by_tile.values())
        print(f"\nLoaded {n_logged} logged overlay action(s) from {ANIMATION_LOG_PATH} for cross-reference.")
    else:
        print(f"\n(No cross-reference: {ANIMATION_LOG_PATH} not found/readable -- ConfirmedByLog will be blank.)")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    cyclic_groups = 0
    max_depth_seen = 1
    with open(args.out, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['GroupID', 'GroupSize', 'Tile', 'EntryIndex', 'LastNameSegment', 'StackDepth', 'Role',
                          'Overlays', 'OverlaidBy', 'AreaKm2', 'GroupWindowFrom', 'GroupWindowTo',
                          'DistinctWindows', 'MaxIntersectionRatio', 'ConfirmedByLog', 'AllOwnersEver'])
        for gi, (entities, ids) in enumerate(groups, start=1):
            members = sorted(entities, key=lambda k: (k[0], k[1], k[2]))
            group_windows = sorted({(all_events[i]['lo'], all_events[i]['hi']) for i in ids})
            group_from = min(w[0] for w in group_windows)
            group_to = max(w[1] for w in group_windows)
            max_ratio = max(all_events[i]['ratio'] for i in ids)
            depth, above, overlaid_by, cyclic = compute_stack(entities, ids, all_events)
            if cyclic:
                cyclic_groups += 1
            else:
                max_depth_seen = max(max_depth_seen, max(depth.values()))

            group_tile = f"{members[0][0]}/{members[0][1]}"
            logged_hits = match_logged_overlays(logged_by_tile, group_tile, group_from, group_to)
            confirmed_by_log = '; '.join(logged_hits)

            def display_name(key):
                info = all_entry_info[key]
                own_windows = sorted({w for rec in list(above.get(key, {}).values()) + list(overlaid_by.get(key, {}).values())
                                       for w in rec['windows']}) or group_windows
                return active_last_segment_during(info['dateRanges'], own_windows)

            names = {k: display_name(k) for k in members}

            def format_relations(rec_dict, label):
                return '; '.join(f"{names[o]} ({rec_dict[o]['pct']:.0f}% {label}) [{format_window(rec_dict[o]['windows'])}]"
                                  for o in sorted(rec_dict, key=lambda k: -rec_dict[k]['pct']))

            for key in members:
                lat, lon, entry_idx = key
                info = all_entry_info[key]

                if cyclic:
                    stack_depth, role, overlays_str, overlaid_by_str = '', 'AMBIGUOUS (cyclic evidence)', '', ''
                else:
                    stack_depth = depth[key]
                    role = 'BASE' if stack_depth == 1 else 'OVERLAY'
                    overlays_str = format_relations(above[key], 'of its own area') if above[key] else ''
                    overlaid_by_str = format_relations(overlaid_by[key], 'of THIS entity covered') if overlaid_by[key] else ''

                writer.writerow([gi, len(entities), f'{lat}/{lon}', entry_idx, names[key], stack_depth, role,
                                  overlays_str, overlaid_by_str, info['area_km2'],
                                  round(group_from, 1), round(group_to, 1), len(group_windows),
                                  round(max_ratio, 3), confirmed_by_log, '; '.join(info['names'])])
    total_entities = len(set().union(*[e for e, _ in groups])) if groups else 0
    print(f"\nWrote {total_entities} entity row(s) across {len(groups)} relationship group(s) to {args.out}")
    print(f"  Stack depths found: up to {max_depth_seen} layer(s).")
    if cyclic_groups:
        print(f"  ({cyclic_groups} group(s) had a genuine cyclic contradiction in the duration ordering -- "
              f"marked AMBIGUOUS, review manually)")


if __name__ == '__main__':
    main()
