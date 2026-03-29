// projection.js — MapProjection
// Converts between geographic coordinates (lon/lat) and canvas pixel coordinates.
//
// Supported projections:
//   'equirect'  — Equirectangular (plate carrée).  Simple, fast.  Default.
//   'robinson'  — Robinson compromise projection.  Always shows the full world.
//   'lcc'       — Lambert Conformal Conic.  Applies to the current viewport.
//
// Equirectangular:
//   Zoom controls how many degrees are visible horizontally.
//   xScale === yScale so 1° lon == 1° lat in pixels.
//
// Robinson:
//   Uses Arthur Robinson's 1963 lookup-table projection.
//   Full world always fits the canvas (letterboxed if needed).
//   Zoom parameter is ignored; viewport is always ±180° × ±90°.
//
// Lambert Conformal Conic:
//   Conformal conic projection.  Shows the current viewport region.
//   Standard parallels auto-set to ±1/3 of the visible latitude span.
//   Looks like a standard atlas page — curved parallels, straight meridians from pole.
//   Tile loading uses the same bounding box as the equivalent equirect view.

// ── Robinson lookup table ─────────────────────────────────────────────────────
// Values at 5° intervals from 0° to 90°.
// Column 0 = PLEN (parallel length factor, X scale).
// Column 1 = PDFE (parallel displacement from equator, Y scale).
// Source: Arthur Robinson (1974) / Snyder & Voxland (1989).
const _ROB = [
    [1.0000, 0.0000],  //  0°
    [0.9986, 0.0620],  //  5°
    [0.9954, 0.1240],  // 10°
    [0.9900, 0.1860],  // 15°
    [0.9822, 0.2480],  // 20°
    [0.9730, 0.3100],  // 25°
    [0.9600, 0.3720],  // 30°
    [0.9427, 0.4340],  // 35°
    [0.9216, 0.4958],  // 40°
    [0.8962, 0.5571],  // 45°
    [0.8679, 0.6176],  // 50°
    [0.8350, 0.6769],  // 55°
    [0.7986, 0.7346],  // 60°
    [0.7597, 0.7903],  // 65°
    [0.7186, 0.8435],  // 70°
    [0.6732, 0.8936],  // 75°
    [0.6213, 0.9394],  // 80°
    [0.5722, 0.9761],  // 85°
    [0.5322, 1.0000],  // 90°
];

// Linearly interpolate PLEN and PDFE for any |lat| in [0, 90].
function _robLerp(absLat) {
    const clamped = Math.min(absLat, 90);
    const i  = Math.min(Math.floor(clamped / 5), 17);
    const t  = (clamped - i * 5) / 5;
    return {
        plen: _ROB[i][0] + t * (_ROB[i + 1][0] - _ROB[i][0]),
        pdfe: _ROB[i][1] + t * (_ROB[i + 1][1] - _ROB[i][1]),
    };
}

// Full-world Robinson extents in normalized projection units:
//   x ∈ [-0.8487π, +0.8487π]  →  total width  = 2 × 0.8487π ≈ 5.3326
//   y ∈ [-1.3523,  +1.3523 ]  →  total height = 2 × 1.3523   ≈ 2.7046
const _ROB_W = 2 * 0.8487 * Math.PI;   // ≈ 5.3326
const _ROB_H = 2 * 1.3523;             // ≈ 2.7046

class MapProjection {
    // projType: 'equirect' (default) | 'robinson' | 'lcc'
    constructor(centerLon, centerLat, zoom, canvasWidth, canvasHeight, projType = 'equirect') {
        this.centerLon    = centerLon;
        this.centerLat    = centerLat;
        this.zoom         = zoom;
        this.canvasWidth  = canvasWidth;
        this.canvasHeight = canvasHeight;
        this.projType     = projType;

        if (projType === 'robinson') {
            this._initRobinson();
        } else if (projType === 'lcc') {
            this._initLCC();
        } else {
            this._initEquirect();
        }
    }

    // ── Equirectangular ────────────────────────────────────────────────────────

    _initEquirect() {
        this.degX   = 360 / (this.zoom + 1);
        this.xScale = this.canvasWidth / this.degX;
        this.yScale = this.xScale;
        this.degY   = this.canvasHeight / this.yScale;
        this.lon1   = this.centerLon - this.degX / 2;
        this.lon2   = this.centerLon + this.degX / 2;
        this.lat1   = this.centerLat - this.degY / 2;
        this.lat2   = this.centerLat + this.degY / 2;
    }

    // ── Robinson ───────────────────────────────────────────────────────────────

    _initRobinson() {
        // Fit full world into canvas, maintaining Robinson aspect ratio.
        const scaleX      = this.canvasWidth  / _ROB_W;
        const scaleY      = this.canvasHeight / _ROB_H;
        this._robScale    = Math.min(scaleX, scaleY);
        this._robOffX     = this.canvasWidth  / 2;
        this._robOffY     = this.canvasHeight / 2;

        // Tile system reads these to decide which tiles to load.
        // Robinson always shows the full world.
        this.lon1   = -180;
        this.lon2   =  180;
        this.lat1   = -90;
        this.lat2   =  90;
        this.degX   = 360;
        this.degY   = 180;
        // Approximate pixel-per-degree scale (used by lineWidth helpers).
        this.xScale = this.canvasWidth  / 360;
        this.yScale = this.canvasHeight / 180;
    }

    // ── Lambert Conformal Conic ────────────────────────────────────────────────

    _initLCC() {
        // Step 1: compute equirect viewport extents (same as equirect at this zoom).
        //   These are used for tile loading and as a fallback when LCC degenerates.
        this.degX   = 360 / (this.zoom + 1);
        this.xScale = this.canvasWidth / this.degX;
        this.yScale = this.xScale;
        this.degY   = this.canvasHeight / this.yScale;
        this.lon1   = this.centerLon - this.degX / 2;
        this.lon2   = this.centerLon + this.degX / 2;
        this.lat1   = this.centerLat - this.degY / 2;
        this.lat2   = this.centerLat + this.degY / 2;

        // Step 2: compute LCC parameters.
        //   Standard parallels at ±1/3 of the visible latitude span from center.
        const clamp89 = v => Math.max(-89, Math.min(89, v));
        const φ0 = clamp89(this.centerLat) * Math.PI / 180;
        const φ1 = clamp89(this.centerLat - this.degY / 3) * Math.PI / 180;
        const φ2 = clamp89(this.centerLat + this.degY / 3) * Math.PI / 180;

        // Cone constant n.  When φ1 == φ2, n = sin(φ1).
        let n;
        const tφ1 = Math.tan(Math.PI / 4 + φ1 / 2);
        const tφ2 = Math.tan(Math.PI / 4 + φ2 / 2);
        if (Math.abs(φ1 - φ2) < 1e-10) {
            n = Math.sin(φ1);
        } else {
            n = (Math.log(Math.cos(φ1)) - Math.log(Math.cos(φ2))) /
                (Math.log(tφ2) - Math.log(tφ1));
        }

        // Degenerate (equatorial belt): fall back to equirect rendering.
        this._lccOk = Math.abs(n) >= 0.01;
        if (!this._lccOk) return;

        const F  = (Math.cos(φ1) * Math.pow(tφ1, n)) / n;
        const tφ0 = Math.tan(Math.PI / 4 + φ0 / 2);
        const ρ0 = F / Math.pow(tφ0, n);

        this._lccN   = n;
        this._lccF   = F;
        this._lccRho0 = ρ0;
        this._lccLon0 = this.centerLon;

        // Step 3: project viewport corners (+ mid-edge samples) to find LCC extent.
        //   LCC meridians converge so edge midpoints can extend the bounding box.
        const samplePts = [];
        const M = 10;   // sample count per edge
        for (let i = 0; i <= M; i++) {
            const t = i / M;
            const lon = this.lon1 + t * (this.lon2 - this.lon1);
            const lat = this.lat1 + t * (this.lat2 - this.lat1);
            samplePts.push([lon,       this.lat2]);  // top edge
            samplePts.push([lon,       this.lat1]);  // bottom edge
            samplePts.push([this.lon1, lat      ]);  // left edge
            samplePts.push([this.lon2, lat      ]);  // right edge
        }

        let minX = Infinity, maxX = -Infinity;
        let minY = Infinity, maxY = -Infinity;
        for (const [lon, lat] of samplePts) {
            const { x, y } = this._lccProject(lon, lat);
            if (x < minX) minX = x;
            if (x > maxX) maxX = x;
            if (y < minY) minY = y;
            if (y > maxY) maxY = y;
        }

        // Step 4: fit the LCC bounding box to the canvas (letterbox if needed).
        const lccW = maxX - minX;
        const lccH = maxY - minY;
        const sx = this.canvasWidth  / lccW;
        const sy = this.canvasHeight / lccH;
        this._lccScale = Math.min(sx, sy);

        const projCX = (minX + maxX) / 2;
        const projCY = (minY + maxY) / 2;
        this._lccOffX = this.canvasWidth  / 2 - projCX * this._lccScale;
        this._lccOffY = this.canvasHeight / 2 + projCY * this._lccScale;
    }

    // Project (lon, lat) → LCC normalized coordinates {x, y} (northing positive up).
    _lccProject(lon, lat) {
        const φ = Math.max(-89.9, Math.min(89.9, lat)) * Math.PI / 180;
        const dλ = (lon - this._lccLon0) * Math.PI / 180;
        const ρ = this._lccF / Math.pow(Math.tan(Math.PI / 4 + φ / 2), this._lccN);
        const θ = this._lccN * dλ;
        return {
            x:  ρ * Math.sin(θ),
            y:  this._lccRho0 - ρ * Math.cos(θ),
        };
    }

    // ── geoToPixel ─────────────────────────────────────────────────────────────

    geoToPixel(lon, lat) {
        if (this.projType === 'robinson') {
            const { plen, pdfe } = _robLerp(Math.abs(lat));
            const sign = lat >= 0 ? 1 : -1;
            const rx = 0.8487 * plen * (lon * Math.PI / 180);
            const ry = 1.3523 * pdfe * sign;
            return {
                x: this._robOffX + rx * this._robScale,
                y: this._robOffY - ry * this._robScale,
            };
        }
        if (this.projType === 'lcc' && this._lccOk) {
            const { x, y } = this._lccProject(lon, lat);
            return {
                x: this._lccOffX + x * this._lccScale,
                y: this._lccOffY - y * this._lccScale,
            };
        }
        // Equirectangular (also fallback for degenerate LCC)
        return {
            x: this.xScale * (lon - this.lon1),
            y: this.yScale * (this.lat2 - lat),
        };
    }

    // ── pixelToGeo ─────────────────────────────────────────────────────────────

    pixelToGeo(px, py) {
        if (this.projType === 'robinson') {
            // Convert canvas pixel → Robinson normalized coordinates
            const rx = (px - this._robOffX) / this._robScale;
            const ry = (this._robOffY - py) / this._robScale;

            // Invert Y → latitude via PDFE table search
            const absPdfe = Math.abs(ry) / 1.3523;
            let lat = 90;
            if (absPdfe < 1.0) {
                for (let i = 0; i < 18; i++) {
                    if (absPdfe <= _ROB[i + 1][1]) {
                        const t = (absPdfe - _ROB[i][1]) / (_ROB[i + 1][1] - _ROB[i][1]);
                        lat = (i + t) * 5;
                        break;
                    }
                }
            }
            if (ry < 0) lat = -lat;

            // Invert X → longitude using the PLEN at this latitude
            const { plen } = _robLerp(Math.abs(lat));
            const lon = plen > 0.001
                ? (rx / (0.8487 * plen)) * (180 / Math.PI)
                : 0;

            return {
                lon: Math.max(-180, Math.min(180, lon)),
                lat: Math.max(-90,  Math.min(90,  lat)),
            };
        }
        if (this.projType === 'lcc' && this._lccOk) {
            // Convert canvas pixel → LCC normalized coordinates
            const lx = (px - this._lccOffX) / this._lccScale;
            const ly = (this._lccOffY - py) / this._lccScale;

            const dy = this._lccRho0 - ly;
            const ρ = Math.sign(this._lccN) * Math.sqrt(lx * lx + dy * dy);
            const θ = Math.atan2(lx, dy);

            const lat = (2 * Math.atan(Math.pow(this._lccF / ρ, 1 / this._lccN)) - Math.PI / 2)
                        * 180 / Math.PI;
            const lon = this._lccLon0 + (θ / this._lccN) * 180 / Math.PI;
            return {
                lon: Math.max(-180, Math.min(180, lon)),
                lat: Math.max(-90,  Math.min(90,  lat)),
            };
        }
        // Equirectangular (also fallback for degenerate LCC)
        return {
            lon: px / this.xScale + this.lon1,
            lat: this.lat2 - py / this.yScale,
        };
    }

    // Clamp pixel coordinates to canvas bounds
    clampPixel(px, py) {
        return {
            x: Math.max(0, Math.min(this.canvasWidth,  px)),
            y: Math.max(0, Math.min(this.canvasHeight, py)),
        };
    }
}
