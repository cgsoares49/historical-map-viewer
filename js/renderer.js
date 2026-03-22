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
const COAST_COLOR  = '#5a4020';
const COAST_WIDTH  = 0.8;
const BORDER_COLOR = '#3a2010';
const BORDER_WIDTH = 0.7;

class MapRenderer {
    constructor(dataLoader, tileManager, colorLookup) {
        this._loader  = dataLoader;
        this._tiles   = tileManager;
        this._colors  = colorLookup;
    }

    // Renders onto ctx for the given MapProjection and year.
    // onTileDrawn(done, total) called as tiles complete (optional).
    async render(ctx, projection, year, showBorders, showDots, onTileDrawn) {
        const { width: W, height: H } = ctx.canvas;

        // Water background
        ctx.fillStyle = WATER_COLOR;
        ctx.fillRect(0, 0, W, H);

        const tileDescs = this._tiles.getTiles(projection);
        const total = tileDescs.length;

        // Load all tiles in parallel for speed
        const loaded = await Promise.all(
            tileDescs.map(tile => this._loader.loadTile(tile))
        );

        for (let i = 0; i < tileDescs.length; i++) {
            const { cst, pol, par } = loaded[i];
            this._drawPoliticalFill(ctx, projection, cst, pol, par, year, showDots);
            this._drawCoastOutlines(ctx, projection, cst, year);
            if (showBorders) this._drawBorders(ctx, projection, pol, year);
            if (showDots) this._drawDots(ctx, projection, par, year);
            if (onTileDrawn) onTileDrawn(i + 1, total);
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
                ctx.fillStyle = fillColor;
                ctx.fill(path, 'evenodd');   // GDI+ FillPolygon default = Alternate = evenodd
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
        ctx.lineWidth   = COAST_WIDTH;
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
        ctx.lineWidth   = BORDER_WIDTH;
        for (const poly of pol) {
            if (!matchDate(poly.dateRanges, year)) continue;
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
            ctx.beginPath();
            ctx.arc(x, y, 4, 0, Math.PI * 2);
            ctx.fillStyle = fillColor;
            ctx.fill();
            ctx.strokeStyle = 'rgba(0,0,0,0.6)';
            ctx.lineWidth = 0.8;
            ctx.stroke();
        }
    }

    // ── Path builder ───────────────────────────────────────────────────────────

    // Converts geo points to pixel path.
    // Clamps every pixel coordinate to [0,W]×[0,H] exactly as VB does:
    //   intPixPoint.X = Int(scale*(lon-lon1)), clamped to [0, picMap.Width]
    //   intPixPoint.Y = Int(scale*(lat2-lat)), clamped to [0, picMap.Height]
    // This pins off-viewport segment endpoints to the canvas edge so the
    // polygon always closes cleanly along the boundary rather than making
    // large off-screen excursions that corrupt the evenodd fill.
    //
    // close=true  → call closePath() (land fill, political fill)
    // close=false → leave path open (coastline stroke — CST polys are open segments;
    //               closePath() would draw a spurious straight line across water)
    _buildPath(projection, points, close = true) {
        if (!points || points.length < 2) return null;
        const path = new Path2D();
        const W = projection.canvasWidth;
        const H = projection.canvasHeight;
        let first = true;
        for (const pt of points) {
            const raw = projection.geoToPixel(pt.lon, pt.lat);
            const x = Math.max(0, Math.min(W, Math.floor(raw.x)));
            const y = Math.max(0, Math.min(H, Math.floor(raw.y)));
            if (first) { path.moveTo(x, y); first = false; }
            else        { path.lineTo(x, y); }
        }
        if (close) path.closePath();
        return path;
    }
}
