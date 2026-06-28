# Plan: Rationalize geodata.js and Add Proper Centroids

## Context

geodata.js has two sections that have grown inconsistently:

1. **Hand-curated section** (lines 1–226, 83 entries): manually maintained navigation
   shortcuts — continents, historical regions, modern countries, cities. Most have no
   date ranges. These were excluded from the refs_export.csv, confusing the user.

2. **PAR-derived section** (lines 228–1320, 1,092 entries): auto-generated from PAR
   tile data on every deploy. Has dates and bounding boxes but uses bounding box
   midpoints as "centers", which are often geographically wrong.

Goals: eliminate entries that don't belong, ensure everything has proper dates, compute
real geographic centers, and produce a single complete CSV of all entries.

---

## Step 1 — Remove city entries from hand-curated section

22 entries in the "Cities & Landmarks" section (lines 203–226) will be deleted:
`rome`, `athens (city)`, `jerusalem`, `ur`, `babylon (city)`, `persepolis`,
`carthage (city)`, `alexandria`, `istanbul`/`constantinople`/`byzantium`,
`london`, `paris`, `berlin`, `moscow`, `cairo`, `baghdad`, `tehran`, `delhi`,
`beijing`, `new york`, `nineveh` (city duplicate).

These will be replaced later from the mapper cities data files with proper dates and
coordinates. No other action for this step.

**Note:** `nineveh` and `carthage (city)` appear in BOTH the historical-regions section
and the cities section — when the city entries are removed, the regional entries remain.

---

## Step 2 — Clean up historical region shortcuts

The 49 historical region entries fall into three groups:

### A. Remove — outside current content range (261 BCE–2400 BCE)
These are post-classical entities with no PAR coverage in the current date window:
- `mali empire`, `byzantine empire`, `ottoman empire`, `mongol empire`, `silk road`
  (silk road's main period is 2nd century BCE onward — borderline, but remove for now)

### B. Remove — PAR data already covers them, hand-curated entry blocks it
`merge_geodata.py` silently skips PAR rows whose names match a hand-curated key.
Removing these from hand-curated lets PAR data provide them with proper dates and
proper centroids automatically:
- `achaemenid empire`, `maurya empire`, `roman empire`, `ancient greece`,
  `ancient rome`, `ancient egypt`, `ancient india`, `ancient china`,
  `mali empire` (already in group A), `byzantine empire` (already in A)

  **Decision needed:** Also remove `scythia`, `pontic steppe`, `steppe`,
  `indus valley`, `north africa`, `sub-saharan africa`, `horn of africa`,
  `central asia`, `caucasus` if they have PAR counterparts? I'll check during
  implementation and only remove where confirmed PAR coverage exists.

### C. Keep — genuine geographic concepts with no PAR counterpart; need manual dates
These are spatial concepts that don't correspond to a named political entity in PAR
data. They should stay but need date ranges manually assigned:

| Entry | Proposed date range | Rationale |
|---|---|---|
| `mesopotamia` | -3500 to -539 | Sumer through fall of Babylon |
| `fertile crescent` | -3500 to -539 | Same window |
| `sumer` | -3000 to -2004 | Classic Sumerian period |
| `levant` | -3000 to -200 | Broad Levantine history in range |
| `canaan` | -2000 to -900 | Canaanite period |
| `phoenicia` | -1200 to -300 | Phoenician city-states |
| `judea` | -1000 to -261 | Kingdom through Hasmonean |
| `israel (ancient)` | -1200 to -722 | Through Assyrian conquest |
| `persia (ancient)` | -2000 to -261 | Pre-Achaemenid through scope limit |
| `anatolia` / `asia minor` | -2400 to -261 | Full scope |
| `gaul` | -600 to -261 | Gaul in scope |
| `britannia` | -600 to -261 | Iron Age Britain |
| `iberia (ancient)` | -800 to -261 | Iberian cultures |
| `germania` | -800 to -261 | Germanic tribes |
| `nile valley` | -3500 to -261 | Full Egyptian/Nubian scope |
| `nubia` | -3500 to -261 | Nubian kingdoms |
| `arabia (ancient)` / `arabian peninsula` | -2000 to -261 | In scope |
| `near east` / `middle east` | -3500 to -261 | Geographic concept |
| `pontic steppe` / `steppe` | -1500 to -261 | Steppe cultures |
| `babylonia (region)` | -2000 to -539 | Babylonian period |

**Decision needed:** Do you agree with these date ranges, or should I propose
different values? Should I add any not in this list, or cut any from it?

### D. Remove — too broad, no meaningful date range possible
`world`, `earth`, `africa`, `europe`, `asia`, `eurasia`, `north america`,
`south america`, `americas`, `australia`, `oceania`, `antarctica`
(all 12 continent/world entries). These are spatial shortcuts with no historical
specificity. Remove them.

---

## Step 3 — Verify and fix modern countries completeness

**Problem:** The user reports Uruguay is missing. The hand-curated modern countries
section has 118 entries (~102 distinct countries); the PAR section adds 91 more.
Countries missing from BOTH would not appear.

**Action:** During implementation, check `primaries.txt` for Uruguay and any other
missing countries. If they are in primaries but their bounding box came up empty
(e.g. very small tile coverage), that would explain absence.

If Uruguay IS in primaries.txt and PAR files, investigate why build_geodata.py didn't
produce an entry (could be a date-span filtering issue). Fix accordingly.

No structural change to how modern countries are handled — they stay in the hand-curated
section for now (aliases like `uk`/`britain` are needed there).

---

## Step 4 — Add tile-area-weighted centroids to build_geodata.py

**Current approach:** `vibeNavigateTo` in mapper.html computes `(minLon+maxLon)/2`
and `(minLat+maxLat)/2` — bounding box midpoint. Wrong for asymmetric entities.

**New approach (feasible without POL parsing):** For each tile that contains the entity,
weight the tile centre by its approximate surface area:

```
weight = tile_width_degrees × cos(lat_centre_radians)
```

This is computable from the tile bounds already available in `tile_bounds()` in
build_geodata.py. Accumulate per-entity:

```python
sum_w   += weight
sum_wlon += tile_centre_lon * weight
sum_wlat += tile_centre_lat * weight
# ...
centre_lon = sum_wlon / sum_w
centre_lat = sum_wlat / sum_w
```

**Changes to build_geodata.py:**
- Add three accumulators (`sum_w`, `sum_wlon`, `sum_wlat`) to each entry in `results`
- Compute and accumulate per tile (only when `span > 0` and name matches, same filter as bounding box)
- Add `CentLon`, `CentLat` columns to `geodata_from_par.csv` (rounded to 2 decimal places)

---

## Step 5 — Pass centroids through merge_geodata.py into geodata.js

**Extend the geodata.js array format** to 8 elements (optional elements 6 and 7):
```
[minLon, minLat, maxLon, maxLat, fromYear, toYear, centLon, centLat]
```

**Changes to merge_geodata.py:**
- Read `CentLon`/`CentLat` from CSV
- When writing JS for a PAR entry that has centre data, output 8-element array
- Hand-curated entries stay at 4 or 6 elements; the navigation code falls back to
  midpoint for those (or we can pre-bake midpoints for the kept geographic concepts)

---

## Step 6 — Update mapper.html navigation to use centroid

In `vibeNavigateTo` (around line 2506), change:
```js
centerLon = (minLon + maxLon) / 2;
centerLat = (minLat + maxLat) / 2;
```
to:
```js
centerLon = entry.length >= 8 ? entry[6] : (minLon + maxLon) / 2;
centerLat = entry.length >= 8 ? entry[7] : (minLat + maxLat) / 2;
```

---

## Step 7 — Generate complete CSV of ALL geodata entries

New script (replacing / extending `gen_refs_csv.py`) that reads ALL entries from
`geodata.js` (not just refs.json), joins with refs.json for reference URLs.

**Output columns:**
```
Search Term | Date From | Date To | Center Lat | Center Lon | WHE 1 | WHE 2 | Wiki 1 | Wiki 2
```

**Date format:** Plain integers, negative for BC (e.g. `-509`), positive for AD,
blank if no date, `1990` for modern sentinel. No BCE/CE labels anywhere.

Script saved as `mapper/export_geodata_csv.py` (replaces `gen_refs_csv.py`).

---

## Decisions Needed Before Implementation

1. **Historical region date ranges** (Step 2C): Do the proposed date ranges in the
   table above look right? Any to add, remove, or adjust?

2. **Geographic concepts to keep**: Should `silk road` stay with dates (e.g. -200 to +1500),
   or remove it since it's outside the current content range?

3. **Continents**: Confirm removal of all continent/world entries is OK — users who
   want to zoom to "Europe" will lose that shortcut.

4. **PAR-blocked entries** (Step 2B): Confirm that removing `ancient greece`,
   `ancient rome`, `ancient egypt`, `ancient india`, `ancient china`, `roman empire`,
   `achaemenid empire`, `maurya empire` from hand-curated is the right call (lets PAR
   data with proper dates and centroids take over).

## Verification

After implementation, run `deploy.ps1` (data rebuild only, no Cloudflare upload needed
initially) and open the exported CSV to confirm:
- All entries have dates (except modern countries showing `1990`)
- No city entries present
- Centroids look geographically reasonable (spot-check Roman Empire, Achaemenid Empire,
  Ancient Egypt)
- Uruguay and other previously missing modern countries now appear
- Total entry count is consistent with what was removed/retained
