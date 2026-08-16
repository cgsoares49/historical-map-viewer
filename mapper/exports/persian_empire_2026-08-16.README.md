# Persian Empire — Milestone 4 stress test

Generated: 2026-08-16, by `mapper/export_polity_polygons.py --polity "Persian Empire"
--auto-tiles`, 54 auto-discovered tiles (`polareas/` lat bands 110–135, lon 015–075) —
by far the largest scope run through this pipeline so far (the 3 Roman samples used
2–6 tiles each). Deliberately chosen to stress-test the recursive nesting from
Milestone 1, since the user specifically noted this empire's data goes several levels
deeper than anything seen in the Roman samples.

Same schema, build process, color rule, and transient-typing as the Roman Republic
export — see that README for the full write-up.

## Contents

1239 rows total: 970 `Type="POLITY"`, 269 `Type="TRANSIENT"`, across 207 distinct entity
names. 594 real territory PAR entries and 306 transient/army entries were found across
the 54 tiles; 20 ring repairs (self-intersecting "keyhole" rings), all resolved cleanly.
Parent's own timeline (`Persian Empire`, 155 rows) has 0 continuity gaps.

## Nesting confirmed to real depth (Milestone 1 validation)

238 distinct nested member paths were discovered, several genuinely 4-5 levels deep —
this is the concrete evidence the recursive MemberOf design (built for exactly this
case) works correctly at real depth, not just the 2-3 levels seen in the Roman data:

- `Persian Empire > Arakhosia > Drangiana > Ariaspai` — `Ariaspai` row has
  `MemberOf="(Drangiana)"`, and `Drangiana` itself has `MemberOf="(Arakhosia)"`.
- `Persian Empire > Babylonia > Assyria > Kilikia > Pityussa` — a genuine 5-level chain.
- `Persian Empire > Assyria > Cypriot Kingdoms > {Amathous, Kition, Salamis, ...}` — a
  3-level chain with many siblings (the individual Cypriot city-kingdoms) at the same
  depth.

## A real data quirk this surfaced: self-referential naming

The raw data has both `"Persian Empire - Arakhosia"` (the province, directly under the
empire) *and* `"Persian Empire - Arakhosia - Arakhosia"` (a sub-region within it, sharing
the province's own name — presumably its administrative core vs. the broader province).
This produces two distinct output rows both named `Arakhosia`: one with
`MemberOf="(Persian Empire)"`, one with `MemberOf="(Arakhosia)"` — exactly the correct,
distinguishable representation given `MemberOf` always resolves relative to the
*immediate* parent. Not a bug; the mechanism handled this real-data pattern correctly
without any special-casing.

## Parser fix this run required

Two malformed polyRef lines were found across the 54 tiles that crashed the previous
strict-`int()` parser: a connector-point flag value of `"32.6"` (`polareas/120/PAR035.ASC`
line 1943) and a comma-less `"1012     0"` pair (`polareas/125/PAR040.ASC` line 283). The
live JS renderer's own polyRef parsing already uses `parseInt`, which silently tolerates
both (truncates the decimal, defaults flag to 0 when there's no second comma-separated
value) rather than crashing — the Python port now replicates that exact leniency
(`js_parse_int`) instead of failing, consistent with this project's established
"replicate what MAPPER actually displays, don't silently correct it" approach (see the
`newoffsets.txt` quirk in the Roman Republic README for precedent). Also fixed
`discover_tiles` matching WIP/backup files (`"PAR040 bad partial fix.ASC"` etc.) as if
they were extra real tiles — found in the same tile 120/040 while investigating.

## Color-conflict warnings (cosmetic, expected)

362 "conflicting colorIndex" warnings were logged — far more than any Roman sample, an
expected consequence of scale: many nested paths (like the `Arakhosia`/`Arakhosia` case
above) have multiple contributing entries with different `colorIndex` values at the same
merged interval. The exported color is a "first contributor wins" pick, same as before;
this doesn't affect geometry correctness, only which of several plausible shades gets
picked for the row.
