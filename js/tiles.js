// tiles.js — TileManager
// Determines which data tiles cover the current map viewport and returns their file paths.
//
// The globe is divided into 36 latitude bands of 5° each (latD = 0 to 175, where
// latD=0 is 90°S and latD=175 is 85°N). Within each band, tiles have variable width
// depending on latitude — more tiles at mid-latitudes, fewer near the poles.
//
// File coordinate system:
//   Geographic lon=0° (prime meridian) → file "000"
//   Files run 0–355° eastward
//   Geographic lon → file lon via: fileLon = geo >= 0 ? geo : geo + 360
//
// Internal shifted system (used during tile range calculation):
//   shiftedLon = geoLon + 180   (puts -180° at 0, prime meridian at 180)
//   After finding tile, convert back: fileLon = shifted >= 180 ? shifted - 180 : shifted + 180

const N_VALUES = [
    8, 8, 18, 24, 30, 36, 45, 45,   // latD 0–35   (-90° to -55°)
    60, 60, 72, 72, 72, 72, 72, 72, // latD 40–75  (-50° to -15°)
    72, 72, 72, 72, 72, 72, 72, 72, // latD 80–115 (-10° to +25°)
    72, 72, 60, 60, 45, 45, 36, 30, // latD 120–155 (+30° to +65°)
    24, 18, 8, 8                     // latD 160–175 (+70° to +85°)
];

// Convert latD (0–175) to geographic latitude in degrees
function latDToGeo(latD) {
    return latD - 90;
}

// Format a 3-digit zero-padded string from an integer (e.g. 5 → "005", 175 → "175")
// Mirrors VB: Str(1000 + n).Remove(0, 2)  [VB Str() prepends a space for positives]
function fmt3(n) {
    return String(1000 + n).slice(1);  // "1005" → "005"
}

class TileManager {
    // Returns an array of tile descriptors for the given MapProjection.
    // Each descriptor: { latD, lonD, fileLon, latStr, lonStr, coastsFile, polsFile, polareasFile }
    getTiles(projection) {
        const { lon1, lon2, lat1, lat2 } = projection;
        const tiles = [];

        // Shift longitude range to 0–360 system for internal calculation
        const L1 = lon1 + 180;
        const L2 = lon2 + 180;

        // Latitude bands to cover (latD = 0–175 in steps of 5)
        let latMin = 5 * Math.floor((90 + lat1) / 5);
        let latMax = 5 * Math.floor((90 + lat2) / 5);
        if (latMax > 175) latMax = 175;
        if (latMin < 0)   latMin = 0;

        for (let latD = latMin; latD <= latMax; latD += 5) {
            const nTiles    = N_VALUES[latD / 5];
            const tileWidth = 360 / nTiles;

            let lonMin = tileWidth * Math.floor(L1 / tileWidth);
            let lonMax = tileWidth * Math.floor(L2 / tileWidth);

            // Don't double-count when viewport edge lands exactly on a tile boundary
            if (L2 / tileWidth === Math.floor(L2 / tileWidth)) lonMax -= tileWidth;

            // Special offset for certain latitude bands (ported directly from VB)
            if (latD === 30 || latD === 35 || latD === 140 || latD === 145) {
                lonMin += 4;
                lonMax += 4;
                if (lonMin > L1) lonMin -= 8;
            }

            for (let lonD = lonMin; lonD <= lonMax; lonD += tileWidth) {
                // Convert from shifted system back to file coordinate system
                const fileLon = lonD >= 180 ? lonD - 180 : lonD + 180;

                const latStr = fmt3(latD);
                const lonStr = fmt3(fileLon);

                tiles.push({
                    latD,
                    lonD,
                    fileLon,
                    geoLat: latDToGeo(latD),   // geographic latitude of tile bottom edge
                    geoLon: fileLon > 180 ? fileLon - 360 : fileLon,  // geographic lon of tile left edge
                    tileWidth,
                    latStr,
                    lonStr,
                    coastsFile:    `coasts/${latStr}/CST${lonStr}.PRN`,
                    polsFile:      `pols/${latStr}/POL${lonStr}.PRN`,
                    polareasFile:  `polareas/${latStr}/PAR${lonStr}.ASC`,
                    citiesFile:    `cities/${latStr}/CIT${lonStr}.TXT`,
                    inwaterFile:   `inwaters/${latStr}/IWA${lonStr}.PRN`,
                    niwFile:       `niw/${latStr}/NIW${lonStr}.ASC`,
                });
            }
        }

        return tiles;
    }
}
