"""
regenerate_full_master.py
One-time (well, one-per-schema-change) full regeneration of every SourceRun
already in cliopatria_master.geojsonl, used when a new schema column has to
be backfilled onto every existing row (e.g. 2026-08-21's FullPath/Region/
Subregion additions) -- as opposed to incremental_update_master.py, which
only re-runs names whose *canonical source data* actually changed.

Reuses export_name()/batch_merge() from incremental_update_master.py (same
single-streamed-rewrite design that turned the original full-batch run from
3+ hours into minutes -- see project history) rather than re-implementing
that plumbing. Merges happen in chunks (CHUNK_SIZE names per batch_merge
call), not one merge at the very end -- regenerating all ~988 SourceRuns
means holding every one's exported features in memory simultaneously if
merged only once, which risks a large memory footprint; chunking bounds
that while still cutting the rewrite count from O(names) to O(names/chunk).

Resumable like batch_run_polities.py: every completed name is logged to
exports/regen_run_log.tsv, and a re-run skips anything already logged there
-- needed because background processes in this environment get killed after
roughly 20-40 minutes, so a run covering all ~988 SourceRuns may need several
invocations to finish.

Usage:
  python regenerate_full_master.py             # regenerate everything remaining
  python regenerate_full_master.py --limit 20   # do at most 20 more names, then stop
"""

import os
import sys
import time
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import incremental_update_master as ium

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(MAPPER_DIR, 'exports', 'processed_polities.txt')
LOG_PATH = os.path.join(MAPPER_DIR, 'exports', 'regen_run_log.tsv')
MASTER_PATH = ium.MASTER_PATH
CHUNK_SIZE = 60


def load_all_names():
    names = []
    for line in open(MANIFEST_PATH, encoding='utf-8'):
        if line.startswith('#') or not line.strip():
            continue
        names.append(line.rsplit(None, 1)[0].strip())
    return names


# Terminal states for resumability purposes -- a name in any of these will
# never be retried on a future run. 'OK' means merged into the master;
# 'SKIP_NO_TILES'/'SKIP_NO_FEATURES' mean the name is a pure nested secondary
# with nothing of its own to export (expected for a large fraction of
# primaries.txt, see batch_run_polities.py's original full-batch notes) --
# both are cheap to detect but retrying them on every resume forever would
# still waste a subprocess launch per name for no benefit.
DONE_STATUSES = {'OK', 'SKIP_NO_TILES', 'SKIP_NO_FEATURES'}


def load_done_names():
    done = set()
    if os.path.exists(LOG_PATH):
        for line in open(LOG_PATH, encoding='utf-8'):
            parts = line.rstrip('\n').split('\t')
            if len(parts) >= 2 and parts[1] in DONE_STATUSES:
                done.add(parts[0])
    return done


def log(name, status, detail=''):
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(f"{name}\t{status}\t{detail}\t{datetime.now().isoformat(timespec='seconds')}\n")


def export_one(name, out_path):
    """Like incremental_update_master.export_name(), but special-cases
    'Cities' (exported via --cities, not --polity NAME --auto-tiles --
    'Cities' isn't a PAR owner name), and classifies the result into the
    same OK/SKIP_NO_TILES/SKIP_NO_FEATURES/ERROR statuses batch_run_polities.py
    uses, so benign nested-only secondaries are marked done (not retried
    forever) without being confused with a real failure."""
    if name == 'Cities':
        r = ium.run([sys.executable, 'export_polity_polygons.py', '--cities', '--out', out_path])
        if r.returncode != 0:
            return 'ERROR', f'{(r.stdout + r.stderr).strip()[-300:]}', None
        import json
        with open(out_path, encoding='utf-8') as f:
            feats = json.load(f)['features']
        return 'OK', '', feats

    status_text, feats = ium.export_name(name, out_path)
    if feats is not None:
        return 'OK', '', feats
    if status_text.startswith('no tiles found'):
        return 'SKIP_NO_TILES', status_text, None
    if status_text.startswith('no output rows'):
        return 'SKIP_NO_FEATURES', status_text, None
    return 'ERROR', status_text, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=None, help='Stop after processing this many more names')
    args = ap.parse_args()

    names = load_all_names()
    done = load_done_names()
    todo = [n for n in names if n not in done]
    print(f"{len(names)} SourceRuns total, {len(done)} already regenerated, {len(todo)} to go.")

    if args.limit is not None:
        todo = todo[:args.limit]
        print(f"--limit {args.limit}: processing {len(todo)} this run.")

    t0 = time.time()
    processed = 0
    features_by_run = {}
    tmp_files = []
    pending_ok = []  # names to log as 'OK' -- deferred until AFTER the merge

    def flush_chunk():
        nonlocal features_by_run, tmp_files, pending_ok
        if features_by_run:
            ium.batch_merge(MASTER_PATH, MANIFEST_PATH, set(features_by_run), features_by_run)
            # Only now, after the merge has actually landed in the master, is
            # it safe to mark these names done -- logging 'OK' any earlier
            # would let a kill-before-merge permanently skip an un-merged
            # name on the next resume (the whole point of the resumability
            # log is that 'logged' must mean 'actually in the master').
            for n, count in pending_ok:
                log(n, 'OK', f'{count} features')
        for p in tmp_files:
            for sidecar in (p, os.path.splitext(p)[0] + '.csv', os.path.splitext(p)[0] + '_hulls.geojson'):
                if os.path.exists(sidecar):
                    os.remove(sidecar)
        features_by_run = {}
        tmp_files = []
        pending_ok = []

    for i, name in enumerate(todo, start=1):
        tmp_path = os.path.join(MAPPER_DIR, 'exports', f'_regen_tmp_{i}.geojson')
        tmp_files.append(tmp_path)
        state, detail, feats = export_one(name, tmp_path)
        elapsed = time.time() - t0
        processed += 1
        if state == 'OK':
            features_by_run[name] = feats
            pending_ok.append((name, len(feats)))
            print(f"[{i}/{len(todo)}] {name}: OK ({len(feats)} rows, {elapsed:.1f}s elapsed)")
        elif state in ('SKIP_NO_TILES', 'SKIP_NO_FEATURES'):
            # Nothing to merge, so it's safe to log immediately (unlike 'OK',
            # there's no pending master write this could get ahead of).
            log(name, state, detail)
            print(f"[{i}/{len(todo)}] {name}: {state.lower()}")
        else:
            log(name, 'ERROR', detail)
            print(f"[{i}/{len(todo)}] {name}: *** ERROR: {detail} ***")

        if processed % CHUNK_SIZE == 0:
            print(f"  -- merging chunk of {len(features_by_run)} SourceRun(s) into master --")
            flush_chunk()

    flush_chunk()

    remaining = len(load_all_names()) - len(load_done_names())
    print(f"\nDone this run: {len(todo)} processed in {time.time()-t0:.1f}s. {remaining} name(s) still remaining.")


if __name__ == '__main__':
    main()
