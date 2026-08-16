# Combined sample — Roman Republic + Roman Ally + Roman Latin Colony

Generated: 2026-08-16. A manual concatenation of the three individual exports
(`roman_republic_2026-08-15`, `roman_ally_2026-08-16`, `roman_latin_colony_2026-08-16`),
`Index` renumbered sequentially across the combined set. Not yet the "real" cumulative
master-file architecture — see the planning discussion for that; this is a one-off
snapshot so the three current samples can be reviewed together.

297 rows, 98 distinct entity names. No exact-duplicate rows (same Name/FromYear/ToYear/
MemberOf) — some names legitimately repeat (e.g. `Praeneste`, `Campania`, `Falerii`
appear as secondaries under more than one parent, at non-overlapping date ranges, since
these places changed allegiance over time) — that's expected, not an error.

Known gaps this sample does **not** yet address (see the accompanying plan — Milestone 1,
nested/multi-level MemberOf, is now done; regenerated below): transient/campaign entries
(currently excluded entirely rather than typed — Milestone 2), tribal areas (dot clusters
not yet converted to any geometry — Milestone 5), and cities (not yet in this schema at
all — Milestone 6).

**Update**: regenerated after Milestone 1 (recursive/nested MemberOf). Tauromenion is now
correctly chained as `Roman Ally > Kingdom of Syracuse > Tauromenion`
(`MemberOf="(Kingdom of Syracuse)"`) instead of being flattened directly under Roman
Ally — same row count (297), same distinct-name count (98), only that one entity's
`MemberOf` value changed.
