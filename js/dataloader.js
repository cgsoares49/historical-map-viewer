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

    // Fetch and parse all three tile files for a tile descriptor from TileManager.
    // Returns { cst, pol, par } where each is an array of parsed objects.
    // Missing files (404) silently return empty arrays.
    async loadTile(tile) {
        const [cst, pol, par] = await Promise.all([
            this._fetchAndParse(tile.coastsFile,   this._parseCstPol.bind(this)),
            this._fetchAndParse(tile.polsFile,      this._parseCstPol.bind(this)),
            this._fetchAndParse(tile.polareasFile,  this._parsePar.bind(this)),
        ]);
        return { cst, pol, par };
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
            const pointCount = parseInt(lines[i++]);
            const points = [];
            for (let pt = 0; pt < pointCount; pt++) {
                if (i >= lines.length) break;
                // Coordinates may be "lon lat", "lon , lat", or "[xN] lon lat"
                const raw = lines[i++].trim().split(/[\s,]+/).filter(t => t.length > 0);
                // Skip [xN] repeat-count prefix if present
                const off = raw[0].startsWith('[') ? 1 : 0;
                if (raw.length - off >= 2) {
                    const lon = parseFloat(raw[off]);
                    const lat = parseFloat(raw[off + 1]);
                    if (!isNaN(lon) && !isNaN(lat)) {
                        points.push({ lon, lat });
                    }
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
            const numRefs = parseInt(lines[i++]);
            const polyRefs = [];
            let dotPoint = null;
            if (numRefs < 0) {
                // Dot entry: one "lon\tlat" coordinate follows
                const coords = lines[i++].trim().split(/[\s,]+/);
                dotPoint = { lon: parseFloat(coords[0]), lat: parseFloat(coords[1]) };
            } else {
                for (let r = 0; r < numRefs; r++) {
                    if (i >= lines.length) break;
                    const parts = lines[i++].split(',');
                    const polIndex = parseInt(parts[0]);
                    const flag     = parts.length > 1 ? parseInt(parts[1]) : 0;
                    polyRefs.push({ polIndex, flag });
                }
            }

            entries.push({ entryIndex, areaType, dateRanges, polyRefs, dotPoint });
        }
        return entries;
    }

    // Parse "date_from  ,  date_to" → { from: number, to: number }
    _parseDateRange(line) {
        const parts = line.split(',');
        return {
            from: parseFloat(parts[0]),
            to:   parts.length > 1 ? parseFloat(parts[1]) : 9999
        };
    }
}
