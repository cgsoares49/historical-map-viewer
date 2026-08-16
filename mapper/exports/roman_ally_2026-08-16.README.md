# Roman Ally — sample polity polygon export

Generated: 2026-08-16, by `mapper/export_polity_polygons.py` from MAPPER's canonical raw
tile data (`C:\My stuff\mapper\polareas`, `pols`, `coasts`), tiles `125/010`, `125/015`,
`130/000`, `130/006`, `130/012`, `130/018` — the tiles containing "Roman Ally" geometry.

Same schema, build process, and color rule as the Roman Republic sample (see that
export's README for the full write-up) — this one is a much larger, more varied test of
the same pipeline.

## Contents

132 rows total: 128 `Type="POLITY"` (53 for Roman Ally itself, plus 57 distinct nested
member names — tribes/city-states that appear as `"Roman Ally - X"` at some point,
including some well outside Rome's own territory, e.g. `Massalia`/Marseille and
`Kingdom of Syracuse`, since "allied" status was recorded broadly across Italy and
Sicily) and 4 `Type="TRANSIENT"` (`Apulia`, `Army`, `Kingdom of Syracuse`,
`Naval expedition` — see the Roman Republic README for what these are and why they're
kept, not discarded). Spans **-486.5 to -1.0**.

## Notable results

- **92 real territory entries, plus a handful of transient/army entries newly surfaced**
  as their own `Type="TRANSIENT"` rows (4 of them) — far fewer than Roman Republic's 354,
  consistent with the theory that campaigns tend to be recorded under whichever polity
  conducted them, not under an ally's own name; a few still slipped in here.
- **Confirms a name can be both**: `Apulia` and `Kingdom of Syracuse` each produce *both*
  a `POLITY` row-set (their real held territory) *and* a separate `TRANSIENT` row-set
  (a campaign that happens to share the same name chain) — the pipeline was designed to
  support this, and this is the first real data confirming it actually occurs.
- **One member produced zero rows**: `Vulci` — its only "Roman Ally" date range has
  `from == to` (a zero-span/instant marker), same pattern as `Latin League` in the Roman
  Republic export; correctly produces no interval, not a bug.
- **A real 3-level MemberOf chain**: `Roman Ally > Kingdom of Syracuse > Tauromenion`.
  `Kingdom of Syracuse` itself has `MemberOf="(Roman Ally)"`; `Tauromenion` has
  `MemberOf="(Kingdom of Syracuse)"`, not `"(Roman Ally)"` — nested MemberOf chains of
  arbitrary depth are fully supported (this pipeline goes as deep as the source data
  does, needed for e.g. the Persian Empire, which nests 4+ levels).
- 14 ring repairs at the parent level (self-intersecting "keyhole" rings needing
  `shapely.make_valid`) — more than the Roman Republic run's 4, expected given the larger
  entry count, and all resolved cleanly (0 invalid geometries in the final output).

## Scope caveat

6 tiles here (vs. 2 for Roman Republic) because Roman-allied territory was recorded much
more broadly. Still not exhaustive — this reflects wherever "Roman Ally" text appears in
the tiles already known to matter for the Rome-adjacent story; a fully general export
would need per-polity tile auto-discovery (not yet built — see project memory).
