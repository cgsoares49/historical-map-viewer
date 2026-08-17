# cliopatria_master.geojsonl — internal accretion store

This is the canonical, cumulative dataset — every polity/entity ever exported, one row
per line. **Not a deliverable.** Nobody (not the user, not Bennett, not Nono) should open
this file directly; it exists so adding/updating one polity doesn't require touching
everything else. Use `export_master.py` to get an actual `.geojson`/`.csv` out of it —
see below.

**Not committed to git** — see "Local-only / reproducibility" below.

## Format

Newline-delimited GeoJSON: each line is one complete GeoJSON `Feature` object (same
`properties`/`geometry` shape as any other export from this pipeline, including the
`SourceRun` bookkeeping column — the top-level `--polity` name that produced that row).
Chosen over a single big `FeatureCollection` array specifically so updates stay
append/stream-friendly at scale — see `merge_into_master.py`'s docstring for why.

Currently 4480 lines across 5 `SourceRun`s (Roman Republic, Roman Ally, Roman Latin
Colony, Persian Empire, and — new as of Milestone 6, 2026-08-17 — `Cities`) and 4 `Type`
values in active use: `POLITY` (1263), `TRANSIENT` (627), `TRIBAL_AREA` (5, Milestone 5 —
see `roman_ally_2026-08-16.README.md` for what that means and a real bug it
surfaced/fixed), `CITY` (2585, Milestone 6). See `exports/processed_polities.txt` for
the current exact list with
row counts — that file *is* committed (see below).

**`Cities` is not like the other `SourceRun`s** — it isn't a `--polity` name at all, it's
a single global run (`export_polity_polygons.py --cities`) covering every populated
`cities/<lat>/CIT<lon>.TXT` tile in one pass (76 of 1,820 tiles have data; 1,031 cities,
2,585 date-range rows full-fidelity, ~900KB). Each city is one fixed point; its
date-range entries (sometimes a real rename/refounding history, e.g. Beijing has 11 —
Youzhou → ... → Beijing) become rows directly, no breakpoint/union step needed the way
polygons need. `MemberOf` is blank (no point-in-polygon spatial join against the
master's own polygons yet — not worth building until there's polity coverage that
extends into the eras city date-ranges actually reach). Color resolves differently too:
`resolve_city_color()` uses `offsets[colorIndex]` directly with no primaries-base
addition (mirrors `colormatcher.js::resolveCityRgb`), unlike every other row's
`resolve_color()`. Re-run with:
```
python export_polity_polygons.py --cities --out exports/_tmp.geojson
python merge_into_master.py --polity "Cities" --geojson exports/_tmp.geojson
```

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
python export_master.py --name "Lucanians" --out exports/lucanians_everywhere.geojson
```

`--name` is for a specific discoverability problem: a nested member like `Lucanians`
(its own `primaries.txt` entry, not just a category) only shows up under whichever
top-level `SourceRun` happened to touch it — e.g. it's currently only reachable via the
`Roman Ally` run, with `MemberOf="(Roman Ally)"`, even though that's just one period of
its history. `--source-run "Roman Ally"` wouldn't find it if you didn't already know
that; `--name "Lucanians"` finds every row with that exact `Name` across the *entire*
master regardless of which run or parent produced it.

Filters combine (AND across different filter kinds, OR within repeated uses of the same
one, e.g. `--type POLITY --type TRANSIENT`). `Index` is renumbered sequentially within
whatever the filters keep, since the master's own per-row `Index` values come from
independent per-polity runs and aren't globally unique — they're only meaningful in a
delivered subset. Always writes a `.geojson` + a sibling `.csv` (same truncated-WKT
convention as every other export in this project).

## Local-only / reproducibility (added 2026-08-16)

`cliopatria_master.geojsonl` and any `.geojson` export over GitHub's 100MB/file limit
(currently `full_dataset_*.geojson` and `persian_empire_*.geojson`) are `.gitignore`'d —
GitHub's Free plan caps total LFS storage at 500MB and per-file at 100MB regardless of
LFS, and this dataset will only get bigger. This is intentional, not a stopgap: nothing
in the master is hand-authored, so it's entirely reproducible from the canonical PAR/
POL/CST source data + the scripts in this repo (which *are* committed). The only thing
that isn't otherwise recoverable if the local master were ever lost is *which `--polity`
names have already been run* — that's what `exports/processed_polities.txt` is for.
`merge_into_master.py` rewrites it automatically after every merge (scanned fresh from
the master's actual current content, not hand-maintained), and it's small enough to
commit regardless of how large the master itself gets. To rebuild the master from
scratch: for each name listed there, re-run the two commands under "Updating" above.

The user's own backup routine (mapper subdirectory mirrored across 2 SD drives + an
external HD) covers the canonical source data already; the master itself doesn't need
adding to that routine given the above.

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
