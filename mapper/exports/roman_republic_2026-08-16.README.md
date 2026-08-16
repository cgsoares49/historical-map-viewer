# Roman Republic — sample polity polygon export

Generated: 2026-08-16, by `mapper/export_polity_polygons.py` from MAPPER's canonical raw
tile data (`C:\My stuff\mapper\polareas`, `pols`, `coasts`), tiles `125` and `130` only —
the only 2 tiles containing Roman Republic geometry.

## Schema

One row (GeoJSON `Feature` / CSV row) per entity per contiguous date-range where its
shape is constant, modeled on the Cliopatria geospatial history database (Bennett et al.
2025, *Scientific Data* 12:247, https://doi.org/10.1038/s41597-025-04516-9):

| Field | Meaning |
|---|---|
| `Index` | Sequential row number, unique across the whole file |
| `Name` | Entity name — the parent polity, or a bare member/campaign name (e.g. `Anxur`, `Army of Furius Camillus`) |
| `FromYear` / `ToYear` | Year range (negative = BCE), decimal precision preserved |
| `Area` | km², equal-area projection (EPSG:6933), same convention Cliopatria uses |
| `Type` | `"POLITY"` for real territory, `"TRANSIENT"` for army/campaign entries (see below) |
| `References` | Empty in this sample — not yet populated |
| `MemberOf` | Empty for the root polity; `"(Parent name)"` for every nested member, at any depth |
| `ColorR/G/B` | See **Color** below |
| `geometry` | Polygon or MultiPolygon, EPSG:4326 (lon, lat) — full in the `.geojson`, truncated to a ~60-char WKT preview in the `.csv` |

468 rows total: 114 `Type="POLITY"` (81 for Roman Republic itself, plus 33 nested members
— places like `Antium`, `Anxur`, `Garrison`, etc.) and 354 `Type="TRANSIENT"` (individual
army/naval campaigns, e.g. `Army of Furius Camillus`, `Consular army`, `Naval expedition`
— see **Transients** below). The 114 `POLITY` rows are unchanged from the original
2-tile Roman Republic sample; the 354 `TRANSIENT` rows are new.

## Nested members (MemberOf)

Sub-regions recorded in the raw data as `"Roman Republic - X"` (e.g. `"Roman Republic -
Anxur"`) already contributed their territory to the Republic's own merged shape (that's
unchanged — a composite's area intentionally duplicates its members', matching
Cliopatria's own convention), and each distinct `X` also gets its own row set, run
through the identical union/time-slicing logic scoped to just that name, with
`MemberOf="(Roman Republic)"`. Example: `Anxur` gets its own rows for `-509.4..-507.5`
(matches the historical record directly — Anxur was Roman only briefly before reverting
to Volsci control), then two later re-conquests. This nesting is not limited to one
level — a chain like `Parent - X - Y` produces `Y` with `MemberOf="(X)"`, not
`MemberOf="(Parent)"`, at any depth (needed for e.g. the Persian Empire, which nests 4+
levels; this Roman Republic sample only has 2-level chains, but the mechanism is general).

## Transients (Type="TRANSIENT")

Some PAR entries depict a moving army or fleet rather than held territory — MAPPER
represents these identically to real territory (same file format, same ownership-history
structure), so they're detected rather than named: either structurally (the boundary
segment carries a special marker date range, `-9999.0, -9998.0`) or, for a handful of
"convenience" cases that reuse an *existing real* polity boundary to depict a movement
instead of digitizing a dedicated path, by the descriptor after the dash (`"Army"`,
`"Naval"`, more to be added as found). These now get their own `Type="TRANSIENT"` rows
(nested the same way real territory is — e.g. `Army of Furius Camillus` has
`MemberOf="(Roman Republic)"`) instead of being discarded, but their territory still does
**not** fold into the Republic's own `POLITY`-type area — a marching army passing through
isn't held territory the way `Anxur` is.

## Color

The root polity's color is a flat lookup in `primaries.txt` (Roman Republic =
240,240,160) — its single "identifying/legend" color. Every nested entity's color
(whether `POLITY` or `TRANSIENT`, at any depth) is instead `root's base RGB +
newoffsets.txt[colorIndex]` (clamped to 255), exactly matching how the live MAPPER
renderer resolves it — so a nested entity's color is always a distinct-but-related shade
of the root's, e.g. Anxur = (240,241,167). If the same place later becomes independent
(no longer `"Roman Republic - X"` in the raw data at all), it would get its own base
color instead — that's out of scope for this Roman-Republic-scoped run.

## How this was built

MAPPER's raw data doesn't store standalone polygons. Each map tile holds fixed
vertex-chain geometries ("PAR entries"), each carrying an *ownership history* — when
territory changes hands the boundary line never moves, only the owner label swaps
(this is exactly the mechanism behind the "recolor + erase boundary" trick used when
authoring the map — e.g. Picenum becomes Roman Republic at **-268.6** with the identical
boundary points before and after).

For every year, this script finds every geometry fragment whose current owner matches a
given name (at any nesting depth), assembles each fragment's ring from the raw POL/CST
boundary segments it references, and unions them into one shape. It then finds every
year where that set of fragments changes and emits one row per resulting interval,
merging consecutive intervals whose unioned shape is identical.

## Known caveats

- Two data-quality issues found and fixed at the source during this project: a typo
  (`-9990.0` instead of `-9999.0`) in `pols/130/POL012.PRN`, and a sign typo
  (`-281.2, 280.4` instead of `-281.2, -280.4`, making an entry look like it ran to
  280 CE) in `polareas/125/PAR015.ASC` line 1089 — the user found several more instances
  of this second pattern elsewhere in the dataset; worth a broader sweep at some point.
- **Scope is 2 tiles only** (lon ~5-24°E, lat 35-45°N — the Italian peninsula and
  Sicily). Not Rome's full extent at its historical peak (~1-2M km² once Spain, North
  Africa, and Greece are included) — those territories live on other tiles, out of scope
  for this sample.
- **Decimal-year precision preserved** (e.g. `-268.6`) rather than rounded to whole
  years as Cliopatria's own published table does.
- `References` is still empty — not yet built for this test.
