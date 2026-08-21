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

Currently 23,145 lines across 988 `SourceRun`s (essentially the whole primaries.txt
dataset, from the 2026-08-17 full batch run, plus `Cities`) and 4 `Type` values in active
use: `POLITY`, `TRANSIENT`, `TRIBAL_AREA` (Milestone 5 — see
`roman_ally_2026-08-16.README.md` for what that means and a real bug it surfaced/fixed),
`CITY` (Milestone 6). See `exports/processed_polities.txt` for the current exact list
with row counts — that file *is* committed (see below).

## Schema additions, 2026-08-21: `FullPath`, `Region`, `Subregion`

**`FullPath`** is the complete dash-chain from the top-level `--polity` down to this row
(e.g. `"Persian Empire - Egypt - Egypt - Egypt - Lower Egypt Nome 6 Khaset/Kaset"`).
Added because `MemberOf` alone (just the immediate parent's bare name) is ambiguous
wherever the same name repeats at adjacent nesting depths — a real, non-typo pattern in
the source data (the Persian Empire's Egyptian administrative chain reuses "Egypt" three
times in a row before reaching an actual nome name). Two rows can legitimately have
identical `Name`+`MemberOf` and only be distinguishable via `FullPath`. `python
build_area_checksum_csv.py` (see below) depends on `FullPath` to build parent/child edges
unambiguously.

**`Region`/`Subregion`** classify each row into Seshat's own filtering taxonomy
(seshat-db.com/core/polities-light/ — 10 regions, ~40 subregions), via `geo_region.py`:
each row's geometry centroid is reverse-geocoded against modern country boundaries
(Natural Earth 110m, `mapper/data/ne_110m_countries.geojson`), then mapped to
`(Region, Subregion)` via a hand-built `COUNTRY_TO_SESHAT_REGION` table. This is a coarse,
*modern*-political approximation of a historical/cultural geographic scheme — the same
simplification Seshat's own regions are built on. A handful of very large countries
(Russia, China, India, USA, Canada, Brazil, Kazakhstan) genuinely span multiple Seshat
subregions and are pinned to one default subregion each; see `geo_region.py`'s docstring.

Both columns are additive to every row — when a *new* schema column needs backfilling
onto the whole master (as opposed to picking up real canonical-data edits, which is what
`incremental_update_master.py` is for), use `regenerate_full_master.py`: it unconditionally
re-runs every name already in `processed_polities.txt` and re-merges, chunked and
resumable the same way `batch_run_polities.py` is.

## `ColorR`/`ColorG`/`ColorB` can read `"various component colors"`

A composite/parent entity's territory is a prefix-inclusive union of its own direct area
plus every nested descendant's area (needed for geometry — a composite's polygon must
include its children's, per Cliopatria's composite-duplicates-members convention). Colors
don't work the same way: whenever a nested descendant (e.g. a Nome inside "Egypt") is
active during a row's date range — whether alongside the entity's own territory or, in the
narrowest case, as the *only* thing active — that row genuinely has no single true color of
its own, so `ColorR` is the literal string `"various component colors"` and `ColorG`/
`ColorB` are blank, instead of an arbitrary/misleading single RGB. When nothing but the
entity's own (non-descendant) territory is active, the real resolved RGB is used as normal.
Found 2026-08-21: a Persian Empire → Egypt → Egypt → Egypt row had ONLY its Nome 1 child
active in one narrow 2-year window and silently inherited Nome 1's own color with no
conflict even detectable under a naive "do all active contributors agree" check — the fix
(`slice_into_rows`/`slice_into_dot_rows`'s `own_path` parameter) separates "this entity's
own exact-path entries" from "descendant entries swept in by the prefix match" specifically
for color resolution, geometry/Area are unaffected. ~764 of 23,145 master rows (~3.3%) are
affected as of the 2026-08-21 regeneration.

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
