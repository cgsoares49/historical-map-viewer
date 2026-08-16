# Combined sample — Roman Republic + Roman Ally + Roman Latin Colony

Generated: 2026-08-16. A manual concatenation of the three individual exports
(`roman_republic_2026-08-16`, `roman_ally_2026-08-16`, `roman_latin_colony_2026-08-16`),
`Index` renumbered sequentially across the combined set. Not yet the "real" cumulative
master-file architecture — see the planning discussion for that; this is a one-off
snapshot so the three current samples can be reviewed together.

655 rows total: 297 `Type="POLITY"` (98 distinct entity names — some legitimately repeat,
e.g. `Praeneste`, `Campania`, `Falerii` appear under more than one parent at
non-overlapping date ranges, since these places changed allegiance over time — expected,
not an error) and 358 `Type="TRANSIENT"` (army/naval campaign entries, kept as their own
typed rows rather than discarded — see the Roman Republic README for what these are).
No exact-duplicate rows (same Name/FromYear/ToYear/MemberOf/Type).

Known gaps this sample does **not** yet address (see the accompanying plan): tribal areas
(dot clusters not yet converted to any geometry — Milestone 5) and cities (not yet in
this schema at all — Milestone 6). **Milestones 1 (nested MemberOf) and 2 (transient
typing) are both done** and reflected in this snapshot.
