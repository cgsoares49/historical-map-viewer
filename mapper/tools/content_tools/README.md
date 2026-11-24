# content_tools — helper scripts from the post -240 "Content creation" sessions

These are Claude's working scripts, saved 2026-11-23 so they survive a /clear or a reset of the temp scratch folder.
They are **examples/starting points**, not polished tools: several have hard-coded years, tile names, POL/PAR numbers and
file paths (check the top of each file). Run with `py script.py [args]`. Nothing here writes to `C:\My stuff\mapper`
(the user's canonical data, read-only for scripts); drafts go to `mapper/exports/` and the user copies them over.

Workbooks (`animation actions.xlsx`, `ancient index.xlsx`, `cities.xlsx`, `ancient secondaries.xlsx`) are read from
`C:\Users\csoar\OneDrive\Documents` — ALWAYS copy to a temp folder first (read-only) and check the file's LastWriteTime;
the user has repeatedly edited a stale copy in `C:\My stuff\VID` or forgotten to save.

| script | what it does |
|---|---|
| `iwa_lib.py` | parser for IWA (inland waters) files: groups -> rings -> points (ring 1 = outer, 2+ = islands) |
| `snake_builder_example.py` | the main "army snake" builder: A* route on a 1.5 km grid around lakes (IWA) with 3.2 km clearance, string-pull, lateral meander, variable-radius circle union (round heads, heads centred on the battle point), split at a tile line (30E) with chord vertices snapped to an EXISTING transient crossing pair, simplify, validity/lake-overlap checks, preview PNG, rings pickled for the writers below |
| `replace_pol_blocks_example.py` | rewrites the LAST N POL blocks of a canonical POL file into a draft (keeps CRLF + trailing Ctrl-Z, header count, spacing) and verifies with the parser |
| `draft_pol_par_from_canonical_example.py` | appends new POL blocks and new PAR entries to copies of canonical files (`1000+POL` refs, number line precedes entry, header bump) and verifies old entries unchanged |
| `draft_cit_entry_example.py` | appends one entry to a city (CIT) file in that file's own spacing (check the file's ending: CIT010/020/025 end with Ctrl-Z, CIT030 does not) |
| `measure_transient_widths.py` | mean width (2A/P) of existing army transients in tiles 125/025+030; the user wants new snakes ~9-10 km wide (median 9-11), crossing chords ~11-12 km; radius may shrink to squeeze past lakes |
| `route_lengths_and_tile_crossing_pairs.py` | route lengths -> days at 10 mi/day (16 km/day); lists existing transient vertex pairs on a tile line (lon 30.0) to reuse |
| `changed_since_last_deploy.py` | compares canonical data with `dist\mapper` (last deploy) and lists new/edited polity vs transient PAR entries |
| `verify_*_example.py`, `map_owner_at_year_example.py`, `list_K_cells_example.py` | re-check pasted workbook rows / date shifts, who owns a point at a year, and list K cells (find them by opening words; numbers shift) |

Conventions learned (see Claude's memory `reference_content_creation_start_here.md` for the full list):
a rerun = add a date range to the EXISTING PAR entry; transient POL range is exactly (-9999.0,-9998.0); later PAR entries draw on top;
tile-crossing pieces use exact lon 30.0 vertices shared by both tiles; time: year runs ~-239.9 (Jan) to -239.0 (Dec); 0.1 yr = 36.5 days;
army pace 10 mi/day; use "Attalus" not "Attalus I" for a first appearance (Roman numerals only for later namesakes).

| `par_pol_range_edit.py` | NEW 2026-11-24: line-accurate editors for canonical PAR and POL files: `par_set_ranges(lines, entry, [(from,to,name,color),...])` replaces an entry's date-range block, `pol_set_ranges(lines, pol, [(from,to),...])` replaces a border POL's draw windows (keep the leading (-9998,-9997) marker range). Unchanged ranges keep their original lines; blank lines/CRLF/Ctrl-Z preserved. Used for the Sardinia/Corsica natives-hold-all window (draft_sard.py logic). |
