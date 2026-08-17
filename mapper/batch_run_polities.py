"""
batch_run_polities.py
Runs every remaining top-level name from primaries.txt (starting at "Kingdom of
Ur", index 195 -- entries before that are a leftover modern-country color
palette, not ancient polities) through export_polity_polygons.py --auto-tiles
+ merge_into_master.py, in primaries.txt order.

Resumable by construction: skips any name already listed in
exports/processed_polities.txt, and (separately) any name already recorded in
exports/batch_run_log.tsv from a prior interrupted run -- re-running this
script after a crash/timeout just continues where it left off, nothing needs
to be passed in by hand.

Never lets one bad entry stop the batch: subprocess failures, 0-tile misses
(most of the 1015 remaining primaries entries are expected to be pure
secondaries/sub-tribes that only ever appear nested under some other
top-level polity, never as their own root name -- 0 tiles there is normal,
not an error), and 0-feature exports are all logged and skipped, not raised.

Usage:
  python batch_run_polities.py            # run everything remaining
  python batch_run_polities.py --limit 20 # process at most 20 more names, then stop
"""

import os
import re
import sys
import subprocess
import argparse
from datetime import datetime

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
PRIMARIES_PATH = r'C:\My stuff\mapper\primaries.txt'
MANIFEST_PATH = os.path.join(MAPPER_DIR, 'exports', 'processed_polities.txt')
LOG_PATH = os.path.join(MAPPER_DIR, 'exports', 'batch_run_log.tsv')
TMP_GEOJSON = os.path.join(MAPPER_DIR, 'exports', '_batch_tmp.geojson')
START_NAME = 'Kingdom of Ur'


def load_primaries_names():
    lines = open(PRIMARIES_PATH, encoding='latin-1').read().splitlines()
    names = []
    for line in lines[1:]:
        parts = line.split(',')
        if len(parts) >= 2:
            names.append(parts[1].strip())
    start_idx = names.index(START_NAME)
    return names[start_idx:]


def load_done_names():
    done = set()
    if os.path.exists(MANIFEST_PATH):
        for line in open(MANIFEST_PATH, encoding='utf-8'):
            if line.startswith('#') or not line.strip():
                continue
            done.add(line.rsplit(None, 1)[0].strip())
    if os.path.exists(LOG_PATH):
        for line in open(LOG_PATH, encoding='utf-8'):
            parts = line.rstrip('\n').split('\t')
            if len(parts) >= 2 and parts[1] in ('OK', 'SKIP_NO_TILES', 'SKIP_NO_FEATURES'):
                done.add(parts[0])
    return done


def log(name, status, detail=''):
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(f"{name}\t{status}\t{detail}\t{datetime.now().isoformat(timespec='seconds')}\n")


def run(cmd):
    return subprocess.run(cmd, cwd=MAPPER_DIR, capture_output=True, text=True)


def process_one(name):
    r = run([sys.executable, 'export_polity_polygons.py', '--polity', name,
             '--auto-tiles', '--out', TMP_GEOJSON])
    out = r.stdout + r.stderr

    m = re.search(r'Auto-discovered (\d+) tiles', out)
    tile_count = int(m.group(1)) if m else None
    if tile_count == 0:
        log(name, 'SKIP_NO_TILES', '')
        return 'SKIP_NO_TILES', 0

    if r.returncode != 0:
        log(name, 'ERROR', out.strip().replace('\n', ' | ')[-500:])
        return 'ERROR', 0

    m = re.search(r'Wrote (\d+) features to', out)
    feat_count = int(m.group(1)) if m else 0
    if feat_count == 0:
        log(name, 'SKIP_NO_FEATURES', f'tiles={tile_count}')
        return 'SKIP_NO_FEATURES', 0

    warnings = re.findall(r'WARNING:.*', out)
    gaps = re.findall(r'GAP \[.*?\]:.*', out)

    r2 = run([sys.executable, 'merge_into_master.py', '--polity', name, '--geojson', TMP_GEOJSON])
    if r2.returncode != 0:
        log(name, 'ERROR', ('merge failed: ' + (r2.stdout + r2.stderr).strip())[-500:])
        return 'ERROR', 0

    detail_bits = [f'tiles={tile_count}', f'rows={feat_count}']
    if warnings:
        detail_bits.append(f'{len(warnings)} warning(s): ' + ' | '.join(warnings[:3]))
    if gaps:
        detail_bits.append(f'{len(gaps)} continuity gap(s)')
    log(name, 'OK', '; '.join(detail_bits))
    return 'OK', feat_count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=None, help='Stop after processing this many new names')
    args = ap.parse_args()

    names = load_primaries_names()
    done = load_done_names()
    todo = [n for n in names if n not in done]
    print(f"{len(names)} names from {START_NAME!r} onward, {len(done)} already done, {len(todo)} to go.")

    processed = 0
    counts = {'OK': 0, 'SKIP_NO_TILES': 0, 'SKIP_NO_FEATURES': 0, 'ERROR': 0}
    for name in todo:
        if args.limit is not None and processed >= args.limit:
            print(f"Hit --limit {args.limit}, stopping.")
            break
        status, feat_count = process_one(name)
        counts[status] += 1
        processed += 1
        marker = {'OK': 'OK', 'SKIP_NO_TILES': 'skip(no tiles)',
                  'SKIP_NO_FEATURES': 'skip(no features)', 'ERROR': '*** ERROR ***'}[status]
        print(f"[{processed}/{len(todo)}] {name}: {marker}" + (f" ({feat_count} rows)" if status == 'OK' else ''))

    if os.path.exists(TMP_GEOJSON):
        os.remove(TMP_GEOJSON)

    print(f"\nDone this run: {processed} processed -- {counts}")
    remaining = len(todo) - processed
    print(f"{remaining} name(s) still remaining for a future run.")


if __name__ == '__main__':
    main()
