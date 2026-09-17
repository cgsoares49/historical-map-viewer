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
import argparse
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export_polity_polygons import (
    load_tile, build_combined_ring, ring_to_polygon, is_transient,
    is_keyword_transient, owner_name, path_of, TO_EQUAL_AREA,
)
from shapely.ops import transform

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TILES = ['120:030', '120:035']

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
        poly = ring_to_polygon(ring, repair_log)
        if poly is None or poly.is_empty or not poly.is_valid:
            continue
        proj = transform(TO_EQUAL_AREA, poly)
        out.append({
            'entry': entry, 'proj': proj,
            'area_km2': proj.area / 1_000_000.0,
            'bounds': poly.bounds,
        })
    return out, repair_log[0]


def date_overlap_windows(entry_a, entry_b):
    """Every (from, to) window where entry_a and entry_b are BOTH active with
    DIFFERENT top-level owner names -- the temporal+ownership half of the
    overlay signal. Cheap: no geometry involved, checked before any
    intersection test. A window where either side's owner is UNKNOWN is
    skipped -- an "unclear who ruled this" gap in one entry's own history
    isn't evidence the other entry is a different real owner."""
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
                windows.append((lo, hi))
    return windows


def bbox_overlap(b1, b2):
    return not (b1[2] < b2[0] or b2[2] < b1[0] or b1[3] < b2[1] or b2[3] < b1[1])


def entry_names(entry):
    return sorted(set(owner_name(dr['name']) for dr in entry['dateRanges']))


def _active_segments_during(date_ranges, windows, picker):
    """Shared machinery for active_owners_during/active_last_segment_during
    below: which of this entry's OWN date-ranges actually overlap the given
    windows -- i.e. what it was really doing during the flagged overlap, not
    its whole history -- with `picker` choosing which dash-segment of the
    matching date-range name(s) to report. Returns '(no active entry -- data
    gap here)' if none of the entry's date-ranges cover any of the windows
    at all (a real, informative case: found 2026-09-17, a nome entry can
    have a genuine gap in its own recorded history that happens to coincide
    with the window)."""
    segs = []
    for lo, hi in windows:
        for dr in date_ranges:
            if max(dr['from'], lo) < min(dr['to'], hi):
                segs.append(picker(dr['name']))
    if not segs:
        return '(no active entry -- data gap here)'
    return '; '.join(sorted(set(segs)))


def active_owners_during(date_ranges, windows):
    """The top-level owner (first dash-segment) actually active during the
    flagged windows -- see _active_segments_during. `AllOwnersEver` lists
    every owner an entry has EVER had, which for a long-lived entry (30+
    date-ranges over centuries) buries the one relevant to a specific
    flagged window; this is the targeted answer."""
    return _active_segments_during(date_ranges, windows, owner_name)


def active_last_segment_during(date_ranges, windows):
    """The entry's own place/nome name (LAST dash-segment) during the
    flagged windows -- e.g. 'Lower Egypt Nome 3 Ahment/Ament', regardless of
    which empire currently governs it. Added per user request, to let the
    entry be matched against nome numbers/names on the map or a POL #
    reference. NOT perfectly stable across an entry's whole history --
    checked #113: its own last segment reads 'Lower Egypt Nome 3
    Ahment/Ament' for most of its ~3000-year history but 'Prospithes' in the
    Ptolemaic-Greek-naming era and 'Libu and Meshwesh' during a Libyan
    interregnum -- so this is deliberately scoped to the flagged window via
    the same _active_segments_during machinery as active_owners_during,
    not just "the first name found", to report the name actually in use at
    the relevant moment."""
    return _active_segments_during(date_ranges, windows, lambda n: path_of(n)[-1])


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
    candidates, repairs = load_candidates(tile)
    print(f"  {lat}/{lon}: {len(candidates)} candidate entries (dots/transients excluded, {repairs} ring repairs)")

    entry_info = {}
    for c in candidates:
        key = (lat, lon, c['entry']['entryIndex'])
        entry_info[key] = {'names': entry_names(c['entry']), 'area_km2': round(c['area_km2'], 1),
                            'dateRanges': c['entry']['dateRanges']}

    events = []
    n = len(candidates)
    checked, geom_checked, pairs_flagged = 0, 0, 0
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
            inter = ca['proj'].intersection(cb['proj'])
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
            for lo, hi in windows:
                events.append({'a': key_a, 'b': key_b, 'lo': lo, 'hi': hi, 'ratio': ratio})
    print(f"    {checked} bbox-overlapping pair(s), {geom_checked} passed temporal+ownership, "
          f"{pairs_flagged} pair(s) passed the {min_ratio:.2f} overlap-ratio threshold "
          f"({len(events)} distinct overlap event(s) from those pairs)")
    return entry_info, events


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tiles', nargs='+', default=DEFAULT_TILES,
                     help='lat:lon pairs to scan (default: the two pilot tiles)')
    ap.add_argument('--min-overlap-ratio', type=float, default=DEFAULT_MIN_OVERLAP_RATIO,
                     help='Flag a pair when intersection_area / smaller_entry_area >= this (default 0.6)')
    ap.add_argument('--out', default=os.path.join(MAPPER_DIR, 'exports', 'polity_overlay_candidates.csv'))
    args = ap.parse_args()

    all_entry_info = {}
    all_events = []
    for tile_spec in args.tiles:
        lat, lon = tile_spec.split(':')
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

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['GroupID', 'GroupSize', 'Tile', 'EntryIndex', 'LastNameSegment', 'ActiveDuringOverlap',
                          'AllOwnersEver', 'AreaKm2', 'OverlapFromYear', 'OverlapToYear', 'DistinctWindows',
                          'MaxIntersectionRatio'])
        for gi, (entities, ids) in enumerate(groups, start=1):
            members = sorted(entities, key=lambda k: (k[0], k[1], k[2]))
            windows = sorted({(all_events[i]['lo'], all_events[i]['hi']) for i in ids})
            overlap_from = min(w[0] for w in windows)
            overlap_to = max(w[1] for w in windows)
            max_ratio = max(all_events[i]['ratio'] for i in ids)
            for lat, lon, entry_idx in members:
                info = all_entry_info[(lat, lon, entry_idx)]
                active = active_owners_during(info['dateRanges'], windows)
                last_seg = active_last_segment_during(info['dateRanges'], windows)
                writer.writerow([gi, len(entities), f'{lat}/{lon}', entry_idx,
                                  last_seg, active, '; '.join(info['names']), info['area_km2'],
                                  round(overlap_from, 1), round(overlap_to, 1), len(windows),
                                  round(max_ratio, 3)])
    total_entities = len(set().union(*[e for e, _ in groups])) if groups else 0
    print(f"\nWrote {total_entities} entity row(s) across {len(groups)} relationship group(s) to {args.out}")


if __name__ == '__main__':
    main()
