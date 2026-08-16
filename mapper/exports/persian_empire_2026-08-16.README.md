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

Two malformed-looking polyRef lines were found across the 54 tiles that crashed the
previous strict-`int()` parser: a connector-point flag value of `"32.6"`
(`polareas/120/PAR035.ASC` line 1943) and a comma-less `"1012     0"` pair
(`polareas/125/PAR040.ASC` line 283, fixed at the source by the user — added the missing
comma). The two turned out to be different in kind, not the same issue twice:

- **`"32.6"` is legitimate data, not a typo** — per the user (2026-08-16): a synthetic
  connector point's latitude has no rule requiring it to land on a whole degree. `flag`
  is now parsed with `js_parse_number` (int or float, whichever the text actually is) and
  the decimal is preserved exactly, not truncated. An earlier version of this fix used
  `parseInt`-style truncation here on the reasoning that it should replicate the live
  renderer's own lossy parsing (matching the precedent for the `newoffsets.txt` quirk) —
  that reasoning didn't apply to this case: `newoffsets.txt` is about cosmetic *display*
  fidelity, whereas this is the actual coordinate data the export's geometry is built
  from, which needs to stay accurate for the export's own purpose.
- The comma-less pair was a genuine typo, now fixed at the source. `js_parse_number`
  still defaults a comma-less token's flag to 0 (matching the live renderer's own
  `parts.length > 1 ? parseInt(parts[1]) : 0`), kept as a safety net in case the same
  delimiter mistake recurs elsewhere in the ~1015-polity dataset.

Also fixed `discover_tiles` matching WIP/backup files (`"PAR040 bad partial fix.ASC"`
etc.) as if they were extra real tiles — found in the same tile 120/040 while
investigating.

## Color-conflict warnings (cosmetic, expected)

362 "conflicting colorIndex" warnings were logged — far more than any Roman sample, an
expected consequence of scale: many nested paths (like the `Arakhosia`/`Arakhosia` case
above) have multiple contributing entries with different `colorIndex` values at the same
merged interval. The exported color is a "first contributor wins" pick, same as before;
this doesn't affect geometry correctness, only which of several plausible shades gets
picked for the row.
