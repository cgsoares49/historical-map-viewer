// dataloader.js — DataLoader
// Fetches and parses CST/POL/PAR tile data files via fetch().
//
// File formats (all are CRLF text):
//
//  CST (coasts):
//    <polygon_count>
//    For each polygon:
//      <poly_index>  <poly_type>
//      <num_date_lines>          ← usually 1; CST polygons have time-dependent date ranges
//      <date_from>  ,  <date_to>
//      <point_count>
//      <lon>  <lat>  (repeated point_count times)
//
//  POL (political boundaries):
//    Same structure as CST, but num_date_lines can be > 1.
//
//  PAR (political areas):
//    <entry_count>
//    For each entry:
//      <entry_index>
//      <ignored_line>            ← always "1" in every file seen
//      <num_date_ranges>
//      For each date range:
//        <date_from>  ,  <date_to>
//        <area_name>
//        <color_index>
//      <num_poly_refs>
//      For each poly_ref:
//        <pol_polygon_index>  ,  <flag>
//
// Returned structures:
//   cst:  [ { polyIndex, polyType, dateRanges:[{from,to}], points:[{lon,lat}] }, … ]
//   pol:  [ { polyIndex, polyType, dateRanges:[{from,to}], points:[{lon,lat}] }, … ]
//   par:  [ { entryIndex, dateRanges:[{from,to,name,colorIndex}], polyRefs:[{polIndex,flag}] }, … ]

class DataLoader {
    constructor() {
        // Cache: url → parsed object (null if file was 404/empty)
        this._cache = new Map();
    }

    // ── Public API ──────────────────────────────────────────────────────────────

    // Fetch and parse all tile files for a tile descriptor from TileManager.
    // Returns { cst, pol, par, cities, iwa, niw } where each is an array of parsed objects.
    // Missing files (404) silently return empty arrays.
    async loadTile(tile) {
        const [cst, pol, par, cities, iwa, niw] = await Promise.all([
            this._fetchAndParse(tile.coastsFile,   this._parseCstPol.bind(this)),
            this._fetchAndParse(tile.polsFile,      this._parseCstPol.bind(this)),
            this._fetchAndParse(tile.polareasFile,  this._parsePar.bind(this)),
            this._fetchAndParse(tile.citiesFile,    this._parseCities.bind(this)),
            this._fetchAndParse(tile.inwaterFile,   this._parseIwa.bind(this)),
            this._fetchAndParse(tile.niwFile,       this._parseNiw.bind(this)),
        ]);
        return { cst, pol, par, cities, iwa, niw };
    }

    // Load primaries.txt → Map<lowercaseName, {r,g,b}>
    // Format: index,name,R,G,B  (1-based sequential, matching VB ReadInCountryNames)
    async loadPrimaries(path = 'primaries.txt') {
        const text = await this._fetchText(path);
        if (!text) return new Map();
        const lines = this._lines(text);
        let i = 0;
        const count = parseInt(lines[i++]);
        const map = new Map();
        for (let n = 0; n < count && i < lines.length; n++, i++) {
            const parts = lines[i].split(',');
            if (parts.length < 5) continue;
            const name = parts[1].trim().toLowerCase();
            const r    = parseInt(parts[2]);
            const g    = parseInt(parts[3]);
            const b    = parseInt(parts[4]);
            map.set(name, { r, g, b });
        }
        return map;
    }

    // Load newoffsets.txt → array of 4096 {r,g,b} offset entries (tab-separated)
    // Index 0 = no offset (0,0,0). Matches VB ReadInOffsets.
    async loadOffsets(path = 'newoffsets.txt') {
        const text = await this._fetchText(path);
        if (!text) return new Array(4096).fill({ r: 0, g: 0, b: 0 });
        const lines = this._lines(text);
        const offsets = [];
        for (const line of lines) {
            const parts = line.split(/\t/);
            offsets.push({
                r: parseInt(parts[0]) || 0,
                g: parseInt(parts[1]) || 0,
                b: parseInt(parts[2]) || 0,
            });
        }
        // Pad to 4096 if needed
        while (offsets.length < 4096) offsets.push({ r: 0, g: 0, b: 0 });
        return offsets;
    }

    // ── Private helpers ─────────────────────────────────────────────────────────

    async _fetchAndParse(url, parseFn) {
        if (this._cache.has(url)) return this._cache.get(url) ?? [];
        const text = await this._fetchText(url);
        const result = text ? parseFn(text) : [];
        this._cache.set(url, result.length ? result : null);
        return result;
    }

    async _fetchText(url) {
        try {
            const resp = await fetch(url);
            if (!resp.ok) return null;
            return await resp.text();
        } catch {
            return null;
        }
    }

    // Split text into non-empty trimmed lines (handles CRLF and LF)
    _lines(text) {
        return text
            .split(/\r?\n/)
            .map(l => l.trim())
            .filter(l => l.length > 0 && l !== '\x1a');  // strip EOF marker
    }

    // Parse CST and POL files (same format)
    _parseCstPol(text) {
        const lines = this._lines(text);
        if (!lines.length) return [];

        let i = 0;
        const polyCount = parseInt(lines[i++]);
        if (!polyCount) return [];

        const polys = [];
        for (let p = 0; p < polyCount; p++) {
            if (i >= lines.length) break;

            // Header: "poly_type  poly_seq_index"
            // header[0] = classification type (1 or 2)
            // header[1] = sequential index used in PAR polyRefs  ← this is the key
            const header = lines[i++].trim().split(/\s+/);
            const polyType  = parseInt(header[0]);
            const polyIndex = header.length > 1 ? parseInt(header[1]) : 1;

            // Date range lines
            const numDates = parseInt(lines[i++]);
            const dateRanges = [];
            for (let d = 0; d < numDates; d++) {
                if (i >= lines.length) break;
                const dr = this._parseDateRange(lines[i++]);
                dateRanges.push(dr);
            }

            // Points
            // pointCount is the LOGICAL count (after [xN] expansion).
            // "[xN] lon lat" means repeat (lon,lat) N times — one physical line counts as N logical points.
            const pointCount = parseInt(lines[i++]);
            const points = [];
            let logicalPt = 0;
            while (logicalPt < pointCount) {
                if (i >= lines.length) break;
                const raw = lines[i++].trim().split(/[\s,]+/).filter(t => t.length > 0);
                let off = 0;
                let repeat = 1;
                if (raw[0] && raw[0].startsWith('[')) {
                    const m = raw[0].match(/\[x(\d+)\]/i);
                    if (m) repeat = parseInt(m[1]);
                    off = 1;
                }
                if (raw.length - off >= 2) {
                    const lon = parseFloat(raw[off]);
                    const lat = parseFloat(raw[off + 1]);
                    if (!isNaN(lon) && !isNaN(lat)) {
                        for (let k = 0; k < repeat && logicalPt < pointCount; k++) {
                            points.push({ lon, lat });
                            logicalPt++;
                        }
                    } else {
                        logicalPt += repeat;
                    }
                } else {
                    logicalPt++;
                }
            }

            polys.push({ polyIndex, polyType, dateRanges, points });
        }
        return polys;
    }

    // Parse PAR file
    _parsePar(text) {
        const lines = this._lines(text);
        if (!lines.length) return [];

        let i = 0;
        const entryCount = parseInt(lines[i++]);
        if (!entryCount) return [];

        const entries = [];
        for (let e = 0; e < entryCount; e++) {
            if (i >= lines.length) break;

            const entryIndex = parseInt(lines[i++]);

            // areaType: 1 = normal polygon fill; 0 = "dot" (only shown when ShowDots enabled)
            const areaType = parseInt(lines[i++]);

            // Date ranges
            const numDateRanges = parseInt(lines[i++]);
            const dateRanges = [];
            for (let d = 0; d < numDateRanges; d++) {
                if (i + 2 >= lines.length) break;
                const { from, to } = this._parseDateRange(lines[i++]);
                const name       = lines[i++];
                const colorIndex = parseInt(lines[i++]);
                dateRanges.push({ from, to, name, colorIndex });
            }

            // Polygon references
            // numRefs < 0 signals a "dot" entry: one lon\tlat coordinate follows instead of poly refs
            // Use parseFloat so that values like -0.9 (not just -1, -2, -3) are correctly negative
            const numRefs = parseFloat(lines[i++]);
            const polyRefs = [];
            let dotPoint = null;
            let dotDiameter = 1;
            if (numRefs < 0) {
                // Dot entry: one "lon\tlat" coordinate follows.
                // The absolute value of numRefs is the circle diameter in degrees.
                const coords = lines[i++].trim().split(/[\s,]+/);
                dotPoint = { lon: parseFloat(coords[0]), lat: parseFloat(coords[1]) };
                dotDiameter = Math.abs(numRefs) / 10;
            } else {
                for (let r = 0; r < numRefs; r++) {
                    if (i >= lines.length) break;
                    const parts = lines[i++].split(',');
                    const polIndex = parseInt(parts[0]);
                    const flag     = parts.length > 1 ? parseInt(parts[1]) : 0;
                    polyRefs.push({ polIndex, flag });
                }
            }

            entries.push({ entryIndex, areaType, dateRanges, polyRefs, dotPoint, dotDiameter });
        }
        return entries;
    }

    // Parse CIT*.TXT city tile files.
    //
    // Format per entry:
    //   <entry_index>           ← ignored
    //   <numDateRanges>
    //   For each date range:
    //     <from>  ,  <to>
    //     <name>
    //     <colorIndex>
    //     <symCode>             ← float: ≥0 = filled circle(s), <0 = X mark
    //     <detCode>             ← int: >0 = draw, 0 = skip
    //   <numCoords>             ← always 1; ignored
    //   <lon>  <lat>            ← tab/space/comma separated
    //
    // Returns: [ { dateRanges:[{from,to,name,colorIndex,symCode,detCode}], lon, lat }, … ]
    _parseCities(text) {
        const lines = this._lines(text);
        if (!lines.length) return [];

        let i = 0;
        const cityCount = parseInt(lines[i++]);
        if (!cityCount || cityCount <= 0) return [];

        const cities = [];
        for (let c = 0; c < cityCount; c++) {
            if (i >= lines.length) break;

            i++;  // entry index (ignored)

            const numDateRanges = parseInt(lines[i++]);
            const dateRanges = [];
            for (let d = 0; d < numDateRanges; d++) {
                if (i + 4 >= lines.length) break;
                const { from, to } = this._parseDateRange(lines[i++]);
                const name       = lines[i++];
                const colorIndex = parseInt(lines[i++]);
                const symCode    = parseFloat(lines[i++]);
                const detCode    = parseInt(lines[i++]);
                dateRanges.push({ from, to, name, colorIndex, symCode, detCode });
            }

            i++;  // numCoords (always 1, ignored)

            if (i >= lines.length) break;
            const parts = lines[i++].trim().split(/[\s,\t]+/).filter(t => t.length > 0);
            const lon = parseFloat(parts[0]);
            const lat = parseFloat(parts[1]);

            if (!isNaN(lon) && !isNaN(lat)) {
                cities.push({ dateRanges, lon, lat });
            }
        }
        return cities;
    }

    // Parse "date_from  ,  date_to" → { from: number, to: number }
    _parseDateRange(line) {
        const parts = line.split(',');
        return {
            from: parseFloat(parts[0]),
            to:   parts.length > 1 ? parseFloat(parts[1]) : 9999
        };
    }

    // Parse IWA (InWater Areas) tile files.
    //
    // Format:
    //   <group_count>
    //   For each group (one water body):
    //     <num_rings>
    //     For each ring:
    //       <ring_type>  <ring_index>
    //       <num_date_ranges>
    //       <date_from>  ,  <date_to>       ← always -9999..9990 in practice
    //       7                               ← constant field, ignored
    //       <point_count>
    //       <lon>  <lat>  (repeated)
    //
    // Ring 1 = outer water boundary; rings 2+ = island inner rings.
    // Returns: [ { rings: [ { ringType, ringIndex, points:[{lon,lat}] } ] } ]
    _parseIwa(text) {
        const lines = this._lines(text);
        if (!lines.length) return [];

        let i = 0;
        const groupCount = parseInt(lines[i++]);
        if (!groupCount) return [];

        const groups = [];
        for (let g = 0; g < groupCount; g++) {
            if (i >= lines.length) break;
            const numRings = parseInt(lines[i++]);
            const rings = [];
            for (let r = 0; r < numRings; r++) {
                if (i >= lines.length) break;

                const header  = lines[i++].trim().split(/\s+/);
                const ringType  = parseInt(header[0]);
                const ringIndex = header.length > 1 ? parseInt(header[1]) : r + 1;

                const numDates = parseInt(lines[i++]);
                for (let d = 0; d < numDates; d++) {
                    if (i < lines.length) i++;   // skip date range lines
                }
                i++;  // skip constant "7" field

                const pointCount = parseInt(lines[i++]);
                const points = [];
                let logicalPt = 0;
                while (logicalPt < pointCount) {
                    if (i >= lines.length) break;
                    const raw = lines[i++].trim().split(/[\s,]+/).filter(t => t.length > 0);
                    let off = 0, repeat = 1;
                    if (raw[0] && raw[0].startsWith('[')) {
                        const m = raw[0].match(/\[x(\d+)\]/i);
                        if (m) repeat = parseInt(m[1]);
                        off = 1;
                    }
                    if (raw.length - off >= 2) {
                        const lon = parseFloat(raw[off]);
                        const lat = parseFloat(raw[off + 1]);
                        if (!isNaN(lon) && !isNaN(lat)) {
                            for (let k = 0; k < repeat && logicalPt < pointCount; k++) {
                                points.push({ lon, lat });
                                logicalPt++;
                            }
                        } else {
                            logicalPt += repeat;
                        }
                    } else {
                        logicalPt++;
                    }
                }
                rings.push({ ringType, ringIndex, points });
            }
            groups.push({ rings });
        }
        return groups;
    }

    // Parse NIW (Named InWater) tile files.
    //
    // Format (similar to PAR but refs point to IWA rings instead of POL polygons):
    //   <entry_count>
    //   For each entry:
    //     <entry_index>
    //     <num_date_ranges>
    //     For each date_range:
    //       <date_from>  ,  <date_to>
    //       <area_name>
    //       <color_index>
    //     <num_refs>
    //     For each ref:
    //       <iwa_group_index>  ,  <ring_index>   ← 1-based group position in IWA file
    //
    // Returns: [ { entryIndex, dateRanges:[{from,to,name,colorIndex}], refs:[{groupIndex,ringIndex}] } ]
    _parseNiw(text) {
        const lines = this._lines(text);
        if (!lines.length) return [];

        let i = 0;
        const entryCount = parseInt(lines[i++]);
        if (!entryCount) return [];

        const entries = [];
        for (let e = 0; e < entryCount; e++) {
            if (i >= lines.length) break;

            const entryIndex = parseInt(lines[i++]);

            const numDateRanges = parseInt(lines[i++]);
            const dateRanges = [];
            for (let d = 0; d < numDateRanges; d++) {
                if (i + 2 >= lines.length) break;
                const { from, to } = this._parseDateRange(lines[i++]);
                const name       = lines[i++];
                const colorIndex = parseInt(lines[i++]);
                dateRanges.push({ from, to, name, colorIndex });
            }

            const numRefs = parseInt(lines[i++]);
            const refs = [];
            for (let r = 0; r < numRefs; r++) {
                if (i >= lines.length) break;
                const parts = lines[i++].split(',');
                refs.push({
                    groupIndex: parseInt(parts[0]),
                    ringIndex:  parts.length > 1 ? parseInt(parts[1]) : 1,
                });
            }

            entries.push({ entryIndex, dateRanges, refs });
        }
        return entries;
    }
}
