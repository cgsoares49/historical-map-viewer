"""
polity_overlay_report.py
Detailed "polity overlay" list for manual untangling of one region/period --
the non-blob counterpart to mark_blob_overlays.py. Same detector underneath
(find_polity_overlays.scan_tile / compute_stack), but:

  * restricted to a tile set and a date window (default: Palestine/Levant,
    -1200..-800),
  * blob-tier entries (mark_blob_overlays AUTO) and already-areaType-2
    entries are REMOVED before clustering, so what is left is genuine
    polity-vs-polity overlap, re-clustered without the blobs,
  * much richer per-entity information for working out the repair by hand
    (terminate/split the base's date range, re-author clean children), and
  * a separate pair table and a date-range timeline table.

READ-ONLY: nothing is written to any PAR file.

Outputs (exports/, <label> = --label):
  polity_overlays_<label>.csv             one row per entity per group
  polity_overlays_<label>_pairs.csv       one row per entry pair per window
  polity_overlays_<label>_dateranges.csv  every date-range of every entity

Usage:
  python polity_overlay_report.py
  python polity_overlay_report.py --tiles 120:030 120:035 --from -1200 --to -800 --label palestine
"""

import os
import sys
import csv
import math
import argparse
import contextlib
import io
from types import SimpleNamespace
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export_polity_polygons import load_tile, owner_name, path_of, build_combined_ring, is_semitransient_entry
from find_polity_overlays import (
    scan_tile, load_candidates, compute_stack, UnionFind, load_transient_registry,
    load_logged_overlays, active_last_segment_during, entry_names, format_window,
    DEFAULT_MIN_OVERLAP_RATIO, SKIP_NAMES, ANIMATION_LOG_PATH,
)
from mark_blob_overlays import analyse_tile, direction_scan_entry, DEFAULT_MAX_AREA
from shapely.geometry import Polygon
from shapely.ops import unary_union

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORTS = os.path.join(MAPPER_DIR, 'exports')
DEFAULT_TILES = ['115:030', '115:035', '120:030', '120:035', '125:030', '125:035']


# ── personal logs, ALL descriptions (not just "(overlay)"-tagged) ───────────

def load_all_log_rows(path=ANIMATION_LOG_PATH):
    """{tile 'lat/lon' zero-padded: [(start, end, description, source)]} from
    animation actions.xlsx 'data' sheet, every row with a numeric start date.
    Context for WHY something was drawn, not a gate. {} if unavailable."""
    out = defaultdict(list)
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb['data']
        rows = ws.iter_rows(values_only=True, max_col=24)
        next(rows)
        for row in rows:
            desc, start, end = row[4], row[2], row[5]
            if not isinstance(desc, str) or not isinstance(start, (int, float)):
                continue
            end = end if isinstance(end, (int, float)) else start
            for cell in row[6:24]:
                if isinstance(cell, str) and '/' in cell:
                    la, lo = cell.split('/', 1)
                    try:
                        out[f'{int(la):03d}/{int(lo):03d}'].append((start, end, desc.strip(), 'log'))
                    except ValueError:
                        pass
        wb.close()
    except Exception as e:
        print(f"(animation actions log unavailable: {e})")
    return out


def log_context(tile_key, lo, hi, all_log, date_registry, name_words=(), limit=6, tol=3.0):
    """Log rows most likely to explain THIS entry's overlay: either the row's
    start date falls inside the overlap window (+-tol years), or its text
    names the entry (any significant word of its name) and it starts in the
    report window. Tile-wide rows that merely span the era are not shown --
    they were noise (the same five earliest rows for every entry)."""
    words = [w.lower() for w in name_words if len(w) >= 4]
    hits = []
    for s, e, d, src in all_log.get(tile_key, []):
        in_win = lo - tol <= s <= hi + tol
        named = bool(words) and any(w in d.lower() for w in words) and lo - 300 <= s <= hi + 300
        if in_win or named:
            hits.append((s, f"{s:g}: {d}" + ('' if in_win else '  (names this entry)')))
    for s, e, d in date_registry.get(tile_key, []):
        if isinstance(d, str) and (s <= hi + tol and e >= lo - tol):
            hits.append((s, f"[transient {s:g}..{e:g}] {d.strip()}"))
    mid = (lo + hi) / 2
    hits.sort(key=lambda h: abs(h[0] - mid))
    seen, out = set(), []
    for _, t in hits:
        if t[:70] not in seen:
            seen.add(t[:70])
            out.append(t[:120])
    more = len(out) - limit
    out = out[:limit]
    if more > 0:
        out.append(f"(+{more} more)")
    return ' || '.join(out)


# ── helpers ────────────────────────────────────────────────────────────────

def merge_windows(wins, gap=0.05):
    wins = sorted(wins)
    out = []
    for lo, hi in wins:
        if out and lo <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return out


def fmt_windows(wins):
    return '; '.join(f'{lo:g}..{hi:g}' for lo, hi in merge_windows(wins))


def relation(pct_a, pct_b):
    if pct_a >= 95 and pct_b >= 95:
        return 'NEAR-IDENTICAL'
    if pct_a >= 95:
        return 'A INSIDE B'
    if pct_b >= 95:
        return 'B INSIDE A'
    return 'PARTIAL'


def polyrefs_text(entry, tile):
    parts = []
    for pi, fl in entry['polyRefs']:
        if fl in (0, 1):
            kind = 'CST' if pi <= 1000 else 'POL'
            num = pi if pi <= 1000 else pi - 1000
            parts.append(f"{kind}{num}{'r' if fl == 1 else ''}")
        else:
            parts.append(f"pt({pi:g},{0 if fl == 1000 else fl:g})")
    return ' '.join(parts)


def pol_ids(entry):
    return {(pi if pi <= 1000 else pi - 1000, 'CST' if pi <= 1000 else 'POL')
            for pi, fl in entry['polyRefs'] if fl in (0, 1)}


# Big real entries the Ancient Index registry wrongly drops as 'known transient' (POL# drift).
# Applied by every tool that calls build() (report, steplist, diff) so they all see the same polities.
DEFAULT_FORCE_INCLUDE = ['120/035:192', '120/035:423', '120/035:205', '120/035:224', '120/035:235', '120/035:427', '120/035:428']   # Israelites (tribal dots -> polity); shares POL233/234 with logged transients


def build(args):
    force_tokens = list(DEFAULT_FORCE_INCLUDE) + list(getattr(args, 'force_include', None) or [])
    if force_tokens:
        import find_polity_overlays as _fpo
        forced = set()
        for tok in force_tokens:
            tk, ent = tok.split(':')
            forced.add((tk.replace(':', '/'), int(ent)))
        _orig_known = _fpo.is_known_transient

        def _known(tile_key, entry, *a, **kw):
            if (tile_key, entry['entryIndex']) in forced:
                return False
            return _orig_known(tile_key, entry, *a, **kw)
        _fpo.is_known_transient = _known
        print(f"  force-include (registry transient test bypassed): {sorted(forced)}")
    tiles = [tuple(t.split(':')) for t in args.tiles]
    registry = load_transient_registry()
    logged = load_logged_overlays()
    all_log = load_all_log_rows()
    date_registry = registry[1]
    ns = SimpleNamespace(registry=registry, logged=logged, max_area=args.max_area)
    sink = io.StringIO()

    entity_rows, pair_rows, range_rows = [], [], []
    excluded_rows = []
    group_counter = 0
    stats = defaultdict(int)

    for lat, lon in tiles:
        tile_key = f'{lat}/{lon}'
        with contextlib.redirect_stdout(sink):
            _, events = scan_tile(lat, lon, DEFAULT_MIN_OVERLAP_RATIO, *registry)
        tile = load_tile(lat, lon)
        cands, _, _, _ = load_candidates(tile, tile_key, *registry)
        by_key = {(lat, lon, c['entry']['entryIndex']): c for c in cands}

        # Tiers from the blob classifier (full-history events, not window-limited).
        with contextlib.redirect_stdout(sink):
            rows, _, _ = analyse_tile(lat, lon, events, ns, {})
        tier = {r['_key']: r['Tier'] for r in rows}
        rowby = {r['_key']: r for r in rows}
        if args.include_blobs:
            handled = {k for k, t in tier.items() if t.startswith('ALREADY')}
        else:
            handled = {k for k, t in tier.items() if t == 'AUTO' or t.startswith('ALREADY')}
        for k in handled:
            r = rowby[k]
            if tier[k] == 'AUTO' and float(r['OverlayTo']) > args.from_year and float(r['OverlayFrom']) < args.to_year:
                excluded_rows.append({'Tile': tile_key, 'EntryIndex': k[2], 'Name': r['Name'], 'AreaKm2': r['AreaKm2'],
                                      'OverlayFrom': r['OverlayFrom'], 'OverlayTo': r['OverlayTo'],
                                      'LifeFrom': r['LifeFrom'], 'LifeTo': r['LifeTo'], 'SitsInside': r['Overlays'],
                                      'PctContained': r['PctContained'], 'Compactness': r['Compactness'],
                                      'CenterLon': r['CenterLon'], 'CenterLat': r['CenterLat'],
                                      'Why': 'blob-tier AUTO (small, compact, inside a bigger entry) -- re-run with --include-blobs to keep'})
        stats['events_total'] += len(events)
        stats['handled_entries'] += len(handled)

        keep = []
        for ev in events:
            if ev['a'] in handled or ev['b'] in handled:
                stats['events_dropped_blob_or_marked'] += 1
                continue
            lo, hi = max(ev['lo'], args.from_year), min(ev['hi'], args.to_year)
            if lo >= hi:
                stats['events_outside_window'] += 1
                continue
            e = dict(ev); e['lo'], e['hi'] = lo, hi
            keep.append(e)
        if not keep:
            continue

        # ── cluster (same event-level logic as find_polity_overlays.main) ──
        uf = UnionFind()
        for i in range(len(keep)):
            uf.find(i)
        for i in range(len(keep)):
            for j in range(i + 1, len(keep)):
                ei, ej = keep[i], keep[j]
                if ei['a'] not in (ej['a'], ej['b']) and ei['b'] not in (ej['a'], ej['b']):
                    continue
                if ei['lo'] < ej['hi'] and ej['lo'] < ei['hi']:
                    uf.union(i, j)
        clusters = defaultdict(list)
        for i in range(len(keep)):
            clusters[uf.find(i)].append(i)
        groups = defaultdict(list)
        for ids in clusters.values():
            ents = set()
            for i in ids:
                ents.add(keep[i]['a']); ents.add(keep[i]['b'])
            groups[frozenset(ents)].extend(ids)

        for ents, ids in sorted(groups.items(), key=lambda kv: (min(k[2] for k in kv[0]))):
            group_counter += 1
            gid = group_counter
            members = sorted(ents, key=lambda k: k[2])
            depth, above, overlaid_by, cyclic = compute_stack(set(ents), ids, keep)
            gwins = [(keep[i]['lo'], keep[i]['hi']) for i in ids]
            g_lo, g_hi = min(w[0] for w in gwins), max(w[1] for w in gwins)

            # per-entity own windows, partners and union overlap
            own_wins = defaultdict(list)
            partners = defaultdict(lambda: defaultdict(list))   # key -> other -> [(lo,hi,pct_self,pct_other,dur_self,dur_other)]
            for i in ids:
                ev = keep[i]
                a, b = ev['a'], ev['b']
                own_wins[a].append((ev['lo'], ev['hi'])); own_wins[b].append((ev['lo'], ev['hi']))
                partners[a][b].append((ev['lo'], ev['hi'], ev['pct_a'], ev['pct_b'], ev['dur_a'], ev['dur_b']))
                partners[b][a].append((ev['lo'], ev['hi'], ev['pct_b'], ev['pct_a'], ev['dur_b'], ev['dur_a']))

            names = {}
            for k in members:
                c = by_key[k]
                names[k] = active_last_segment_during(c['entry']['dateRanges'], own_wins[k])

            # ── pair rows ──
            seen_pairs = set()
            for a in members:
                for b, evs in partners[a].items():
                    if (b, a) in seen_pairs or a == b:
                        continue
                    seen_pairs.add((a, b))
                    ca, cb = by_key[a], by_key[b]
                    wins = [(e[0], e[1]) for e in evs]
                    pct_a = max(e[2] for e in evs); pct_b = max(e[3] for e in evs)
                    shorter_a = sum(1 for e in evs if e[4] < e[5])
                    shorter_b = sum(1 for e in evs if e[5] < e[4])
                    upper = 'A' if shorter_a > shorter_b else 'B' if shorter_b > shorter_a else 'tie'
                    pair_rows.append({
                        'GroupID': gid, 'Tile': tile_key,
                        'A': a[2], 'A_Name': names[a], 'A_AreaKm2': round(ca['area_km2'], 1),
                        'B': b[2], 'B_Name': names[b], 'B_AreaKm2': round(cb['area_km2'], 1),
                        'OverlapWindows': fmt_windows(wins), 'WindowCount': len(merge_windows(wins)),
                        'OverlapKm2_est': round(pct_a / 100 * ca['area_km2'], 1),
                        'PctOfA': round(pct_a, 1), 'PctOfB': round(pct_b, 1),
                        'Relation': relation(pct_a, pct_b),
                        'ShorterLivedSide': upper,
                        'SharedBoundarySegments': ', '.join(f'{t}{n}' for n, t in sorted(pol_ids(ca['entry']) & pol_ids(cb['entry']))),
                    })

            # ── entity rows + timeline rows ──
            for k in members:
                c = by_key[k]; e = c['entry']
                wl = merge_windows(own_wins[k])
                lo_k, hi_k = wl[0][0], wl[-1][1]
                try:
                    union = unary_union([by_key[o]['proj'] for o in partners[k]])
                    pct_cov = c['proj'].intersection(union).area / c['proj'].area * 100
                except Exception:
                    pct_cov = float('nan')
                if cyclic:
                    role, d = 'AMBIGUOUS (cyclic evidence)', ''
                else:
                    d = depth[k]
                    up, dn = bool(above[k]), bool(overlaid_by[k])
                    role = 'BOTH' if up and dn else 'OVERLAYER' if up else 'BASE' if dn else 'ISOLATED'
                def rel(o):
                    evs = partners[k][o]
                    return (f"#{o[2]} {names[o]} [{max(x[2] for x in evs):.0f}% of this entry; "
                            f"{max(x[3] for x in evs):.0f}% of it; {fmt_windows([(x[0], x[1]) for x in evs])}]")
                geo = []
                for o in sorted(partners[k], key=lambda o: o[2]):
                    evs = partners[k][o]
                    ps, po = max(x[2] for x in evs), max(x[3] for x in evs)
                    if ps >= 90 and po >= 90:
                        geo.append(f"SAME-FOOTPRINT as #{o[2]}")
                    elif ps >= 90:
                        geo.append(f"INSIDE #{o[2]} ({by_key[o]['area_km2']:.0f} km2)")
                    elif po >= 90:
                        geo.append(f"CONTAINS #{o[2]} ({by_key[o]['area_km2']:.0f} km2)")
                    else:
                        geo.append(f"PARTIAL with #{o[2]} ({ps:.0f}%/{po:.0f}%)")
                shared = []
                for o in members:
                    if o != k:
                        s = pol_ids(e) & pol_ids(by_key[o]['entry'])
                        if s:
                            shared.append(f"#{o[2]} via " + ','.join(f'{t}{n}' for n, t in sorted(s)))
                dirsus = ''
                try:
                    if direction_scan_entry(e, tile):
                        dirsus = 'flip-fixable'
                    ring, _ = build_combined_ring(e['polyRefs'], tile['cst_by_index'], tile['pol_by_index'])
                    if not Polygon(ring).is_valid:
                        dirsus = (dirsus + ' self-intersecting').strip()
                except Exception:
                    pass
                life = [dr for dr in e['dateRanges'] if owner_name(dr['name']) not in SKIP_NAMES]
                cl, ch = c['bounds'][0], c['bounds'][2]
                entity_rows.append({
                    'GroupID': gid, 'GroupSize': len(members), 'Tile': tile_key, 'EntryIndex': k[2],
                    'GeometryRole': '; '.join(geo), 'RoleByDuration': role, 'StackDepth': d,
                    'Name': names[k],
                    'FullNameInWindow': '; '.join(sorted({dr['name'] for dr in e['dateRanges']
                                                          if any(max(dr['from'], w0) < min(dr['to'], w1) for w0, w1 in wl)}))[:160],
                    'OwnersInWindow': '; '.join(sorted({owner_name(dr['name']) for dr in e['dateRanges']
                                                        if any(max(dr['from'], w0) < min(dr['to'], w1) for w0, w1 in wl)})),
                    'AreaKm2': round(c['area_km2'], 1),
                    'CenterLon': round((c['bounds'][0] + c['bounds'][2]) / 2, 3),
                    'CenterLat': round((c['bounds'][1] + c['bounds'][3]) / 2, 3),
                    'OverlapFrom': round(lo_k, 1), 'OverlapTo': round(hi_k, 1),
                    'OverlapWindows': fmt_windows(wl),
                    'PctOfOwnAreaOverlapped': round(pct_cov, 1),
                    'OverlapsWith': ' | '.join(rel(o) for o in sorted(partners[k], key=lambda o: o[2])),
                    'LifeFrom': round(min(dr['from'] for dr in life), 1) if life else '',
                    'LifeTo': round(max(dr['to'] for dr in life), 1) if life else '',
                    'DateRanges': len(e['dateRanges']),
                    'PolyRefs': polyrefs_text(e, tile)[:200],
                    'SharesBoundaryWith': ' | '.join(shared),
                    'DirectionSuspect': dirsus,
                    'AreaType': e['areaType'],
                    'LogContext': log_context(tile_key, lo_k, hi_k, all_log, date_registry,
                                          name_words=[w for n in entry_names(e) for w in n.replace('/', ' ').split()]),
                })
                for dr in e['dateRanges']:
                    inwin = any(max(dr['from'], w0) < min(dr['to'], w1) for w0, w1 in wl)
                    range_rows.append({
                        'GroupID': gid, 'Tile': tile_key, 'EntryIndex': k[2], 'RoleByDuration': role,
                        'From': dr['from'], 'To': dr['to'], 'Name': dr['name'],
                        'Owner': owner_name(dr['name']), 'ColorIndex': dr['colorIndex'],
                        'InOverlapWindow': 'Y' if inwin else '',
                    })
    return entity_rows, pair_rows, range_rows, stats, excluded_rows


def write_csv(path, rows):
    if not rows:
        return
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tiles', nargs='+', default=DEFAULT_TILES)
    ap.add_argument('--from', dest='from_year', type=float, default=-1200.0)
    ap.add_argument('--to', dest='to_year', type=float, default=-800.0)
    ap.add_argument('--label', default='palestine')
    ap.add_argument('--include-blobs', action='store_true',
                    help='keep blob-tier (AUTO) entries in the report instead of excluding them')
    ap.add_argument('--force-include', nargs='*', default=[], metavar='LAT/LON:ENTRY',
                    help="entries the Ancient Index registry wrongly drops as 'known transient' (e.g. 120/035:192); "
                         "they are kept as real polities for this report only")
    ap.add_argument('--max-area', type=float, default=DEFAULT_MAX_AREA,
                    help='blob-tier area limit passed to mark_blob_overlays (default 5000 km2)')
    args = ap.parse_args()

    ent, pairs, rngs, stats, excluded = build(args)
    base = os.path.join(EXPORTS, f'polity_overlays_{args.label}')
    write_csv(base + '.csv', ent)
    write_csv(base + '_pairs.csv', pairs)
    write_csv(base + '_dateranges.csv', rngs)
    if excluded:
        write_csv(base + '_excluded_blobs.csv', sorted(excluded, key=lambda r: (r['Tile'], float(r['OverlayFrom']))))

    groups = {r['GroupID'] for r in ent}
    from collections import Counter
    print(f"Tiles {args.tiles}, window {args.from_year:g}..{args.to_year:g}")
    print(f"  events seen {stats['events_total']}; dropped {stats['events_dropped_blob_or_marked']} "
          f"(blob-tier AUTO or already areaType 2; {stats['handled_entries']} such entries), "
          f"{stats['events_outside_window']} outside the window")
    print(f"  -> {len(groups)} polity-overlay groups, {len(ent)} entity rows, {len(pairs)} pair rows")
    gs = {r['GroupID']: r['GroupSize'] for r in ent}
    print("  groups by size:", dict(sorted(Counter(gs.values()).items())))
    if excluded:
        print(f"  {len(excluded)} blob-tier entries excluded in this window -> _excluded_blobs.csv:")
        for r in sorted(excluded, key=lambda r: (r['Tile'], float(r['OverlayFrom']))):
            print(f"     {r['Tile']} #{r['EntryIndex']:<4} {r['Name'][:30]:30s} {r['AreaKm2']:>7} km2  {r['OverlayFrom']}..{r['OverlayTo']}")
    print("  roles by duration:", dict(Counter(r['RoleByDuration'] for r in ent)))
    print("  by tile:", dict(Counter(r['Tile'] for r in ent)))
    print(f"Wrote {base}.csv, _pairs.csv, _dateranges.csv" + (", _excluded_blobs.csv" if excluded else ""))


if __name__ == '__main__':
    main()
