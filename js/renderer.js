// renderer.js — MapRenderer
// Draws the full map onto a canvas context for a given year and projection.
//
// Key architectural insight (from VB source):
//   All polyRefs for ONE PAR entry are concatenated into a SINGLE combined polygon,
//   then filled once. The refs work as follows:
//
//   flag = 0           → append polygon segment FORWARD  (CST or POL)
//   flag = 1           → append polygon segment REVERSED (connects from opposite end)
//   |flag| > 1         → insert explicit connector POINT at (lon=polIndex, lat=flag)
//   flag = 1000        → connector point with lat=0  (equator special-case)
//   polIndex <= 1000   → CST polygon at that index
//   polIndex >  1000   → POL polygon at (polIndex - 1000)
//
// The combined polygon traces the country outline by chaining coastal and border
// segments in alternating directions, with tile-corner points to close the shape.
//
// Draw order per tile (matches VB — no separate land fill):
//   1. Water background  (once, before tile loop)
//   2. Political fill    (PAR combined polygons → country colors)
//   3. Coastline stroke  (CST points → open polyline, no closing line)
//
// VB draws coastlines as individual DrawLine(k-1, k) calls — an open polyline.
// It does NOT fill CST polygons separately; the PAR political fills cover all land.

const WATER_COLOR  = '#5ba3d9';
const RIVER_COLOR  = '#4a90d9';
const COAST_COLOR  = '#5a4020';
const BORDER_COLOR = '#3a2010';

// Polygons whose matched date range starts before this year are content-creation
// sentinel entries (e.g. -9997 "show all" mode) and are excluded from display.
const SENTINEL_FROM = -2500;

// Line widths scale with the projection so strokes remain visible at any zoom level.
// At world zoom (degX≈360) lines are ~2px; at street zoom (degX≈1) they are ~0.5px.
function _lineWidth(projection, base) {
    return Math.max(0.5, Math.min(base * 3, base * projection.degX / 30));
}

class MapRenderer {
    constructor(dataLoader, tileManager, colorLookup) {
        this._loader  = dataLoader;
        this._tiles   = tileManager;
        this._colors  = colorLookup;
    }

    // Renders onto ctx for the given MapProjection and year.
    // showCoasts: draw coastline strokes (disable for overview renders)
    // onTileDrawn(done, total): progress callback (optional)
    // Tiles are loaded and painted in batches so the map fills in progressively.
    async render(ctx, projection, year, showBorders, showDots, onTileDrawn, showCoasts = true, showCities = false, showCityNames = false, cityDetail = 10, showInlandWaters = false, showRivers = false) {
        const { width: W, height: H } = ctx.canvas;

        // Water background
        ctx.fillStyle = WATER_COLOR;
        ctx.fillRect(0, 0, W, H);

        const tileDescs = this._tiles.getTiles(projection);
        const total = tileDescs.length;

        // Load and render in batches of 24 so the map paints progressively.
        // allCities accumulates city arrays for label placement.
        // allRivPolys accumulates river segments for cross-tile chain merging.
        const BATCH = 24;
        const allCities   = [];
        const allRivPolys = [];
        for (let start = 0; start < total; start += BATCH) {
            const batch = tileDescs.slice(start, start + BATCH);
            const loaded = await Promise.all(batch.map(t => this._loader.loadTile(t)));
            for (let j = 0; j < batch.length; j++) {
                const { cst, pol, par, cities, iwa, niw, riv } = loaded[j];
                this._drawPoliticalFill(ctx, projection, cst, pol, par, year, showDots);
                if (showInlandWaters) this._drawInlandWaters(ctx, projection, iwa, niw, year);
                if (showCoasts)       this._drawCoastOutlines(ctx, projection, cst, year);
                if (showBorders)      this._drawBorders(ctx, projection, pol, year);
                if (showRivers)       for (const p of riv) allRivPolys.push(p);
                if (showDots)    this._drawDots(ctx, projection, par, year);
                if (showCities) {
                    this._drawCities(ctx, projection, cities, year, cityDetail);
                    if (showCityNames) allCities.push(cities);
                }
            }
            if (onTileDrawn) onTileDrawn(start + batch.length, total);
            await new Promise(r => setTimeout(r, 0));
        }

        // Second pass: greedy label placement after all dots are drawn
        if (showCities && showCityNames) {
            this._placeAndDrawCityLabels(ctx, projection, allCities, year, cityDetail);
        }

        // River pass: draw after all tiles loaded so cross-tile segments can be chained
        if (showRivers) {
            this._drawRiversConnected(ctx, projection, allRivPolys);
        }
    }

    // ── Political fill ─────────────────────────────────────────────────────────

    _drawPoliticalFill(ctx, projection, cst, pol, par, year, showDots) {
        if (!par.length) return;

        // Index polygons by polyIndex for O(1) lookup
        const cstByIndex = new Map();
        for (const p of cst) cstByIndex.set(p.polyIndex, p);
        const polByIndex = new Map();
        for (const p of pol) polByIndex.set(p.polyIndex, p);

        for (const entry of par) {
            // areaType=0 → only shown when ShowDots enabled.
            // Coord-dot entries (dotPoint set) are drawn separately by _drawDots; skip them here.
            // Poly-ref areaType=0 entries are drawn as fills when showDots is on.
            if (entry.areaType === 0 && (!showDots || entry.dotPoint)) continue;

            const dateMatch = matchDate(entry.dateRanges, year);
            if (!dateMatch) continue;

            const fillColor = this._colors.toCss(dateMatch, null, null);
            if (!fillColor) continue;   // UNKNOWN area → no fill

            // Build one combined polygon from all refs
            const { points: combined, hasSegment } = this._buildCombinedPolygon(
                entry.polyRefs, cstByIndex, polByIndex
            );

            if (combined.length < 3) continue;

            const path = this._buildPath(projection, combined);
            if (path) {
                ctx.fillStyle   = fillColor;
                ctx.fill(path, 'evenodd');   // GDI+ FillPolygon default = Alternate = evenodd
                // Cover the ~0.5px anti-aliasing seam at tile-boundary connector edges.
                // Canvas 2D AA leaves a thin gap where adjacent tile fills meet exactly;
                // stroking with the same fill color closes it. Coast/border strokes drawn
                // later will cover this thin edge on actual country boundaries.
                ctx.strokeStyle = fillColor;
                ctx.lineWidth   = 2;
                ctx.stroke(path);
            }
        }
    }

    // Concatenates all polyRefs for one PAR entry into a single point array.
    //
    // PAR ref index convention (from VB source):
    //   polIndex <= 1000  → CST polygon at index polIndex
    //   polIndex >  1000  → POL polygon at index (polIndex - 1000)
    _buildCombinedPolygon(polyRefs, cstByIndex, polByIndex) {
        const combined = [];
        let hasSegment = false;  // true if any real CST/POL segment was appended

        for (const { polIndex, flag } of polyRefs) {

            if (flag === 0 || flag === 1) {
                // ── Polygon segment (forward or reversed) ───────────────────
                let poly;
                if (polIndex <= 1000) {
                    // CST polygon
                    poly = cstByIndex.get(polIndex);
                } else {
                    // POL polygon — VB never checks POL date ranges when assembling
                    // combined polygons; the PAR entry itself is the only date gate.
                    poly = polByIndex.get(polIndex - 1000);
                }
                if (!poly || poly.points.length === 0) continue;

                hasSegment = true;
                const pts = poly.points;
                if (flag === 0) {
                    for (const pt of pts) combined.push(pt);
                } else {
                    for (let k = pts.length - 1; k >= 0; k--) combined.push(pts[k]);
                }

            } else {
                // ── Explicit connector point: (lon=polIndex, lat=flag) ───────
                let lat = flag;
                if (lat === 1000) lat = 0;   // equator special-case
                combined.push({ lon: polIndex, lat });
            }
        }

        // Close if not already closed
        if (combined.length > 1) {
            const f = combined[0], l = combined[combined.length - 1];
            if (f.lon !== l.lon || f.lat !== l.lat) combined.push(f);
        }

        return { points: combined, hasSegment };
    }

    // ── Coastline outlines ─────────────────────────────────────────────────────

    // VB checks each CST polygon's date range (intPlotTime) before drawing.
    // Polygons outside the current year are silently skipped.
    _drawCoastOutlines(ctx, projection, cst, year) {
        ctx.strokeStyle = COAST_COLOR;
        ctx.lineWidth   = _lineWidth(projection, 0.8);
        for (const poly of cst) {
            if (!matchDate(poly.dateRanges, year)) continue;
            const path = this._buildPath(projection, poly.points, false);  // open path — don't close tile-edge gap
            if (path) ctx.stroke(path);
        }
    }

    // ── Political borders ──────────────────────────────────────────────────────

    // Draws POL polygon segments as open polylines — same approach as coastlines.
    // No tile-crossing connections; each polygon is drawn independently within its tile.
    _drawBorders(ctx, projection, pol, year) {
        ctx.strokeStyle = BORDER_COLOR;
        ctx.lineWidth   = _lineWidth(projection, 0.7);
        for (const poly of pol) {
            const m = matchDate(poly.dateRanges, year);
            if (!m || m.from < SENTINEL_FROM) continue;
            const path = this._buildPath(projection, poly.points, false);  // open — no tile-edge closing line
            if (path) ctx.stroke(path);
        }
    }

    // ── Dots ───────────────────────────────────────────────────────────────────

    _drawDots(ctx, projection, par, year) {
        for (const entry of par) {
            if (!entry.dotPoint) continue;
            const dateMatch = matchDate(entry.dateRanges, year);
            if (!dateMatch) continue;
            const fillColor = this._colors.toCss(dateMatch, null, null);
            if (!fillColor) continue;
            const { x, y } = projection.geoToPixel(entry.dotPoint.lon, entry.dotPoint.lat);
            // Radius in pixels = half the degree-diameter × pixels-per-degree
            const radiusPx = Math.max(2, (entry.dotDiameter / 2) * projection.xScale);
            ctx.beginPath();
            ctx.arc(x, y, radiusPx, 0, Math.PI * 2);
            ctx.fillStyle = fillColor;
            ctx.fill();
        }
    }

    // ── Rivers ─────────────────────────────────────────────────────────────────

    // Draws rivers after all tiles are loaded, chaining adjacent tile segments
    // into single continuous paths.  Adjacent polys share their boundary
    // endpoint exactly (end of A == start of B); merging them into one path
    // eliminates per-segment stroke endpoints at tile boundaries.
    //
    // The key subtlety: polys are in file order, so a poly that STARTS at a
    // tile boundary may appear before the poly that ENDS there.  Processing it
    // first would start a new stroke right at the boundary.  We therefore
    // identify "chain heads" — polys whose start point is not the end point of
    // any other loaded poly — and only begin chains from those.  Polys that
    // have a predecessor are reached later when their predecessor is processed.
    _drawRiversConnected(ctx, projection, allPolys) {
        if (!allPolys.length) return;

        // startMap: first-point key → list of poly indices
        const startMap = new Map();
        for (let i = 0; i < allPolys.length; i++) {
            const pts = allPolys[i].points;
            if (!pts.length) continue;
            const key = `${pts[0].lon.toFixed(4)},${pts[0].lat.toFixed(4)}`;
            if (!startMap.has(key)) startMap.set(key, []);
            startMap.get(key).push(i);
        }

        // hasPredecessor: poly indices whose first point is the END of some other poly.
        // These are continuations — they must not start a new chain on their own.
        const hasPredecessor = new Set();
        for (let i = 0; i < allPolys.length; i++) {
            const pts = allPolys[i].points;
            if (!pts.length) continue;
            const last   = pts[pts.length - 1];
            const endKey = `${last.lon.toFixed(4)},${last.lat.toFixed(4)}`;
            for (const j of (startMap.get(endKey) || [])) hasPredecessor.add(j);
        }

        const visited = new Set();
        ctx.strokeStyle = RIVER_COLOR;
        ctx.lineWidth   = _lineWidth(projection, 0.5);

        const drawChain = (startIdx) => {
            visited.add(startIdx);
            let currentPts = allPolys[startIdx].points;
            // If the first point is at exact integer-degree coordinates it is a tile
            // boundary split point — real river points are never exactly integer degrees.
            // Skipping it removes stroke endpoint artifacts at tributary-split boundaries.
            const fp = currentPts[0];
            const firstIsIntCoord = (fp.lon === Math.round(fp.lon) || fp.lat === Math.round(fp.lat));
            const chainPts = (firstIsIntCoord && currentPts.length > 1)
                ? currentPts.slice(1)
                : [...currentPts];
            while (true) {
                const last   = currentPts[currentPts.length - 1];
                const endKey = `${last.lon.toFixed(4)},${last.lat.toFixed(4)}`;
                const nexts  = startMap.get(endKey) || [];
                const nextIdx = nexts.find(j => !visited.has(j));
                if (nextIdx === undefined) break;
                visited.add(nextIdx);
                currentPts = allPolys[nextIdx].points;
                // Skip index 0 — shared boundary point already at end of chainPts
                for (let k = 1; k < currentPts.length; k++) chainPts.push(currentPts[k]);
            }
            const path = this._buildPath(projection, chainPts, false);
            if (path) ctx.stroke(path);
        };

        // First pass: true global chain heads (no predecessor among any loaded poly)
        for (let i = 0; i < allPolys.length; i++) {
            if (!visited.has(i) && !hasPredecessor.has(i)) drawChain(i);
        }

        // Second pass: handle orphan clusters (chains whose global head is outside the
        // loaded tile set).  Naïvely iterating in array order would start chains at
        // interior boundary points — so reapply the hasPredecessor logic restricted to
        // the unvisited subset to find the local head of each orphan cluster.
        if (visited.size < allPolys.length) {
            // Collect end-keys of every still-unvisited poly
            const orphanEndKeys = new Set();
            for (let i = 0; i < allPolys.length; i++) {
                if (visited.has(i)) continue;
                const pts = allPolys[i].points;
                if (!pts.length) continue;
                const last = pts[pts.length - 1];
                orphanEndKeys.add(`${last.lon.toFixed(4)},${last.lat.toFixed(4)}`);
            }
            // Draw from orphan polys whose start is not any orphan's end (local heads)
            for (let i = 0; i < allPolys.length; i++) {
                if (visited.has(i)) continue;
                const pts = allPolys[i].points;
                if (!pts.length) continue;
                const firstKey = `${pts[0].lon.toFixed(4)},${pts[0].lat.toFixed(4)}`;
                if (!orphanEndKeys.has(firstKey)) drawChain(i);
            }
            // Final pass: cycles and anything still unreached
            for (let i = 0; i < allPolys.length; i++) {
                if (!visited.has(i)) drawChain(i);
            }
        }
    }

    // ── Inland waters ──────────────────────────────────────────────────────────

    // Draws inland water bodies from IWA tile data.
    //
    // Each IWA group represents one water body (lake, etc.).  The first ring is
    // the outer boundary; rings 2+ are islands inside the lake.
    //
    // Step 1: fill the entire group as a single evenodd path with WATER_COLOR.
    //         The outer area gets water-blue; island rings become transparent
    //         holes that show the PAR political fills painted beneath them.
    //
    // Step 2: for each NIW entry whose date range matches the current year, fill
    //         the referenced island ring with the country color.  This re-colors
    //         any island whose affiliation changes over time.
    //         NIW entries with name "UNKNOWN" are skipped — the hole already
    //         shows the correct PAR fill.
    _drawInlandWaters(ctx, projection, iwa, niw, year) {
        if (!iwa || !iwa.length) return;

        // Step 1 — water body fills (evenodd so islands are holes)
        ctx.fillStyle = WATER_COLOR;
        for (const group of iwa) {
            if (!group.rings.length) continue;
            const path = new Path2D();
            for (const ring of group.rings) {
                if (ring.points.length < 3) continue;
                let first = true;
                for (const pt of ring.points) {
                    const { x, y } = projection.geoToPixel(pt.lon, pt.lat);
                    if (first) { path.moveTo(x, y); first = false; }
                    else        path.lineTo(x, y);
                }
                path.closePath();
            }
            ctx.fill(path, 'evenodd');
        }

        // Step 2 — island re-fills from NIW (time-dependent country coloring)
        if (!niw || !niw.length) return;
        for (const entry of niw) {
            const match = matchDate(entry.dateRanges, year);
            if (!match) continue;
            const fillColor = this._colors.toCss(match, null, null);
            if (!fillColor) continue;   // UNKNOWN → leave as hole

            for (const { groupIndex, ringIndex } of entry.refs) {
                const group = iwa[groupIndex - 1];  // groupIndex is 1-based
                if (!group) continue;
                const ring = group.rings.find(r => r.ringIndex === ringIndex);
                if (!ring || ring.points.length < 3) continue;
                const path = this._buildPath(projection, ring.points);
                if (path) {
                    ctx.fillStyle = fillColor;
                    ctx.fill(path, 'evenodd');
                }
            }
        }
    }

    // ── Cities ─────────────────────────────────────────────────────────────────

    // Draws city symbols from CIT tile data.
    //
    // symCode >= 0: filled decagon(s)
    //   symCode = 0  → trefoil: 3 small dots (r=0.01°) arranged in triangle, offset 0.02° from centre
    //   symCode > 0  → single dot, r = (symCode+1)*0.01°
    // symCode < 0: X mark, arm length = 0.05*|symCode| degrees
    //
    // Color = offsets[colorIndex] directly (VB uses offset RGB as city color, no primaries base).
    // Minimum radius of 2px applied so cities are always visible at world zoom.
    _drawCities(ctx, projection, cities, year, cityDetail = 10) {
        if (!cities || !cities.length) return;
        const BASE_DEG = 0.01;
        const scale    = projection.xScale;

        for (const city of cities) {
            const match = matchDate(city.dateRanges, year);
            if (!match || match.detCode <= 0 || match.detCode > cityDetail) continue;

            const color   = this._colors.cityColor(match.colorIndex);
            const symCode = match.symCode;
            const { x: cx, y: cy } = projection.geoToPixel(city.lon, city.lat);

            if (symCode >= 0) {
                const r      = Math.max(2, (symCode !== 0 ? (Math.abs(symCode) + 1) * BASE_DEG : BASE_DEG) * scale);
                const ndots  = symCode === 0 ? 3 : 1;
                const offset = 2 * BASE_DEG * scale;
                ctx.fillStyle = color;
                for (let j = 0; j < ndots; j++) {
                    const angle = (j * 2 * Math.PI / ndots) - Math.PI / 6;
                    const dx = ndots > 1 ? offset * Math.cos(angle) : 0;
                    const dy = ndots > 1 ? offset * Math.sin(angle) : 0;
                    ctx.beginPath();
                    ctx.arc(cx + dx, cy + dy, r, 0, Math.PI * 2);
                    ctx.fill();
                }
            } else {
                const arm = Math.max(3, 0.05 * Math.abs(symCode) * scale) / Math.SQRT2;
                ctx.strokeStyle = color;
                ctx.lineWidth   = 1;
                ctx.beginPath(); ctx.moveTo(cx - arm, cy - arm); ctx.lineTo(cx + arm, cy + arm); ctx.stroke();
                ctx.beginPath(); ctx.moveTo(cx + arm, cy - arm); ctx.lineTo(cx - arm, cy + arm); ctx.stroke();
            }
        }
    }

    // Greedy label placement: collect all visible cities, sort larger symbols first,
    // try 8 candidate positions per city and pick the first non-overlapping one.
    _placeAndDrawCityLabels(ctx, projection, allCities, year, cityDetail = 10) {
        const BASE_DEG = 0.01;
        const scale    = projection.xScale;
        const W = ctx.canvas.width;
        const H = ctx.canvas.height;
        const LINE_H = 12;  // effective height for 10px font

        // Collect all matching cities with pixel coords and symbol radius
        const entries = [];
        for (const cities of allCities) {
            for (const city of cities) {
                const match = matchDate(city.dateRanges, year);
                if (!match || match.detCode <= 0 || match.detCode > cityDetail) continue;
                const { x: cx, y: cy } = projection.geoToPixel(city.lon, city.lat);
                if (cx <= 0 || cx >= W || cy <= 0 || cy >= H) continue;

                const symCode = match.symCode;
                let symbolRadius;
                if (symCode >= 0) {
                    const r      = Math.max(2, (symCode !== 0 ? (Math.abs(symCode) + 1) * BASE_DEG : BASE_DEG) * scale);
                    const offset = 2 * BASE_DEG * scale;
                    symbolRadius = r + (symCode === 0 ? offset : 0);
                } else {
                    symbolRadius = Math.max(3, 0.05 * Math.abs(symCode) * scale) / Math.SQRT2;
                }
                entries.push({ cx, cy, name: match.name, symbolRadius, symCode, detCode: match.detCode });
            }
        }

        // Lower detCode = more important → label first; symCode as tiebreaker
        entries.sort((a, b) => a.detCode - b.detCode || Math.abs(b.symCode) - Math.abs(a.symCode));

        ctx.font         = '10px Arial, sans-serif';
        ctx.textBaseline = 'alphabetic';

        const placed = [];  // bounding boxes of successfully placed labels

        const overlaps = r => placed.some(p =>
            r.x < p.x + p.w && r.x + r.w > p.x &&
            r.y < p.y + p.h && r.y + r.h > p.y
        );

        for (const { cx, cy, name, symbolRadius } of entries) {
            const w   = ctx.measureText(name).width;
            const h   = LINE_H;
            const gap = symbolRadius + 3;
            const d   = gap * 0.707;  // diagonal offset component (cos/sin 45°)

            // 8 candidates: NE first (matches VB default), then around the clock
            const candidates = [
                { lx: cx + d,         ly: cy - d         },  // NE
                { lx: cx + gap,       ly: cy + h * 0.35  },  // E  (vertically centred)
                { lx: cx - w / 2,     ly: cy - gap       },  // N  (horizontally centred)
                { lx: cx + d,         ly: cy + d + h     },  // SE
                { lx: cx - d - w,     ly: cy - d         },  // NW
                { lx: cx - gap - w,   ly: cy + h * 0.35  },  // W
                { lx: cx - w / 2,     ly: cy + gap + h   },  // S
                { lx: cx - d - w,     ly: cy + d + h     },  // SW
            ];

            for (const { lx, ly } of candidates) {
                const rect = { x: lx - 1, y: ly - h, w: w + 2, h: h + 2 };
                if (!overlaps(rect)) {
                    placed.push(rect);
                    ctx.lineWidth   = 2.5;
                    ctx.strokeStyle = 'rgba(255,255,255,0.75)';
                    ctx.strokeText(name, lx, ly);
                    ctx.fillStyle   = '#000000';
                    ctx.fillText(name, lx, ly);
                    break;
                }
            }
        }
    }

    // ── Path builder ───────────────────────────────────────────────────────────

    // Converts geo points to pixel path.
    // No clamping: let the canvas clip naturally. Clamping to [0,W]×[0,H] causes
    // connector points far outside the viewport (e.g. lon=-20 when viewing Greece)
    // to all collapse onto the canvas edge, dragging polygon edges across the map.
    //
    // close=true  → call closePath() (political fill)
    // close=false → leave path open (coastline/border stroke — CST/POL are open segments;
    //               closePath() would draw a spurious straight line across water)
    _buildPath(projection, points, close = true) {
        if (!points || points.length < 2) return null;
        const path = new Path2D();
        let first = true;
        for (const pt of points) {
            const { x, y } = projection.geoToPixel(pt.lon, pt.lat);
            if (first) { path.moveTo(x, y); first = false; }
            else        { path.lineTo(x, y); }
        }
        if (close) path.closePath();
        return path;
    }
}
