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
const COAST_COLOR  = '#000000';
const BORDER_COLOR = '#000000';

// Polygons whose matched date range starts before this year are content-creation
// sentinel entries (e.g. -9997 "show all" mode) and are excluded from display.
const SENTINEL_FROM = -2500;

// ── "Friendly army" hatch fill ───────────────────────────────────────────────
// A transient army/path (e.g. an army marching over its own parent country's
// territory) is filled with only a slight color offset from its background,
// so it's often nearly invisible. Entries built entirely from transient-marked
// POL segments (see _isTransientEntry) get a diagonal-stripe overlay — mostly
// the entry's own real color, with sparse neutral stripes — but ONLY over the
// pixels where the color already rendered underneath (sampled right before
// this entry's own fill, since canvas draws are sequential onto one shared
// context) is close to this entry's own color. A single polygon can cross
// from near-identical-colored territory into differently-colored territory
// (or open water, whose color is never close to a political fill) within
// itself, so this is decided per pixel against the real render, not once per
// entry — see _overlayHatchWhereSimilar. First version (no similarity check,
// hatched unconditionally whenever an entry was transient) hatched water and
// unrelated territory indiscriminately; fixed 2026-08-09.
//
// Click-to-identify (colorNameMap, built from colorLookup.resolve — see
// mapper.html/mapper-local.html rebuildColorNameMap) only ever registers the
// solid base color. A click landing on a stripe pixel intentionally does NOT
// resolve directly; it falls through to the existing nearest-registered-color
// search (_findNearestLandEntry) already used for water clicks, which finds
// the base color a pixel or two away. Deliberately NOT registering the stripe
// color as a second key for the same entry: the stripe color is shared/fixed
// across every hatched entry for visual consistency, so multiple different
// armies visible at once would collide on that one key.
const HATCH_STRIPE_COLOR        = '#808080';
const HATCH_PERIOD_PX           = 4;    // stripe repeat spacing
const HATCH_MIN_BBOX_PX         = 8;    // below this on-screen size (narrower dimension), skip hatching entirely
const HATCH_COLOR_DIST_THRESHOLD = 40;  // max Euclidean RGB distance still counted as "nearly the same color"
                                         // (real offset-only pairs measured ~12-15; different entities / water are 100+)

// SAFETY SWITCH: keep this false in any build going through deploy.ps1/MAPPER
// until the fix above has been visually confirmed. Flip true only for builds
// pushed to CREATOR for testing. See project_friendly_army_problem memory.
const ENABLE_HATCH_FILL   = true;

// Log scale: 0 at world zoom (degX=360), grows slowly, never heavy at close zoom.
// t=0 at degX=360, t=1 at degX=1; lineWidth = base * t.
function _lineWidth(projection, base) {
    const t = Math.log(360 / projection.degX) / Math.log(360);
    return base * Math.max(0, t);
}

class MapRenderer {
    constructor(dataLoader, tileManager, colorLookup) {
        this._loader  = dataLoader;
        this._tiles   = tileManager;
        this._hatchStripeTile = null;  // lazily-built repeating stripe tile, see _getHatchStripeTile
        this._colors  = colorLookup;
    }

    // Renders onto ctx for the given MapProjection and year.
    // showCoasts: draw coastline strokes (disable for overview renders)
    // onTileDrawn(done, total): progress callback (optional)
    // Tiles are loaded and painted in batches so the map fills in progressively.
    async render(ctx, projection, year, showBorders, showDots, onTileDrawn, showCoasts = true, showCities = false, showCityNames = false, cityDetail = 10, showInlandWaters = false, showRivers = false, showCountryLabels = false, minPixels = 5000, cancelToken = null) {
        const { width: W, height: H } = ctx.canvas;

        // Water background
        ctx.fillStyle = WATER_COLOR;
        ctx.fillRect(0, 0, W, H);

        const tileDescs = this._tiles.getTiles(projection);
        const total = tileDescs.length;

        // Load and render in batches of 24 so the map paints progressively.
        // allCities / allRivPolys / allCountryEntries accumulate cross-tile data.
        const BATCH = 24;
        const allCities         = [];
        const allRivPolys       = [];
        const allCountryEntries = [];
        const allDotPars        = [];
        for (let start = 0; start < total; start += BATCH) {
            const batch = tileDescs.slice(start, start + BATCH);
            const loaded = await Promise.all(batch.map(t => this._loader.loadTile(t)));
            for (let j = 0; j < batch.length; j++) {
                const { cst, pol, par, cities, iwa, niw, riv } = loaded[j];
                this._drawPoliticalFill(ctx, projection, cst, pol, par, year, showDots);
                if (showInlandWaters)   this._drawInlandWaters(ctx, projection, iwa, niw, year);
                if (showCoasts)         this._drawCoastOutlines(ctx, projection, cst, year);
                if (showBorders)        this._drawBorders(ctx, projection, pol, year);
                if (showRivers)         for (const p of riv) allRivPolys.push(p);
                if (showDots && year >= -2400) { this._drawDots(ctx, projection, par, year); allDotPars.push({ par, cst, pol }); }
                if (showCities) {
                    this._drawCities(ctx, projection, cities, year, cityDetail);
                    allCities.push(cities);
                }
                if (showCountryLabels) {
                    const ld = this._collectTileLabelData(par, cst, pol, year);
                    for (const d of ld) allCountryEntries.push(d);
                }
            }
            if (onTileDrawn) onTileDrawn(start + batch.length, total);
            await new Promise(r => setTimeout(r, 0));
            if (cancelToken && cancelToken.cancelled) throw new DOMException('Render cancelled', 'AbortError');
        }

        // Dot label pass: one label per unique name, drawn after all dots
        if (showDots && year >= -2400) {
            this._drawDotLabels(ctx, projection, allDotPars, year);
        }

        // Second pass: greedy label placement after all dots are drawn.
        // Auto-show names when few enough cities are visible and none are crowded.
        const effectiveCityNames = showCityNames ||
            (showCities && this._autoCityNames(projection, allCities, year, cityDetail, W, H));
        if (showCities && effectiveCityNames) {
            this._placeAndDrawCityLabels(ctx, projection, allCities, year, cityDetail);
        }

        // River pass: draw after all tiles loaded so cross-tile segments can be chained
        if (showRivers) {
            this._drawRiversConnected(ctx, projection, allRivPolys);
        }

        // Country label pass: drawn last so labels appear on top of everything
        if (showCountryLabels) {
            this._placeAndDrawCountryLabels(ctx, projection, allCountryEntries, minPixels);
        }

        // Date box: upper-right corner, matching VB style
        this._drawDateBox(ctx, year);
        // Watermark: bottom-right corner
        this._drawWatermark(ctx);
    }

    // ── Date box ───────────────────────────────────────────────────────────────

    // Convert a (possibly fractional) year to a display string using VB-style month ranges.
    // Fractional part → two-month period (10 bi-monthly slots).
    // Integer years show no month suffix.
    _formatYear(year) {
        // No year 0 in the historical calendar.
        if (year === 0) year = -1;

        const absYear = Math.abs(year);
        const intYear = Math.floor(absYear);
        const frac    = absYear - intYear;

        if (year < 0) {
            // BCE: frac=0 → Nov-Dec (year-end), frac=0.9 → Jan-Feb (year-start)
            const MONTHS = [
                'Nov-Dec', 'Jan-Feb', 'Feb-Mar', 'Mar-Apr', 'Apr-May',
                'May-Jun', 'Jul-Aug', 'Aug-Sep', 'Sep-Oct', 'Oct-Nov',
            ];
            const corrFrac = frac > 0 ? 1 - frac : 0;
            const idx      = Math.min(9, Math.round(corrFrac * 10));
            return `${intYear} ${MONTHS[idx]} BCE`;
        } else {
            // CE: frac=0 → Jan-Feb (year-start), frac=0.9 → Nov-Dec (year-end)
            const MONTHS = [
                'Jan-Feb', 'Feb-Mar', 'Mar-Apr', 'Apr-May', 'May-Jun',
                'Jul-Aug', 'Aug-Sep', 'Sep-Oct', 'Oct-Nov', 'Nov-Dec',
            ];
            const idx = Math.min(9, Math.round(frac * 10));
            return `${intYear} ${MONTHS[idx]} CE`;
        }
    }

    _drawDateBox(ctx, year) {
        const label = this._formatYear(year);

        ctx.save();
        ctx.font = 'bold 14px Arial';
        const textW  = ctx.measureText(label).width;
        const padX   = 10;
        const padY   = 8;
        const boxW   = textW + padX * 2;
        const boxH   = 14 + padY * 2;   // font size + padding
        const margin = 8;
        const x = ctx.canvas.width  - boxW - margin;
        const y = margin;

        // White fill
        ctx.fillStyle = 'white';
        ctx.fillRect(x, y, boxW, boxH);

        // Black border (3px, matching VB)
        ctx.strokeStyle = 'black';
        ctx.lineWidth   = 3;
        ctx.strokeRect(x, y, boxW, boxH);

        // Text
        ctx.fillStyle   = 'black';
        ctx.textBaseline = 'top';
        ctx.fillText(label, x + padX, y + padY);
        ctx.restore();
    }

    _drawWatermark(ctx) {
        const now    = new Date();
        const label  = `Soares Ancient History Mapping  ${now.toLocaleDateString()}`;
        const margin = 6;
        ctx.save();
        ctx.font         = '11px Arial';
        ctx.fillStyle    = 'black';
        ctx.textBaseline = 'bottom';
        ctx.textAlign    = 'right';
        ctx.fillText(label, ctx.canvas.width - margin, ctx.canvas.height - margin);
        ctx.restore();
    }

    // ── Political fill ─────────────────────────────────────────────────────────

    _drawPoliticalFill(ctx, projection, cst, pol, par, year, showDots) {
        if (!par.length) return;

        // Index polygons by polyIndex for O(1) lookup
        const cstByIndex = new Map();
        for (const p of cst) cstByIndex.set(p.polyIndex, p);
        const polByIndex = new Map();
        for (const p of pol) polByIndex.set(p.polyIndex, p);

        // Resolve every drawable entry once up front (path, color, transient-ness),
        // splitting real territory from transients — see the three-pass draw order
        // below for why this can't just be one loop in PAR-array order.
        const prepared = [];
        for (const entry of par) {
            // areaType=0 → only shown when ShowDots enabled.
            // Coord-dot entries (dotPoint set) are drawn separately by _drawDots; skip them here.
            // Poly-ref areaType=0 entries are drawn as fills when showDots is on.
            if (entry.areaType === 0 && (!showDots || entry.dotPoint)) continue;

            const dateMatch = matchDate(entry.dateRanges, year);
            if (!dateMatch) continue;

            const fillColor = this._colors.toCss(dateMatch, null, null);
            if (!fillColor) continue;   // UNKNOWN area → no fill

            const { points: combined } = this._buildCombinedPolygon(entry.polyRefs, cstByIndex, polByIndex);
            if (combined.length < 3) continue;

            const path = this._buildPath(projection, combined);
            if (!path) continue;

            const isTransient = ENABLE_HATCH_FILL && this._isTransientEntry(entry.polyRefs, polByIndex);
            prepared.push({ dateMatch, fillColor, combined, path, isTransient });
        }

        const drawSolid = (p) => {
            ctx.fillStyle   = p.fillColor;
            ctx.fill(p.path, 'evenodd');   // GDI+ FillPolygon default = Alternate = evenodd
            // Cover the ~0.5px anti-aliasing seam at tile-boundary connector edges.
            // Canvas 2D AA leaves a thin gap where adjacent tile fills meet exactly;
            // stroking with the same fill color closes it. Coast/border strokes drawn
            // later will cover this thin edge on actual country boundaries.
            ctx.strokeStyle = p.fillColor;
            ctx.lineWidth   = 1;
            ctx.stroke(p.path);
        };

        // Pass 1: all REAL (non-transient) territory — establishes the true base
        // that transients get compared against.
        for (const p of prepared) if (!p.isTransient) drawSolid(p);

        // Pass 2: snapshot every transient's "underneath" BEFORE any transient is
        // drawn. If two transients overlap (e.g. two armies crossing paths at
        // Messana), each must be judged against the same real base territory
        // captured here — not against whichever one happened to paint first,
        // which is what caused overlapping transients to hatch against EACH
        // OTHER'S color instead of the actual (often unfriendly / very
        // different) territory underneath both (reported 2026-08-10).
        for (const p of prepared) {
            if (!p.isTransient) continue;
            const bbox = this._pixelBBox(projection, p.combined);
            if (Math.min(bbox.w, bbox.h) < HATCH_MIN_BBOX_PX) continue;
            const rgb = this._colors.resolve(p.dateMatch);
            const under = rgb && this._readUnderlying(ctx, bbox);
            if (under) p.hatchCandidate = { bbox, rgb, under };
        }

        // Pass 3: draw every transient (solid fill always; masked hatch overlay
        // only where pass 2's frozen snapshot was close enough in color).
        for (const p of prepared) {
            if (!p.isTransient) continue;
            drawSolid(p);
            if (p.hatchCandidate) this._overlayHatchWhereSimilar(ctx, p.path, p.hatchCandidate);
        }
    }

    // A transient path/army's own POL segments are marked with a single
    // date range of exactly (-9999.0, -9998.0) — the content-creation
    // "reusable template" convention (see the transients-index tooling in
    // mapper/tools/). VB never date-gates POL when assembling combined
    // polygons, so these entries are present in polByIndex at every year;
    // only their dateRanges marker identifies them. An entry built purely
    // from CST refs (polIndex <= 1000, real coastline, never transient)
    // returns false.
    _isTransientEntry(polyRefs, polByIndex) {
        let sawPol = false;
        for (const { polIndex } of polyRefs) {
            if (polIndex <= 1000) continue;
            sawPol = true;
            const poly = polByIndex.get(polIndex - 1000);
            if (!poly) return false;
            const dr = poly.dateRanges;
            if (!(dr.length === 1 && dr[0].from === -9999.0 && dr[0].to === -9998.0)) return false;
        }
        return sawPol;
    }

    // Pixel-space bounding box (including top-left corner) of a combined
    // polygon at the current projection — used both to size-gate hatching
    // (HATCH_MIN_BBOX_PX) and to know where to read/write the underlying-color
    // sample.
    _pixelBBox(projection, geoPoints) {
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        for (const pt of geoPoints) {
            const { x, y } = projection.geoToPixel(pt.lon, pt.lat);
            if (x < minX) minX = x; if (x > maxX) maxX = x;
            if (y < minY) minY = y; if (y > maxY) maxY = y;
        }
        const x0 = Math.floor(minX), y0 = Math.floor(minY);
        return { x0, y0, w: Math.ceil(maxX) - x0, h: Math.ceil(maxY) - y0 };
    }

    // Snapshot of whatever's already painted on the canvas within bbox, taken
    // BEFORE this entry's own fill is drawn — this is the real "what's under
    // this transient polygon right here" the hatch decision compares against.
    _readUnderlying(ctx, bbox) {
        try {
            return ctx.getImageData(bbox.x0, bbox.y0, bbox.w, bbox.h);
        } catch {
            return null;   // e.g. bbox partly off-canvas
        }
    }

    // A repeating diagonal-stripe tile, HATCH_STRIPE_COLOR on transparent —
    // used as the overlay source (masked per pixel below), not drawn directly.
    _getHatchStripeTile() {
        if (this._hatchStripeTile) return this._hatchStripeTile;
        const p = HATCH_PERIOD_PX;
        const tile = document.createElement('canvas');
        tile.width = p; tile.height = p;
        const tctx = tile.getContext('2d');
        tctx.strokeStyle = HATCH_STRIPE_COLOR;
        tctx.lineWidth   = 1;
        tctx.beginPath();
        // A single diagonal touching both corners tiles seamlessly when repeated.
        tctx.moveTo(0, p);
        tctx.lineTo(p, 0);
        tctx.stroke();
        this._hatchStripeTile = tile;
        return tile;
    }

    // Draws the diagonal-stripe overlay on top of an already-solid-filled
    // transient entry, but ONLY over the pixels where the underlying color
    // (sampled before the fill, in candidate.under) is close to the entry's
    // own color (candidate.rgb) — i.e. only where the "friendly army problem"
    // actually applies right here. Elsewhere within the same polygon (crossing
    // into differently-colored territory, or — though it's already excluded by
    // the same color-distance test, since water's color is never close to a
    // political fill — open water) the solid fill drawn just before this call
    // is left untouched.
    _overlayHatchWhereSimilar(ctx, path, candidate) {
        const { bbox, rgb, under } = candidate;
        const stripeTile = this._getHatchStripeTile();

        const overlay = document.createElement('canvas');
        overlay.width = bbox.w; overlay.height = bbox.h;
        const octx = overlay.getContext('2d');
        // Pattern phase is local to this entry's own bbox corner (not aligned to
        // the main canvas's global coordinate space) — a minor cosmetic
        // simplification; stripes are internally consistent within one polygon,
        // just not necessarily phase-matched to an adjacent different entry's.
        octx.fillStyle = ctx.createPattern(stripeTile, 'repeat');
        octx.fillRect(0, 0, bbox.w, bbox.h);

        const overlayData = octx.getImageData(0, 0, bbox.w, bbox.h);
        const od = overlayData.data, ud = under.data;
        const thresh2 = HATCH_COLOR_DIST_THRESHOLD * HATCH_COLOR_DIST_THRESHOLD;
        for (let i = 0; i < od.length; i += 4) {
            if (od[i + 3] === 0) continue;   // already-transparent gap between stripes
            const dr = ud[i] - rgb.r, dg = ud[i + 1] - rgb.g, db = ud[i + 2] - rgb.b;
            if (dr * dr + dg * dg + db * db > thresh2) od[i + 3] = 0;
        }
        octx.putImageData(overlayData, 0, 0);

        ctx.save();
        ctx.clip(path);
        ctx.drawImage(overlay, bbox.x0, bbox.y0);
        ctx.restore();
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
            if (!m) continue;
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
            // Radius scales with zoom; skip dots that would be sub-pixel at current zoom
            const radiusPx = (entry.dotDiameter / 2) * projection.xScale;
            if (radiusPx < 0.5) continue;
            ctx.beginPath();
            ctx.arc(x, y, radiusPx, 0, Math.PI * 2);
            ctx.fillStyle = fillColor;
            ctx.fill();
        }
    }

    // ── Dot labels ─────────────────────────────────────────────────────────────
    // One label per unique dot name, placed to the right of one representative dot.

    _drawDotLabels(ctx, projection, allDotPars, year) {
        const W = ctx.canvas.width, H = ctx.canvas.height;
        // Collect first visible dot pixel position per unique name.
        const seen = new Map();   // name → {x, y, r}

        for (const { par, cst, pol } of allDotPars) {
            // Build polygon indexes for classic dot centroid computation
            const cstByIndex = new Map();
            for (const p of cst) cstByIndex.set(p.polyIndex, p);
            const polByIndex = new Map();
            for (const p of pol) polByIndex.set(p.polyIndex, p);

            for (const entry of par) {
                const dateMatch = matchDate(entry.dateRanges, year);
                if (!dateMatch || !dateMatch.name) continue;
                if (seen.has(dateMatch.name)) continue;

                let x, y, r;

                if (entry.dotPoint) {
                    // Coordinate dot — position from file
                    const px = projection.geoToPixel(entry.dotPoint.lon, entry.dotPoint.lat);
                    x = px.x; y = px.y;
                    r = (entry.dotDiameter / 2) * projection.xScale;
                    if (r < 0.5) continue;
                } else if (entry.areaType === 0 && entry.polyRefs && entry.polyRefs.length) {
                    // Classic polygon-referenced dot — compute centroid of assembled polygon
                    const { points } = this._buildCombinedPolygon(entry.polyRefs, cstByIndex, polByIndex);
                    if (points.length === 0) continue;
                    let sumX = 0, sumY = 0;
                    for (const pt of points) {
                        const px = projection.geoToPixel(pt.lon, pt.lat);
                        sumX += px.x; sumY += px.y;
                    }
                    x = sumX / points.length;
                    y = sumY / points.length;
                    r = 4;
                } else {
                    continue;
                }

                if (x < -r || x > W + r || y < -r || y > H + r) continue;
                seen.set(dateMatch.name, { x, y, r });
            }
        }

        ctx.save();
        ctx.font         = 'bold 10px Arial';
        ctx.textBaseline = 'middle';
        ctx.textAlign    = 'left';
        ctx.lineJoin     = 'round';

        const placed  = [];
        const overlaps = r => placed.some(p =>
            r.x < p.x + p.w && r.x + r.w > p.x &&
            r.y < p.y + p.h && r.y + r.h > p.y
        );

        for (const [name, { x, y, r }] of seen) {
            const w  = ctx.measureText(name).width;
            const h  = 14;   // bold 10px + padding
            const gap = r + 3;
            const d   = gap * 0.707;

            // 8 candidate positions around the dot, starting right (most readable)
            const candidates = [
                { lx: x + gap,         ly: y       },
                { lx: x + d,           ly: y - d   },
                { lx: x - w / 2,       ly: y - gap },
                { lx: x - w - d,       ly: y - d   },
                { lx: x - w - gap,     ly: y       },
                { lx: x - w - d,       ly: y + d   },
                { lx: x - w / 2,       ly: y + gap },
                { lx: x + d,           ly: y + d   },
            ];

            for (const { lx, ly } of candidates) {
                if (lx + w < 0 || lx > W || ly + h / 2 < 0 || ly - h / 2 > H) continue;
                const rect = { x: lx - 2, y: ly - h / 2 - 2, w: w + 4, h: h + 4 };
                if (!overlaps(rect)) {
                    placed.push(rect);
                    ctx.strokeStyle = 'white';
                    ctx.lineWidth   = 3;
                    ctx.strokeText(name, lx, ly);
                    ctx.fillStyle   = 'black';
                    ctx.fillText(name, lx, ly);
                    break;
                }
            }
        }
        ctx.restore();
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
    // Returns true when city names should be shown automatically.
    // Hybrid test: total visible cities <= MAX_COUNT AND fewer than MAX_CROWD
    // cities have a neighbour within CROWD_R pixels.
    _autoCityNames(projection, allCities, year, cityDetail, W, H) {
        const MAX_COUNT = 30;
        const CROWD_R   = 60;   // px — label-width proxy
        const MAX_CROWD = 3;    // crowded cities tolerated before suppressing
        const BASE_DEG  = 0.01;
        const scale     = projection.xScale;

        const pts = [];
        for (const cities of allCities) {
            for (const city of cities) {
                const match = matchDate(city.dateRanges, year);
                if (!match || match.detCode <= 0 || match.detCode > cityDetail) continue;
                const sym = match.symCode;
                if (sym >= 0) {
                    const r = (sym !== 0 ? (Math.abs(sym) + 1) * BASE_DEG : BASE_DEG) * scale;
                    if (r < 0.5) continue;
                } else {
                    if ((0.05 * Math.abs(sym) * scale) / Math.SQRT2 < 0.5) continue;
                }
                const { x, y } = projection.geoToPixel(city.lon, city.lat);
                if (x < 0 || x > W || y < 0 || y > H) continue;  // off-screen
                pts.push({ x, y });
                if (pts.length > MAX_COUNT) return false;  // early exit
            }
        }
        if (pts.length === 0) return false;

        const R2 = CROWD_R * CROWD_R;
        let crowded = 0;
        for (let i = 0; i < pts.length; i++) {
            for (let j = 0; j < pts.length; j++) {
                if (i === j) continue;
                const dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y;
                if (dx * dx + dy * dy < R2) { crowded++; break; }
            }
            if (crowded >= MAX_CROWD) return false;
        }
        return true;
    }

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
                const r      = (symCode !== 0 ? (Math.abs(symCode) + 1) * BASE_DEG : BASE_DEG) * scale;
                if (r < 0.5) continue;
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
                const arm = (0.05 * Math.abs(symCode) * scale) / Math.SQRT2;
                if (arm < 0.5) continue;
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
        ctx.lineJoin     = 'round';

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

    // ── Country / area labels ──────────────────────────────────────────────────

    // Collect label geometry for one tile's PAR entries.
    // Returns [{name, points}] for each matched non-dot entry that has real segments.
    _collectTileLabelData(par, cst, pol, year) {
        if (!par.length) return [];
        const cstByIndex = new Map();
        for (const p of cst) cstByIndex.set(p.polyIndex, p);
        const polByIndex = new Map();
        for (const p of pol) polByIndex.set(p.polyIndex, p);
        const result = [];
        for (const entry of par) {
            if (entry.areaType === 0 || entry.dotPoint) continue;
            const dateMatch = matchDate(entry.dateRanges, year);
            if (!dateMatch || !dateMatch.name || dateMatch.name === 'UNKNOWN') continue;
            const { points, hasSegment } = this._buildCombinedPolygon(entry.polyRefs, cstByIndex, polByIndex);
            if (!hasSegment || points.length < 3) continue;
            result.push({ name: dateMatch.name, points });
        }
        return result;
    }

    // Shoelace area centroid of a projected pixel polygon.
    // Returns { area (px²), cx, cy } — area is always non-negative.
    _pixelCentroid(px) {
        const n = px.length;
        let A2 = 0, cx = 0, cy = 0;
        for (let i = 0; i < n; i++) {
            const j = (i + 1) % n;
            const cross = px[i].x * px[j].y - px[j].x * px[i].y;
            A2 += cross;
            cx += (px[i].x + px[j].x) * cross;
            cy += (px[i].y + px[j].y) * cross;
        }
        const area = Math.abs(A2) / 2;
        if (area < 0.5 || A2 === 0) return { area: 0, cx: 0, cy: 0 };
        cx /= 3 * A2;   // signed A2 keeps the correct spatial direction
        cy /= 3 * A2;
        return { area, cx, cy };
    }

    // Place and draw country/territory labels after all tiles are loaded.
    //
    // Naming convention in PAR data: "France - Corsica" means Corsica is a
    // sub-unit of France.  Labels:
    //   • Root group ("France"): one label centered over ALL French territory
    //     (including all "France - *" sub-unit polygons), text = root name.
    //   • Sub-unit ("France - Corsica"): additional label if sub-unit area ≥
    //     minPixels, text = last component ("Corsica").
    //
    // Both use the pixel-area centroid weighted across tiles.
    _placeAndDrawCountryLabels(ctx, projection, allRawEntries, minPixels) {
        if (!allRawEntries.length) return;

        // Project each entry's polygon and compute pixel centroid + area
        const entries = [];
        for (const { name, points } of allRawEntries) {
            const px = points.map(p => projection.geoToPixel(p.lon, p.lat));
            const { area, cx, cy } = this._pixelCentroid(px);
            if (area < 1) continue;
            entries.push({ name, area, cx, cy });
        }
        if (!entries.length) return;

        // ── Root-name groups ──────────────────────────────────────────────
        // All entries share the first component of name as a root label.
        const rootMap = new Map();  // root → { totalArea, wcx, wcy }
        for (const { name, area, cx, cy } of entries) {
            const root = name.split(' - ')[0];
            if (!rootMap.has(root)) rootMap.set(root, { totalArea: 0, wcx: 0, wcy: 0 });
            const g = rootMap.get(root);
            g.totalArea += area;
            g.wcx       += cx * area;
            g.wcy       += cy * area;
        }

        // ── Sub-unit groups ───────────────────────────────────────────────
        // Entries whose full name contains ' - ' also get an individual label.
        const subMap = new Map();   // fullName → { totalArea, wcx, wcy }
        for (const { name, area, cx, cy } of entries) {
            if (!name.includes(' - ')) continue;
            if (!subMap.has(name)) subMap.set(name, { totalArea: 0, wcx: 0, wcy: 0 });
            const g = subMap.get(name);
            g.totalArea += area;
            g.wcx       += cx * area;
            g.wcy       += cy * area;
        }

        // ── Build label list ──────────────────────────────────────────────
        // For each group, compute the weighted centroid then snap to the nearest
        // actual polygon centroid.  For contiguous territories this lands on the
        // central tile; for scattered non-contiguous ones (e.g. Roman colonies)
        // it picks the polygon closest to the center of the distribution rather
        // than floating in empty space between members.
        const _snapToNearest = (cx0, cy0, filterFn) => {
            let bestDist = Infinity, bestX = cx0, bestY = cy0;
            for (const e of entries) {
                if (!filterFn(e)) continue;
                const d = (e.cx - cx0) ** 2 + (e.cy - cy0) ** 2;
                if (d < bestDist) { bestDist = d; bestX = e.cx; bestY = e.cy; }
            }
            return { x: bestX, y: bestY };
        };

        // Which roots have at least one sub-unit entry?
        const rootsWithSubs = new Set();
        for (const fullName of subMap.keys()) rootsWithSubs.add(fullName.split(' - ')[0]);

        const labels = [];
        for (const [root, g] of rootMap) {
            if (g.totalArea < minPixels) continue;
            const cx0 = g.wcx / g.totalArea, cy0 = g.wcy / g.totalArea;
            const { x, y } = _snapToNearest(cx0, cy0, e => e.name.split(' - ')[0] === root);
            labels.push({ text: root, x, y, area: g.totalArea, kind: rootsWithSubs.has(root) ? 'parent' : 'root' });
        }
        for (const [fullName, g] of subMap) {
            if (g.totalArea < minPixels) continue;
            const cx0 = g.wcx / g.totalArea, cy0 = g.wcy / g.totalArea;
            const { x, y } = _snapToNearest(cx0, cy0, e => e.name === fullName);
            const parts = fullName.split(' - ');
            labels.push({ text: parts[parts.length - 1], x, y, area: g.totalArea, kind: 'sub' });
        }

        // Largest territories claim space first
        labels.sort((a, b) => b.area - a.area);

        // ── Greedy placement ──────────────────────────────────────────────
        const W = ctx.canvas.width, H = ctx.canvas.height;
        ctx.textBaseline = 'middle';
        ctx.lineJoin     = 'round';

        const placed = [];
        const overlaps = r => placed.some(p =>
            r.x < p.x + p.w && r.x + r.w > p.x &&
            r.y < p.y + p.h && r.y + r.h > p.y
        );

        for (const { text, x, y, kind } of labels) {
            if (x < 0 || x > W || y < 0 || y > H) continue;

            const baseSize = Math.max(9, Math.min(13, Math.round(250 / projection.degX)));
            const fontSize = kind === 'parent' ? Math.round(baseSize * 1.25)
                           : kind === 'sub'    ? Math.max(8, baseSize - 1)
                           : baseSize;
            ctx.font = `bold ${fontSize}px Arial, sans-serif`;
            const w = ctx.measureText(text).width;
            const h = fontSize + 4;

            // 5 candidates: centered on computed centroid, then 4 shifted positions
            const candidates = [
                { lx: x - w / 2,             ly: y             },
                { lx: x - w / 2,             ly: y - h * 1.3   },
                { lx: x - w / 2,             ly: y + h * 1.3   },
                { lx: x - w / 2 + w * 0.7,   ly: y             },
                { lx: x - w / 2 - w * 0.7,   ly: y             },
            ];

            for (const { lx, ly } of candidates) {
                if (lx + w < -10 || lx > W + 10 || ly + h < -10 || ly > H + 10) continue;
                const rect = { x: lx - 2, y: ly - h / 2 - 2, w: w + 4, h: h + 4 };
                if (!overlaps(rect)) {
                    placed.push(rect);
                    ctx.lineWidth   = 3;
                    ctx.strokeStyle = 'rgba(0,0,0,0.75)';
                    ctx.strokeText(text, lx, ly);
                    ctx.fillStyle   = '#ffffff';
                    ctx.fillText(text, lx, ly);
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
