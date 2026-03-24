// projection.js — MapProjection
// Converts between geographic coordinates (lon/lat) and canvas pixel coordinates.
//
// Coordinate system:
//   lon: -180 (west) to +180 (east)
//   lat: -90  (south) to +90  (north)
//   Pixel (0,0) is top-left; y increases downward, so lat decreases downward.
//
// Zoom:  zoom=0 → full world (360°×180°)
//        zoom=1 → half world (180°×90°)
//        zoom=N → 360/(N+1) degrees wide

class MapProjection {
    constructor(centerLon, centerLat, zoom, canvasWidth, canvasHeight) {
        this.centerLon   = centerLon;
        this.centerLat   = centerLat;
        this.zoom        = zoom;
        this.canvasWidth = canvasWidth;
        this.canvasHeight = canvasHeight;

        // Degrees of longitude visible on screen (controlled by zoom)
        this.degX = 360 / (zoom + 1);

        // Single scale (pixels per degree) derived from horizontal span.
        // xScale === yScale so that 1° longitude == 1° latitude in pixels.
        this.xScale = canvasWidth / this.degX;
        this.yScale = this.xScale;

        // Vertical span follows from the scale and canvas height
        this.degY = canvasHeight / this.yScale;

        // Viewport bounds in geographic coordinates
        this.lon1 = centerLon - this.degX / 2;
        this.lon2 = centerLon + this.degX / 2;
        this.lat1 = centerLat - this.degY / 2;
        this.lat2 = centerLat + this.degY / 2;
    }

    // Geographic → pixel
    geoToPixel(lon, lat) {
        return {
            x: this.xScale * (lon - this.lon1),
            y: this.yScale * (this.lat2 - lat)   // lat increases upward, pixels downward
        };
    }

    // Pixel → geographic
    pixelToGeo(px, py) {
        return {
            lon: px / this.xScale + this.lon1,
            lat: this.lat2 - py / this.yScale
        };
    }

    // Clamp pixel coordinates to canvas bounds (matches VB clamping)
    clampPixel(px, py) {
        return {
            x: Math.max(0, Math.min(this.canvasWidth,  px)),
            y: Math.max(0, Math.min(this.canvasHeight, py))
        };
    }
}
