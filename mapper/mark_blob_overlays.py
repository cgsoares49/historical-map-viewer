"""
mark_blob_overlays.py
Finds small, compact "blob" overlays (city-states, garrisons, revolts, stasis
fragments ...) among find_polity_overlays.py's candidates, so they can be
marked areaType=2 (confirmed semi-transient) in the PAR files instead of
being reviewed one by one. See the approved plan (2026-10-01).

DRY RUN BY DEFAULT: nothing is written to any PAR file. Writes
  exports/blob_overlay_proposal.csv     one row per overlayer entry + its tier
  exports/par_direction_suspects.csv    PAR entries whose polyRef flags look flipped
and prints a summary with a sensitivity table for the area threshold.

An entry is AUTO (proposed for areaType 1 -> 2) only if ALL hold:
  1. INSIDE a bigger entry: in >= 1 detector overlap event it is <= HIER_RATIO
     of the other entry's area and >= INSIDE_MIN_PCT of its own area is covered
     by it; and >= CONTAIN_MIN of its area lies inside the union of the entries
     it sits in. (An earlier duration-based "shorter-lived side is the overlay"
     gate was dropped: it failed 13 of the user's 19 hand-marked entries --
     in the Carthage/Numidia tiles the base entry's own ownership date-ranges
     are short, so the city-state counts as the "longer-lived" side. The user
     marks these by nature -- a small blob inside a much bigger polygon -- not
     by duration. UpperSharePct is kept as an informational column.)
  2. area <= --max-area
  3. blob-shaped: Polsby-Popper >= PP_MIN and minimum-rotated-rectangle
     aspect <= ASPECT_MAX (both: each alone has a known blind spot)
  4. not already areaType 2, and no polyRef-direction suspicion (flip-fixable
     join): a wrong 0/1 flag makes a bowtie whose repaired lobes can themselves
     be the "overlay", so those are held for a border fix first.
areaType is per ENTRY, but the exporter's subtraction is geometric and
date-aware, so marking a long-lived city-state is safe: it only carves area
where it really overlaps something (e.g. Utica's overlay windows are 0.7% of
its life and the user marked it anyway). LifetimeCoverage is informational.
Entries failing exactly one of 1-3 are NEAR-MISS:<rule>. Others are MANUAL.

Usage:
  python mark_blob_overlays.py --all-tiles
  python mark_blob_overlays.py --tiles 120:030 120:035 --max-area 3000
"""

import os
import sys
import csv
import math
import argparse
import contextlib
import io
import random
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export_polity_polygons import (
    load_tile, build_combined_ring, ring_to_polygon, owner_name, TO_EQUAL_AREA,
    is_semitransient_entry,
)
from find_polity_overlays import (
    scan_tile, load_candidates, discover_all_tiles, load_transient_registry,
    load_logged_overlays, match_logged_overlays, active_last_segment_during,
    entry_names, DEFAULT_MIN_OVERLAP_RATIO, SKIP_NAMES,
)
from shapely.geometry import Polygon
from shapely.ops import transform, unary_union

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORTS = os.path.join(MAPPER_DIR, 'exports')
ANCIENT_INDEX_PATH = r'C:\My stuff\VID\ancient index.xlsx'

CONTAIN_MIN = 0.70       # calibrated on the user's 19 hand-marked entries (min 75.9%)
HIER_RATIO = 0.5         # blob must be <= this fraction of the entry it sits in
INSIDE_MIN_PCT = 30.0    # ... with at least this % of its own area covered by it
PP_MIN = 0.30
ASPECT_MAX = 3.5         # hand-marked set reaches 3.24 (Utica); 4.07 (Southern Oasis) still excluded
DEFAULT_MAX_AREA = 5000.0
JOIN_TOL = 0.05          # degrees; segment end-to-start gap treated as "joined"
SENSITIVITY_AREAS = [1000, 2000, 5000, 10000, 25000]


# ── shape metrics (on equal-area projected geometry, metres) ───────────────

def shape_metrics(proj):
    area = proj.area
    per = proj.length
    pp = (4 * math.pi * area / (per * per)) if per > 0 else 0.0
    aspect = 99.0
    try:
        rect = proj.minimum_rotated_rectangle
        if rect.geom_type == 'Polygon':
            c = list(rect.exterior.coords)
            s1 = math.hypot(c[1][0] - c[0][0], c[1][1] - c[0][1])
            s2 = math.hypot(c[2][0] - c[1][0], c[2][1] - c[1][1])
            lo, hi = min(s1, s2), max(s1, s2)
            aspect = hi / lo if lo > 0 else 99.0
    except Exception:
        pass
    return pp, aspect


# ── polyRef direction scan (Part 2) ────────────────────────────────────────

def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _segments_of(entry, tile):
    """[(ref_position, pol_index, flag, points_as_written_oriented)] for the
    entry's real segment refs (flag 0/1 only; literal-coordinate refs skipped,
    same as build_combined_ring treats them as plain points, not segments)."""
    segs = []
    for pos, (pi, fl) in enumerate(entry['polyRefs']):
        if fl not in (0, 1):
            continue
        poly = tile['cst_by_index'].get(pi) if pi <= 1000 else tile['pol_by_index'].get(pi - 1000)
        if not poly or not poly['points']:
            continue
        pts = poly['points'] if fl == 0 else list(reversed(poly['points']))
        segs.append((pos, pi, fl, pts))
    return segs


def _chain_gap_sum(pts_list):
    return sum(_dist(pts_list[i][-1], pts_list[i + 1][0]) for i in range(len(pts_list) - 1))


def _ring_area_km2(poly_refs, tile):
    ring, has_seg = build_combined_ring(poly_refs, tile['cst_by_index'], tile['pol_by_index'])
    if not has_seg or len(ring) < 4:
        return None, None
    try:
        poly = ring_to_polygon(ring, [0])
        if poly is None or poly.is_empty:
            return None, None
        valid_raw = poly.is_valid
        a = transform(TO_EQUAL_AREA, poly).area / 1e6
        return (a if math.isfinite(a) else None), valid_raw
    except Exception:
        return None, None


def direction_scan_entry(entry, tile):
    """Flip-fixable joins for one entry: consecutive segments that don't join
    as written, but would if one of the two had its 0/1 flag flipped. Returns
    a list of dicts (one per fixable join). Pure gaps that no single flip
    closes are NOT returned (informational only, mostly benign: tile-edge
    segments, UNKNOWN fills). Report-only -- nothing is ever edited here."""
    segs = _segments_of(entry, tile)
    if len(segs) < 2:
        return []
    pts_list = [s[3] for s in segs]
    base_sum = _chain_gap_sum(pts_list)
    out = []
    for i in range(len(segs) - 1):
        g = _dist(pts_list[i][-1], pts_list[i + 1][0])
        if g <= JOIN_TOL:
            continue
        best = None
        for k in (i, i + 1):
            trial = list(pts_list)
            trial[k] = list(reversed(trial[k]))
            if _dist(trial[i][-1], trial[i + 1][0]) > JOIN_TOL:
                continue
            tsum = _chain_gap_sum(trial)
            if best is None or tsum < best[0]:
                best = (tsum, k)
        if best is None:
            continue
        k = best[1]
        pos, pi, fl, _ = segs[k]
        new_refs = list(entry['polyRefs'])
        new_refs[pos] = (pi, 1 - fl)
        a0, v0 = _ring_area_km2(entry['polyRefs'], tile)
        a1, v1 = _ring_area_km2(new_refs, tile)
        out.append({'join': f'{segs[i][1]}->{segs[i + 1][1]}', 'ref_pos': pos, 'pol': pi,
                    'flag': fl, 'suggest_flag': 1 - fl, 'gap_before': round(g, 4),
                    'chain_gap_before': round(base_sum, 4), 'chain_gap_after': round(best[0], 4),
                    'area_before': None if a0 is None else round(a0, 1),
                    'area_after': None if a1 is None else round(a1, 1),
                    'valid_before': v0, 'valid_after': v1})
    return out


# ── Ancient Index "tribal dots" sheet (negative control) ───────────────────

def load_tribal_dot_log(path=ANCIENT_INDEX_PATH):
    """{tile 'lat/lon' zero-padded: {PAR#}} from the tribal dots sheet. PAR#
    values are a snapshot from creation time and drift, so a hit is only a
    weak 'worth a look' signal, never an exclusion."""
    out = defaultdict(set)
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb['tribal dots']
        header = None
        for row in ws.iter_rows(values_only=True):
            if header is None:
                header = row
                continue
            # tile at col 5 (+ PAR# at col 7); further (Tile, POL#, PAR#) triples from col 12
            triples = [(row[5], row[7])]
            for c in range(12, len(row) - 2, 3):
                triples.append((row[c], row[c + 2]))
            for tile, par in triples:
                if not tile or par in (None, ''):
                    continue
                try:
                    la, lo = str(tile).split('/')
                    out[f'{int(la):03d}/{int(lo):03d}'].add(int(par))
                except (ValueError, TypeError):
                    continue
        wb.close()
    except Exception as e:
        print(f"(No tribal-dots cross-reference: {e})")
    return out


# ── per-entry analysis ─────────────────────────────────────────────────────

def merge_windows(wins):
    wins = sorted(wins)
    out = []
    for lo, hi in wins:
        if out and lo <= out[-1][1]:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return out


def lifetime_coverage(date_ranges, windows):
    """Fraction of the entry's own non-UNKNOWN date-range time covered by the
    given overlay windows."""
    merged = merge_windows(windows)
    total = covered = 0.0
    for dr in date_ranges:
        if owner_name(dr['name']) in SKIP_NAMES:
            continue
        span = dr['to'] - dr['from']
        if span <= 0:
            continue
        total += span
        for lo, hi in merged:
            ov = min(dr['to'], hi) - max(dr['from'], lo)
            if ov > 0:
                covered += ov
    return (covered / total) if total > 0 else 0.0, total


def owners_during(date_ranges, windows):
    s = set()
    for lo, hi in windows:
        for dr in date_ranges:
            if max(dr['from'], lo) < min(dr['to'], hi):
                s.add(owner_name(dr['name']))
    return '; '.join(sorted(s))


def analyse_tile(lat, lon, events, args, tribal_log):
    """events: this tile's overlap events. Returns (rows, dir_rows, ring_rows)."""
    tile = load_tile(lat, lon)
    cands, _, _, _ = load_candidates(tile, f'{lat}/{lon}', *args.registry)
    by_key = {(lat, lon, c['entry']['entryIndex']): c for c in cands}

    # Per event: (a) the shorter-lived "upper" side (informational only) and
    # (b) which side, if any, is a small entry sitting INSIDE the other.
    upper_events = defaultdict(list)
    lower_wins = defaultdict(list)
    inside_events = defaultdict(list)
    for ev in events:
        a, b = ev['a'], ev['b']
        if ev['dur_a'] < ev['dur_b'] or (ev['dur_a'] == ev['dur_b'] and a < b):
            hi_e, lo_e = a, b
        else:
            hi_e, lo_e = b, a
        upper_events[hi_e].append((lo_e, ev['lo'], ev['hi']))
        lower_wins[lo_e].append((ev['lo'], ev['hi']))
        ca_, cb_ = by_key.get(a), by_key.get(b)
        if ca_ is None or cb_ is None:
            continue
        for x, y, cx, cy, pct_x in ((a, b, ca_, cb_, ev['pct_a']), (b, a, cb_, ca_, ev['pct_b'])):
            if pct_x >= INSIDE_MIN_PCT and cx['area_km2'] <= HIER_RATIO * cy['area_km2']:
                inside_events[x].append((y, ev['lo'], ev['hi']))

    dir_cache = {}
    dir_rows = []
    ring_rows = []
    bad_ring = set()
    for key, c in by_key.items():
        entry = c['entry']
        ring, _ = build_combined_ring(entry['polyRefs'], tile['cst_by_index'], tile['pol_by_index'])
        try:
            if not Polygon(ring).is_valid:
                bad_ring.add(key)
                ring_rows.append({'Tile': f'{lat}/{lon}', 'EntryIndex': entry['entryIndex'],
                                  'Name': '; '.join(entry_names(entry))[:80],
                                  'RepairedAreaKm2': round(c['area_km2'], 1), 'PolyRefs': len(entry['polyRefs'])})
        except Exception:
            pass
        fixes = direction_scan_entry(entry, tile)
        if fixes:
            dir_cache[key] = fixes
            for fx in fixes:
                dir_rows.append({'Tile': f'{lat}/{lon}', 'EntryIndex': entry['entryIndex'],
                                 'Name': '; '.join(entry_names(entry))[:80],
                                 'Joins': fx['join'], 'PolyRefPosition': fx['ref_pos'],
                                 'PolIndex': fx['pol'], 'CurrentFlag': fx['flag'],
                                 'SuggestedFlag': fx['suggest_flag'],
                                 'GapBefore': fx['gap_before'],
                                 'ChainGapBefore': fx['chain_gap_before'],
                                 'ChainGapAfter': fx['chain_gap_after'],
                                 'AreaKm2Before': fx['area_before'], 'AreaKm2After': fx['area_after'],
                                 'ValidBefore': fx['valid_before'], 'ValidAfter': fx['valid_after']})

    rows = []
    for key in set(upper_events) | set(inside_events):
        ups = inside_events.get(key) or upper_events[key]
        c = by_key.get(key)
        if c is None:
            continue
        entry = c['entry']
        wins = [(lo, hi) for _, lo, hi in ups]
        cov, life_total = lifetime_coverage(entry['dateRanges'], wins)
        up_len = sum(h - l for l, h in merge_windows([(lo, hi) for _, lo, hi in upper_events.get(key, [])]))
        low_len = sum(h - l for l, h in merge_windows(lower_wins.get(key, [])))
        upper_share = up_len / (up_len + low_len) if (up_len + low_len) > 0 else 1.0
        overlaid = {o for o, _, _ in ups}
        union = unary_union([by_key[o]['proj'] for o in overlaid if o in by_key])
        try:
            contained = c['proj'].intersection(union).area / c['proj'].area
        except Exception:
            contained = 0.0
        pp, aspect = shape_metrics(c['proj'])
        area = c['area_km2']
        rules = {
            'inside': contained >= CONTAIN_MIN and key in inside_events,
            'area': area <= args.max_area,
            'shape': pp >= PP_MIN and aspect <= ASPECT_MAX,
        }
        failed = [r for r, ok in rules.items() if not ok]
        dir_suspect = key in dir_cache or key in bad_ring
        already = is_semitransient_entry(entry)
        if already:
            tier = 'ALREADY-AREATYPE2' + ('' if not failed else ' (rules would not mark: ' + ','.join(failed) + ')')
        elif dir_suspect:
            tier = 'HOLD:DIRECTION' + (' (otherwise AUTO)' if not failed else '')
        elif not failed:
            tier = 'AUTO'
        elif len(failed) == 1:
            tier = 'NEAR-MISS:' + failed[0]
        else:
            tier = 'MANUAL'
        merged = merge_windows(wins)
        all_from = [dr['from'] for dr in entry['dateRanges'] if owner_name(dr['name']) not in SKIP_NAMES]
        all_to = [dr['to'] for dr in entry['dateRanges'] if owner_name(dr['name']) not in SKIP_NAMES]
        tile_key = f'{lat}/{lon}'
        other_names = []
        for o in sorted(overlaid):
            if o in by_key:
                oe = by_key[o]['entry']
                ow = [(lo, hi) for oo, lo, hi in ups if oo == o]
                other_names.append(f"#{o[2]} {active_last_segment_during(oe['dateRanges'], ow)}")
        rows.append({
            'Tile': tile_key, 'EntryIndex': entry['entryIndex'],
            'Name': active_last_segment_during(entry['dateRanges'], merged),
            'OwnersDuringOverlay': owners_during(entry['dateRanges'], merged),
            'LifeFrom': round(min(all_from), 1) if all_from else '',
            'LifeTo': round(max(all_to), 1) if all_to else '',
            'OverlayFrom': round(merged[0][0], 1), 'OverlayTo': round(merged[-1][1], 1),
            'OverlayWindows': len(merged), 'DateRanges': len(entry['dateRanges']),
            'AreaKm2': round(area, 1), 'Overlays': '; '.join(other_names)[:300],
            'PctContained': round(contained * 100, 1), 'UpperSharePct': round(upper_share * 100, 1),
            'LifetimeCoveragePct': round(cov * 100, 1),
            'Compactness': round(pp, 2), 'Aspect': round(aspect, 2),
            'Tier': tier, 'FailedRules': ','.join(failed),
            'DirectionSuspect': ('flip-fixable' if key in dir_cache else '') + (' self-intersecting' if key in bad_ring else ''),
            'ConfirmedByLog': '; '.join(match_logged_overlays(args.logged, tile_key, merged[0][0], merged[-1][1]))[:120],
            '_key': key, '_rules': rules, '_dir': dir_suspect,
        })
    return rows, dir_rows, ring_rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tiles', nargs='+', default=['120:030', '120:035'])
    ap.add_argument('--all-tiles', action='store_true')
    ap.add_argument('--max-area', type=float, default=DEFAULT_MAX_AREA)
    ap.add_argument('--min-overlap-ratio', type=float, default=DEFAULT_MIN_OVERLAP_RATIO)
    ap.add_argument('--out', default=os.path.join(EXPORTS, 'blob_overlay_proposal.csv'))
    ap.add_argument('--dir-out', default=os.path.join(EXPORTS, 'par_direction_suspects.csv'))
    args = ap.parse_args()

    tile_pairs = discover_all_tiles() if args.all_tiles else [tuple(t.split(':')) for t in args.tiles]
    args.registry = load_transient_registry()
    args.logged = load_logged_overlays()
    tribal_log = {}  # tribal-dots PAR#-only matching was noise (44/147 coincidental hits); not used
    print(f"{len(tile_pairs)} tile(s). Max area {args.max_area:.0f} km2. DRY RUN -- no PAR files are written.")

    all_rows, all_dir, all_events, all_ring = [], [], [], []
    sink = io.StringIO()
    for n, (lat, lon) in enumerate(tile_pairs, 1):
        with contextlib.redirect_stdout(sink):
            _, events = scan_tile(lat, lon, args.min_overlap_ratio, *args.registry)
        all_events.extend(events)
        rows, dir_rows, ring_rows = analyse_tile(lat, lon, events, args, tribal_log)
        all_ring.extend(ring_rows)
        all_rows.extend(rows)
        all_dir.extend(dir_rows)
        if n % 200 == 0:
            print(f"  ...{n}/{len(tile_pairs)} tiles")

    os.makedirs(EXPORTS, exist_ok=True)
    cols = [k for k in all_rows[0] if not k.startswith('_')] if all_rows else []
    tier_order = lambda r: (0 if r['Tier'] == 'AUTO' else 1 if r['Tier'].startswith('NEAR') else 2, r['Tile'], r['EntryIndex'])
    with open(args.out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        for r in sorted(all_rows, key=tier_order):
            w.writerow(r)
    if all_dir:
        with open(args.dir_out, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(all_dir[0].keys()))
            w.writeheader()
            w.writerows(all_dir)

    ring_out = os.path.join(EXPORTS, 'par_self_intersecting_rings.csv')
    if all_ring:
        with open(ring_out, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(all_ring[0].keys()))
            w.writeheader()
            w.writerows(all_ring)

    # ── summary ──
    tiers = Counter(r['Tier'].split(' ')[0] for r in all_rows)
    print(f"\nEntries that are inside, or the shorter-lived side of, an overlap event: {len(all_rows)}")
    for t, n in sorted(tiers.items(), key=lambda kv: -kv[1]):
        print(f"  {t:28s} {n}")
    fail_counts = Counter(fr for r in all_rows if not r['Tier'].startswith('ALREADY')
                          for fr in r['FailedRules'].split(',') if fr)
    print("  Failed-rule counts (not-already-marked overlayers):", dict(fail_counts))

    print("\nSensitivity of AUTO count to --max-area (other rules fixed, direction-suspects excluded):")
    elig = [r for r in all_rows if not r['Tier'].startswith('ALREADY') and not r['_dir']
            and r['_rules']['inside'] and r['_rules']['shape']]
    for a in SENSITIVITY_AREAS:
        print(f"  area <= {a:>6} km2 : {sum(1 for r in elig if r['AreaKm2'] <= a)}")

    handled_now = {r['_key'] for r in all_rows if r['Tier'].startswith('ALREADY')}
    for ev in all_events:
        pass
    auto = {r['_key'] for r in all_rows if r['Tier'] == 'AUTO'}

    def entities_left(excluded):
        s = set()
        for ev in all_events:
            if ev['a'] in excluded or ev['b'] in excluded:
                continue
            s.add(ev['a']); s.add(ev['b'])
        return len(s)
    print(f"\nEntities appearing in any overlap event: {entities_left(set())}")
    print(f"  after removing already-areaType-2 entries' events: {entities_left(handled_now)}")
    print(f"  after ALSO removing the {len(auto)} AUTO entries' events: {entities_left(handled_now | auto)}"
          f"  (estimate: handled entries removed, remainder re-clustered)")

    print(f"\nDirection scan: {len(all_dir)} flip-fixable join(s) in "
          f"{len({(d['Tile'], d['EntryIndex']) for d in all_dir})} candidate entries -> {args.dir_out}")
    n_dir_over = sum(1 for r in all_rows if r['_dir'])
    print(f"  Self-intersecting-as-written rings: {len(all_ring)} candidate entries -> {ring_out}")
    print(f"  {n_dir_over} overlay-event entries are direction/ring suspects (held out of AUTO).")
    print(f"\nWrote {args.out}")


if __name__ == '__main__':
    main()
