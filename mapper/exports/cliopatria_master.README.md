# cliopatria_master.geojsonl — internal accretion store

This is the canonical, cumulative dataset — every polity/entity ever exported, one row
per line. **Not a deliverable.** Nobody (not the user, not Bennett, not Nono) should open
this file directly; it exists so adding/updating one polity doesn't require touching
everything else. Use `export_master.py` to get an actual `.geojson`/`.csv` out of it —
see below.

## Format

Newline-delimited GeoJSON: each line is one complete GeoJSON `Feature` object (same
`properties`/`geometry` shape as any other export from this pipeline, including the
`SourceRun` bookkeeping column — the top-level `--polity` name that produced that row).
Chosen over a single big `FeatureCollection` array specifically so updates stay
append/stream-friendly at scale — see `merge_into_master.py`'s docstring for why.

Currently 655 lines (Roman Republic, Roman Ally, Roman Latin Colony — the 3 samples so
far). Will grow substantially as more polities are added (Milestone 4 onward).

## Updating (adding or re-running a polity)

```
python export_polity_polygons.py --polity "Some Polity" --auto-tiles --out exports/_tmp.geojson
python merge_into_master.py --polity "Some Polity" --geojson exports/_tmp.geojson
```

`merge_into_master.py` **upserts**: it removes every existing line whose `SourceRun`
matches `--polity`, then appends the fresh rows — so re-running a polity after fixing a
source-data typo (as has already happened twice) is safe and idempotent; it never
duplicates or needs any cross-row deduplication. It refuses to merge if the input
file's rows don't all carry the matching `SourceRun` (wrong file, or generated with a
different `--polity`), as a sanity check. The `--out exports/_tmp.geojson` intermediate
file can be deleted after merging — it's scratch, not a keeper.

## Getting a deliverable out

```
python export_master.py --out exports/full_dataset.geojson              # everything
python export_master.py --source-run "Roman Republic" --out exports/rr.geojson
python export_master.py --type TRANSIENT --out exports/campaigns.geojson
python export_master.py --from-year -300 --to-year -250 --out exports/mid_republic.geojson
```

Filters combine (AND across different filter kinds, OR within repeated uses of the same
one, e.g. `--type POLITY --type TRANSIENT`). `Index` is renumbered sequentially within
whatever the filters keep, since the master's own per-row `Index` values come from
independent per-polity runs and aren't globally unique — they're only meaningful in a
delivered subset. Always writes a `.geojson` + a sibling `.csv` (same truncated-WKT
convention as every other export in this project).

## Verified 2026-08-16

- `export_master.py` with no filters reproduces `all_polities_2026-08-16.geojson`
  (the earlier manual merge) exactly, content-wise (ignoring `Index`/`Generated`/
  `SourceRun`, which the manual merge didn't have).
- Re-running an unchanged polity (`Roman Latin Colony`) through the upsert leaves the
  master's total line count unchanged (55 removed, 55 added) — confirms replace-not-
  duplicate.
- `--type`, `--source-run`, and `--from-year`/`--to-year` filters each produce correctly
  sized subsets.
- Not yet stress-tested at a much larger scale (the streaming design should hold up by
  construction — the removal pass never holds more than one line in memory at a time —
  but this hasn't been empirically confirmed against a large synthetic file yet).
