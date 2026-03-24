// colormatcher.js — ColorLookup + DateMatcher
//
// DateMatcher
// -----------
//   matchDate(dateRanges, year) → matching entry or null
//   Returns the last range where year > from AND year <= to
//   (exclusive start, inclusive stop — matches VB logic)
//
// ColorLookup
// -----------
//   Built from:
//     primariesMap: Map<lowercaseName, {r,g,b}> from DataLoader.loadPrimaries()
//     offsets:      array[4096] of {r,g,b}       from DataLoader.loadOffsets()
//
//   resolve(name, colorIndex) → {r,g,b} or null
//     name:       PAR area name (e.g. "France - Corsica") → uses first segment "France"
//     colorIndex: PAR offset index (0–4095) into newoffsets array (NOT a primaries index)
//     Returns: primaries[name].rgb + offsets[colorIndex], clamped to [0,255]
//     Returns null if name is "UNKNOWN", empty, or not found in primaries.

// ── DateMatcher ────────────────────────────────────────────────────────────────

// Matches VB logic: year > start AND year <= stop  (exclusive start, inclusive stop)
// Last matching range wins (handles rare overlaps in the data).
function matchDate(dateRanges, year) {
    if (!dateRanges || !dateRanges.length) return null;
    let match = null;
    for (const range of dateRanges) {
        if (year > range.from && year <= range.to) {
            match = range;
        }
    }
    return match;
}

// ── ColorLookup ────────────────────────────────────────────────────────────────

class ColorLookup {
    // primariesMap: Map<lowercaseName, {r,g,b}> from DataLoader.loadPrimaries()
    // offsets:      array[4096] of {r,g,b}      from DataLoader.loadOffsets()
    constructor(primariesMap, offsets) {
        this._primaries = primariesMap;
        this._offsets   = offsets;
    }

    // Resolve a PAR date-range entry to {r,g,b}, or null for no fill.
    // Accepts a full PAR dateRange object { name, colorIndex }.
    // Color = primaries[firstName].rgb + offsets[colorIndex], clamped 0–255.
    resolve(dateRange) {
        const rawName    = dateRange.name    ?? '';
        const colorIndex = dateRange.colorIndex ?? 0;

        if (!rawName) return null;

        // Always use first segment before " - " for primaries lookup (matches VB)
        const lookupName = rawName.split(' - ')[0].trim().toLowerCase();

        const base = this._primaries.get(lookupName);
        if (!base) return null;

        const off = this._offsets[colorIndex] ?? { r: 0, g: 0, b: 0 };

        const r = Math.min(255, base.r + off.r);
        const g = Math.min(255, base.g + off.g);
        const b = Math.min(255, base.b + off.b);
        // VB skips fill if final color is (0,0,0) — matches "GoTo skipfill" guard
        if (r === 0 && g === 0 && b === 0) return null;
        return { r, g, b };
    }

    // Return a CSS rgb() string, or fallback if unresolvable.
    toCss(dateRange, _unused1, fallback = null) {
        const c = this.resolve(dateRange);
        return c ? `rgb(${c.r},${c.g},${c.b})` : fallback;
    }

    // City symbols use the offset value directly as the full RGB color (no primaries base).
    // Matches VB: intC = intRedoffset(intOffset) with no intCCred addition.
    resolveCityRgb(colorIndex) {
        return this._offsets[colorIndex] ?? { r: 0, g: 0, b: 0 };
    }

    cityColor(colorIndex) {
        const { r, g, b } = this.resolveCityRgb(colorIndex);
        return `rgb(${r},${g},${b})`;
    }
}
