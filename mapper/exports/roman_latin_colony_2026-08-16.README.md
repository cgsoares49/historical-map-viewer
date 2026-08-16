# Roman Latin Colony — sample polity polygon export

Generated: 2026-08-16, by `mapper/export_polity_polygons.py` from MAPPER's canonical raw
tile data (`C:\My stuff\mapper\polareas`, `pols`, `coasts`), tiles `130/006`, `130/012` —
the only 2 tiles containing "Roman Latin Colony" geometry.

Same schema, build process, and color rule as the Roman Republic sample (see that
export's README for the full write-up).

## Contents

55 rows total: 25 for Roman Latin Colony itself, plus 26 secondaries, one row each for
most (a few — `Ardea`, `Cales`, `Circeii`, `Fregellae` — have 2, reflecting a colony
being founded, lost, and re-founded). Spans **-495.7 to -1.0**.

## Notable results

- **26 real territory entries, 0 excluded as transient** — clean run, no army/campaign
  markers under this owner name, no ring repairs needed at all (unlike Roman Republic and
  Roman Ally, both of which needed several `shapely.make_valid` repairs).
- Every discovered secondary produced at least one row (no zero-span dummy entries in
  this scope, unlike `Latin League` in Roman Republic or `Vulci` in Roman Ally).
- Recognizable named colonies throughout: `Ariminum` (Rimini), `Beneventum`, `Luceria`,
  `Venusia`, `Paestum`, `Sora`, among others — a good visual/historical sanity check when
  reviewing the shapes.
