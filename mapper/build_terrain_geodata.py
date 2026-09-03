"""build_terrain_geodata.py — VMAP0 contour lines -> CTR tile files for CREATOR.

Converts VMAP0 (Vector Map Level 0) elevation contour data into the app's
5-degree tile grid (see js/tiles.js TileManager) as CTR<lonStr>.PRN files
under terrain/<latStr>/, matching the existing RIV/CST/POL tile pattern.

Requires GDAL 3.10 (pre-3.11, before OGDI/VPF support was removed) with the
OGDI driver -- see project_mapper_vmap_terrain memory for how this was set
up. Point GDAL_BIN at the install if it's not on PATH.

Usage:
    python build_terrain_geodata.py --libs EURNASIA --out terrain
    python build_terrain_geodata.py --libs EURNASIA NOAMER SASAUS SOAMAFR --out terrain

Each run processes all requested libraries in memory and writes tile files
once at the end, so a tile that straddles two libraries' coverage naturally
gets lines from both merged into one file (no separate merge step needed).
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

GDAL_BIN = r"C:\Program Files\GDAL-3.10"
VMAP_ROOT = r"C:\My stuff\VMAP Level 0 CDs"

# Earth's highest point (Everest) is 8848m -- anything at or above this is a
# VMAP0 sentinel/nodata marker, not a real elevation. Confirmed by inspection
# 2026-09-02: round-thousand values (10000, 11000, ..., 15000) plus a literal
# 9999/29999 "unsurveyed" marker used heavily in Antarctica. 118 out of ~1.3M
# contour segments hit this globally -- small but real, filter them out.
MAX_PLAUSIBLE_ELEVATION_M = 9000

# Port of js/tiles.js's TileManager tiling scheme -- keep in sync with that file.
N_VALUES = [
    8, 8, 18, 24, 30, 36, 45, 45,
    60, 60, 72, 72, 72, 72, 72, 72,
    72, 72, 72, 72, 72, 72, 72, 72,
    72, 72, 60, 60, 45, 45, 36, 30,
    24, 18, 8, 8,
]

SIMPLIFY_TOLERANCE_DEG = 0.0015  # ~sub-pixel at typical zoom; tune after measuring output size


def fmt3(n):
    return f"{n:03d}"


def tile_for(lon, lat):
    latD = 5 * math.floor((90 + lat) / 5)
    latD = max(0, min(175, latD))

    nTiles = N_VALUES[latD // 5]
    tileWidth = 360 / nTiles

    shiftedLon = ((lon + 180) % 360 + 360) % 360
    lonD = tileWidth * math.floor(shiftedLon / tileWidth)

    if latD in (30, 35, 140, 145):
        lonD += 4
        if lonD > shiftedLon:
            lonD -= 8

    fileLon = lonD - 180 if lonD >= 180 else lonD + 180
    return fmt3(int(round(latD))), fmt3(int(round(fileLon)))


def is_index_contour(elevation_m):
    feet = elevation_m / 0.3048
    nearest5000 = round(feet / 5000) * 5000
    return abs(feet - nearest5000) < 50


def split_by_tile(coords):
    """Cut a line's point list wherever consecutive points cross a tile
    boundary. The crossing point itself is duplicated into both the
    outgoing and incoming tile's runs (no interpolation, just a shared
    endpoint) so the two fragments still meet exactly at the seam when
    drawn independently -- otherwise the connecting segment is silently
    dropped and the line visibly gaps at every tile boundary it crosses."""
    runs = []
    cur_tile = None
    cur_pts = []
    for lon, lat in coords:
        t = tile_for(lon, lat)
        if t != cur_tile and cur_tile is not None:
            cur_pts.append((lon, lat))
            if len(cur_pts) >= 2:
                runs.append((cur_tile, cur_pts))
            cur_tile = t
            cur_pts = [(lon, lat)]
        else:
            cur_tile = t
            cur_pts.append((lon, lat))
    if len(cur_pts) >= 2:
        runs.append((cur_tile, cur_pts))
    return runs


def export_library_contours(lib_name, tmp_geojson_path, simplify_tol):
    """ogr2ogr the contourl layer out of one VMAP0 library via the OGDI/VRF driver."""
    src = f"gltp:/vrf/{VMAP_ROOT}\\{lib_name}\\VMAPLV0\\{lib_name}".replace("\\", "/")
    ogr2ogr = os.path.join(GDAL_BIN, "ogr2ogr.exe")
    env = dict(os.environ)
    env["GDAL_DATA"] = os.path.join(GDAL_BIN, "gdal-data")
    cmd = [
        ogr2ogr, "-f", "GeoJSON",
        "-simplify", str(simplify_tol),
        tmp_geojson_path, src, "contourl@elev(*)_line",
    ]
    print(f"  exporting {lib_name}...", flush=True)
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ogr2ogr stderr: {result.stderr}", file=sys.stderr)
        raise RuntimeError(f"ogr2ogr failed for {lib_name}")


def _endpoint_key(pt):
    return (round(pt[0], 6), round(pt[1], 6))


def merge_chains(segments):
    """Stitch same-elevation line fragments that share exact endpoints back
    into the longest continuous chains possible.

    VMAP0 stores contour lines as topological edges, not whole rings -- a
    single physical contour is routinely split into many short edge
    features, both across the library's own internal tile grid (endpoints
    land on round numbers like lon=15.0) and just from ordinary edge
    topology within one tile. Left unmerged, each edge gets stroked as its
    own separate canvas path; even though adjacent edges share an exact
    endpoint, butt line-caps leave a visible notch wherever two separate
    strokes meet at an angle -- exactly the "gaps in the rings" seen around
    Etna's tightly-curved summit contours. Merging first means each output
    poly is one real continuous line, drawn as a single unbroken stroke.

    segments: list of (poly_type, elevation, points). Only merges through a
    point when it's unambiguous -- exactly one other unused edge touches it.
    An earlier version took the first available match at any shared point,
    which silently stitched together unrelated edges wherever VPF's
    topology graph put a real node with 3+ incident edges (e.g. two
    unrelated hills' same-elevation rings happening to meet the graph at
    one point) -- confirmed 2026-09-03 by rendering the raw tile data: it
    produced long, jagged, geographically nonsensical lines cutting across
    the map (mistaken by the user for "gaps" in Etna's rings, though Etna's
    own rings were actually fine -- the bogus line was a separate artifact
    in the same viewport, over the Centuripe/Adranum hill country). Real
    branch points are just left unmerged now; each fragment still gets a
    round line-cap from the renderer, which is enough to visually close a
    genuine 2-edge junction without risking a wrong 3+-edge guess.
    """
    groups = {}
    for poly_type, elevation, points in segments:
        groups.setdefault((poly_type, elevation), []).append(points)

    merged = []
    for (poly_type, elevation), lines in groups.items():
        endpoint_map = {}
        for idx, pts in enumerate(lines):
            for end in (0, -1):
                endpoint_map.setdefault(_endpoint_key(pts[end]), []).append((idx, end))

        used = [False] * len(lines)
        for start_idx in range(len(lines)):
            if used[start_idx]:
                continue
            used[start_idx] = True
            chain = list(lines[start_idx])

            while True:  # extend forward from the chain's tail
                candidates = [(i, e) for i, e in endpoint_map.get(_endpoint_key(chain[-1]), []) if not used[i]]
                if len(candidates) != 1:
                    break
                idx, end = candidates[0]
                used[idx] = True
                pts = lines[idx]
                chain.extend(pts[1:] if end == 0 else reversed(pts[:-1]))

            while True:  # extend backward from the chain's head
                candidates = [(i, e) for i, e in endpoint_map.get(_endpoint_key(chain[0]), []) if not used[i]]
                if len(candidates) != 1:
                    break
                idx, end = candidates[0]
                used[idx] = True
                pts = lines[idx]
                chain = (pts[:-1] if end == -1 else list(reversed(pts[1:]))) + chain

            merged.append((poly_type, elevation, chain))

    return merged


def process_library(lib_name, tiles, simplify_tol):
    with tempfile.TemporaryDirectory() as tmpdir:
        geojson_path = os.path.join(tmpdir, f"{lib_name}_contourl.geojson")
        export_library_contours(lib_name, geojson_path, simplify_tol)

        n_features = 0
        n_segments = 0
        n_sentinel = 0
        raw_segments = []
        with open(geojson_path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s.startswith('{ "type": "Feature"'):
                    continue
                if s.endswith(","):
                    s = s[:-1]
                try:
                    feat = json.loads(s)
                except json.JSONDecodeError:
                    continue
                z = feat["properties"].get("zv2")
                if z is None or z >= MAX_PLAUSIBLE_ELEVATION_M:
                    if z is not None and z >= MAX_PLAUSIBLE_ELEVATION_M:
                        n_sentinel += 1
                    continue
                coords = feat["geometry"]["coordinates"]
                if len(coords) < 2:
                    continue
                n_features += 1
                poly_type = 2 if is_index_contour(z) else 1
                raw_segments.append((poly_type, z, coords))

        for poly_type, z, chain in merge_chains(raw_segments):
            for tile, pts in split_by_tile(chain):
                tiles.setdefault(tile, []).append((poly_type, z, pts))
                n_segments += 1

        print(f"  {lib_name}: {n_features} features -> {n_segments} tile segments"
              f" ({n_sentinel} sentinel/nodata elevations filtered)")


def write_tiles(tiles, out_root):
    # Clear any prior output first -- a tile that had only sentinel/nodata
    # content before filtering now has zero entries and would otherwise never
    # get overwritten, leaving stale garbage files sitting next to the fresh
    # ones (bit us 2026-09-02: 6 leftover 29999m Antarctic entries survived a
    # regeneration run for exactly this reason).
    if os.path.isdir(out_root):
        shutil.rmtree(out_root)

    n_files = 0
    total_bytes = 0
    total_verts = 0
    for (latStr, lonStr), polys in tiles.items():
        tile_dir = os.path.join(out_root, latStr)
        os.makedirs(tile_dir, exist_ok=True)
        out_path = os.path.join(tile_dir, f"CTR{lonStr}.PRN")
        with open(out_path, "w", encoding="utf-8", newline="\r\n") as out:
            out.write(f"{len(polys)}\n")
            for idx, (poly_type, elevation, pts) in enumerate(polys, start=1):
                out.write(f"{poly_type},{idx}\n")
                out.write(f"{elevation:.1f}\n")
                out.write(f"{len(pts)}\n")
                for lon, lat in pts:
                    out.write(f"{lon:.6f}\t{lat:.6f}\n")
                total_verts += len(pts)
        n_files += 1
        total_bytes += os.path.getsize(out_path)

    print(f"\nWrote {n_files} tile files, {total_verts:,} vertices, "
          f"{total_bytes / 1024 / 1024:.1f} MB total under {out_root}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--libs", nargs="+", required=True,
                     choices=["EURNASIA", "NOAMER", "SASAUS", "SOAMAFR"])
    ap.add_argument("--out", default="terrain")
    ap.add_argument("--simplify", type=float, default=SIMPLIFY_TOLERANCE_DEG)
    args = ap.parse_args()

    tiles = {}
    for lib in args.libs:
        process_library(lib, tiles, args.simplify)

    write_tiles(tiles, args.out)


if __name__ == "__main__":
    main()
