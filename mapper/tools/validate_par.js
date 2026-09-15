#!/usr/bin/env node
// validate_par.js — sanity-checks PAR/POL/CST tile data files before you
// trust them (or overwrite the live ones). Written after a Notepad Ctrl-Z
// accident silently deleted one poly-ref line from a PAR file without
// updating its declared ref count, which desynced every entry after it in
// the file (garbage names, negative entry indices, refs to nonexistent
// polygons — the "crazy rendering" symptom).
//
// USAGE
//   node validate_par.js <file-or-dir> [<file-or-dir> ...] [--geometry]
//
// Point it at one file:
//   node validate_par.js "polareas/125/PAR025.ASC"
//   node validate_par.js "pols/125/POL025.PRN"
//   node validate_par.js "coasts/125/CST025.PRN"
//
// Or a directory — it recurses and validates every PAR*.ASC/POL*.PRN/CST*.PRN
// file it finds under it, e.g. check every tile in one go:
//   node validate_par.js polareas
//   node validate_par.js polareas pols coasts        (the whole dataset)
//   node validate_par.js polareas/125                (just that latitude band)
//
// With a single file, full detail is always printed. With more than one file,
// each gets a one-line PASS/FAIL status as it's checked, full diagnostic
// detail is still printed for any FAIL, and a summary totals everything at
// the end.
//
// What it checks, by file type (guessed from the filename):
//   PAR*.ASC  — walks every entry with strict field-shape checks (entry
//               index/areaType/date-range/color-index/ref-count all have to
//               look plausible). The FIRST implausible value hit is reported
//               with 10 lines of context — that's almost always exactly
//               where a line got added/removed without the count above it
//               being updated. If the matching POL/CST files can be found
//               next to it (same tile, standard folder layout), it also
//               checks that every poly-ref actually resolves to a real
//               polygon (per the polIndex<=1000 → CST, polIndex>1000 →
//               POL[polIndex-1000] convention from renderer.js).
//   POL*.PRN / CST*.PRN — same idea, structural-only (no PAR to cross-check
//               refs against).
//
// Pass --geometry to additionally flag entries whose assembled boundary
// self-intersects (segments stitched in the wrong order, or a wrong
// forward/reverse flag — renders as a self-crossing "bowtie" shape if the
// entry has a real fill color). Off by default because a fair number of
// hits are legitimate multi-part/disjoint territories rather than bugs —
// treat a --geometry hit as "worth a look," not "definitely broken," and
// check it visually (like the one already confirmed and fixed: a wrong
// 0/1 direction flag on one ref) before touching the data.
//
// Exit code: 0 if everything checked was clean, 1 if anything failed.
//
// This is a read-only diagnostic — it never modifies any file you point it at.

const fs = require('fs');
const path = require('path');

function lines(text) {
    return text.split(/\r?\n/).map(l => l.trim()).filter(l => l.length > 0 && l !== '\x1a');
}

function parseDateRangeLine(line) {
    const parts = line.split(',');
    if (parts.length !== 2) return null;
    const from = parseFloat(parts[0]), to = parseFloat(parts[1]);
    if (!Number.isFinite(from) || !Number.isFinite(to)) return null;
    return { from, to };
}

// ── Generic "fail with context" reporter ────────────────────────────────────
function makeFailer(ls, label) {
    return function fail(i, msg) {
        console.log(`\n!! ${label}: DESYNC/CORRUPTION DETECTED at line ~${i + 1}: ${msg}`);
        console.log('Context (10 lines before/after):');
        for (let k = Math.max(0, i - 10); k < Math.min(ls.length, i + 10); k++) {
            console.log(`${k === i ? '>>>' : '   '} [line ${k + 1}] ${ls[k]}`);
        }
        return { ok: false, atLine: i + 1, message: msg };
    };
}

// ── CST/POL structural parse+validate ───────────────────────────────────────
// Returns { ok, polys } on success, or { ok:false, atLine, message } on failure.
function validateCstPol(text, label) {
    const ls = lines(text);
    const fail = makeFailer(ls, label);
    let i = 0;
    if (!ls.length) return { ok: true, polys: [] };

    const polyCount = parseInt(ls[i]);
    if (!Number.isFinite(polyCount) || polyCount < 0 || polyCount > 50000) return fail(i, `bad polygon count "${ls[i]}"`);
    i++;

    const polys = [];
    for (let p = 0; p < polyCount; p++) {
        if (i >= ls.length) return fail(i, `ran out of lines at polygon ${p}/${polyCount}`);
        const header = ls[i].trim().split(/\s+/);
        const polyType = parseInt(header[0]);
        const polyIndex = header.length > 1 ? parseInt(header[1]) : 1;
        if (![1, 2].includes(polyType)) return fail(i, `polygon ${p}: bad polyType=${polyType} in header "${ls[i]}" (expected 1 or 2)`);
        if (!Number.isFinite(polyIndex) || polyIndex < 0 || polyIndex > 50000) return fail(i, `polygon ${p}: bad polyIndex=${polyIndex} in header "${ls[i]}"`);
        i++;

        if (i >= ls.length) return fail(i, `polygon ${p} (index ${polyIndex}): ran out of lines before date-range count`);
        const numDates = parseInt(ls[i]);
        if (!Number.isFinite(numDates) || numDates < 0 || numDates > 500) return fail(i, `polygon ${p} (index ${polyIndex}): bad date-range count "${ls[i]}"`);
        i++;
        for (let d = 0; d < numDates; d++) {
            if (i >= ls.length) return fail(i, `polygon ${p} (index ${polyIndex}): ran out of lines mid date-range ${d}`);
            const dr = parseDateRangeLine(ls[i]);
            if (!dr) return fail(i, `polygon ${p} (index ${polyIndex}): bad date-range line "${ls[i]}" (date ${d}), expected "from , to"`);
            i++;
        }

        if (i >= ls.length) return fail(i, `polygon ${p} (index ${polyIndex}): ran out of lines before point count`);
        const pointCount = parseInt(ls[i]);
        if (!Number.isFinite(pointCount) || pointCount < 0 || pointCount > 200000) return fail(i, `polygon ${p} (index ${polyIndex}): bad point count "${ls[i]}"`);
        i++;

        const points = [];
        let logicalPt = 0;
        while (logicalPt < pointCount) {
            if (i >= ls.length) return fail(i, `polygon ${p} (index ${polyIndex}): ran out of lines mid points (${logicalPt}/${pointCount})`);
            const raw = ls[i].trim().split(/[\s,]+/).filter(t => t.length > 0);
            let off = 0, repeat = 1;
            if (raw[0] && raw[0].startsWith('[')) {
                const m = raw[0].match(/\[x(\d+)\]/i);
                if (!m) return fail(i, `polygon ${p} (index ${polyIndex}): unrecognized repeat marker "${raw[0]}"`);
                repeat = parseInt(m[1]);
                off = 1;
            }
            if (raw.length - off < 2) return fail(i, `polygon ${p} (index ${polyIndex}): point line "${ls[i]}" doesn't have lon/lat`);
            const lon = parseFloat(raw[off]), lat = parseFloat(raw[off + 1]);
            if (!Number.isFinite(lon) || !Number.isFinite(lat)) return fail(i, `polygon ${p} (index ${polyIndex}): unparseable point "${ls[i]}"`);
            if (Math.abs(lon) > 361 || Math.abs(lat) > 91) return fail(i, `polygon ${p} (index ${polyIndex}): out-of-range coordinate lon=${lon} lat=${lat}`);
            for (let k = 0; k < repeat && logicalPt < pointCount; k++) { points.push({ lon, lat }); logicalPt++; }
            i++;
        }
        polys.push({ polyIndex, polyType, points });
    }

    if (i !== ls.length) {
        return { ok: true, polys, extraLines: ls.length - i };
    }
    return { ok: true, polys };
}

// ── PAR structural parse+validate ───────────────────────────────────────────
function validatePar(text, label) {
    const ls = lines(text);
    const fail = makeFailer(ls, label);
    let i = 0;
    if (!ls.length) return { ok: true, entries: [] };

    const entryCount = parseInt(ls[i]);
    if (!Number.isFinite(entryCount) || entryCount < 0 || entryCount > 50000) return fail(i, `bad entry count "${ls[i]}"`);
    i++;

    const entries = [];
    for (let e = 0; e < entryCount; e++) {
        if (i >= ls.length) return fail(i, `ran out of lines at entry ${e}/${entryCount}`);

        const entryIndex = parseInt(ls[i]);
        if (!Number.isFinite(entryIndex) || entryIndex < 0 || entryIndex > 20000) return fail(i, `entry ${e}: bad entryIndex "${ls[i]}" (expected a small non-negative int)`);
        i++;

        if (i >= ls.length) return fail(i, `entry ${e} (entryIndex ${entryIndex}): ran out of lines before areaType`);
        const areaType = parseInt(ls[i]);
        if (areaType !== 0 && areaType !== 1) return fail(i, `entry ${e} (entryIndex ${entryIndex}): bad areaType "${ls[i]}" (expected 0 or 1)`);
        i++;

        if (i >= ls.length) return fail(i, `entry ${e} (entryIndex ${entryIndex}): ran out of lines before date-range count`);
        const numDateRanges = parseInt(ls[i]);
        if (!Number.isFinite(numDateRanges) || numDateRanges < 0 || numDateRanges > 500) return fail(i, `entry ${e} (entryIndex ${entryIndex}): bad date-range count "${ls[i]}"`);
        i++;

        const dateRanges = [];
        for (let d = 0; d < numDateRanges; d++) {
            if (i >= ls.length) return fail(i, `entry ${e} (entryIndex ${entryIndex}): ran out of lines mid date-range ${d}`);
            const dr = parseDateRangeLine(ls[i]);
            if (!dr) return fail(i, `entry ${e} (entryIndex ${entryIndex}): bad date-range line "${ls[i]}" (date ${d}), expected "from , to"`);
            i++;
            if (i >= ls.length) return fail(i, `entry ${e} (entryIndex ${entryIndex}): ran out of lines before name (date ${d})`);
            const name = ls[i]; i++;
            if (i >= ls.length) return fail(i, `entry ${e} (entryIndex ${entryIndex}, name "${name}"): ran out of lines before colorIndex`);
            const colorLine = ls[i];
            const colorIndex = parseInt(colorLine);
            if (!Number.isFinite(colorIndex) || colorIndex < 0 || colorIndex > 5000 || /[a-zA-Z]/.test(colorLine)) {
                return fail(i, `entry ${e} (entryIndex ${entryIndex}, name "${name}"): bad colorIndex "${colorLine}"`);
            }
            i++;
            dateRanges.push({ from: dr.from, to: dr.to, name, colorIndex });
        }

        if (i >= ls.length) return fail(i, `entry ${e} (entryIndex ${entryIndex}): ran out of lines before ref count`);
        const numRefsLine = ls[i];
        const numRefs = parseFloat(numRefsLine);
        if (!Number.isFinite(numRefs) || numRefs > 2000 || numRefs < -10000) return fail(i, `entry ${e} (entryIndex ${entryIndex}): bad ref count "${numRefsLine}"`);
        i++;

        const polyRefs = [];
        let dotPoint = null;
        if (numRefs < 0) {
            if (i >= ls.length) return fail(i, `entry ${e} (entryIndex ${entryIndex}): ran out of lines before dot coordinate`);
            const coords = ls[i].trim().split(/[\s,]+/);
            const lon = parseFloat(coords[0]), lat = parseFloat(coords[1]);
            if (!Number.isFinite(lon) || !Number.isFinite(lat)) return fail(i, `entry ${e} (entryIndex ${entryIndex}): bad dot coordinate "${ls[i]}"`);
            dotPoint = { lon, lat };
            i++;
        } else {
            for (let r = 0; r < numRefs; r++) {
                if (i >= ls.length) return fail(i, `entry ${e} (entryIndex ${entryIndex}): ran out of lines mid poly-refs (${r}/${numRefs})`);
                const parts = ls[i].split(',');
                const polIndex = parseInt(parts[0]);
                if (!Number.isFinite(polIndex)) return fail(i, `entry ${e} (entryIndex ${entryIndex}): unparseable poly-ref "${ls[i]}" (ref ${r}/${numRefs})`);
                const flag = parts.length > 1 ? parseInt(parts[1]) : 0;
                polyRefs.push({ polIndex, flag });
                i++;
            }
        }
        entries.push({ entryIndex, areaType, dateRanges, polyRefs, dotPoint });
    }

    if (i !== ls.length) {
        return { ok: true, entries, extraLines: ls.length - i };
    }
    return { ok: true, entries };
}

// ── Cross-check PAR refs against sibling POL/CST files, and flag self-intersecting boundaries ──
function buildCombinedPolygon(polyRefs, cstByIndex, polByIndex) {
    const combined = [];
    let sawMissing = false;
    for (const { polIndex, flag } of polyRefs) {
        if (flag === 0 || flag === 1) {
            const poly = polIndex <= 1000 ? cstByIndex.get(polIndex) : polByIndex.get(polIndex - 1000);
            if (!poly || poly.points.length === 0) { sawMissing = true; continue; }
            const pts = poly.points;
            if (flag === 0) for (const pt of pts) combined.push(pt);
            else for (let k = pts.length - 1; k >= 0; k--) combined.push(pts[k]);
        } else {
            let lat = flag; if (lat === 1000) lat = 0;
            combined.push({ lon: polIndex, lat });
        }
    }
    if (combined.length > 1) {
        const f = combined[0], l = combined[combined.length - 1];
        if (f.lon !== l.lon || f.lat !== l.lat) combined.push(f);
    }
    return { points: combined, sawMissing };
}
function ccw(a, b, c) { return (c.lat - a.lat) * (b.lon - a.lon) - (b.lat - a.lat) * (c.lon - a.lon); }
function segsIntersect(a, b, c, d) {
    const d1 = ccw(c, d, a), d2 = ccw(c, d, b), d3 = ccw(a, b, c), d4 = ccw(a, b, d);
    return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0));
}

function crossCheckRefs(parEntries, cstPolys, polPolys, checkGeometry) {
    const cstByIndex = new Map(cstPolys.map(p => [p.polyIndex, p]));
    const polByIndex = new Map(polPolys.map(p => [p.polyIndex, p]));
    const maxCst = cstPolys.length ? Math.max(...cstByIndex.keys()) : 0;
    const maxPol = polPolys.length ? Math.max(...polByIndex.keys()) : 0;

    const missingRefs = [];
    const selfIntersecting = [];
    for (const e of parEntries) {
        if (e.dotPoint) continue;
        for (const { polIndex, flag } of e.polyRefs) {
            if (flag !== 0 && flag !== 1) continue; // explicit connector point, not a ref
            const target = polIndex <= 1000 ? cstByIndex.get(polIndex) : polByIndex.get(polIndex - 1000);
            if (!target) {
                missingRefs.push({ entryIndex: e.entryIndex, name: e.dateRanges[e.dateRanges.length - 1]?.name, polIndex, flag, resolvedAs: polIndex <= 1000 ? `CST[${polIndex}] (max ${maxCst})` : `POL[${polIndex - 1000}] (max ${maxPol})` });
            }
        }
        if (checkGeometry && e.polyRefs.length >= 2) {
            const lastName = e.dateRanges[e.dateRanges.length - 1]?.name;
            if (lastName === 'UNKNOWN') continue; // never gets a fill color — a crossing here is invisible, not worth reporting
            const { points: pts, sawMissing } = buildCombinedPolygon(e.polyRefs, cstByIndex, polByIndex);
            if (!sawMissing && pts.length >= 4) {
                const n = pts.length;
                let crossings = 0;
                for (let a = 0; a < n - 1 && crossings === 0; a++) {
                    for (let b = a + 2; b < n - 1; b++) {
                        if (a === 0 && b === n - 2) continue; // shared closing vertex
                        if (segsIntersect(pts[a], pts[a + 1], pts[b], pts[b + 1])) { crossings++; break; }
                    }
                }
                if (crossings > 0) {
                    selfIntersecting.push({ entryIndex: e.entryIndex, name: lastName, numRefs: e.polyRefs.length });
                }
            }
        }
    }
    return { missingRefs, selfIntersecting };
}

// ── Locate sibling POL/CST files for a PAR file, using the standard layout:
//    polareas/<tile>/PAR<lon>.ASC  ↔  pols/<tile>/POL<lon>.PRN  ↔  coasts/<tile>/CST<lon>.PRN
function findSiblingFiles(parPath) {
    const abs = path.resolve(parPath);
    const dir = path.dirname(abs);           // .../polareas/125
    const tileDir = path.basename(dir);      // "125"
    const polareasRoot = path.dirname(dir);  // .../polareas
    const mapperRoot = path.dirname(polareasRoot);
    const base = path.basename(abs);         // PAR025.ASC
    const m = base.match(/^PAR(.+)\.ASC$/i);
    if (!m) return null;
    const lonStr = m[1];
    const polPath = path.join(mapperRoot, 'pols', tileDir, `POL${lonStr}.PRN`);
    const cstPath = path.join(mapperRoot, 'coasts', tileDir, `CST${lonStr}.PRN`);
    return { polPath, cstPath };
}

// ── Discover files to check from a list of file/dir args ───────────────────
const RECOGNIZED = /^(PAR.+\.ASC|POL.+\.PRN|CST.+\.PRN)$/i;

function collectFiles(inputPaths) {
    const found = [];
    const errors = [];
    function walk(p) {
        let stat;
        try { stat = fs.statSync(p); } catch { errors.push(`Not found: ${p}`); return; }
        if (stat.isDirectory()) {
            for (const entry of fs.readdirSync(p).sort()) {
                walk(path.join(p, entry));
            }
        } else if (RECOGNIZED.test(path.basename(p))) {
            found.push(p);
        }
    }
    for (const p of inputPaths) walk(p);
    return { found, errors };
}

// ── Validate one file, returns { ok, file } ─────────────────────────────────
function validateOneFile(file, verbose, checkGeometry) {
    const base = path.basename(file).toUpperCase();
    const text = fs.readFileSync(file, 'utf8');
    let ok = true;

    if (base.match(/^PAR.+\.ASC$/i)) {
        const result = validatePar(text, 'PAR');
        if (!result.ok) { ok = false; }
        else {
            if (verbose) console.log(`OK — ${result.entries.length} entries parsed with no structural desync.`);
            if (result.extraLines && verbose) console.log(`   note: ${result.extraLines} extra line(s) after the last declared entry (harmless, but check the file wasn't truncated/duplicated).`);

            const siblings = findSiblingFiles(file);
            if (siblings && fs.existsSync(siblings.polPath) && fs.existsSync(siblings.cstPath)) {
                if (verbose) console.log(`\nCross-checking against sibling files:\n  ${siblings.polPath}\n  ${siblings.cstPath}`);
                const polResult = validateCstPol(fs.readFileSync(siblings.polPath, 'utf8'), 'POL');
                const cstResult = validateCstPol(fs.readFileSync(siblings.cstPath, 'utf8'), 'CST');
                if (!polResult.ok || !cstResult.ok) {
                    console.log('\n(Sibling POL/CST file itself has a structural problem — see above. Skipping ref cross-check.)');
                    ok = false;
                } else {
                    const { missingRefs, selfIntersecting } = crossCheckRefs(result.entries, cstResult.polys, polResult.polys, checkGeometry);
                    if (missingRefs.length) {
                        ok = false;
                        console.log(`\n!! ${missingRefs.length} poly-ref(s) point at polygons that don't exist:`);
                        for (const m of missingRefs.slice(0, 30)) console.log(`   entry ${m.entryIndex} ("${m.name}"): ref polIndex=${m.polIndex} flag=${m.flag} -> ${m.resolvedAs} not found`);
                        if (missingRefs.length > 30) console.log(`   ...and ${missingRefs.length - 30} more`);
                    } else if (verbose) {
                        console.log('All poly-refs resolve to a real CST/POL polygon.');
                    }
                    if (checkGeometry) {
                        if (selfIntersecting.length) {
                            console.log(`\n${selfIntersecting.length} entr${selfIntersecting.length === 1 ? 'y' : 'ies'} assemble a self-intersecting boundary — worth a visual look, not necessarily a bug (could be a legitimate multi-part territory):`);
                            for (const s of selfIntersecting) console.log(`   entry ${s.entryIndex} ("${s.name}", ${s.numRefs} refs)`);
                        } else if (verbose) {
                            console.log('No self-intersecting boundaries found.');
                        }
                    }
                }
            } else if (verbose) {
                console.log(`\n(No matching POL/CST tile files found next to this PAR file — skipping ref cross-check and self-intersection check. Structural check above is still valid.)`);
            }
        }
    } else {
        const result = validateCstPol(text, base.startsWith('POL') ? 'POL' : 'CST');
        if (!result.ok) ok = false;
        else {
            if (verbose) console.log(`OK — ${result.polys.length} polygons parsed with no structural desync.`);
            if (result.extraLines && verbose) console.log(`   note: ${result.extraLines} extra line(s) after the last declared polygon (harmless, but check the file wasn't truncated/duplicated).`);
        }
    }
    return ok;
}

// ── Main ──────────────────────────────────────────────────────────────────
function main() {
    const args = process.argv.slice(2);
    const checkGeometry = args.includes('--geometry') || args.includes('-g');
    const inputs = args.filter(a => a !== '--geometry' && a !== '-g');
    if (!inputs.length) {
        console.log('Usage: node validate_par.js <file-or-dir> [<file-or-dir> ...] [--geometry]');
        console.log('  Point it at one PAR/POL/CST file, or a directory (e.g. "polareas") to check every tile under it.');
        console.log('  Add --geometry to also flag self-intersecting boundaries (noisier, some are legitimate multi-part shapes).');
        process.exit(1);
    }

    const { found, errors } = collectFiles(inputs);
    for (const e of errors) console.log(e);
    if (!found.length) {
        console.log('No PAR*.ASC / POL*.PRN / CST*.PRN files found under the given path(s).');
        process.exit(1);
    }

    const multi = found.length > 1;
    let failCount = 0;
    const failedFiles = [];

    for (const file of found) {
        if (multi) {
            process.stdout.write(`${file} ... `);
        } else {
            console.log(`Validating: ${file}`);
        }
        const ok = validateOneFile(file, !multi, checkGeometry);
        if (multi) {
            console.log(ok ? 'PASS' : 'FAIL');
        }
        if (!ok) { failCount++; failedFiles.push(file); }
    }

    if (multi) {
        console.log(`\n${found.length} file(s) checked: ${found.length - failCount} passed, ${failCount} failed.`);
        if (failedFiles.length) {
            console.log('Failed:');
            for (const f of failedFiles) console.log(`  ${f}`);
        }
    }

    process.exit(failCount || errors.length ? 1 : 0);
}

main();
