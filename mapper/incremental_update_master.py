"""
incremental_update_master.py
Detects which top-level primaries.txt polities have new/changed canonical
data since the last run, then re-exports + re-merges just those into
cliopatria_master.geojsonl -- so a content-creation session doesn't need a
full primaries.txt batch re-run (see batch_run_polities.py), just the
handful of names actually touched.

C:\\My stuff\\mapper isn't a git repo (confirmed 2026-08-17 -- it's the
user's raw canonical working directory, no .git), so there's no `git diff`
to lean on. Change detection is instead:
  1. mtime-based across polareas/ (PAR), pols/ (POL), coasts/ (CST),
     cities/ (CIT) -- any file modified since the last recorded scan time.
  2. For a changed PAR file: parsed structurally (not a text scan) so every
     date-range's owner_name() (the true top-level root, regardless of
     nesting depth) is captured directly -- catches a change anywhere in a
     nested chain, e.g. editing "Roman Ally - Kingdom of Syracuse -
     Tauromenion" correctly flags "Roman Ally" for re-run, not a name that
     was never a real top-level polity.
  3. For a changed POL/CST file (no names of their own): the sibling PAR
     file in the same tile is parsed and EVERY entry's root name is added --
     over-inclusive (some of those entries might not actually reference the
     changed segment) but safe, since re-running an untouched polity is a
     harmless no-op (merge_into_master.py's upsert just rewrites identical
     content).
  4. For a changed CIT file: flags the single global "Cities" run instead
     of trying to identify individual city names (Cities is already the
     cheapest, fastest run in the pipeline -- no need to be clever here).
  5. primaries.txt itself is diffed line-by-line against a saved snapshot,
     to catch pure color/rename edits that never touch a PAR/POL/CST/CIT
     file at all (resolve_color()/primaries_map lookups are keyed by name,
     so those still need a re-run to pick up the new RGB).

State (last scan timestamp + previous primaries.txt content) lives in
exports/incremental_state.json, only updated after a fully successful run.

Usage:
  python incremental_update_master.py            # detect + export + merge
  python incremental_update_master.py --dry-run  # detect only, print the list
"""

import os
import sys
import json
import time
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export_polity_polygons as epp

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = epp.DATA_DIR
STATE_PATH = os.path.join(MAPPER_DIR, 'exports', 'incremental_state.json')
PRIMARIES_PATH = os.path.join(DATA_DIR, 'primaries.txt')
MASTER_PATH = os.path.join(MAPPER_DIR, 'exports', 'cliopatria_master.geojsonl')
MANIFEST_PATH = os.path.join(MAPPER_DIR, 'exports', 'processed_polities.txt')

# "UNKNOWN" is a leftover placeholder name from the -9990.0 sentinel-typo data
# (3 PAR entries near Priene, see project memory 2026-08-17) -- exporting it
# hangs indefinitely (confirmed 2026-08-18, 60s timeout with zero output),
# unlike every other touched name which finishes in seconds. Not a real
# polity worth a standalone export; skip it so one bad name can't block an
# otherwise-fast incremental run.
SKIP_NAMES = {'UNKNOWN'}

SCAN_DIRS = {
    'PAR': (os.path.join(DATA_DIR, 'polareas'), r'^PAR(\d{3})\.ASC$'),
    'POL': (os.path.join(DATA_DIR, 'pols'), r'^POL(\d{3})\.PRN$'),
    'CST': (os.path.join(DATA_DIR, 'coasts'), r'^CST(\d{3})\.PRN$'),
    'CIT': (os.path.join(DATA_DIR, 'cities'), r'^CIT(\d{3})\.TXT$'),
}


def load_state():
    if os.path.exists(STATE_PATH):
        return json.load(open(STATE_PATH, encoding='utf-8'))
    return None


def save_state(scan_time, primaries_text):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    json.dump({'last_scan_time': scan_time, 'primaries_snapshot': primaries_text},
               open(STATE_PATH, 'w', encoding='utf-8'))


def find_changed_files(since):
    import re
    changed = {'PAR': [], 'POL': [], 'CST': [], 'CIT': []}
    for kind, (root, pattern) in SCAN_DIRS.items():
        rx = __import__('re').compile(pattern, re.IGNORECASE)
        if not os.path.isdir(root):
            continue
        for lat_dir in sorted(os.listdir(root)):
            lat_path = os.path.join(root, lat_dir)
            if not os.path.isdir(lat_path):
                continue
            for fname in sorted(os.listdir(lat_path)):
                if not rx.match(fname):
                    continue
                fpath = os.path.join(lat_path, fname)
                if os.path.getmtime(fpath) > since:
                    changed[kind].append((lat_dir, fname))
    return changed


def names_touched_by_par(fpath):
    lines = [l.rstrip('\r\n') for l in open(fpath, encoding='latin-1').readlines()]
    names = set()
    for entry in epp.parse_par_full(lines):
        for dr in entry['dateRanges']:
            names.add(epp.owner_name(dr['name']))
    return names


def detect_touched_names(since):
    changed = find_changed_files(since)
    touched = set()
    cities_touched = bool(changed['CIT'])

    for lat_dir, fname in changed['PAR']:
        fpath = os.path.join(DATA_DIR, 'polareas', lat_dir, fname)
        touched |= names_touched_by_par(fpath)

    for kind in ('POL', 'CST'):
        for lat_dir, fname in changed[kind]:
            lon_code = fname[3:6]
            par_path = os.path.join(DATA_DIR, 'polareas', lat_dir, f'PAR{lon_code}.ASC')
            if os.path.exists(par_path):
                touched |= names_touched_by_par(par_path)

    return touched, cities_touched, changed


def diff_primaries(old_text):
    current_text = open(PRIMARIES_PATH, encoding='latin-1').read()
    if old_text is None:
        return set(), current_text
    old_lines = old_text.splitlines()
    new_lines = current_text.splitlines()
    old_by_idx = {l.split(',')[0].strip(): l for l in old_lines[1:] if l.strip()}
    changed_names = set()
    for line in new_lines[1:]:
        parts = line.split(',')
        if len(parts) < 2:
            continue
        idx, name = parts[0].strip(), parts[1].strip()
        if old_by_idx.get(idx) != line:
            changed_names.add(name)
    return changed_names, current_text


def run(cmd):
    return subprocess.run(cmd, cwd=MAPPER_DIR, capture_output=True, text=True)


def export_name(name, out_path):
    """Export one polity's features to out_path. Returns (status_str, features_or_None).
    Does NOT touch the master -- merging is batched separately so a run touching
    many names only rewrites the (potentially huge) master file once, not once per name."""
    r = run([sys.executable, 'export_polity_polygons.py', '--polity', name,
             '--auto-tiles', '--out', out_path])
    out = r.stdout + r.stderr
    if 'Auto-discovered 0 tiles' in out:
        return 'no tiles found (may be a nested-only secondary, or removed)', None
    if r.returncode != 0 or 'Wrote 0 features' in out:
        if 'Wrote 0 features' in out:
            return 'no output rows (root-only secondary, will be captured under its real parent)', None
        return f'ERROR: {out.strip()[-300:]}', None
    with open(out_path, encoding='utf-8') as f:
        feats = json.load(f)['features']
    return 'OK', feats


def batch_merge(master_path, manifest_path, source_runs, features_by_run):
    """Single-pass upsert of multiple SourceRuns at once: one streamed read of
    the (potentially huge) master, one temp file, one os.replace -- instead of
    merge_into_master.py's one-rewrite-per-polity, which is O(len(source_runs))
    full-master rewrites and dominates runtime once more than a couple of
    names are touched in one run."""
    master_dir = os.path.dirname(master_path) or '.'
    os.makedirs(master_dir, exist_ok=True)
    removed = 0
    tmp_fd, tmp_path = __import__('tempfile').mkstemp(dir=master_dir, suffix='.geojsonl.tmp')
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as tmp_f:
            if os.path.exists(master_path):
                with open(master_path, encoding='utf-8') as f:
                    for line in f:
                        stripped = line.strip()
                        if not stripped:
                            continue
                        obj = json.loads(stripped)
                        if obj.get('properties', {}).get('SourceRun') in source_runs:
                            removed += 1
                            continue
                        tmp_f.write(stripped + '\n')
            added = 0
            for run_name in sorted(features_by_run):
                for feat in features_by_run[run_name]:
                    tmp_f.write(json.dumps(feat, ensure_ascii=False) + '\n')
                    added += 1
        os.replace(tmp_path, master_path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    print(f"Master: removed {removed} old line(s), added {added} new line(s) "
          f"across {len(features_by_run)} SourceRun(s).")

    import merge_into_master as mim
    total = mim.write_manifest(master_path, manifest_path)
    print(f"Master now has {total} total line(s) at {master_path}")
    print(f"Manifest rewritten at {manifest_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='Detect and print only, do not export/merge/save state')
    args = ap.parse_args()

    state = load_state()
    now = time.time()
    since = state['last_scan_time'] if state else 0
    old_primaries = state['primaries_snapshot'] if state else None

    if state is None:
        print("No prior state found -- this is the baseline run. Nothing will be re-processed "
              "now (everything is already current from today's full batch); saving today as the "
              "starting point for future incremental runs.")
        save_state(now, open(PRIMARIES_PATH, encoding='latin-1').read())
        return

    touched, cities_touched, changed = detect_touched_names(since)
    primaries_changed, current_primaries_text = diff_primaries(old_primaries)
    touched |= primaries_changed
    skipped = touched & SKIP_NAMES
    touched -= SKIP_NAMES

    print(f"Since {time.ctime(since)}:")
    print(f"  Changed files: PAR={len(changed['PAR'])} POL={len(changed['POL'])} "
          f"CST={len(changed['CST'])} CIT={len(changed['CIT'])}")
    print(f"  primaries.txt entries changed: {len(primaries_changed)}")
    print(f"  -> {len(touched)} top-level polit{'y' if len(touched)==1 else 'ies'} to re-run"
          + (', plus Cities' if cities_touched else ''))
    for n in sorted(touched):
        print(f"    - {n}")
    if cities_touched:
        print("    - (Cities -- global re-run)")
    if skipped:
        print(f"  Skipped (known-bad, see SKIP_NAMES): {sorted(skipped)}")

    if args.dry_run:
        print("\n--dry-run: nothing was exported/merged, state not updated.")
        return

    if not touched and not cities_touched:
        print("\nNothing to do.")
        save_state(now, current_primaries_text)
        return

    print()
    features_by_run = {}
    tmp_files = []
    for i, name in enumerate(sorted(touched)):
        tmp_path = os.path.join(MAPPER_DIR, 'exports', f'_incremental_tmp_{i}.geojson')
        tmp_files.append(tmp_path)
        status, feats = export_name(name, tmp_path)
        print(f"{name}: {status}")
        if feats is not None:
            features_by_run[name] = feats

    if cities_touched:
        cities_tmp = os.path.join(MAPPER_DIR, 'exports', '_incremental_tmp_cities.geojson')
        tmp_files.append(cities_tmp)
        r = run([sys.executable, 'export_polity_polygons.py', '--cities', '--out', cities_tmp])
        if r.returncode == 0:
            with open(cities_tmp, encoding='utf-8') as f:
                features_by_run['Cities'] = json.load(f)['features']
            print("Cities: OK")
        else:
            print(f"Cities: ERROR exporting: {(r.stdout + r.stderr).strip()[-300:]}")

    if features_by_run:
        batch_merge(MASTER_PATH, MANIFEST_PATH, set(features_by_run), features_by_run)

    for p in tmp_files:
        for sidecar in (p, os.path.splitext(p)[0] + '.csv', os.path.splitext(p)[0] + '_hulls.geojson'):
            if os.path.exists(sidecar):
                os.remove(sidecar)

    save_state(now, current_primaries_text)
    print("\nDone. State saved -- next run only picks up changes after this point.")


if __name__ == '__main__':
    main()
