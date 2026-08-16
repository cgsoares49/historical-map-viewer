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

Known gaps this sample does **not** yet address (see the accompanying plan):
nested/multi-level MemberOf chains (e.g. Tauromenion is flattened under Roman Ally
instead of chained through Kingdom of Syracuse), transient/campaign entries (currently
excluded entirely rather than typed), tribal areas (dot clusters not yet converted to
any geometry), and cities (not yet in this schema at all).
