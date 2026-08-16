# Roman Ally — sample polity polygon export

Generated: 2026-08-16, by `mapper/export_polity_polygons.py` from MAPPER's canonical raw
tile data (`C:\My stuff\mapper\polareas`, `pols`, `coasts`), tiles `125/010`, `125/015`,
`130/000`, `130/006`, `130/012`, `130/018` — the tiles containing "Roman Ally" geometry.

Same schema, build process, and color rule as the Roman Republic sample (see that
export's README for the full write-up) — this one is a much larger, more varied test of
the same pipeline.

## Contents

128 rows total: 53 for Roman Ally itself, plus 58 "secondaries" (tribes/city-states that
appear as `"Roman Ally - X"` at some point) — including some well outside Rome's own
territory, e.g. `Massalia` (Marseille) and `Kingdom of Syracuse`, since "allied" status
was recorded broadly across Italy and Sicily, not just adjacent to Rome. Spans
**-486.5 to -1.0**.

## Notable results

- **92 real territory entries survived, 0 excluded as transient** — unlike the Roman
  Republic run, no army/campaign markers turned up under this owner name in this scope
  (plausible: campaigns tend to be recorded under whichever polity conducted them, not
  under an ally's own name).
- **One secondary produced zero rows**: `Vulci` — its only "Roman Ally" date range has
  `from == to` (a zero-span/instant marker), same pattern as `Latin League` in the Roman
  Republic export; correctly produces no interval, not a bug.
- **One secondary has a dash in its own name**: `Kingdom of Syracuse - Tauromenion`. The
  secondary-name split only splits on the *first* `" - "`, so this is captured whole and
  correctly treated as one distinct entity (not confused with plain `Kingdom of Syracuse`,
  which is also a separate secondary in its own right).
- 14 ring repairs at the parent level (self-intersecting "keyhole" rings needing
  `shapely.make_valid`) — more than the Roman Republic run's 4, expected given the larger
  entry count, and all resolved cleanly (0 invalid geometries in the final output).

## Scope caveat

6 tiles here (vs. 2 for Roman Republic) because Roman-allied territory was recorded much
more broadly. Still not exhaustive — this reflects wherever "Roman Ally" text appears in
the tiles already known to matter for the Rome-adjacent story; a fully general export
would need per-polity tile auto-discovery (not yet built — see project memory).
